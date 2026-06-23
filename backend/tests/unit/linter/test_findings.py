"""LintReport.blocking semantics: severity, suppression, and LLM fail-open."""

from saz.linter.findings import LintCode, LintFinding, LintReport, Severity


def _f(**kw):
    base = dict(
        code=LintCode.PROSE_SCHEMA_COUNT_MISMATCH,
        severity=Severity.ERROR,
        message="x",
        source="deterministic",
    )
    base.update(kw)
    return LintFinding(**base)


def test_error_blocks_warning_does_not():
    report = LintReport(
        findings=[_f(severity=Severity.ERROR), _f(severity=Severity.WARNING)],
        llm_ran=True,
    )
    assert len(report.blocking) == 1
    assert report.blocking[0].severity is Severity.ERROR


def test_suppressed_finding_does_not_block_but_is_retained():
    report = LintReport(findings=[_f(suppressed=True, suppress_reason="ok")], llm_ran=True)
    assert report.blocking == []
    # still present for audit/UI
    assert len(report.findings) == 1
    assert report.findings[0].suppressed is True


def test_llm_finding_blocks_only_when_llm_ran():
    finding = _f(code=LintCode.LLM_CROSS_FIELD_RULE_UNENFORCED, source="llm")
    assert LintReport(findings=[finding], llm_ran=True).blocking == [finding]
    # fail-open: LLM did not run → its findings cannot block
    assert LintReport(findings=[finding], llm_ran=False).blocking == []
