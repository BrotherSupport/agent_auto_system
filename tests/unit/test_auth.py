"""Unit tests for password hashing helpers."""
from src.auth import hash_password, verify_password


def test_hash_round_trip():
    h = hash_password("s3cret-password")
    assert h != "s3cret-password"
    assert verify_password("s3cret-password", h)


def test_wrong_password_rejected():
    h = hash_password("s3cret-password")
    assert not verify_password("wrong", h)


def test_hashes_are_salted_unique():
    assert hash_password("same") != hash_password("same")


def test_verify_handles_garbage_hash():
    assert not verify_password("anything", "not-a-bcrypt-hash")


def test_long_password_truncated_consistently():
    # >72 bytes: bcrypt truncates; hash and verify must agree on the truncation.
    base = "a" * 80
    h = hash_password(base)
    assert verify_password(base, h)
    # Differs only past byte 72 → still verifies (same truncated prefix).
    assert verify_password(base + "EXTRA", h)
