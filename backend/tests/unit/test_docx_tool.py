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
