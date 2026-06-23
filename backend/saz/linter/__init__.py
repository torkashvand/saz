"""Flow consistency linter.

Layered on top of ``compile_dsl`` as a separate authoring-time gate: the compiler
validates structure, the linter checks that natural-language prose and the
structured contract (schemas, params, guards) agree. See
``docs/superpowers/specs/2026-06-22-flow-consistency-linter-design.md``.
"""

from saz.linter.findings import LintCode, LintFinding, LintReport, Severity
from saz.linter.runner import lint_flow

__all__ = ["LintCode", "LintFinding", "LintReport", "Severity", "lint_flow"]
