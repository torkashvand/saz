"""Fake CriticAgent that returns scripted verdicts.

The real CriticAgent makes LLM calls for verify_proposal/critique. For
acceptance tests we want to drive the executor's safety-gate branches
without paying for an LLM round-trip, so this fake satisfies the
same async surface and returns hard-coded Critique values.
"""

from collections.abc import Iterable
from typing import Any

from saz.agents.schemas import Critique, Verdict


def _critique(verdict: Verdict, reasoning: str = "scripted") -> Critique:
    return Critique(
        verdict=verdict,
        reasoning=reasoning,
        issues=[],
        safety_flags=[],
        suggestions={},
        confidence=0.95,
    )


class FakeCritic:
    """Drop-in for CriticAgent in acceptance tests.

    Defaults to PASS for both verify_proposal (pre-execution) and critique
    (post-execution). Override the verdict either by:
      - passing a queue of verdicts, used in order and exhausted to the
        default once empty; or
      - passing default_verify / default_critique to change the falls-back-to
        verdict (useful for "always FAIL" or "always ESCALATE").

    The default tail-verdict matters because the executor's outer retry
    loop can call verify_proposal multiple times for one step — a one-shot
    FAIL queue silently flips to PASS on retry and lets the tool through.
    """

    def __init__(
        self,
        verify_verdicts: Iterable[Verdict] | None = None,
        critique_verdicts: Iterable[Verdict] | None = None,
        default_verify: Verdict = Verdict.PASS,
        default_critique: Verdict = Verdict.PASS,
    ):
        self._verify = list(verify_verdicts or [])
        self._critique = list(critique_verdicts or [])
        self._default_verify = default_verify
        self._default_critique = default_critique
        self.verify_calls: list[dict[str, Any]] = []
        self.critique_calls: list[dict[str, Any]] = []

    async def verify_proposal(self, **kwargs: Any) -> Critique:
        self.verify_calls.append(kwargs)
        if self._verify:
            return _critique(self._verify.pop(0), "scripted verify")
        return _critique(self._default_verify, "default verify")

    async def critique(self, **kwargs: Any) -> Critique:
        self.critique_calls.append(kwargs)
        if self._critique:
            return _critique(self._critique.pop(0), "scripted critique")
        return _critique(self._default_critique, "default critique")
