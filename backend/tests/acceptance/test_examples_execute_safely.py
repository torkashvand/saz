"""Acceptance: every shipped example workflow at least compiles and registers.

This catches drift between the compiler, registered examples, and any
runtime contract change (like the bug #10 step-type cleanup) — if an
example stops compiling, this fails loudly. Actual end-to-end execution
of every example with fake tools/LLM is out of scope here; this is a
compile-and-register smoke test.
"""

from pathlib import Path

import pytest

_UNIFIED_DIR = (Path(__file__).parent.parent.parent / "saz" / "examples" / "unified").resolve()

_EXAMPLE_FILES = sorted(_UNIFIED_DIR.glob("*.yaml")) if _UNIFIED_DIR.exists() else []


def _strip_meta_section(yaml_content: str) -> str:
    """Strip the ``meta:`` block — examples carry workflow-author notes that
    the strict DSL schema rejects. Mirrors tests/examples/test_unified_templates.
    """
    if "meta:" not in yaml_content:
        return yaml_content
    lines = yaml_content.split("\n")
    out: list[str] = []
    in_meta = False
    for line in lines:
        if line.strip().startswith("meta:"):
            in_meta = True
            continue
        if in_meta:
            if line and not line.startswith((" ", "\t")):
                in_meta = False
            else:
                continue
        if not in_meta:
            out.append(line)
    return "\n".join(out)


@pytest.mark.parametrize(
    "yaml_path",
    _EXAMPLE_FILES,
    ids=[p.name for p in _EXAMPLE_FILES],
)
def test_example_compiles_and_registers(yaml_path: Path, app_client):
    yaml_text = _strip_meta_section(yaml_path.read_text())

    compile_resp = app_client.post("/api/v1/flows/compile", json={"yaml": yaml_text})
    assert compile_resp.status_code == 200, (
        f"Example {yaml_path.name} fails to compile: "
        f"{compile_resp.status_code} {compile_resp.text}"
    )

    register_resp = app_client.post("/api/v1/flows", json={"yaml": yaml_text})
    assert register_resp.status_code == 200, (
        f"Example {yaml_path.name} compiled but failed to register: "
        f"{register_resp.status_code} {register_resp.text}"
    )
