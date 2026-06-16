from saz.examples.templates.rfq_tokens import RFQ_TOKENS, TOKEN_SOURCE_HINTS


def test_tokens_are_unique_and_nonempty():
    assert RFQ_TOKENS, "token list must not be empty"
    assert len(RFQ_TOKENS) == len(set(RFQ_TOKENS)), "tokens must be unique"
    assert all(t and t.islower() for t in RFQ_TOKENS)


def test_every_hint_maps_to_a_known_token():
    for substring, token in TOKEN_SOURCE_HINTS:
        assert substring, "hint substring must not be empty"
        assert token in RFQ_TOKENS, f"hint maps to unknown token {token!r}"
