# RFQ/RFP Drafting Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Saz POC that turns structured project + procurement intake into a formatted GÉANT RFQ `.docx`, gated by budget/PONT checks, procurement review, optional market consultation, and dual sign-off.

**Architecture:** One deterministic Saz workflow (`rfq_rfp_drafting.yaml`) using existing primitives, plus one new tool `docx_render` that fills a tokenized copy of the real GÉANT template. A one-time build script derives the tokenized template (`{{token}}` markers) from the original `.docx`, preserving all formatting. A canonical token list shared by the build script, the tool tests, and the workflow keeps names consistent.

**Tech Stack:** Python 3.12, `python-docx`, pytest, Saz DSL (YAML), `uv`.

---

## File Structure

| Path | Responsibility |
|---|---|
| `backend/pyproject.toml` | Add `python-docx` dependency. |
| `backend/saz/examples/templates/rfq_tokens.py` | Single source of truth: canonical token names + ordered source-text hints for the build script. |
| `backend/saz/examples/templates/build_rfq_template.py` | One-time/repeatable: derive tokenized `rfq_template.docx` + `rfq_placeholder_map.md` from the original. |
| `backend/saz/examples/templates/rfq_template.docx` | Generated tokenized template (committed artifact). |
| `backend/saz/tools/docx_tool.py` | `DocxRenderTool`: fill tokens in a `.docx`, write output file, report unfilled tokens. |
| `backend/saz/tools/registry.py` | Register `docx_render` in `ToolRegistry.__init__` + `create_default_registry`. |
| `backend/saz/examples/unified/rfq_rfp_drafting.yaml` | The workflow (auto-discovered by example tests). |
| `backend/tests/unit/test_rfq_tokens.py` | Token list / hint integrity. |
| `backend/tests/unit/test_docx_tool.py` | Tool behavior (fill, unfilled, require_all, missing template, artifact write). |
| `backend/tests/unit/test_build_rfq_template.py` | Run-merge/replace helper behavior. |
| `backend/tests/examples/test_rfq_rfp_workflow.py` | Workflow compiles cleanly + structural contract (gates, dual approvals, render steps). |
| `backend/tests/integration/test_rfq_render_end_to_end.py` | Render tool fills the real tokenized template with canned values; all mandatory tokens filled. |
| `docs/procurement/rfq_placeholder_map.md` | token ↔ form field ↔ template section (generated + curated). |
| `docs/procurement/rfq_workflow_guide.md` | Usage & testing guide for project/procurement teams. |
| `docs/procurement/examples/` | Generated DRAFT + FINAL `.docx` example outputs. |
| `scripts/generate_rfq_example.py` | Produce the example outputs from HRIS test data (no LLM). |

---

## Canonical token list (used across tasks)

Tokens are referenced verbatim in the build script, the workflow YAML, and tests:

```
title_system_name, date_of_issue, version, reference_number,
contact_name, contact_role, contact_phone, contact_email,
background, objective, scope,
plan_rfq_issued, plan_clarification_deadline, plan_response_deadline,
plan_eval1_end, plan_eval2_end, plan_awarding, plan_commencement,
minimum_requirements,
weight_qualitative, q1_weight, q2_weight, q3_weight,
weight_price, budget_cap_licenses, budget_cap_implementation
```

---

### Task 1: Add `python-docx` dependency

**Files:**
- Modify: `backend/pyproject.toml` (dependencies array)

- [ ] **Step 1: Add the dependency**

In `backend/pyproject.toml`, add `"python-docx>=1.1.2"` to the `[project] dependencies` list (keep alphabetical order if the list is sorted).

- [ ] **Step 2: Sync and verify import**

Run: `cd backend && uv sync && uv run python -c "import docx; print(docx.__version__)"`
Expected: prints a version like `1.1.2` (no `ModuleNotFoundError`).

- [ ] **Step 3: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "build: add python-docx dependency"
```

---

### Task 2: Canonical token module

**Files:**
- Create: `backend/saz/examples/templates/rfq_tokens.py`
- Test: `backend/tests/unit/test_rfq_tokens.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_rfq_tokens.py
from saz.examples.templates.rfq_tokens import RFQ_TOKENS, TOKEN_SOURCE_HINTS


def test_tokens_are_unique_and_nonempty():
    assert RFQ_TOKENS, "token list must not be empty"
    assert len(RFQ_TOKENS) == len(set(RFQ_TOKENS)), "tokens must be unique"
    assert all(t and t.islower() for t in RFQ_TOKENS)


def test_every_hint_maps_to_a_known_token():
    for substring, token in TOKEN_SOURCE_HINTS:
        assert substring, "hint substring must not be empty"
        assert token in RFQ_TOKENS, f"hint maps to unknown token {token!r}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_rfq_tokens.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'saz.examples.templates.rfq_tokens'`.

- [ ] **Step 3: Create the module**

```python
# backend/saz/examples/templates/rfq_tokens.py
"""Canonical token names for the GÉANT RFQ template and the ordered hints the
build script uses to map highlighted source spans to those tokens."""

RFQ_TOKENS: list[str] = [
    "title_system_name",
    "date_of_issue",
    "version",
    "reference_number",
    "contact_name",
    "contact_role",
    "contact_phone",
    "contact_email",
    "background",
    "objective",
    "scope",
    "plan_rfq_issued",
    "plan_clarification_deadline",
    "plan_response_deadline",
    "plan_eval1_end",
    "plan_eval2_end",
    "plan_awarding",
    "plan_commencement",
    "minimum_requirements",
    "weight_qualitative",
    "q1_weight",
    "q2_weight",
    "q3_weight",
    "weight_price",
    "budget_cap_licenses",
    "budget_cap_implementation",
]

# Ordered (case-insensitive substring of the highlighted span's text -> token).
# First match wins; the build script applies these to assign semantic tokens.
TOKEN_SOURCE_HINTS: list[tuple[str, str]] = [
    ("badreddine", "contact_name"),
    ("buyer", "contact_role"),
    ("+31", "contact_phone"),
    ("@", "contact_email"),
    ("objective for this procurement", "objective"),
    ("focus will be on securing", "scope"),
    ("rfq issued", "plan_rfq_issued"),
    ("clarification questions", "plan_clarification_deadline"),
    ("quotation responses", "plan_response_deadline"),
    ("end of evaluation phase 1", "plan_eval1_end"),
    ("end of evaluation phase 2", "plan_eval2_end"),
    ("awarding finalized", "plan_awarding"),
    ("commencement date", "plan_commencement"),
    ("system integrates with sso", "minimum_requirements"),
    ("qualitative criteria will make up", "weight_qualitative"),
    ("q1: user experience", "q1_weight"),
    ("q2: technical support", "q2_weight"),
    ("q3: data management", "q3_weight"),
    ("price will make up", "weight_price"),
    ("20.000", "budget_cap_licenses"),
    ("10.000", "budget_cap_implementation"),
    ("t88815", "reference_number"),
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/test_rfq_tokens.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/saz/examples/templates/rfq_tokens.py backend/tests/unit/test_rfq_tokens.py
git commit -m "feat(rfq): add canonical RFQ template token module"
```

