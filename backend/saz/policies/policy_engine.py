"""Policy Engine - Coordinates all policy enforcement."""

from typing import Any

import structlog

from .budget_tracker import BudgetTracker
from .pii_detector import PIIDetector
from .pii_token_vault import PIITokenVault, path_matches_allowed
from .rate_limiter import RateLimiter

logger = structlog.get_logger(__name__)

# Tool classification for PII handling
MODEL_TOOLS = {
    "ai.assess",
    "ai.generate",
    "ai.plan",
    "ai.extract",
    "ai.route",
    "ai.score",
    "ai.normalize",
    "ai.match",
    "ai.evaluate",
    "ai.compare",
    "ai.translate",
    "ai.summarize",
    "ai.fix_json",
}

OUTBOUND_TOOLS = {
    "http_request",
    "webhook_emit",
    "ansible_run",
}


class PolicyViolation(Exception):
    """Raised when a policy is violated"""

    pass


class PolicyEngine:
    """
    Central policy enforcement engine.

    Coordinates:
    - Rate limiting
    - PII detection/redaction
    - Budget tracking
    - Custom policy hooks
    """

    def __init__(
        self,
        rate_limiter: RateLimiter | None = None,
        pii_detector: PIIDetector | None = None,
        budget_tracker: BudgetTracker | None = None,
        enforce_pii_redaction: bool = True,
        tokenize_model_inputs: bool = True,
        pii_allow_lists: dict[str, list[str]] | None = None,
        max_replan_attempts: int = 3,
    ):
        self.rate_limiter = rate_limiter or RateLimiter()
        self.pii_detector = pii_detector or PIIDetector()
        self.budget_tracker = budget_tracker or BudgetTracker()
        self.enforce_pii_redaction = enforce_pii_redaction
        self.tokenize_model_inputs = tokenize_model_inputs
        self.max_replan_attempts = max_replan_attempts

        # Per-tool PII allow-lists (dotted paths where PII is allowed)
        # Example: {"email_send": ["to", "from", "subject"],
        # "http_request": ["headers.Authorization"]}
        self.pii_allow_lists: dict[str, list[str]] = pii_allow_lists or {}

        # Token vaults per run (run_id -> PIITokenVault)
        self._token_vaults: dict[str, PIITokenVault] = {}

        self.logger = logger.bind(component="policy_engine")

    def _get_token_vault(self, run_id: str) -> PIITokenVault:
        """Get or create token vault for a run."""
        if run_id not in self._token_vaults:
            self._token_vaults[run_id] = PIITokenVault(run_id)
            self.logger.info("token_vault_created", run_id=run_id)
        return self._token_vaults[run_id]

    def _is_model_tool(self, tool_name: str) -> bool:
        """Check if tool is a model/AI tool."""
        return tool_name in MODEL_TOOLS

    def _is_outbound_tool(self, tool_name: str) -> bool:
        """Check if tool is an outbound integration."""
        return tool_name in OUTBOUND_TOOLS

    @staticmethod
    def _disallowed_pii_paths(pii_paths: list[str], allowed_paths: set[str]) -> list[str]:
        """Return the subset of detected PII paths that are NOT covered by
        any entry in ``allowed_paths``. An allowed entry covers the path
        itself plus anything nested under it (so ``content`` allows
        ``content.requester``)."""
        return [p for p in pii_paths if not path_matches_allowed(p, allowed_paths)]

    def tokenize_arguments(
        self, tool_name: str, arguments: dict[str, Any], run_id: str
    ) -> dict[str, Any]:
        """
        Tokenize PII in arguments before model tool execution.

        Args:
            tool_name: Tool being called
            arguments: Tool arguments
            run_id: Run identifier

        Returns:
            Arguments with PII replaced by tokens
        """
        if not self.tokenize_model_inputs or not self._is_model_tool(tool_name):
            return arguments

        vault = self._get_token_vault(run_id)
        tokenized = vault.tokenize_dict(arguments, self.pii_detector)

        # Count tokens for audit
        token_paths = vault.scan_for_tokens(tokenized)
        if token_paths:
            self.logger.info(
                "pii_tokenized_for_model",
                run_id=run_id,
                tool=tool_name,
                tokenized_paths=token_paths,
                token_count=len(token_paths),
            )

        return tokenized

    def detokenize_arguments(
        self, tool_name: str, arguments: dict[str, Any], run_id: str
    ) -> dict[str, Any]:
        """
        Selectively detokenize PII in arguments before outbound tool execution.

        Only detokenizes paths that are explicitly allowed for this tool.

        Args:
            tool_name: Tool being called
            arguments: Tool arguments (may contain tokens)
            run_id: Run identifier

        Returns:
            Arguments with selective PII restoration

        Raises:
            PolicyViolation: If tokens found on non-allowed paths
        """
        if not self._is_outbound_tool(tool_name):
            return arguments

        vault = self._get_token_vault(run_id)

        # Find all paths containing tokens
        token_paths = vault.scan_for_tokens(arguments)

        if not token_paths:
            # No tokens, nothing to do
            return arguments

        # Get allow-list for this tool
        allowed_paths = set(self.pii_allow_lists.get(tool_name, []))

        # Check if any tokens are on non-allowed paths
        disallowed_token_paths = []
        for path in token_paths:
            if not vault._path_matches_allowed(path, allowed_paths):
                disallowed_token_paths.append(path)

        if disallowed_token_paths:
            self.logger.error(
                "pii_detected_on_disallowed_paths",
                run_id=run_id,
                tool=tool_name,
                disallowed_paths=disallowed_token_paths,
                allowed_paths=list(allowed_paths),
            )
            raise PolicyViolation(
                f"PII detected on non-approved paths for {tool_name}: {disallowed_token_paths}. "
                f"Approved paths: {list(allowed_paths)}"
            )

        # Detokenize only allowed paths
        detokenized = vault.detokenize_dict(arguments, allowed_paths)

        # Any token still present has no vault mapping — the vault is
        # run-scoped and in-memory, so a resume after suspension starts
        # empty. Sending the literal __PII_*__ placeholder to an external
        # system is silent data corruption; fail loudly instead.
        unresolved = vault.scan_for_tokens(detokenized)
        if unresolved:
            self.logger.error(
                "pii_tokens_unresolved",
                run_id=run_id,
                tool=tool_name,
                unresolved_paths=unresolved,
            )
            raise PolicyViolation(
                f"Unresolved PII tokens for {tool_name} at paths {unresolved}: the token "
                f"vault has no mapping for them (this happens when a run resumes after "
                f"suspension). Refusing to send placeholder tokens to an external system."
            )

        self.logger.info(
            "pii_detokenized_for_outbound",
            run_id=run_id,
            tool=tool_name,
            detokenized_paths=[
                p for p in token_paths if vault._path_matches_allowed(p, allowed_paths)
            ],
        )

        return detokenized

    def check_tool_call(
        self, tool_name: str, arguments: dict[str, Any], run_id: str
    ) -> tuple[bool, str | None]:
        """
        Check if tool call is allowed.

        For model tools: PII check is informational only (will be tokenized)
        For outbound tools: PII is blocked on non-approved paths
        For other tools: Block if enforce_pii_redaction is True

        Args:
            tool_name: Name of tool
            arguments: Tool arguments
            run_id: Current run ID

        Returns:
            Tuple of (allowed: bool, reason: Optional[str])
        """
        # Check rate limits
        allowed, reason = self.rate_limiter.check_and_record(tool_name, run_id)
        if not allowed:
            self.logger.warning(
                "tool_call_blocked_rate_limit", tool=tool_name, run_id=run_id, reason=reason
            )
            return False, f"Rate limit: {reason}"

        # Check budget
        within_budget, budget_reason = self.budget_tracker.check_budget(run_id)
        if not within_budget:
            self.logger.warning(
                "tool_call_blocked_budget", tool=tool_name, run_id=run_id, reason=budget_reason
            )
            return False, f"Budget exceeded: {budget_reason}"

        # Check for PII in arguments
        pii_paths = self.pii_detector.scan_dict(arguments)

        if pii_paths:
            if self._is_model_tool(tool_name):
                # Model tools: informational only, will be tokenized
                self.logger.info(
                    "pii_detected_in_model_tool_args",
                    tool=tool_name,
                    run_id=run_id,
                    paths=pii_paths,
                    will_tokenize=self.tokenize_model_inputs,
                )
                # Don't block model tools - they'll receive tokenized inputs
            elif self._is_outbound_tool(tool_name):
                # Outbound tools always require explicit path allow-lists,
                # regardless of the run-level pii.allow flag — these calls
                # leave the trust boundary.
                allowed_paths = set(self.pii_allow_lists.get(tool_name, []))
                disallowed_paths = self._disallowed_pii_paths(pii_paths, allowed_paths)
                if disallowed_paths:
                    self.logger.error(
                        "pii_on_disallowed_paths",
                        tool=tool_name,
                        run_id=run_id,
                        disallowed_paths=disallowed_paths,
                        allowed_paths=list(allowed_paths),
                    )
                    return False, (
                        f"PII detected on non-approved paths: {disallowed_paths}. "
                        f"Approved paths for {tool_name}: {list(allowed_paths)}"
                    )
                self.logger.info(
                    "pii_detected_on_allowed_paths",
                    tool=tool_name,
                    run_id=run_id,
                    paths=pii_paths,
                    allowed_paths=list(allowed_paths),
                )
            else:
                # Other tools (artifact.store, etc.): when pii.allow=false,
                # honor the same per-path allow-list mechanism as outbound
                # tools. Audit artifacts legitimately need to preserve
                # identity (requester, approver) — that is the whole point
                # of an audit record. Operators opt in by declaring the
                # exact paths under policies.pii.exceptions.tools.<tool>.
                if self.enforce_pii_redaction:
                    allowed_paths = set(self.pii_allow_lists.get(tool_name, []))
                    disallowed_paths = self._disallowed_pii_paths(pii_paths, allowed_paths)
                    if disallowed_paths:
                        self.logger.error(
                            "pii_on_disallowed_paths",
                            tool=tool_name,
                            run_id=run_id,
                            disallowed_paths=disallowed_paths,
                            allowed_paths=list(allowed_paths),
                        )
                        return False, (
                            f"PII detected on non-approved paths: {disallowed_paths}. "
                            f"Approved paths for {tool_name}: {list(allowed_paths)}"
                        )
                    self.logger.info(
                        "pii_detected_on_allowed_paths",
                        tool=tool_name,
                        run_id=run_id,
                        paths=pii_paths,
                        allowed_paths=list(allowed_paths),
                    )
                else:
                    self.logger.warning(
                        "pii_detected_in_tool_args",
                        tool=tool_name,
                        run_id=run_id,
                        paths=pii_paths,
                    )

        self.logger.debug("tool_call_allowed", tool=tool_name, run_id=run_id)

        return True, None

    def redact_output(self, data: dict[str, Any], run_id: str) -> dict[str, Any]:
        """
        Redact/tokenize PII from tool output.

        Outputs are always redacted for safety - we don't restore PII in outputs.

        Args:
            data: Tool output
            run_id: Run identifier

        Returns:
            Data with PII redacted
        """
        # Use traditional redaction for outputs (not tokenization)
        # This ensures PII never appears in stored artifacts or logs
        return self.pii_detector.redact_dict(data)

    def record_llm_usage(self, run_id: str, tokens: int, cost_usd: float) -> None:
        """
        Record LLM usage.

        Args:
            run_id: Run ID
            tokens: Tokens used
            cost_usd: Cost in USD
        """
        self.budget_tracker.record_tokens(run_id, tokens)
        self.budget_tracker.record_cost(run_id, cost_usd)

        self.logger.debug("llm_usage_recorded", run_id=run_id, tokens=tokens, cost_usd=cost_usd)

    def record_step(self, run_id: str) -> None:
        """
        Record step execution.

        Args:
            run_id: Run ID
        """
        self.budget_tracker.record_step(run_id)

    def get_budget_status(self, run_id: str) -> dict[str, Any]:
        """
        Get current budget status.

        Args:
            run_id: Run ID

        Returns:
            Dict with budget details
        """
        return self.budget_tracker.get_remaining(run_id)

    def initialize_run(self, run_id: str) -> None:
        """
        Initialize policy tracking for a run.

        Args:
            run_id: Run ID
        """
        self.budget_tracker.initialize_run(run_id)
        self.logger.info("run_initialized", run_id=run_id)

    def initialize_from_dsl(self, run_id: str, policies_dict: dict[str, Any]) -> None:
        """
        Initialize policy engine from DSL policies section.

        Args:
            run_id: Run identifier
            policies_dict: DSL policies section
        """
        # Extract budget limits. Use ``is not None`` so an explicit zero
        # (e.g. budget_usd: 0) is honored as "no budget" rather than being
        # treated as falsy and silently replaced by the default limit.
        budget_usd = policies_dict.get("budget_usd")
        if budget_usd is not None:
            self.budget_tracker.max_cost_usd = budget_usd
        max_tokens = policies_dict.get("max_tokens")
        if max_tokens is not None:
            self.budget_tracker.max_tokens = int(max_tokens)
        max_steps = policies_dict.get("max_steps")
        if max_steps is not None:
            self.budget_tracker.max_steps = int(max_steps)
        max_time_seconds = policies_dict.get("max_time_seconds")
        if max_time_seconds is not None:
            self.budget_tracker.max_time_seconds = int(max_time_seconds)

        # Extract rate limits.
        # The DSL/compiler shape is {tool_name: {rpm: N}}. We also accept
        # legacy top-level keys (calls_per_minute / calls_per_hour) for any
        # callers that build policies dicts by hand.
        rate_limits = policies_dict.get("rate_limits", {})
        per_tool_rpm: dict[str, int] = {}
        legacy_per_minute: int | None = None
        legacy_per_hour: int | None = None
        if isinstance(rate_limits, dict):
            for key, val in rate_limits.items():
                if key == "calls_per_minute" and isinstance(val, int):
                    legacy_per_minute = val
                elif key == "calls_per_hour" and isinstance(val, int):
                    legacy_per_hour = val
                elif isinstance(val, dict) and "rpm" in val:
                    per_tool_rpm[key] = int(val["rpm"])

        if legacy_per_minute is not None:
            self.rate_limiter.calls_per_minute = legacy_per_minute
        if legacy_per_hour is not None:
            self.rate_limiter.calls_per_hour = legacy_per_hour
        if per_tool_rpm:
            self.rate_limiter.per_tool_rpm = per_tool_rpm

        # Extract PII policy
        pii_config = policies_dict.get("pii", {})
        self.enforce_pii_redaction = not pii_config.get("allow", False)

        # Extract PII tokenization config
        self.tokenize_model_inputs = pii_config.get("tokenize_model_inputs", True)

        # Extract replan policy
        self.max_replan_attempts = int(policies_dict.get("max_replan_attempts", 3))

        # Extract PII exceptions (allow-lists per tool)
        exceptions = pii_config.get("exceptions", {})
        tools_exceptions = exceptions.get("tools", {})

        # Merge with defaults
        default_allow_lists = {
            # Common email tool paths
            "email_send": ["to", "from", "subject", "body"],
            # HTTP Authorization header
            "http_request": ["headers.Authorization"],
        }

        # User-provided exceptions override defaults
        self.pii_allow_lists = {**default_allow_lists, **tools_exceptions}

        # Convert allow lists to proper format if needed
        for tool_name, paths in self.pii_allow_lists.items():
            if isinstance(paths, dict):
                # Handle {"allow": ["path1", "path2"]} format
                self.pii_allow_lists[tool_name] = paths.get("allow", [])

        # Initialize run tracking
        self.initialize_run(run_id)

        self.logger.info(
            "policy_engine_initialized_from_dsl",
            run_id=run_id,
            budget_usd=budget_usd,
            rate_limits=rate_limits,
            pii_blocked=self.enforce_pii_redaction,
            tokenize_model_inputs=self.tokenize_model_inputs,
            pii_allow_lists=self.pii_allow_lists,
        )

    def clear_token_vault(self, run_id: str) -> None:
        """
        Clear token vault for a completed run.

        Args:
            run_id: Run identifier
        """
        if run_id in self._token_vaults:
            vault = self._token_vaults[run_id]
            stats = vault.get_stats()
            vault.clear()
            del self._token_vaults[run_id]
            self.logger.info("token_vault_cleared_for_run", run_id=run_id, stats=stats)

    def get_token_vault_stats(self, run_id: str) -> dict[str, Any] | None:
        """
        Get token vault statistics for a run.

        Args:
            run_id: Run identifier

        Returns:
            Vault statistics or None if vault doesn't exist
        """
        if run_id in self._token_vaults:
            return self._token_vaults[run_id].get_stats()
        return None

    def get_compliance_report(self, run_id: str) -> dict[str, Any]:
        """
        Generate compliance report for a run.

        Args:
            run_id: Run ID

        Returns:
            Dict with compliance metrics
        """
        budget_stats = self.budget_tracker.get_stats(run_id)
        rate_limit_stats = self.rate_limiter.get_stats(run_id)
        token_vault_stats = self.get_token_vault_stats(run_id)

        return {
            "run_id": run_id,
            "budget": budget_stats,
            "rate_limits": rate_limit_stats,
            "pii_tokenization": token_vault_stats,
            "policies_enforced": {
                "rate_limiting": True,
                "pii_detection": True,
                "pii_redaction": self.enforce_pii_redaction,
                "pii_tokenization": self.tokenize_model_inputs,
                "budget_tracking": True,
            },
        }


