import pytest

from saz.engine.templating import TemplateContext, resolve_template

# ----------------------------- Helpers -----------------------------


def _ctx(form=None, steps=None, secret=None) -> TemplateContext:
    return TemplateContext(form or {}, steps or {}, secret)


def _res(template, form=None, steps=None, secret_resolver=None):
    return resolve_template(template, form or {}, steps or {}, secret_resolver)


# ----------------------------- Native / Interpolation -----------------------------


def test_single_expression_returns_native_types():
    form = {"n": 42, "flag": True, "obj": {"a": 1}, "arr": [1, 2, 3]}
    assert _res("{{ $form.n }}", form) == 42
    assert _res("{{ $form.flag }}", form) is True
    assert _res("{{ $form.obj }}", form) == {"a": 1}
    assert _res("{{ $form.arr }}", form) == [1, 2, 3]


def test_mixed_interpolation_coerces_to_string_and_json_for_structs():
    form = {"user": "alice", "prefs": {"theme": "dark"}, "nums": [1, 2]}
    out = _res("Hello {{ $form.user }} with {{ $form.prefs }} and {{ $form.nums }}!", form)
    # dict/list are JSON-encoded when interpolated
    assert out.startswith("Hello alice with ")
    assert '"theme": "dark"' in out
    assert '"nums": [1, 2]' in out or "[1, 2]" in out
    assert out.endswith("]!")


def test_unresolved_expression_behavior_single_and_mixed():
    # Single unknown expression returns literal handlebars
    assert _res("{{ $unknown(42) }}") == "{{ $unknown(42) }}"
    # Mixed with unknown → unknown part becomes empty string
    assert _res("X {{ $unknown(42) }} Y") == "X  Y"


# ----------------------------- $form -----------------------------


def test_form_nested_paths_and_missing_fields(caplog):
    form = {"user": {"profile": {"email": "a@b.com"}}}
    assert _res("{{ $form.user.profile.email }}", form) == "a@b.com"
    # missing field → None for single expr
    assert _res("{{ $form.user.profile.name }}", form) is None
    # mixed interpolation with missing field → empty string
    assert _res("User={{ $form.user.profile.name }}!", form) == "User=!"


# ----------------------------- $step (STRICT output-only) -----------------------------


def test_step_returns_exact_output_native_type():
    steps = {
        "extract": {"output": {"category": "technical", "priority": "high"}},
    }
    assert _res("{{ $step('extract') }}", {}, steps) == {
        "category": "technical",
        "priority": "high",
    }
    assert _res("{{ $step('extract').category }}", {}, steps) == "technical"


def test_step_missing_id_or_missing_output_is_none(caplog):
    steps = {
        "extract": {"metadata": {"model": "x"}},  # no 'output'
    }
    # Missing id
    assert _res("{{ $step('route') }}", {}, steps) is None
    # Present id, but 'output' missing
    assert _res("{{ $step('extract') }}", {}, steps) is None
    # Mixed interpolation → empty
    assert _res("Cat={{ $step('extract').category }}", {}, steps) == "Cat="


def test_step_no_fallback_to_metadata_usage_or_alias():
    steps = {
        "extract": {"output": {"x": 1}, "metadata": {"category": "meta"}},
    }
    # Must use exact step id's 'output'
    assert _res("{{ $step('extract').x }}", {}, steps) == 1
    # No fallback to metadata or *_result alias
    assert _res("{{ $step('extract').category }}", {}, steps) is None
    assert _res("{{ $step('extract_result') }}", {}, steps) is None


def test_step_nested_lists_and_indices():
    steps = {
        "calc": {"output": {"items": [{"name": "a"}, {"name": "b"}]}},
    }
    # Supports list indexing via dotted numeric path
    assert _res("{{ $step('calc').items.0.name }}", {}, steps) == "a"
    assert _res("{{ $step('calc').items.1.name }}", {}, steps) == "b"
    # Out of range → None / empty in mixed
    assert _res("{{ $step('calc').items.2.name }}", {}, steps) is None
    assert _res("X {{ $step('calc').items.2.name }} Y", {}, steps) == "X  Y"


def test_step_output_may_be_primitive_but_deeper_path_then_none():
    steps = {"simple": {"output": "READY"}}
    assert _res("{{ $step('simple') }}", {}, steps) == "READY"
    assert _res("{{ $step('simple').status }}", {}, steps) is None


# ----------------------------- $env -----------------------------


