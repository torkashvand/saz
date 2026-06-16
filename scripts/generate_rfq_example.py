"""Generate DRAFT and FINAL example RFQ documents from canned HRIS test data."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from saz.tools.docx_tool import DocxRenderTool  # noqa: E402
from tests.integration.test_rfq_render_end_to_end import _VALUES  # noqa: E402

TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "saz"
    / "examples"
    / "templates"
    / "rfq_template.docx"
)
OUT = Path(__file__).resolve().parents[1] / "docs" / "procurement" / "examples"


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tool = DocxRenderTool(storage_path=str(OUT))
    draft_vals = {**_VALUES, "version": "0.1 DRAFT"}
    draft = await tool.render(
        template=str(TEMPLATE),
        values=draft_vals,
        output_name="rfq_draft_T88815",
        require_all=False,
    )
    final = await tool.render(
        template=str(TEMPLATE),
        values=_VALUES,
        output_name="rfq_final_T88815",
        require_all=True,
    )
    Path(draft["path"]).rename(OUT / "rfq_draft_T88815.docx")
    Path(final["path"]).rename(OUT / "rfq_final_T88815.docx")
    print("wrote", OUT / "rfq_draft_T88815.docx", "and", OUT / "rfq_final_T88815.docx")


if __name__ == "__main__":
    asyncio.run(main())
