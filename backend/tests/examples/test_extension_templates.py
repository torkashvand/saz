"""Extension-only example workflows must still be valid DSL.

Files under saz/examples/extensions/ demonstrate patterns that need custom
tools not in the default registry. They are NOT auto-loaded as templates, but
they must still compile (so the documented pattern is real) and must clearly
flag themselves as extension-only so nobody mistakes them for runnable demos.
"""

from pathlib import Path

import pytest
import yaml

from saz.compiler import compile_dsl

EXT_DIR = Path(__file__).parent.parent.parent / "saz" / "examples" / "extensions"


def discover_extensions():
    return list(EXT_DIR.glob("*.yaml"))


@pytest.mark.parametrize("path", discover_extensions())
def test_extension_compiles(path):
    compiled = compile_dsl(path.read_text(encoding="utf-8"))
    assert compiled is not None
    assert compiled.flow_name


@pytest.mark.parametrize("path", discover_extensions())
def test_extension_is_flagged_extension_only(path):
    """An extension example must self-identify so it is never presented as a
    ready-to-run demo (the custom tools it documents are not registered)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    meta = raw.get("meta", {})
    assert meta.get("extension_only") is True, f"{path.name} must set meta.extension_only: true"


def test_at_least_one_extension_exists():
    assert discover_extensions(), "expected at least one extension example"
