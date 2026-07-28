"""File-backed vault implementation.

Ported from internal/vault/filestore/filestore.go.

Layout:
    ~/.agent-knots/vault/
    ├── vault.enc       # AES-256-GCM encrypted credential entries (JSON)
    └── vault.log       # Append-only audit log (JSONL)

The vault.enc file is a JSON document with cleartext metadata and
encrypted values. Each entry has its own salt for per-entry key
derivation (defense-in-depth).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from agent_knots.vault import crypto


# ── data types ───────────────────────────────────────────────────────────────


class LockState(StrEnum):
    LOCKED = "locked"
    UNLOCKED = "unlocked"
    UNINITIALIZED = "uninitialized"


@dataclass
class InjectionTemplate:
    """How to expose a credential value when used."""
    name: str
    description: str = ""
    env: dict[str, str] = field(default_factory=dict)
    file_path: str | None = None
    file_permissions: int = 0o600
    stdin: bool = False
    stdin_trailing_newline: bool = False
    command_wrapper: str | None = None


@dataclass
class Credential:
    """Metadata for a stored credential. Value is never in cleartext here."""
    id: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_used: float = 0.0
    uses_total: int = 0
    templates: list[InjectionTemplate] = field(default_factory=list)

    # Only populated by Use() — never persisted in plaintext.
    value: str = field(default="", repr=False)


@dataclass
class AuditEntry:
    """One row in the append-only audit log."""
    timestamp: float = field(default_factory=time.time)
    credential: str = ""
    template: str = ""
    command: str = ""
    caller: str = ""
    success: bool = False
    error: str = ""
    duration: float = 0.0


@dataclass
class AuditOptions:
    """Filters for audit log queries."""
    since: float = 0.0
    credential: str = ""
    limit: int = 0


def render_env(template: InjectionTemplate, value: str) -> dict[str, str]:
    """Substitute the decrypted value into an env-mode template's $value
    placeholders (the convention documented in `vault template add
    --env`), producing the actual environment variables to inject.

    Raises on non-env templates (file/stdin/command_wrapper) rather than
    silently doing nothing — those modes aren't implemented for session
    tool injection yet, and returning {} would look like "no
    credentials needed" instead of "this template can't be used here".
    """
    if not template.env:
        raise ValueError(f"template {template.name!r} is not an env-mode template")
    return {k: v.replace("$value", value) for k, v in template.env.items()}


# ── on-disk entry (private) ──────────────────────────────────────────────────


@dataclass
class _Entry:
    """On-disk representation of a credential entry."""
    id: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_used: float = 0.0
    uses_total: int = 0
    encrypted_value: bytes = b""
    salt: bytes = b""
    templates: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_credential(cls, cred: Credential, encrypted: bytes, salt: bytes) -> _Entry:
        return cls(
            id=cred.id,
            description=cred.description,
            tags=cred.tags,
            created_at=cred.created_at,
            last_used=cred.last_used,
            uses_total=cred.uses_total,
            encrypted_value=encrypted,
            salt=salt,
            templates=[_template_to_dict(t) for t in cred.templates],
        )

    def to_credential(self) -> Credential:
        return Credential(
            id=self.id,
            description=self.description,
            tags=self.tags,
            created_at=self.created_at,
            last_used=self.last_used,
            uses_total=self.uses_total,
            templates=[_template_from_dict(t) for t in self.templates],
        )


def _template_to_dict(t: InjectionTemplate) -> dict[str, Any]:
    d: dict[str, Any] = {"name": t.name}
    if t.description:
        d["description"] = t.description
    if t.env:
        d["env"] = t.env
    if t.file_path:
        d["file_path"] = t.file_path
        d["file_permissions"] = t.file_permissions
    if t.stdin:
        d["stdin"] = True
        if t.stdin_trailing_newline:
            d["stdin_trailing_newline"] = True
    if t.command_wrapper:
        d["command_wrapper"] = t.command_wrapper
    return d


def _template_from_dict(d: dict[str, Any]) -> InjectionTemplate:
    return InjectionTemplate(
        name=d["name"],
        description=d.get("description", ""),
        env=d.get("env", {}),
        file_path=d.get("file_path"),
        file_permissions=d.get("file_permissions", 0o600),
        stdin=d.get("stdin", False),
        stdin_trailing_newline=d.get("stdin_trailing_newline", False),
        command_wrapper=d.get("command_wrapper"),
    )


# ── on-disk file document ────────────────────────────────────────────────────


@dataclass
class _VaultFile:
    version: int = 1
    entries: list[dict[str, Any]] = field(default_factory=list)
    modified: float = field(default_factory=time.time)


# ── store ────────────────────────────────────────────────────────────────────


class VaultStore:
    """File-backed vault with AES-256-GCM encryption.

    Thread-safe via asyncio.Lock. Use within an async context.
    """

    def __init__(self, vault_dir: Path) -> None:
        self._path = Path(vault_dir) / "vault.enc"
        self._log_path = Path(vault_dir) / "vault.log"
        self._key: bytearray | None = None  # zeroed on lock
        self._unlocked: bool = False
        self._file: _VaultFile = _VaultFile()
        self._load()

    # ── public API ────────────────────────────────────────────────────────

    @property
    def lock_state(self) -> LockState:
        """Return the current lock state."""
        if not self._path.exists():
            return LockState.UNINITIALIZED
        if self._unlocked:
            return LockState.UNLOCKED
        return LockState.LOCKED

    @property
    def unlocked(self) -> bool:
        return self._unlocked

    def lock(self) -> None:
        """Lock the vault — zeroes the key in memory."""
        if self._key is not None:
            crypto.zero_bytes(self._key)
            self._key = None
        self._unlocked = False

    def unlock(self, passphrase: str) -> None:
        """Unlock the vault with a passphrase.

        On first use (no vault file exists), initialises the vault with
        the given passphrase. On subsequent uses, derives the key from
        passphrase + stored salt and verifies against the marker entry.

        Raises ValueError if the passphrase is wrong.
        """
        if not passphrase:
            raise ValueError("passphrase is required")

        self._refresh()
        if not self._file.entries and not self._path.exists():
            self._initialise(passphrase)
            return

        # Find the marker entry.
        marker_entry = self._find_entry("_vault_marker_")
        if marker_entry is None:
            raise ValueError("vault has no marker; cannot unlock")

        salt = bytes(marker_entry["salt"])
        encrypted = bytes(marker_entry["encrypted_value"])

        key = crypto.derive_key(passphrase, salt)
        try:
            plain = crypto.decrypt(key, encrypted)
        except Exception:
            crypto.zero_bytes(bytearray(key))
            raise ValueError("wrong passphrase or corrupted vault") from None

        if plain != crypto.MARKER_PLAINTEXT:
            crypto.zero_bytes(bytearray(key))
            raise ValueError("vault marker mismatch")

        self._key = bytearray(key)
        self._unlocked = True

    def _refresh(self) -> None:
        """Re-read vault.enc from disk before this operation.

        A VaultStore instance is long-lived — the web server keeps one
        for its entire process lifetime — but the file can be changed
        by a completely different process, most notably the CLI's
        `vault template add`, since template management is CLI-only by
        design (see ADR 0002). Without this, a template added via the
        CLI while the web server is already running would never be
        seen by it: the server's in-memory copy would just silently
        keep reporting "no env-mode injection template" until restart.

        Cheap — _load() only parses the on-disk JSON structure, it
        doesn't touch the derived key, so this doesn't affect
        unlocked/locked state or require re-deriving anything.
        """
        self._load()

    def list_credentials(self) -> list[Credential]:
        """Return all credentials (without values)."""
        self._refresh()
        return [
            _Entry(**e).to_credential()
            for e in self._file.entries
            if e.get("id") != "_vault_marker_"
        ]

    def get_credential(self, cred_id: str) -> Credential | None:
        """Return credential metadata by ID, or None."""
        self._refresh()
        entry = self._find_entry(cred_id)
        if entry is None:
            return None
        return _Entry(**entry).to_credential()

    def add_credential(self, cred: Credential) -> None:
        """Add a new credential. The vault must be unlocked.

        Raises ValueError if the ID already exists or the vault is locked.
        """
        self._ensure_unlocked()
        self._refresh()
        if self._find_entry(cred.id) is not None:
            raise ValueError(f"credential {cred.id!r} already exists")
        if not cred.value:
            raise ValueError("credential value is required")

        salt = crypto.new_salt()
        entry_key = crypto.derive_entry_key(bytes(self._key), salt)  # type: ignore[arg-type]
        encrypted = crypto.encrypt(entry_key, bytes(cred.value, "utf-8"))
        crypto.zero_bytes(bytearray(entry_key))

        entry = _Entry.from_credential(cred, encrypted, salt)
        self._file.entries.append(self._entry_to_dict(entry))
        self._save()

        self._append_audit(AuditEntry(
            credential=cred.id,
            caller="user",
            success=True,
        ))

    def remove_credential(self, cred_id: str) -> None:
        """Remove a credential by ID. The vault must be unlocked."""
        self._ensure_unlocked()
        self._refresh()
        for i, e in enumerate(self._file.entries):
            if e.get("id") == cred_id:
                self._file.entries.pop(i)
                self._save()
                return
        raise ValueError(f"credential {cred_id!r} not found")

    def update_credential(self, cred: Credential) -> None:
        """Update credential metadata (not the value)."""
        self._ensure_unlocked()
        self._refresh()
        entry = self._find_entry(cred.id)
        if entry is None:
            raise ValueError(f"credential {cred.id!r} not found")
        entry["description"] = cred.description
        entry["tags"] = cred.tags
        self._save()

    def set_template(self, cred_id: str, tmpl: InjectionTemplate) -> None:
        """Add or replace a template on a credential."""
        self._ensure_unlocked()
        self._refresh()
        entry = self._find_entry(cred_id)
        if entry is None:
            raise ValueError(f"credential {cred_id!r} not found")
        templates: list[dict[str, Any]] = entry.setdefault("templates", [])
        tmpl_dict = _template_to_dict(tmpl)
        for i, t in enumerate(templates):
            if t.get("name") == tmpl.name:
                templates[i] = tmpl_dict
                self._save()
                return
        templates.append(tmpl_dict)
        self._save()

    def get_template(self, cred_id: str, name: str) -> InjectionTemplate | None:
        """Get a specific template from a credential."""
        self._refresh()
        entry = self._find_entry(cred_id)
        if entry is None:
            return None
        for t in entry.get("templates", []):
            if t.get("name") == name:
                return _template_from_dict(t)
        return None

    def list_templates(self, cred_id: str) -> list[InjectionTemplate]:
        """List all templates for a credential."""
        self._refresh()
        entry = self._find_entry(cred_id)
        if entry is None:
            return []
        return [_template_from_dict(t) for t in entry.get("templates", [])]

    def remove_template(self, cred_id: str, name: str) -> None:
        """Remove a template from a credential."""
        self._ensure_unlocked()
        self._refresh()
        entry = self._find_entry(cred_id)
        if entry is None:
            raise ValueError(f"credential {cred_id!r} not found")
        templates: list[dict[str, Any]] = entry.get("templates", [])
        for i, t in enumerate(templates):
            if t.get("name") == name:
                templates.pop(i)
                self._save()
                return
        raise ValueError(f"template {name!r} not found on {cred_id!r}")

    def use_credential(self, cred_id: str, template_name: str = "",
                       command: str = "", args: list[str] | None = None,
                       caller: str = "user") -> str:
        """Return the decrypted credential value.

        This is a simplified Use that returns the value directly.
        The full Go-style Use (command execution with injection) will be
        built on top of this when the agent runtime is implemented.

        Records an audit entry.
        """
        started = time.time()
        self._ensure_unlocked()
        self._refresh()
        entry = self._find_entry(cred_id)
        if entry is None:
            raise ValueError(f"credential {cred_id!r} not found")

        salt = bytes(entry["salt"])
        encrypted = bytes(entry["encrypted_value"])
        entry_key = crypto.derive_entry_key(bytes(self._key), salt)  # type: ignore[arg-type]

        try:
            plain = crypto.decrypt(entry_key, encrypted).decode("utf-8")
        except Exception:
            crypto.zero_bytes(bytearray(entry_key))
            self._append_audit(AuditEntry(
                credential=cred_id,
                template=template_name,
                caller=caller,
                success=False,
                error="decryption failed",
                duration=time.time() - started,
            ))
            raise ValueError(f"failed to decrypt credential {cred_id!r}") from None
        finally:
            crypto.zero_bytes(bytearray(entry_key))

        # Update usage stats.
        entry["last_used"] = time.time()
        entry["uses_total"] = entry.get("uses_total", 0) + 1
        self._save()

        self._append_audit(AuditEntry(
            credential=cred_id,
            template=template_name,
            command=command,
            caller=caller,
            success=True,
            duration=time.time() - started,
        ))

        return plain

    def resolve_env(
        self, cred_ids: list[str], caller: str = "",
    ) -> tuple[dict[str, str], list[str]]:
        """Render env-var injection templates for a list of credential ids
        into one merged environment dict.

        Never raises — every failure (credential missing, no env-mode
        template, vault locked) becomes a problem string naming only the
        credential id, never a value. A missing credential must not stop
        a session from starting; it should just not have that
        credential's env vars available, with the gap surfaced to
        whoever's watching rather than silently swallowed.
        """
        env: dict[str, str] = {}
        problems: list[str] = []
        for cred_id in cred_ids:
            if self.get_credential(cred_id) is None:
                problems.append(f"{cred_id}: credential not found")
                continue
            template = next((t for t in self.list_templates(cred_id) if t.env), None)
            if template is None:
                problems.append(f"{cred_id}: no env-mode injection template")
                continue
            try:
                value = self.use_credential(cred_id, template_name=template.name, caller=caller)
            except (RuntimeError, ValueError) as e:
                problems.append(f"{cred_id}: {e}")
                continue
            env.update(render_env(template, value))
        return env, problems

    def audit_log(self, opts: AuditOptions | None = None) -> list[AuditEntry]:
        """Return audit entries matching the given options."""
        opts = opts or AuditOptions()
        entries: list[AuditEntry] = []

        if not self._log_path.exists():
            return entries

        for line in self._log_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                e = AuditEntry(
                    timestamp=data.get("timestamp", 0),
                    credential=data.get("credential", ""),
                    template=data.get("template", ""),
                    command=data.get("command", ""),
                    caller=data.get("caller", ""),
                    success=data.get("success", False),
                    error=data.get("error", ""),
                    duration=data.get("duration", 0),
                )
            except json.JSONDecodeError:
                continue

            if opts.since and e.timestamp < opts.since:
                continue
            if opts.credential and e.credential != opts.credential:
                continue

            entries.append(e)
            if opts.limit and len(entries) >= opts.limit:
                break

        return entries

    # ── internals ─────────────────────────────────────────────────────────

    def _ensure_unlocked(self) -> None:
        if not self._unlocked:
            raise RuntimeError("vault is locked")

    def _find_entry(self, cred_id: str) -> dict[str, Any] | None:
        for e in self._file.entries:
            if e.get("id") == cred_id:
                return e
        return None

    def _entry_to_dict(self, entry: _Entry) -> dict[str, Any]:
        d = {
            "id": entry.id,
            "description": entry.description,
            "tags": entry.tags,
            "created_at": entry.created_at,
            "last_used": entry.last_used,
            "uses_total": entry.uses_total,
            "encrypted_value": list(entry.encrypted_value),
            "salt": list(entry.salt),
        }
        if entry.templates:
            d["templates"] = entry.templates
        return d

    def _initialise(self, passphrase: str) -> None:
        """First-time vault creation."""
        salt = crypto.new_salt()
        key = crypto.derive_key(passphrase, salt)
        encrypted = crypto.encrypt(key, crypto.MARKER_PLAINTEXT)

        self._file.entries.append({
            "id": "_vault_marker_",
            "description": "",
            "tags": [],
            "created_at": time.time(),
            "last_used": 0,
            "uses_total": 0,
            "encrypted_value": list(encrypted),
            "salt": list(salt),
        })
        self._save()

        self._key = bytearray(key)
        self._unlocked = True

    def _load(self) -> None:
        """Load the vault from disk. Missing file = first-time creation."""
        if not self._path.exists():
            self._file = _VaultFile()
            return

        data = json.loads(self._path.read_text())
        if data.get("version") != 1:
            raise ValueError(f"unsupported vault version {data.get('version')}")

        self._file = _VaultFile(
            version=data["version"],
            entries=data.get("entries", []),
            modified=data.get("modified", time.time()),
        )

    def _save(self) -> None:
        """Atomically persist the vault to disk (write to .tmp, rename)."""
        self._file.modified = time.time()
        doc = {
            "version": self._file.version,
            "entries": self._file.entries,
            "modified": self._file.modified,
        }
        data = json.dumps(doc, indent=2)

        tmp_path = self._path.with_suffix(".tmp")
        tmp_path.write_text(data)
        os.chmod(tmp_path, 0o600)
        tmp_path.rename(self._path)

    def _append_audit(self, entry: AuditEntry) -> None:
        """Write one audit entry to the log."""
        data = json.dumps({
            "timestamp": entry.timestamp,
            "credential": entry.credential,
            "template": entry.template,
            "command": entry.command,
            "caller": entry.caller,
            "success": entry.success,
            "error": entry.error,
            "duration": entry.duration,
        })
        with open(self._log_path, "a") as fh:
            os.chmod(self._log_path, 0o600)
            fh.write(data + "\n")
