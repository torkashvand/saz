"""Policy Engine - Coordinates all policy enforcement."""
import structlog
from typing import Dict, Any, Optional, List
from .rate_limiter import RateLimiter
from .pii_detector import PIIDetector
from .budget_tracker import BudgetTracker

logger = structlog.get_logger(__name__)


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
        rate_limiter: Optional[RateLimiter] = None,
        pii_detector: Optional[PIIDetector] = None,
        budget_tracker: Optional[BudgetTracker] = None,
        enforce_pii_redaction: bool = True
    ):
        self.rate_limiter = rate_limiter or RateLimiter()
        self.pii_detector = pii_detector or PIIDetector()
        self.budget_tracker = budget_tracker or BudgetTracker()
        self.enforce_pii_redaction = enforce_pii_redaction
        self.logger = logger.bind(component="policy_engine")

    def check_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        run_id: str
    ) -> tuple[bool, Optional[str]]:
        """
        Check if tool call is allowed.

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
                "tool_call_blocked_rate_limit",
                tool=tool_name,
                run_id=run_id,
                reason=reason
            )
            return False, f"Rate limit: {reason}"

        # Check budget
        within_budget, budget_reason = self.budget_tracker.check_budget(run_id)
        if not within_budget:
            self.logger.warning(
                "tool_call_blocked_budget",
                tool=tool_name,
                run_id=run_id,
                reason=budget_reason
            )
            return False, f"Budget exceeded: {budget_reason}"

        # Check for PII in arguments (warning only unless enforce_pii_redaction=True)
        pii_paths = self.pii_detector.scan_dict(arguments)
        if pii_paths:
            self.logger.warning(
                "pii_detected_in_tool_args",
                tool=tool_name,
                run_id=run_id,
                paths=pii_paths
            )
            if self.enforce_pii_redaction:
                return False, f"PII detected in arguments: {pii_paths}"

        self.logger.debug(
            "tool_call_allowed",
            tool=tool_name,
            run_id=run_id
        )

        return True, None

    def redact_output(
        self,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Redact PII from tool output.

        Args:
            data: Tool output

        Returns:
            Data with PII redacted
        """
        return self.pii_detector.redact_dict(data)

    def record_llm_usage(
        self,
        run_id: str,
        tokens: int,
        cost_usd: float
    ) -> None:
        """
        Record LLM usage.

        Args:
            run_id: Run ID
            tokens: Tokens used
            cost_usd: Cost in USD
        """
        self.budget_tracker.record_tokens(run_id, tokens)
        self.budget_tracker.record_cost(run_id, cost_usd)

        self.logger.debug(
            "llm_usage_recorded",
            run_id=run_id,
            tokens=tokens,
            cost_usd=cost_usd
        )

    def record_step(self, run_id: str) -> None:
        """
        Record step execution.

        Args:
            run_id: Run ID
        """
        self.budget_tracker.record_step(run_id)

    def get_budget_status(self, run_id: str) -> Dict[str, Any]:
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

    def get_compliance_report(self, run_id: str) -> Dict[str, Any]:
        """
        Generate compliance report for a run.

        Args:
            run_id: Run ID

        Returns:
            Dict with compliance metrics
        """
        budget_stats = self.budget_tracker.get_stats(run_id)
        rate_limit_stats = self.rate_limiter.get_stats(run_id)

        return {
            "run_id": run_id,
            "budget": budget_stats,
            "rate_limits": rate_limit_stats,
            "policies_enforced": {
                "rate_limiting": True,
                "pii_detection": True,
                "pii_redaction": self.enforce_pii_redaction,
                "budget_tracking": True
            }
        }


def create_default_policy_engine(
    max_tokens: int = 100000,
    max_cost_usd: float = 10.0,
    max_steps: int = 50,
    calls_per_minute: int = 10,
    calls_per_hour: int = 100,
    enforce_pii_redaction: bool = True
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
    rate_limiter = RateLimiter(
        calls_per_minute=calls_per_minute,
        calls_per_hour=calls_per_hour
    )

    pii_detector = PIIDetector()

    budget_tracker = BudgetTracker(
        max_tokens=max_tokens,
        max_cost_usd=max_cost_usd,
        max_steps=max_steps
    )

    engine = PolicyEngine(
        rate_limiter=rate_limiter,
        pii_detector=pii_detector,
        budget_tracker=budget_tracker,
        enforce_pii_redaction=enforce_pii_redaction
    )

    logger.info(
        "default_policy_engine_created",
        max_tokens=max_tokens,
        max_cost_usd=max_cost_usd,
        max_steps=max_steps
    )

    return engine
