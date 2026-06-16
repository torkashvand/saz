"""Derive a tokenized RFQ template (and placeholder map) from the original
GÉANT RFQ .docx. Highlighted spans become {{token}} markers; original
formatting is preserved by reusing the first run of each span."""

from __future__ import annotations

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