def test_env_reads_and_missing(monkeypatch, caplog):
    monkeypatch.setenv("FOO_ENV", "bar")
    assert _res("{{ $env('FOO_ENV') }}") == "bar"
    # missing → None / empty in mixed
    assert _res("{{ $env('NOPE') }}") is None
    assert _res("V={{ $env('NOPE') }}!") == "V=!"


# ----------------------------- $secret -----------------------------


def test_secret_resolver_success():
    def resolver(name: str):
        return {"API_TOKEN": "xyz"}.get(name)

    assert _res("{{ $secret('API_TOKEN') }}", secret_resolver=resolver) == "xyz"


def test_secret_missing_raises_valueerror():
    def resolver(_):  # always missing
        return None

    with pytest.raises(ValueError):
        _res("{{ $secret('MISSING') }}", secret_resolver=resolver)


# ----------------------------- Complex / Deep structures -----------------------------


def test_nested_structure_resolution_in_dict_and_list():
    form = {
        "customer": {"email": "alice@example.org", "tier": "gold"},
        "limits": [10, 20, 30],
    }
    steps = {
        "extract": {"output": {"category": "billing", "score": 0.87}},
        "route": {"output": {"team": "billing_team"}},
    }

    template = {
        "mail": "{{ $form.customer.email }}",
        "tier": "{{ $form.customer.tier }}",
        "score": "{{ $step('extract').score }}",
        "route": "{{ $step('route').team }}",
        "limits": "{{ $form.limits }}",
        "verbatim": "static",
        "missing": "{{ $step('extract').missing_key }}",  # → None → removed to ""
        "concat": "user={{ $form.customer.email }}; team={{ $step('route').team }}",
        "native_obj": {"a": "{{ $step('extract') }}", "b": 1},  # 'a' becomes native dict
        "mixed_arr": ["x", "{{ $form.customer.email }}", "{{ $step('extract').score }}"],
    }

    out = _res(template, form, steps)
    # Native returns for single expressions embedded in dict/list
    assert out["mail"] == "alice@example.org"
    assert out["tier"] == "gold"
    assert out["score"] == 0.87
    assert out["route"] == "billing_team"
    assert out["limits"] == [10, 20, 30]  # native list
    assert out["verbatim"] == "static"
    assert out["missing"] == ""  # mixed interpolation of None becomes ""
    assert out["concat"].startswith("user=alice@example.org; team=billing_team")
    assert (
        isinstance(out["native_obj"]["a"], dict) and out["native_obj"]["a"]["category"] == "billing"
    )
    assert out["mixed_arr"][1] == "alice@example.org"
    assert out["mixed_arr"][2] == 0.87


# ----------------------------- Robustness -----------------------------


def test_large_payload_is_finite_and_does_not_crash(monkeypatch):
    # Big strings and nested content shouldn’t explode
    long = "A" * 10000
    form = {"blob": long}
    steps = {"s": {"output": {"text": long, "arr": [long, {"k": long}]}}}

    out = _res(
        {
            "a": "{{ $form.blob }}",
            "b": "X{{ $step('s').text }}Y",
            "c": "{{ $step('s').arr }}",
            "d": "Z{{ $step('s').arr.1.k }}W",
        },
        form,
        steps,
    )
    assert out["a"] == long
    assert out["b"].startswith("X") and out["b"].endswith("Y") and long in out["b"]
    assert out["c"] == [long, {"k": long}]
    assert out["d"].startswith("Z") and out["d"].endswith("W") and long in out["d"]


# ----------------------------- Edge parsing -----------------------------


@pytest.mark.parametrize(
    "expr,expected",
    [
        ("{{ $form.a }}", 1),
        ("before {{ $form.a }} after", "before 1 after"),
        ("{{ $step('x') }}", {"v": 2}),
        ("{{ $step('x').v }}", 2),
        ("start {{ $step('x').v }} end", "start 2 end"),
        ("{{ $env('ZZZ') }}", None),
        ("{{ $secret('TOK') }}", "tok"),
    ],
)
def test_parametrized_edge_cases(monkeypatch, expr, expected):
    form = {"a": 1}
    steps = {"x": {"output": {"v": 2}}}
    monkeypatch.setenv("ZZZ", "")  # present but empty is allowed

    def resolver(name):
        return {"TOK": "tok"}.get(name)

    if "secret(" in expr and expected == "tok":
        assert _res(expr, form, steps, resolver) == "tok"
    else:
        assert _res(expr, form, steps, resolver) == expected