---

### Task 3: Run-merge/replace helper for the build script

The original `.docx` fragments highlighted text into many tiny runs. This helper collapses each paragraph's contiguous highlighted runs into a single run and replaces its text with a `{{token}}` marker, preserving the first run's formatting.

**Files:**
- Create: `backend/saz/examples/templates/build_rfq_template.py` (helper only in this task)
- Test: `backend/tests/unit/test_build_rfq_template.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/test_build_rfq_template.py
from docx import Document
from docx.enum.text import WD_COLOR_INDEX

from saz.examples.templates.build_rfq_template import replace_highlighted_spans


def _highlight(run):
    run.font.highlight_color = WD_COLOR_INDEX.YELLOW


def test_collapses_contiguous_highlighted_runs_into_one_token():
    doc = Document()
    p = doc.add_paragraph()
    p.add_run("Objective: ")  # not highlighted
    r1 = p.add_run("find a HR system ")
    r2 = p.add_run("that is cost effective")
    _highlight(r1)
    _highlight(r2)

    n = replace_highlighted_spans(
        doc, hints=[("find a hr system", "objective")]
    )

    assert n == 1
    text = "".join(r.text for r in p.runs)
    assert text == "Objective: {{objective}}"


def test_unmatched_span_gets_extra_token_and_is_reported():
    doc = Document()
    p = doc.add_paragraph()
    r = p.add_run("Some variable value")
    _highlight(r)

    n = replace_highlighted_spans(doc, hints=[])

    assert n == 1
    assert "{{extra_1}}" in "".join(run.text for run in p.runs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_build_rfq_template.py -q`
Expected: FAIL — `ImportError: cannot import name 'replace_highlighted_spans'`.

- [ ] **Step 3: Implement the helper**

```python
# backend/saz/examples/templates/build_rfq_template.py
"""Derive a tokenized RFQ template (and placeholder map) from the original
GÉANT RFQ .docx. Highlighted spans become {{token}} markers; original
formatting is preserved by reusing the first run of each span."""

from __future__ import annotations

import argparse
from pathlib import Path

from docx import Document
from docx.text.paragraph import Paragraph


def _is_highlighted(run) -> bool:
    color = run.font.highlight_color
    return color is not None and str(color).lower() != "none"


def _match_token(text: str, hints: list[tuple[str, str]]) -> str | None:
    low = text.lower()
    for substring, token in hints:
        if substring.lower() in low:
            return token
    return None


def _replace_in_paragraph(
    paragraph: Paragraph, hints: list[tuple[str, str]], counters: dict[str, int]
) -> int:
    """Collapse each contiguous highlighted run-span into one {{token}} run."""
    runs = paragraph.runs
    replaced = 0
    i = 0
    while i < len(runs):
        if not _is_highlighted(runs[i]):
            i += 1
            continue
        j = i
        while j + 1 < len(runs) and _is_highlighted(runs[j + 1]):
            j += 1
        span_text = "".join(r.text for r in runs[i : j + 1])
        token = _match_token(span_text, hints)
        if token is None:
            counters["extra"] += 1
            token = f"extra_{counters['extra']}"
        runs[i].text = f"{{{{{token}}}}}"
        for k in range(i + 1, j + 1):
            runs[k].text = ""
        replaced += 1
        i = j + 1
    return replaced


def replace_highlighted_spans(doc, hints: list[tuple[str, str]]) -> int:
    """Replace every highlighted span in the document body with a token.
    Returns the number of spans replaced."""
    counters = {"extra": 0}
    total = 0
    for paragraph in doc.paragraphs:
        total += _replace_in_paragraph(paragraph, hints, counters)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    total += _replace_in_paragraph(paragraph, hints, counters)
    return total
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/unit/test_build_rfq_template.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/saz/examples/templates/build_rfq_template.py backend/tests/unit/test_build_rfq_template.py
git commit -m "feat(rfq): add highlighted-span tokenizer helper"
```

---

### Task 4: Build-script CLI + generate the tokenized template

**Files:**
- Modify: `backend/saz/examples/templates/build_rfq_template.py` (add `main()`)
- Create (generated): `backend/saz/examples/templates/rfq_template.docx`
- Create (generated): `docs/procurement/rfq_placeholder_map.md`

- [ ] **Step 1: Add the CLI + map emitter**

Append to `build_rfq_template.py`:

