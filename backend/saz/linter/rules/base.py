"""LintRule protocol."""

from __future__ import annotations

from typing import Protocol

from saz.linter.context import LintContext
from saz.linter.findings import LintFinding


class LintRule(Protocol):
    code_prefix: str

    def check(self, ctx: LintContext) -> list[LintFinding]: ...
