"""lint_flow orchestration: suppression marking, unknown ignore codes."""

from saz.linter import lint_flow
from saz.linter.findings import LintCode


def _flow_with_count_bug(lint_ignore=None):
    step = {
        "id": "summarize",
        "type": "ai.extract",
        "instruction": '- "pre_checks" is a list (3-6 items).\n',
        "expect": {
            "type": "object",
            "properties": {
                "pre_checks": {"type": "array", "items": {"type": "string"}, "minItems": 1}
            },
        },
    }
    if lint_ignore is not None:
        step["lint_ignore"] = lint_ignore
    return {"workflow": {"steps": [step]}}


def test_count_bug_blocks_by_default():
    report = lint_flow(_flow_with_count_bug(), run_llm=False)
    assert any(f.code is LintCode.PROSE_SCHEMA_COUNT_MISMATCH for f in report.findings)
    assert len(report.blocking) == 1


def test_lint_ignore_marks_suppressed_not_dropped():
    report = lint_flow(
        _flow_with_count_bug(
            lint_ignore=[{"code": "PROSE_SCHEMA_COUNT_MISMATCH", "reason": "intentional"}]
        ),
        run_llm=False,
    )
    # finding is retained...
    matched = [f for f in report.findings if f.code is LintCode.PROSE_SCHEMA_COUNT_MISMATCH]
    assert len(matched) == 1
    assert matched[0].suppressed is True
    assert matched[0].suppress_reason == "intentional"
    # ...but no longer blocks
    assert report.blocking == []


def test_unknown_ignore_code_is_blocking_error():
    report = lint_flow(
        _flow_with_count_bug(
            lint_ignore=[{"code": "PROSE_SCHEMA_COUNT_MISMATC", "reason": "typo"}]
        ),
        run_llm=False,
    )
    codes = {f.code for f in report.findings}
    assert LintCode.LINT_IGNORE_UNKNOWN_CODE in codes
    # the real finding is NOT suppressed (the typo'd ignore didn't match) and the
    # unknown-code error itself blocks
    blocking_codes = {f.code for f in report.blocking}
    assert LintCode.LINT_IGNORE_UNKNOWN_CODE in blocking_codes
    assert LintCode.PROSE_SCHEMA_COUNT_MISMATCH in blocking_codes


def test_clean_flow_no_findings():
    flow = {
        "workflow": {
            "steps": [
                {
                    "id": "summarize",
                    "type": "ai.extract",
                    "instruction": '- "pre_checks" must list EXACTLY 3 to 6 items.\n',
                    "expect": {
                        "type": "object",
                        "properties": {
                            "pre_checks": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 3,
                                "maxItems": 6,
                            }
                        },
                    },
                }
            ]
        }
    }
    report = lint_flow(flow, run_llm=False)
    assert report.findings == []
    assert report.blocking == []