```python
def build(source: Path, out_docx: Path, out_map: Path) -> dict[str, int]:
    from saz.examples.templates.rfq_tokens import RFQ_TOKENS, TOKEN_SOURCE_HINTS

    doc = Document(str(source))
    replaced = replace_highlighted_spans(doc, TOKEN_SOURCE_HINTS)
    out_docx.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_docx))

    # Which canonical tokens actually landed in the template?
    rendered = Document(str(out_docx))
    body_text = "\n".join(p.text for p in rendered.paragraphs)
    for table in rendered.tables:
        for row in table.rows:
            for cell in row.cells:
                body_text += "\n" + cell.text
    present = [t for t in RFQ_TOKENS if f"{{{{{t}}}}}" in body_text]
    missing = [t for t in RFQ_TOKENS if t not in present]

    lines = ["# RFQ Placeholder Map", "", "| Token | In template | Notes |", "|---|---|---|"]
    for t in RFQ_TOKENS:
        lines.append(f"| `{{{{{t}}}}}` | {'yes' if t in present else 'NO'} | |")
    out_map.parent.mkdir(parents=True, exist_ok=True)
    out_map.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {"replaced": replaced, "present": len(present), "missing": len(missing)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build tokenized RFQ template.")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument(
        "--out-docx",
        type=Path,
        default=Path(__file__).parent / "rfq_template.docx",
    )
    parser.add_argument(
        "--out-map",
        type=Path,
        default=Path(__file__).resolve().parents[4]
        / "docs"
        / "procurement"
        / "rfq_placeholder_map.md",
    )
    args = parser.parse_args()
    stats = build(args.source, args.out_docx, args.out_map)
    print(f"replaced={stats['replaced']} present={stats['present']} missing={stats['missing']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Generate the template from the real source**

Run:
```bash
cd backend && uv run python -m saz.examples.templates.build_rfq_template \
  --source "$HOME/Documents/saz/(EXAMPLE) RFQ HRIS System.docx"
```
Expected: prints `replaced=<N> present=<M> missing=<K>`.

- [ ] **Step 3: Inspect coverage and tighten hints if needed**

Open `docs/procurement/rfq_placeholder_map.md`. For every token marked `NO`, inspect the generated `rfq_template.docx` (open in Word/LibreOffice or dump paragraph text) and adjust the matching substring in `TOKEN_SOURCE_HINTS` (Task 2) so the span is captured, then re-run Step 2. Add a one-line note in the map's Notes column for tokens intentionally left as fixed text (e.g. an evaluation-phase paragraph kept static for the POC). Goal: every token in `RFQ_TOKENS` is either `yes` or has an explicit Notes justification.

- [ ] **Step 4: Commit the template + map**

```bash
git add backend/saz/examples/templates/build_rfq_template.py \
        backend/saz/examples/templates/rfq_template.docx \
        docs/procurement/rfq_placeholder_map.md
git commit -m "feat(rfq): generate tokenized RFQ template and placeholder map"
```

---

### Task 5: `docx_render` tool

**Files:**
- Create: `backend/saz/tools/docx_tool.py`
- Test: `backend/tests/unit/test_docx_tool.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_docx_tool.py
import pytest
from docx import Document

from saz.tools.docx_tool import DocxRenderTool


def _make_template(tmp_path, body: str):
    path = tmp_path / "tpl.docx"
    doc = Document()
    doc.add_paragraph(body)
    doc.save(str(path))
    return str(path)


@pytest.mark.asyncio
async def test_fills_tokens_and_stores_artifact(tmp_path):
    tpl = _make_template(tmp_path, "Objective: {{objective}}")
    tool = DocxRenderTool(storage_path=str(tmp_path / "art"))

    result = await tool.render(
        template=tpl,
        values={"objective": "Find a modern HR system"},
        output_name="draft_rfq",
        run_id="r1",
        step_id="s1",
    )

    assert result["filled"] == 1
    assert result["unfilled"] == []
    rendered = Document(result["path"])
    assert rendered.paragraphs[0].text == "Objective: Find a modern HR system"


@pytest.mark.asyncio
async def test_reports_unfilled_and_fails_when_require_all(tmp_path):
    tpl = _make_template(tmp_path, "A {{objective}} B {{scope}}")
    tool = DocxRenderTool(storage_path=str(tmp_path / "art"))

    with pytest.raises(ValueError) as exc:
        await tool.render(
            template=tpl,
            values={"objective": "x"},
            output_name="draft",
            require_all=True,
        )
    assert "scope" in str(exc.value)


@pytest.mark.asyncio
async def test_reports_unfilled_without_failing_when_not_require_all(tmp_path):
    tpl = _make_template(tmp_path, "A {{objective}} B {{scope}}")
    tool = DocxRenderTool(storage_path=str(tmp_path / "art"))

    result = await tool.render(
        template=tpl, values={"objective": "x"}, output_name="draft", require_all=False
    )
    assert result["unfilled"] == ["scope"]


