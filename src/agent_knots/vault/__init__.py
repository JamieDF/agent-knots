"""Vault — encrypted credential storage with injection templates.

Usage:
    from agent_knots.vault import VaultStore, Credential, LockState

    store = VaultStore(Path("~/.agent-knots/vault"))
    store.unlock("my-passphrase")
    store.add_credential(Credential(id="github", value="ghp_..."))
    value = store.use_credential("github")
    store.lock()
"""

from agent_knots.vault.store import (
    AuditEntry,
    AuditOptions,
    Credential,
    InjectionTemplate,
    LockState,
    VaultStore,
)

__all__ = [
    "AuditEntry",
    "AuditOptions",
    "Credential",
    "InjectionTemplate",
    "LockState",
    "VaultStore",
]
