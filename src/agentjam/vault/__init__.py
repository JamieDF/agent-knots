"""Vault — encrypted credential storage with injection templates.

Usage:
    from agentjam.vault import VaultStore, Credential, LockState

    store = VaultStore(Path("~/.agentjam/vault"))
    store.unlock("my-passphrase")
    store.add_credential(Credential(id="github", value="ghp_..."))
    value = store.use_credential("github")
    store.lock()
"""

from agentjam.vault.store import (
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
