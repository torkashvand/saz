"""Unit tests for the password hashing helpers."""

import pytest

from saz.security.passwords import hash_password, verify_password


def test_hash_returns_bcrypt_prefix():
    h = hash_password("hunter2-correct-horse")
    assert h.startswith("$2b$"), f"expected bcrypt $2b$ prefix, got: {h[:7]}"


def test_hash_is_not_plaintext():
    plain = "hunter2-correct-horse"
    h = hash_password(plain)
    assert plain not in h


def test_each_hash_uses_a_fresh_salt():
    # Two hashes of the same input must differ because of per-call salt.
    h1 = hash_password("same-pw-twice")
    h2 = hash_password("same-pw-twice")
    assert h1 != h2


def test_verify_accepts_correct_password():
    h = hash_password("hunter2-correct-horse")
    assert verify_password("hunter2-correct-horse", h) is True


def test_verify_rejects_wrong_password():
    h = hash_password("hunter2-correct-horse")
    assert verify_password("wrong-password", h) is False


def test_verify_rejects_empty_inputs():
    h = hash_password("nonempty")
    assert verify_password("", h) is False
    assert verify_password("nonempty", "") is False


def test_verify_does_not_raise_on_garbage_hash():
    assert verify_password("anything", "not-a-real-hash") is False


def test_hash_rejects_overlong_password():
    # bcrypt silently truncates over 72 bytes — we reject instead so that
    # a 100-char password can't accidentally match a 72-char prefix.
    with pytest.raises(ValueError):
        hash_password("a" * 73)


def test_verify_rejects_overlong_password_attempt():
    h = hash_password("a" * 72)
    # An attempt longer than the bcrypt limit must not authenticate.
    assert verify_password("a" * 100, h) is False
