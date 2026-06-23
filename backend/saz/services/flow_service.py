"""Flow service - business logic for flow operations."""

import yaml

from saz.api.errors import FlowLintError
from saz.compiler import compile_dsl
from saz.db.unit_of_work import UnitOfWork
from saz.linter import LintReport, lint_flow
from saz.repositories.read.dtos import FlowDetailDTO, FlowListItemDTO
from saz.settings import settings


def _validate_tool_references(dsl: dict) -> None:
    """Reject ``tool.call`` steps that name a tool the registry does not know.

    Catches typos (e.g. ``artifact_store`` vs ``artifact.store``) at register
    time instead of at execute time. Skipped when the global registry is not
    initialized (e.g. isolated unit tests) — the executor still fails closed
    on unknown tools at grounding.
    """
    try:
        from saz.globals import get_tool_registry

        known = set(get_tool_registry().list_tools())
    except RuntimeError:
        return

    steps = (dsl.get("workflow") or {}).get("steps") or []
    unknown = sorted(
        {
            s["tool"]
            for s in steps
            if isinstance(s, dict) and s.get("type") == "tool.call" and s.get("tool") not in known
        }
    )
    if unknown:
        raise ValueError(
            f"Unknown tool(s) in tool.call steps: {unknown}. Registered tools: {sorted(known)}."
        )


def _lint_and_raise(dsl: dict) -> None:
    """Run the consistency linter and block the write on any blocking finding.

    All findings (including warnings and suppressed ones) are attached to the
    error so consumers can render the full picture, but only ``report.blocking``
    determines whether the write is rejected.
    """
    report = lint_flow(dsl, run_llm=settings.LINT_LLM_ENABLED)
    if report.blocking:
        raise FlowLintError(
            f"Flow has {len(report.blocking)} consistency error(s)",
            findings=[f.model_dump(mode="json") for f in report.findings],
            llm_ran=report.llm_ran,
        )


class FlowService:
    """Service for flow operations."""

    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    def lint(self, yaml_content: str) -> LintReport:
        """Compile + lint a flow without persisting (powers POST /flows/lint).

        Raises ValueError on a structurally invalid DSL (compile failure) so the
        route can surface compile errors distinctly from lint findings.
        """
        try:
            dsl = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {e}") from None
        compile_dsl(yaml_content)
        _validate_tool_references(dsl)
        return lint_flow(dsl, run_llm=settings.LINT_LLM_ENABLED)

    def register(self, yaml_content: str, created_by_user_id: str) -> str:
        """Register a new flow from YAML DSL.

        Runs the full DSL compiler before persisting so /flows and
        /flows/compile agree on what's valid. Invalid workflows fail at
        register time with a clear error instead of being saved and crashing
        the executor later.

        Execution contract: the compiler is a *validation + normalization gate*.
        The runtime executes the raw, validated DSL (``flow.definition``), not
        the compiled artifact — see WorkflowExecutor.execute_run which reads
        ``definition["workflow"]`` / ``definition["policies"]`` directly, and
        PolicyEngine.initialize_from_dsl which reads the raw policies. The
        compiler's normalized policy shape (``compile_policies``) is kept in
        sync with what the runtime enforces so the two never diverge; a
        regression test pins this equivalence.
        """
        # Parse YAML for an early friendly error before compile_dsl runs its
        # own parser (compile_dsl also catches yaml errors but the message is
        # less actionable than this one for clients).
        try:
            dsl = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {e}") from None

        # Full compile: validates schema, step types, templates, expect
        # schemas, credential refs, etc. Raises ValueError on any failure.
        compile_dsl(yaml_content)
        _validate_tool_references(dsl)
        _lint_and_raise(dsl)

        # Extract metadata
        flow_meta = dsl.get("flow", {})
        name = flow_meta.get("name")
        if not name:
            raise ValueError("Flow name is required")

        version = flow_meta.get("version")
        description = flow_meta.get("description")

        # Check if flow exists
        assert self.uow.flows is not None
        existing = self.uow.flows.get_by_name(name)

        if existing:
            # Update existing flow — keep the original creator on the row.
            flow = self.uow.flows.update_definition(name, dsl, version, description, yaml_content)
            assert flow is not None
            self.uow.commit()
            return flow.id
        else:
            flow = self.uow.flows.create(
                name=name,
                definition=dsl,
                version=version,
                description=description,
                source_yaml=yaml_content,
                created_by_user_id=created_by_user_id,
            )
            self.uow.commit()
            return flow.id

    def update_by_id(self, flow_id: str, yaml_content: str) -> str:
        """Update an existing flow by its ID.

        Identified by row id (not by flow name) so renaming a flow does not
        create a new row. Validates the YAML through the compiler first so a
        bad payload cannot wipe a working flow.
        """

        try:
            dsl = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML: {e}") from None

        compile_dsl(yaml_content)
        _validate_tool_references(dsl)
        _lint_and_raise(dsl)

        flow_meta = dsl.get("flow", {})
        name = flow_meta.get("name")
        if not name:
            raise ValueError("Flow name is required")
        version = flow_meta.get("version")
        description = flow_meta.get("description")

        assert self.uow.flows is not None
        flow = self.uow.flows.update_by_id(
            flow_id=flow_id,
            new_name=name,
            definition=dsl,
            version=version,
            description=description,
            source_yaml=yaml_content,
        )
        if flow is None:
            raise LookupError(f"Flow not found: {flow_id}")
        self.uow.commit()
        return flow.id

    def get(self, flow_id: str) -> FlowDetailDTO | None:
        """Get flow detail."""
        assert self.uow.flow_reads is not None
        return self.uow.flow_reads.detail(flow_id)

    def get_by_name(self, name: str) -> FlowDetailDTO | None:
        """Get flow by name."""
        assert self.uow.flow_reads is not None
        return self.uow.flow_reads.get_by_name(name)

    def list(self, limit: int = 100, offset: int = 0) -> tuple[list[FlowListItemDTO], int]:
        """List flows."""
        assert self.uow.flow_reads is not None
        return self.uow.flow_reads.list(limit, offset)
