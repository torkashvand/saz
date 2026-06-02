"""The compiled policy shape must not be a lossy subset of what the runtime
enforces. PolicyEngine.initialize_from_dsl reads max_tokens/max_steps/
max_time_seconds and pii.tokenize_model_inputs/exceptions from the raw DSL;
compile_policies must surface the same keys so compile and execute can never
diverge."""

from saz.compiler.dsl import compile_policies


def test_compiled_policy_preserves_budget_sublimits():
    pol = compile_policies(
        {
            "budget_usd": 2.0,
            "max_tokens": 1234,
            "max_steps": 7,
            "max_time_seconds": 60,
        }
    )
    assert pol["max_tokens"] == 1234
    assert pol["max_steps"] == 7
    assert pol["max_time_seconds"] == 60


def test_compiled_policy_omits_unset_sublimits():
    pol = compile_policies({"budget_usd": 2.0})
    # Not declared -> not emitted (runtime keeps BudgetTracker defaults).
    assert "max_tokens" not in pol
    assert "max_steps" not in pol
    assert "max_time_seconds" not in pol


def test_compiled_policy_preserves_pii_tokenize_and_exceptions():
    pol = compile_policies(
        {
            "pii": {
                "allow": False,
                "tokenize_model_inputs": False,
                "exceptions": {"tools": {"http_request": ["body.comment"]}},
            }
        }
    )
    assert pol["pii"]["allow"] is False
    assert pol["pii"]["tokenize_model_inputs"] is False
    assert pol["pii"]["exceptions"]["tools"]["http_request"] == ["body.comment"]


def test_compiled_pii_tokenize_defaults_true():
    pol = compile_policies({"pii": {"allow": True}})
    assert pol["pii"]["tokenize_model_inputs"] is True
