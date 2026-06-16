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

    n = replace_highlighted_spans(doc, hints=[("find a hr system", "objective")])

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
