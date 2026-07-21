"""Tests for vault cryptographic primitives."""

import pytest

from agent_knots.vault.crypto import (
    KEY_LEN,
    MARKER_PLAINTEXT,
    SALT_LEN,
    decrypt,
    derive_entry_key,
    derive_key,
    encrypt,
    new_salt,
    scrub,
    zero_bytes,
)


def test_new_salt_length():
    salt = new_salt()
    assert len(salt) == SALT_LEN


def test_new_salt_random():
    """Two salts should not be equal (astronomically unlikely to collide)."""
    assert new_salt() != new_salt()


def test_derive_key_length():
    key = derive_key("my-passphrase", new_salt())
    assert len(key) == KEY_LEN


def test_derive_key_deterministic():
    """Same passphrase + salt = same key."""
    salt = new_salt()
    k1 = derive_key("p4ssw0rd", salt)
    k2 = derive_key("p4ssw0rd", salt)
    assert k1 == k2


def test_derive_key_different_passphrase():
    """Different passphrase = different key."""
    salt = new_salt()
    k1 = derive_key("alpha", salt)
    k2 = derive_key("beta", salt)
    assert k1 != k2


def test_derive_key_different_salt():
    k1 = derive_key("same", new_salt())
    k2 = derive_key("same", new_salt())
    assert k1 != k2


def test_encrypt_roundtrip():
    key = derive_key("test", new_salt())
    plaintext = b"Hello, world!"
    encrypted = encrypt(key, plaintext)
    assert encrypted != plaintext
    assert len(encrypted) > len(plaintext)  # nonce + ciphertext + tag
    assert decrypt(key, encrypted) == plaintext


def test_encrypt_different_key_fails():
    k1 = derive_key("key1", new_salt())
    k2 = derive_key("key2", new_salt())
    encrypted = encrypt(k1, b"secret")
    with pytest.raises(Exception):
        decrypt(k2, encrypted)


def test_encrypt_tampered_data_fails():
    key = derive_key("test", new_salt())
    encrypted = bytearray(encrypt(key, b"secret"))
    encrypted[15] ^= 0x01  # flip a bit in the ciphertext
    with pytest.raises(Exception):
        decrypt(key, bytes(encrypted))


def test_encrypt_short_blob():
    with pytest.raises(ValueError, match="too short"):
        decrypt(b"short-key-that-is-32-bytes!!", b"x")


def test_encrypt_wrong_key_length():
    with pytest.raises(ValueError, match="key length"):
        encrypt(b"short", b"data")


def test_empty_plaintext():
    key = derive_key("test", new_salt())
    encrypted = encrypt(key, b"")
    assert decrypt(key, encrypted) == b""


def test_marker_roundtrip():
    """The vault marker must encrypt and decrypt correctly."""
    key = derive_key("vault-pass", new_salt())
    encrypted = encrypt(key, MARKER_PLAINTEXT)
    assert decrypt(key, encrypted) == MARKER_PLAINTEXT


def test_derive_entry_key():
    master = derive_key("master", new_salt())
    entry_salt = new_salt()
    entry_key = derive_entry_key(master, entry_salt)
    assert len(entry_key) == KEY_LEN
    # Different salt = different entry key
    entry_key2 = derive_entry_key(master, new_salt())
    assert entry_key != entry_key2


def test_entry_key_roundtrip():
    """Per-entry keys should work for encrypt/decrypt."""
    master = derive_key("master", new_salt())
    entry_salt = new_salt()
    entry_key = derive_entry_key(master, entry_salt)
    encrypted = encrypt(entry_key, b"entry data")
    assert decrypt(entry_key, encrypted) == b"entry data"


def test_zero_bytes():
    buf = bytearray(b"hello world")
    zero_bytes(buf)
    assert buf == bytearray(b"\x00" * 11)


def test_scrub_simple():
    assert scrub("hello world", "world") == "hello [REDACTED]"


def test_scrub_multiple():
    assert scrub("token=abc token=abc", "abc") == "token=[REDACTED] token=[REDACTED]"


def test_scrub_empty_secret():
    assert scrub("hello", "") == "hello"


def test_scrub_not_found():
    assert scrub("hello", "xyz") == "hello"
