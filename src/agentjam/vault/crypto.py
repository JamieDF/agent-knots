"""Vault cryptographic primitives.

Ported from internal/vault/filestore/crypto.go.

Uses AES-256-GCM for encryption and argon2id for key derivation.
The on-disk format is: nonce (12 bytes) || ciphertext+tag.
"""

from __future__ import annotations

import os

from argon2.low_level import hash_secret_raw, Type
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# ── constants (matching Go) ──────────────────────────────────────────────────

KEY_LEN = 32       # AES-256
SALT_LEN = 16      # argon2id salt
NONCE_LEN = 12     # GCM nonce
ARGON_TIME = 2     # argon2id time cost
ARGON_MEMORY = 64 * 1024  # KiB (64 MiB)
ARGON_THREADS = 2  # argon2id parallelism

# Per-entry key derivation (defense-in-depth: compromising one entry key
# doesn't expose the master key). Uses lighter argon2 params since the
# input is already high-entropy.
ENTRY_KEY_TIME = 1
ENTRY_KEY_MEMORY = 8 * 1024   # 8 MiB
ENTRY_KEY_THREADS = 1

MARKER_PLAINTEXT = b"agentjam-vault-marker-v1"


# ── key derivation ───────────────────────────────────────────────────────────

def derive_key(passphrase: str, salt: bytes,
               time_cost: int = ARGON_TIME,
               memory_cost: int = ARGON_MEMORY,
               parallelism: int = ARGON_THREADS) -> bytes:
    """Derive a 32-byte AES key from a passphrase using argon2id."""
    return hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
        hash_len=KEY_LEN,
        type=Type.ID,
    )


def derive_entry_key(master_key: bytes, entry_salt: bytes) -> bytes:
    """Derive a per-entry key from the master key + entry salt.

    Uses lighter argon2 params because the master key is already
    high-entropy. Defense-in-depth: compromising one entry doesn't
    expose the master.
    """
    return hash_secret_raw(
        secret=master_key,
        salt=entry_salt,
        time_cost=ENTRY_KEY_TIME,
        memory_cost=ENTRY_KEY_MEMORY,
        parallelism=ENTRY_KEY_THREADS,
        hash_len=KEY_LEN,
        type=Type.ID,
    )


# ── encryption ───────────────────────────────────────────────────────────────

def encrypt(key: bytes, plaintext: bytes) -> bytes:
    """Encrypt plaintext with AES-256-GCM.

    Returns nonce || ciphertext+tag — the same format as the Go code.
    """
    if len(key) != KEY_LEN:
        raise ValueError(f"key length {len(key)}, want {KEY_LEN}")

    nonce = os.urandom(NONCE_LEN)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def decrypt(key: bytes, blob: bytes) -> bytes:
    """Decrypt a blob produced by encrypt().

    Raises cryptography.exceptions.InvalidTag if the key is wrong or
    the data was tampered with.
    """
    if len(blob) < NONCE_LEN:
        raise ValueError("blob too short")
    if len(key) != KEY_LEN:
        raise ValueError(f"key length {len(key)}, want {KEY_LEN}")

    nonce = blob[:NONCE_LEN]
    ciphertext = blob[NONCE_LEN:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


# ── utilities ────────────────────────────────────────────────────────────────

def new_salt() -> bytes:
    """Return a fresh random salt."""
    return os.urandom(SALT_LEN)


def zero_bytes(buf: bytearray) -> None:
    """Zero a mutable byte buffer in memory.

    Used to scrub keys from memory on lock, matching the Go code's
    key-zeroing hygiene.
    """
    for i in range(len(buf)):
        buf[i] = 0


def scrub(text: str, secret: str) -> str:
    """Remove all occurrences of secret from text.

    Exact substring replacement. Catches the common case where tool
    output echoes a credential.
    """
    if not secret:
        return text
    return text.replace(secret, "[REDACTED]")