def create_default_policy_engine(
    max_tokens: int = 100000,
    max_cost_usd: float = 10.0,
    max_steps: int = 50,
    calls_per_minute: int = 10,
    calls_per_hour: int = 100,
    enforce_pii_redaction: bool = True,
) -> PolicyEngine:
    """
    Create a default policy engine with standard settings.

    Args:
        max_tokens: Max tokens per run
        max_cost_usd: Max cost per run
        max_steps: Max steps per run
        calls_per_minute: Max tool calls per minute
        calls_per_hour: Max tool calls per hour
        enforce_pii_redaction: Block calls with PII

    Returns:
        Configured PolicyEngine
    """
    rate_limiter = RateLimiter(calls_per_minute=calls_per_minute, calls_per_hour=calls_per_hour)

    pii_detector = PIIDetector()

    budget_tracker = BudgetTracker(
        max_tokens=max_tokens, max_cost_usd=max_cost_usd, max_steps=max_steps
    )

    engine = PolicyEngine(
        rate_limiter=rate_limiter,
        pii_detector=pii_detector,
        budget_tracker=budget_tracker,
        enforce_pii_redaction=enforce_pii_redaction,
    )

    logger.info(
        "default_policy_engine_created",
        max_tokens=max_tokens,
        max_cost_usd=max_cost_usd,
        max_steps=max_steps,
    )

    return engine