@pytest.mark.asyncio
async def test_missing_template_raises(tmp_path):
    tool = DocxRenderTool(storage_path=str(tmp_path / "art"))
    with pytest.raises(FileNotFoundError):
        await tool.render(template=str(tmp_path / "nope.docx"), values={}, output_name="x")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_docx_tool.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'saz.tools.docx_tool'`.

- [ ] **Step 3: Implement the tool**

```python
# backend/saz/tools/docx_tool.py
"""Document render tool: fill {{token}} markers in a .docx template."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog
from docx import Document
from docx.text.paragraph import Paragraph

logger = structlog.get_logger(__name__)

_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


class DocxRenderTool:
    """Fill {{token}} markers in a .docx and write the result to storage."""

    def __init__(self, storage_path: str = "/tmp/saz/artifacts"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.logger = logger.bind(tool="docx_render")

    @property
    def spec(self) -> dict[str, Any]:
        return {
            "name": "docx_render",
            "description": "Fill {{token}} placeholders in a .docx template and store the result.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "template": {"type": "string", "description": "Path to the tokenized .docx."},
                    "values": {
                        "type": "object",
                        "description": "Map of token name -> replacement string.",
                        "additionalProperties": True,
                    },
                    "output_name": {"type": "string", "description": "Name for the rendered file."},
                    "require_all": {
                        "type": "boolean",
                        "default": True,
                        "description": "Fail if any token is left unfilled.",
                    },
                },
                "required": ["template", "values", "output_name"],
            },
        }

    def _fill_paragraph(self, paragraph: Paragraph, values: dict[str, str]) -> int:
        filled = 0
        for run in paragraph.runs:
            if "{{" not in run.text:
                continue

            def repl(match: re.Match[str]) -> str:
                nonlocal filled
                token = match.group(1)
                if token in values:
                    filled += 1
                    return str(values[token])
                return match.group(0)

            run.text = _TOKEN_RE.sub(repl, run.text)
        return filled

    @staticmethod
    def _remaining_tokens(doc: Document) -> list[str]:
        found: list[str] = []

        def scan(paragraph: Paragraph) -> None:
            for m in _TOKEN_RE.finditer(paragraph.text):
                if m.group(1) not in found:
                    found.append(m.group(1))

        for p in doc.paragraphs:
            scan(p)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        scan(p)
        return found

    async def render(
        self,
        template: str,
        values: dict[str, Any],
        output_name: str,
        require_all: bool = True,
        run_id: str = "",
        step_id: str = "",
    ) -> dict[str, Any]:
        template_path = Path(template)
        if not template_path.exists():
            raise FileNotFoundError(f"Template not found: {template}")

        str_values = {k: ("" if v is None else str(v)) for k, v in values.items()}
        doc = Document(str(template_path))

        filled = 0
        for p in doc.paragraphs:
            filled += self._fill_paragraph(p, str_values)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        filled += self._fill_paragraph(p, str_values)

        unfilled = self._remaining_tokens(doc)
        if require_all and unfilled:
            raise ValueError(f"Unfilled mandatory tokens: {', '.join(unfilled)}")

        artifact_id = str(uuid4())
        out_path = self.storage_path / f"{artifact_id}_{output_name}.docx"
        doc.save(str(out_path))

        self.logger.info(
            "docx.rendered",
            artifact_id=artifact_id,
            output_name=output_name,
            filled=filled,
            unfilled=len(unfilled),
            run_id=run_id,
            step_id=step_id,
            path=str(out_path),
        )

        return {
            "artifact_id": artifact_id,
            "name": output_name,
            "path": str(out_path),
            "filled": filled,
            "unfilled": unfilled,
            "byte_size": out_path.stat().st_size,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_docx_tool.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/saz/tools/docx_tool.py backend/tests/unit/test_docx_tool.py
git commit -m "feat(tools): add docx_render tool"
```

---

### Task 6: Register `docx_render` in the tool registry

**Files:**
- Modify: `backend/saz/tools/registry.py`
- Test: `backend/tests/unit/test_docx_tool.py` (add a registry test)

- [ ] **Step 1: Add the failing registry test**

Append to `backend/tests/unit/test_docx_tool.py`:

```python
def test_docx_render_in_default_registry():
    from saz.tools.registry import create_default_registry

    registry = create_default_registry(enable_ai_ops=False)
    assert "docx_render" in registry.list_tools()
    assert registry.get_tool_spec("docx_render")["name"] == "docx_render"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_docx_tool.py::test_docx_render_in_default_registry -q`
Expected: FAIL — `assert 'docx_render' in [...]`.

- [ ] **Step 3: Wire the tool into the registry**

In `backend/saz/tools/registry.py`:

1. Add the import near the other tool imports (line ~9-12):
```python
from .docx_tool import DocxRenderTool
```

2. Add a register method after `register_ansible_tool` (after line ~168):
```python
    def register_docx_tool(self, docx_tool: DocxRenderTool) -> None:
        """Register docx render tool"""
        self._tools["docx_render"] = docx_tool.spec
        self._executors["docx_render"] = docx_tool.render
        self.logger.info("tool_registered", tool="docx_render")
```

3. Extend `ToolRegistry.__init__` signature and body to accept and register it:
```python
        ansible_tool: AnsibleTool | None = None,
        docx_tool: DocxRenderTool | None = None,
    ):
```
and after the `ansible_tool` registration block:
```python
        if docx_tool:
            self.register_docx_tool(docx_tool)
```

4. In `create_default_registry`, instantiate and pass it. After the `ansible_tool = AnsibleTool(...)` block:
```python
    docx_tool = DocxRenderTool(storage_path=artifact_storage_path)
```
and add `docx_tool=docx_tool,` to the `ToolRegistry(...)` constructor call.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_docx_tool.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/saz/tools/registry.py backend/tests/unit/test_docx_tool.py
git commit -m "feat(tools): register docx_render in tool registry"
```

---

### Task 7: Author the workflow YAML

**Files:**
- Create: `backend/saz/examples/unified/rfq_rfp_drafting.yaml`

- [ ] **Step 1: Write the workflow**

Create the file with this content (template path is resolved at run time via `$env` with a default to the bundled template):

```yaml
schema_version: 1

meta:
  id: rfq_rfp_drafting
  title: RFQ/RFP Drafting (GÉANT procurement)
  description: Draft a GÉANT RFQ from project + procurement intake, gated by budget/PONT and dual sign-off.
  tags: ["procurement", "rfq", "document-generation"]
  complexity: advanced

flow:
  name: rfq_rfp_drafting
  description: Generate a formatted GÉANT RFQ document from structured intake with compliance gates and approvals.

form:
  fields:
    # --- Project team ---
    - name: project_name
      type: string
      required: true
    - name: objective_input
      type: text
      required: true
      description: Raw objective summary from the project team.
    - name: scope_input
      type: text
      required: true
    - name: background_input
      type: text
      required: true
    - name: technical_requirements
      type: text
      required: true
    - name: criticality
      type: string
      required: true
      enum: [low, medium, high]
    - name: num_users
      type: integer
      required: true
      minimum: 1
    - name: data_sensitivity
      type: string
      required: true
      enum: [none, internal, confidential, highly_confidential]
    - name: estimated_value_eur
      type: number
      required: true
      minimum: 0
    - name: contract_duration
      type: string
      required: true
    - name: vendor_constraints
      type: text
      required: false
    # --- Procurement team ---
    - name: pricing_model
      type: string
      required: true
      enum: [per_user, fixed_fee, time_and_materials, subscription]
    - name: budget_cap_licenses_eur
      type: number
      required: true
      minimum: 0
    - name: budget_cap_implementation_eur
      type: number
      required: true
      minimum: 0
    - name: sourcing_strategy
      type: string
      required: true
    - name: gdpr_data_residency
      type: text
      required: true
    - name: security_requirements
      type: text
      required: true
    - name: minimum_requirements
      type: text
      required: true
      description: One requirement per line.
    - name: weight_qualitative_pct
      type: integer
      required: true
      minimum: 0
      maximum: 100
    - name: weight_price_pct
      type: integer
      required: true
      minimum: 0
      maximum: 100
    - name: q1_pct
      type: integer
      required: true
      minimum: 0
      maximum: 100
    - name: q2_pct
      type: integer
      required: true
      minimum: 0
      maximum: 100
    - name: q3_pct
      type: integer
      required: true
      minimum: 0
      maximum: 100
    - name: reference_number
      type: string
      required: true
    - name: date_of_issue
      type: string
      required: true
    - name: deadline_clarification
      type: string
      required: true
    - name: deadline_response
      type: string
      required: true
    - name: eval1_end
      type: string
      required: true
    - name: eval2_end
      type: string
      required: true
    - name: awarding_date
      type: string
      required: true
    - name: commencement_date
      type: string
      required: true
    - name: contact_name
      type: string
      required: true
    - name: contact_role
      type: string
      required: true
    - name: contact_phone
      type: string
      required: true
    - name: contact_email
      type: string
      required: true
      format: email
    - name: consultation_required
      type: boolean
      required: true
      default: false

workflow:
  planner_mode: deterministic
  steps:
    - id: validate_inputs
      type: ai.extract
      description: Structure and validate the combined intake.
      instruction: |
        Review the procurement intake. Return:
        - missing_fields: names of mandatory fields that are empty or placeholder-like.
        - inconsistencies: short phrases describing contradictions (e.g. high criticality with near-zero budget).
        - high_level_requirements: technical requirements that are high-level.
        - detailed_requirements: technical requirements that are specific/testable.
        Do not invent requirements; only classify what is provided.
      params:
        data:
          project_name: "{{ $form.project_name }}"
          objective: "{{ $form.objective_input }}"
          scope: "{{ $form.scope_input }}"
          technical_requirements: "{{ $form.technical_requirements }}"
          criticality: "{{ $form.criticality }}"
          estimated_value_eur: "{{ $form.estimated_value_eur }}"
          minimum_requirements: "{{ $form.minimum_requirements }}"
      expect:
        type: object
        additionalProperties: false
        properties:
          missing_fields:
            type: array
            items: { type: string }
          inconsistencies:
            type: array
            items: { type: string }
          high_level_requirements:
            type: array
            items: { type: string }
          detailed_requirements:
            type: array
            items: { type: string }
        required: [missing_fields, inconsistencies, high_level_requirements, detailed_requirements]
      temperature: 0.1
      max_tokens: 1024

    - id: gate_budget
      type: condition
      description: Confirm budget caps, required fields, and that weights sum to 100.
      if: |
        {{ $form.budget_cap_licenses_eur <= 20000 && $form.budget_cap_implementation_eur <= 10000 && $form.estimated_value_eur < 100000 && (($form.weight_qualitative_pct + $form.weight_price_pct) == 100) && (($form.q1_pct + $form.q2_pct + $form.q3_pct) == 100) }}

    - id: pont_check
      type: ai.evaluate
      description: Assess procurement inputs against PONT principles.
      instruction: |
        Evaluate the procurement inputs against PONT:
        - Proportional: requirements proportionate to value/criticality.
        - Objective: criteria measurable, not arbitrary.
        - Non-discriminatory: no clauses that unfairly exclude EU suppliers.
        - Transparent: scoring weights and thresholds clearly stated.
        Return pass=false if any principle is materially violated; list concrete issues.
      params:
        data:
          minimum_requirements: "{{ $form.minimum_requirements }}"
          security_requirements: "{{ $form.security_requirements }}"
          gdpr_data_residency: "{{ $form.gdpr_data_residency }}"
          sourcing_strategy: "{{ $form.sourcing_strategy }}"
          weights:
            qualitative: "{{ $form.weight_qualitative_pct }}"
            price: "{{ $form.weight_price_pct }}"
      expect:
        type: object
        additionalProperties: false
        properties:
          pass: { type: boolean }
          issues:
            type: array
            items: { type: string }
        required: [pass, issues]
      temperature: 0.1
      max_tokens: 768

    - id: draft_narrative
      type: ai.generate
      description: Draft formal background, objective, and scope prose.
      instruction: |
        Write formal procurement prose for a GÉANT RFQ using ONLY the provided inputs.
        Do not invent facts, numbers, vendors, or requirements.
        Produce three fields: background, objective, scope. Keep each concise and formal.
      params:
        data:
          background: "{{ $form.background_input }}"
          objective: "{{ $form.objective_input }}"
          scope: "{{ $form.scope_input }}"
          project_name: "{{ $form.project_name }}"
      expect:
        type: object
        additionalProperties: false
        properties:
          background: { type: string }
          objective: { type: string }
          scope: { type: string }
        required: [background, objective, scope]
      temperature: 0.3
      max_tokens: 2048

    - id: procurement_review
      type: human.approval
      description: Procurement officer reviews narrative and PONT findings before drafting.
      params:
        title: "Review RFQ narrative: {{ $form.project_name }}"
        message: |
          Project: {{ $form.project_name }}
          PONT pass: {{ $step('pont_check').pass }}
          Validation issues: {{ $step('validate_inputs').inconsistencies }}
        approvers:
          - "{{ $form.contact_email }}"
        payload:
          narrative: "{{ $step('draft_narrative') }}"
          pont: "{{ $step('pont_check') }}"
          validation: "{{ $step('validate_inputs') }}"

    - id: render_draft
      type: tool.call
      tool: docx_render
      description: Render the DRAFT RFQ document from the tokenized template.
      params:
        template: "{{ $env('SAZ_RFQ_TEMPLATE', 'saz/examples/templates/rfq_template.docx') }}"
        output_name: "rfq_draft_{{ $form.reference_number }}"
        require_all: false
        values:
          title_system_name: "{{ $form.project_name }}"
          date_of_issue: "{{ $form.date_of_issue }}"
          version: "0.1 DRAFT"
          reference_number: "{{ $form.reference_number }}"
          contact_name: "{{ $form.contact_name }}"
          contact_role: "{{ $form.contact_role }}"
          contact_phone: "{{ $form.contact_phone }}"
          contact_email: "{{ $form.contact_email }}"
          background: "{{ $step('draft_narrative').background }}"
          objective: "{{ $step('draft_narrative').objective }}"
          scope: "{{ $step('draft_narrative').scope }}"
          plan_rfq_issued: "{{ $form.date_of_issue }}"
          plan_clarification_deadline: "{{ $form.deadline_clarification }}"
          plan_response_deadline: "{{ $form.deadline_response }}"
          plan_eval1_end: "{{ $form.eval1_end }}"
          plan_eval2_end: "{{ $form.eval2_end }}"
          plan_awarding: "{{ $form.awarding_date }}"
          plan_commencement: "{{ $form.commencement_date }}"
          minimum_requirements: "{{ $form.minimum_requirements }}"
          weight_qualitative: "{{ $form.weight_qualitative_pct }}%"
          q1_weight: "{{ $form.q1_pct }}%"
          q2_weight: "{{ $form.q2_pct }}%"
          q3_weight: "{{ $form.q3_pct }}%"
          weight_price: "{{ $form.weight_price_pct }}%"
          budget_cap_licenses: "{{ $form.budget_cap_licenses_eur }}"
          budget_cap_implementation: "{{ $form.budget_cap_implementation_eur }}"

    - id: needs_consultation
      type: condition
      description: Branch into market consultation when requested.
      if: "{{ $form.consultation_required == true }}"

    - id: supplier_feedback
      type: webhook.wait
      description: Suspend for supplier market-consultation feedback via callback.
      when: "{{ $form.consultation_required == true }}"
      params:
        event_name: "rfq.supplier_feedback"
        timeout_minutes: 4320

    - id: incorporate_feedback
      type: ai.generate
      description: Fold supplier feedback into the narrative.
      when: "{{ $form.consultation_required == true }}"
      instruction: |
        Revise the scope and objective to reflect supplier feedback.
        Do not introduce requirements that were not raised by the project team or suppliers.
      params:
        data:
          current: "{{ $step('draft_narrative') }}"
          feedback: "{{ $step('supplier_feedback') }}"
      expect:
        type: object
        additionalProperties: false
        properties:
          background: { type: string }
          objective: { type: string }
          scope: { type: string }
        required: [background, objective, scope]
      temperature: 0.3
      max_tokens: 2048

    - id: procurement_signoff
      type: human.approval
      description: Final procurement sign-off.
      params:
        title: "Procurement sign-off: {{ $form.project_name }}"
        message: "Final procurement approval for {{ $form.reference_number }}."
        approvers:
          - "{{ $form.contact_email }}"

    - id: project_signoff
      type: human.approval
      description: Final project-team sign-off.
      params:
        title: "Project sign-off: {{ $form.project_name }}"
        message: "Final project-team approval for {{ $form.reference_number }}."
        approvers:
          - "{{ $form.contact_email }}"

    - id: render_final
      type: tool.call
      tool: docx_render
      description: Render the FINAL RFQ document.
      params:
        template: "{{ $env('SAZ_RFQ_TEMPLATE', 'saz/examples/templates/rfq_template.docx') }}"
        output_name: "rfq_final_{{ $form.reference_number }}"
        require_all: true
        values:
          title_system_name: "{{ $form.project_name }}"
          date_of_issue: "{{ $form.date_of_issue }}"
          version: "1.0"
          reference_number: "{{ $form.reference_number }}"
          contact_name: "{{ $form.contact_name }}"
          contact_role: "{{ $form.contact_role }}"
          contact_phone: "{{ $form.contact_phone }}"
          contact_email: "{{ $form.contact_email }}"
          background: "{{ $step('draft_narrative').background }}"
          objective: "{{ $step('draft_narrative').objective }}"
          scope: "{{ $step('draft_narrative').scope }}"
          plan_rfq_issued: "{{ $form.date_of_issue }}"
          plan_clarification_deadline: "{{ $form.deadline_clarification }}"
          plan_response_deadline: "{{ $form.deadline_response }}"
          plan_eval1_end: "{{ $form.eval1_end }}"
          plan_eval2_end: "{{ $form.eval2_end }}"
          plan_awarding: "{{ $form.awarding_date }}"
          plan_commencement: "{{ $form.commencement_date }}"
          minimum_requirements: "{{ $form.minimum_requirements }}"
          weight_qualitative: "{{ $form.weight_qualitative_pct }}%"
          q1_weight: "{{ $form.q1_pct }}%"
          q2_weight: "{{ $form.q2_pct }}%"
          q3_weight: "{{ $form.q3_pct }}%"
          weight_price: "{{ $form.weight_price_pct }}%"
          budget_cap_licenses: "{{ $form.budget_cap_licenses_eur }}"
          budget_cap_implementation: "{{ $form.budget_cap_implementation_eur }}"

    - id: audit_record
      type: artifact.store
      description: Store the full RFQ audit trail.
      params:
        name: "rfq_audit_{{ $form.reference_number }}"
        content:
          project_name: "{{ $form.project_name }}"
          reference_number: "{{ $form.reference_number }}"
          validation: "{{ $step('validate_inputs') }}"
          pont: "{{ $step('pont_check') }}"
          narrative: "{{ $step('draft_narrative') }}"
          procurement_review: "{{ $step('procurement_review') }}"
          procurement_signoff: "{{ $step('procurement_signoff') }}"
          project_signoff: "{{ $step('project_signoff') }}"
          draft_document: "{{ $step('render_draft').artifact_id }}"
          final_document: "{{ $step('render_final').artifact_id }}"

policies:
  budget_usd: 0.50
  pii:
    allow: false
    exceptions:
      tools:
        artifact.store:
          allow:
            - content.procurement_review
            - content.procurement_signoff
            - content.project_signoff
```

- [ ] **Step 2: Verify it compiles cleanly via the API**

Run:
```bash
cd backend && uv run python -c "
from saz.compiler.dsl import compile_dsl
from pathlib import Path
y = Path('saz/examples/unified/rfq_rfp_drafting.yaml').read_text()
c = compile_dsl(y)
print('name:', c.flow_name)
print('warnings:', c.warnings)
"
```
Expected: `name: rfq_rfp_drafting` and `warnings: []`. If warnings list template issues, fix the offending `{{ }}` references and re-run.

- [ ] **Step 3: Commit**

```bash
git add backend/saz/examples/unified/rfq_rfp_drafting.yaml
git commit -m "feat(rfq): add RFQ/RFP drafting workflow"
```

---

### Task 8: Workflow contract test

**Files:**
- Create: `backend/tests/examples/test_rfq_rfp_workflow.py`

- [ ] **Step 1: Write the test**

```python
# backend/tests/examples/test_rfq_rfp_workflow.py
from pathlib import Path

from saz.compiler.dsl import compile_dsl

_YAML = (
    Path(__file__).resolve().parents[2]
    / "saz" / "examples" / "unified" / "rfq_rfp_drafting.yaml"
)


def _compiled():
    return compile_dsl(_YAML.read_text())


def _steps():
    return {s["id"]: s for s in _compiled().workflow_spec["steps"]}


def test_compiles_without_warnings():
    assert _compiled().warnings == []


def test_has_budget_and_weight_gate():
    gate = _steps()["gate_budget"]
    assert gate["type"] == "condition"
    expr = gate["if"]
    assert "20000" in expr and "10000" in expr and "100000" in expr
    assert "== 100" in expr  # weight-sum checks


def test_dual_signoff_and_render_steps_present():
    steps = _steps()
    assert steps["procurement_signoff"]["type"] == "human.approval"
    assert steps["project_signoff"]["type"] == "human.approval"
    assert steps["render_draft"]["tool"] == "docx_render"
    assert steps["render_final"]["tool"] == "docx_render"
    assert steps["render_final"]["params"]["require_all"] is True


def test_ai_steps_have_strict_expect():
    for sid in ("validate_inputs", "pont_check", "draft_narrative"):
        step = _steps()[sid]
        expect = step["expect"]
        assert expect["type"] == "object"
        assert expect["required"], f"{sid} must declare required fields"
```

- [ ] **Step 2: Run the test**

Run: `cd backend && uv run pytest tests/examples/test_rfq_rfp_workflow.py -q`
Expected: PASS (4 passed). If `compile_dsl` exposes the workflow under a different attribute than `workflow_spec`, adjust `_steps()` to match the `DSLCompiled` field used elsewhere in `tests/examples/` (grep an existing example test for the accessor).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/examples/test_rfq_rfp_workflow.py
git commit -m "test(rfq): contract test for RFQ workflow structure"
```

---

### Task 9: End-to-end render test + example generator

This proves the real tokenized template renders to a complete document, without needing an LLM (canned narrative values fed straight to the tool).

**Files:**
- Create: `scripts/generate_rfq_example.py`
- Create: `backend/tests/integration/test_rfq_render_end_to_end.py`
- Create (generated): `docs/procurement/examples/rfq_draft_T88815.docx`, `docs/procurement/examples/rfq_final_T88815.docx`

- [ ] **Step 1: Write the failing integration test**

```python
# backend/tests/integration/test_rfq_render_end_to_end.py
from pathlib import Path

import pytest
from docx import Document

from saz.tools.docx_tool import DocxRenderTool

_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "saz" / "examples" / "templates" / "rfq_template.docx"
)

_VALUES = {
    "title_system_name": "HR Information System",
    "date_of_issue": "05/07/2024",
    "version": "1.0",
    "reference_number": "T88815",
    "contact_name": "Badreddine Ajbar El Gueriri",
    "contact_role": "Buyer",
    "contact_phone": "+31 6 29003633",
    "contact_email": "badre.ajbar@geant.org",
    "background": "GÉANT seeks to replace its existing HR Information System.",
    "objective": "Find a cost-effective, modern, well-supported HR system.",
    "scope": "A core HR system with optional modules for future expansion.",
    "plan_rfq_issued": "05/07/2024",
    "plan_clarification_deadline": "15/07/2024",
    "plan_response_deadline": "19/07/2024",
    "plan_eval1_end": "02/08/2024",
    "plan_eval2_end": "09/08/2024",
    "plan_awarding": "15/08/2024",
    "plan_commencement": "01/10/2024",
    "minimum_requirements": "1. SSO via OIDC/SAML2\n2. EU/UK data residency\n3. TLS 1.2+",
    "weight_qualitative": "80%",
    "q1_weight": "50%",
    "q2_weight": "20%",
    "q3_weight": "10%",
    "weight_price": "20%",
    "budget_cap_licenses": "20.000",
    "budget_cap_implementation": "10.000",
}


@pytest.mark.asyncio
async def test_real_template_renders_with_all_tokens(tmp_path):
    tool = DocxRenderTool(storage_path=str(tmp_path))
    result = await tool.render(
        template=str(_TEMPLATE),
        values=_VALUES,
        output_name="rfq_final_T88815",
        require_all=True,
    )
    assert result["unfilled"] == []
    doc = Document(result["path"])
    full = "\n".join(p.text for p in doc.paragraphs)
    assert "T88815" in full
    assert "{{" not in full  # no leftover tokens in body paragraphs
```

- [ ] **Step 2: Run test to verify it fails (or reveals coverage gaps)**

Run: `cd backend && uv run pytest tests/integration/test_rfq_render_end_to_end.py -q`
Expected: initially FAIL if any canonical token is absent from the template (the `_VALUES` keys must match the tokens the build script produced). If it fails on `unfilled`, return to Task 4 Step 3 to capture the missing span, or drop the token from `_VALUES` and document it as fixed-text in the placeholder map. Iterate until PASS.

- [ ] **Step 3: Write the example generator script**

```python
# scripts/generate_rfq_example.py
"""Generate DRAFT and FINAL example RFQ documents from canned HRIS test data."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from saz.tools.docx_tool import DocxRenderTool  # noqa: E402
from tests.integration.test_rfq_render_end_to_end import _VALUES  # noqa: E402

TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "backend" / "saz" / "examples" / "templates" / "rfq_template.docx"
)
OUT = Path(__file__).resolve().parents[1] / "docs" / "procurement" / "examples"


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tool = DocxRenderTool(storage_path=str(OUT))
    draft_vals = {**_VALUES, "version": "0.1 DRAFT"}
    draft = await tool.render(
        template=str(TEMPLATE), values=draft_vals, output_name="rfq_draft_T88815", require_all=False
    )
    final = await tool.render(
        template=str(TEMPLATE), values=_VALUES, output_name="rfq_final_T88815", require_all=True
    )
    Path(draft["path"]).rename(OUT / "rfq_draft_T88815.docx")
    Path(final["path"]).rename(OUT / "rfq_final_T88815.docx")
    print("wrote", OUT / "rfq_draft_T88815.docx", "and", OUT / "rfq_final_T88815.docx")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Generate the example outputs**

Run: `cd backend && uv run python ../scripts/generate_rfq_example.py`
Expected: prints the two output paths; both `.docx` files exist under `docs/procurement/examples/`.

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_rfq_example.py \
        backend/tests/integration/test_rfq_render_end_to_end.py \
        docs/procurement/examples/rfq_draft_T88815.docx \
        docs/procurement/examples/rfq_final_T88815.docx
