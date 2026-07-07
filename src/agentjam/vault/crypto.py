"""Vault cryptographic primitives.

Ported from the Go vault implementation. Uses AES-256-GCM for encryption
and argon2id for key derivation.

Design (from original Go code):
  - Master key derived from passphrase via argon2id (salt stored in vault header).
  - Each entry encrypted with AES-256-GCM (random nonce, stored with ciphertext).
  - Output scrubbing prevents credential leakage into agent context.
  - Every use is audit-logged.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field


@dataclass
class VaultHeader:
    """Unencrypted vault metadata."""

    salt: bytes
    argon2_time: int = 3
    argon2_memory: int = 64 * 1024  # 64 MB
    argon2_threads: int = 4
    created_at: float = field(default_factory=time.time)


@dataclass
class VaultEntry:
    """A single encrypted credential entry."""

    id: str
    name: str
    encrypted_data: bytes
    nonce: bytes
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


def derive_key(passphrase: str, salt: bytes, time_cost: int = 3,
               memory_cost: int = 64 * 1024, parallelism: int = 4) -> bytes:
    """Derive a 256-bit key from a passphrase using argon2id.

    Not yet implemented.
    """
    raise NotImplementedError


def encrypt(key: bytes, plaintext: bytes) -> tuple[bytes, bytes]:
    """Encrypt plaintext with AES-256-GCM. Returns (ciphertext, nonce).

    Not yet implemented.
    """
    raise NotImplementedError


def decrypt(key: bytes, ciphertext: bytes, nonce: bytes) -> bytes:
    """Decrypt ciphertext with AES-256-GCM.

    Not yet implemented.
    """
    raise NotImplementedError


def scrub(data: bytes) -> None:
    """Zero a byte buffer in memory to prevent credential leakage.

    Not yet implemented.
    """
    raise NotImplementedError
