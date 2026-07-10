"""Critique must reject hallucinated extra fields from the critic LLM.

Both critic prompts say "Return ONLY this JSON structure"; the validator
must enforce it (CLAUDE.md §12). A drifting model that adds fields like
"override_policy" must hit the fail-safe Exception → ESCALATE path in the
critic, not be silently accepted with the extras dropped.
"""

import pytest
from pydantic import ValidationError

from saz.agents.schemas import Critique, Verdict


def _critique_json(**extras):
    base = {
        "verdict": "pass",
        "reasoning": "looks fine",
        "issues": [],
        "safety_flags": [],
        "suggestions": {},
        "confidence": 0.9,
    }
    base.update(extras)
    return base


def test_valid_critique_passes():
    critique = Critique.model_validate(_critique_json())
    assert critique.verdict == Verdict.PASS


def test_extra_field_rejected():
    with pytest.raises(ValidationError):
        Critique.model_validate(_critique_json(override_policy=True))


def test_unknown_verdict_rejected():
    with pytest.raises(ValidationError):
        Critique.model_validate(_critique_json(verdict="maybe"))