git commit -m "test(rfq): end-to-end render test and example outputs"
```

---

### Task 10: Usage & testing documentation

**Files:**
- Create: `docs/procurement/rfq_workflow_guide.md`

- [ ] **Step 1: Write the guide**

Write `docs/procurement/rfq_workflow_guide.md` covering:
- **Overview**: what the workflow does and the lifecycle diagram (reference `RFP Workflow.png`).
- **Intake fields**: the Project and Procurement form sections, with which template tokens each maps to (link to `rfq_placeholder_map.md`).
- **Running it**: compile/register the example (`POST /api/v1/flows`), start a run with a form payload (give the HRIS payload from `_VALUES`/the form as a concrete JSON example), and the approval/callback steps (how procurement approves, how a supplier POSTs feedback to `/api/v1/webhooks/callback/{callback_id}` with `{"action":"approve","data":{...}}`).
- **Compliance gates**: what `gate_budget` and `pont_check` enforce and what happens when they fail.
- **Rebuilding the template**: the `build_rfq_template.py` command and when to re-run it.
- **Generating examples**: the `scripts/generate_rfq_example.py` command.
- **Known limitations**: from spec §10 (`.docx` only; fixed-row requirements/criteria; single combined form).

- [ ] **Step 2: Commit**

```bash
git add docs/procurement/rfq_workflow_guide.md
git commit -m "docs(rfq): add workflow usage and testing guide"
```

---

### Task 11: Full verification sweep

**Files:** none (verification only)

- [ ] **Step 1: Run the targeted test suite**

Run:
```bash
cd backend && uv run pytest \
  tests/unit/test_rfq_tokens.py \
  tests/unit/test_build_rfq_template.py \
  tests/unit/test_docx_tool.py \
  tests/examples/test_rfq_rfp_workflow.py \
  tests/integration/test_rfq_render_end_to_end.py -q
