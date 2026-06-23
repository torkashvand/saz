"""Drift guard: every shipped example flow must lint clean (no blocking
findings) under the deterministic rules.

Runs with run_llm=False so CI stays hermetic (no model calls). This would have
caught the change_approval_ansible prose/schema mismatch.
"""

from pathlib import Path

import pytest
import yaml

from saz.linter import lint_flow

_EXAMPLES_DIR = Path(__file__).parent.parent.parent / "saz" / "examples"


def _example_files() -> list[Path]:
    return sorted(p for p in _EXAMPLES_DIR.rglob("*.y*ml"))


@pytest.mark.parametrize("path", _example_files(), ids=lambda p: p.name)
def test_example_lints_clean(path: Path):
    dsl = yaml.safe_load(path.read_text())
    if not isinstance(dsl, dict) or "workflow" not in dsl:
        pytest.skip(f"{path.name} is not a flow definition")
    report = lint_flow(dsl, run_llm=False)
    blocking = report.blocking
    assert not blocking, "\n".join(
        f"{f.code.value} [{f.step_id}.{f.field}]: {f.message}" for f in blocking
    )