```
Expected: all pass.

- [ ] **Step 2: Run the example-discovery acceptance tests**

Run: `cd backend && uv run pytest tests/acceptance/test_examples_execute_safely.py tests/integration/test_examples_plan_and_ground.py -q`
Expected: pass, including the new `rfq_rfp_drafting.yaml` (it is auto-discovered). If `plan_and_ground` fails on a template reference, fix the offending `{{ }}` in the YAML and re-run.

- [ ] **Step 3: Lint/type/format gate**

Run: `cd backend && uv run pre-commit run --all-files`
Expected: passes (ruff, ruff-format, mypy). Fix any reported issues in the new files and re-run.

- [ ] **Step 4: Broader regression (feasible subset)**

Run: `cd backend && uv run pytest -n auto -q`
Expected: no new failures attributable to this change. Note any pre-existing unrelated failures in the final summary rather than fixing them here.

- [ ] **Step 5: Final commit (if lint made changes)**

```bash
git add -A
git commit -m "chore(rfq): apply lint/format fixes"
```

---

## Self-Review

**Spec coverage:**
- Structured intake (project + procurement) → Task 7 form (§5).
- ai.extract validation / classification / missing fields → Task 7 `validate_inputs`.
- Budget + weight-sum gate → Task 7 `gate_budget`, asserted in Task 8.
- PONT check → Task 7 `pont_check`.
- AI narrative drafting (no invented content) → Task 7 `draft_narrative`.
- Template mapping/merging + real .docx → Tasks 2–6 (tokens, build script, tool) + render steps in Task 7; proven in Task 9.
- Procurement review, market consultation (condition→webhook.wait→ai.generate), dual sign-off → Task 7.
- Final render + artifact audit trail → Task 7 `render_final`, `audit_record`.
- Placeholder mapping doc → Task 4. Usage/testing docs → Task 10. Example outputs → Task 9.
- Tests across tool/build/workflow/gates/e2e → Tasks 2,3,5,6,8,9,11.
- Out of scope (RAG) → not implemented, per spec §1.

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The only deliberate "iterate until coverage" loops are Task 4 Step 3 and Task 9 Step 2, which are inspection/tuning steps with concrete acceptance criteria, not unwritten code.

**Type/name consistency:** Token names match between `rfq_tokens.py` (Task 2), the build hints, the workflow `values` blocks (Task 7), and `_VALUES` (Task 9). Tool method `render(...)` signature is consistent across Tasks 5, 6, 9. Registry method `register_docx_tool` and constructor arg `docx_tool` consistent in Task 6.

**Known risk to watch:** `compile_dsl` result attribute (`workflow_spec`) used in Task 8 must match the real `DSLCompiled` field — Task 8 Step 2 says to verify against an existing example test if it differs.
