"""Tests for the VaultStore."""

import tempfile
from pathlib import Path

import pytest

from agentjam.vault.store import (
    AuditOptions,
    Credential,
    InjectionTemplate,
    LockState,
    VaultStore,
)


@pytest.fixture
def vault_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def unlocked_store(vault_dir):
    store = VaultStore(vault_dir)
    store.unlock("correct-horse-battery-staple")
    return store


class TestLockState:
    def test_uninitialized(self, vault_dir):
        store = VaultStore(vault_dir)
        assert store.lock_state == LockState.UNINITIALIZED
        assert not store.unlocked

    def test_lock_unlock_cycle(self, vault_dir):
        store = VaultStore(vault_dir)
        store.unlock("passphrase")
        assert store.lock_state == LockState.UNLOCKED
        assert store.unlocked

        store.lock()
        assert store.lock_state == LockState.LOCKED
        assert not store.unlocked

    def test_unlock_wrong_passphrase(self, vault_dir):
        store = VaultStore(vault_dir)
        store.unlock("correct")
        store.lock()
        with pytest.raises(ValueError, match="wrong passphrase"):
            store.unlock("wrong")

    def test_reload_persists_state(self, vault_dir):
        store = VaultStore(vault_dir)
        store.unlock("pass")
        store.add_credential(Credential(id="test", value="secret"))
        store.lock()

        # Re-open from disk.
        store2 = VaultStore(vault_dir)
        assert store2.lock_state == LockState.LOCKED
        store2.unlock("pass")
        assert store2.get_credential("test") is not None


class TestCredentials:
    def test_add_and_list(self, unlocked_store):
        unlocked_store.add_credential(Credential(
            id="github", value="ghp_token", tags=["git", "production"]
        ))
        creds = unlocked_store.list_credentials()
        assert len(creds) == 1
        assert creds[0].id == "github"
        assert creds[0].tags == ["git", "production"]
        assert creds[0].value == ""  # never in plaintext

    def test_add_duplicate_fails(self, unlocked_store):
        unlocked_store.add_credential(Credential(id="key", value="v1"))
        with pytest.raises(ValueError, match="already exists"):
            unlocked_store.add_credential(Credential(id="key", value="v2"))

    def test_add_no_value_fails(self, unlocked_store):
        with pytest.raises(ValueError, match="value is required"):
            unlocked_store.add_credential(Credential(id="key"))

    def test_add_requires_unlock(self, vault_dir):
        store = VaultStore(vault_dir)
        with pytest.raises(RuntimeError, match="locked"):
            store.add_credential(Credential(id="key", value="v"))

    def test_get(self, unlocked_store):
        unlocked_store.add_credential(Credential(id="aws", value="akid"))
        cred = unlocked_store.get_credential("aws")
        assert cred is not None
        assert cred.id == "aws"

    def test_get_missing(self, unlocked_store):
        assert unlocked_store.get_credential("nope") is None

    def test_remove(self, unlocked_store):
        unlocked_store.add_credential(Credential(id="temp", value="x"))
        unlocked_store.remove_credential("temp")
        assert unlocked_store.get_credential("temp") is None
        assert len(unlocked_store.list_credentials()) == 0

    def test_remove_missing(self, unlocked_store):
        with pytest.raises(ValueError, match="not found"):
            unlocked_store.remove_credential("nope")

    def test_remove_missing_raises(self, unlocked_store):
        with pytest.raises(ValueError, match="not found"):
            unlocked_store.remove_credential("nonexistent")

    def test_update_metadata(self, unlocked_store):
        unlocked_store.add_credential(Credential(id="key", value="v", tags=["old"]))
        unlocked_store.update_credential(Credential(id="key", description="updated", tags=["new"]))
        cred = unlocked_store.get_credential("key")
        assert cred.description == "updated"
        assert cred.tags == ["new"]

    def test_use_credential(self, unlocked_store):
        unlocked_store.add_credential(Credential(id="token", value="my-secret-value"))
        value = unlocked_store.use_credential("token")
        assert value == "my-secret-value"

    def test_use_increments_counter(self, unlocked_store):
        unlocked_store.add_credential(Credential(id="token", value="v"))
        unlocked_store.use_credential("token")
        unlocked_store.use_credential("token")
        cred = unlocked_store.get_credential("token")
        assert cred.uses_total == 2
        assert cred.last_used > 0

    def test_use_requires_unlock(self, vault_dir):
        store = VaultStore(vault_dir)
        store.unlock("pass")
        store.add_credential(Credential(id="k", value="v"))
        store.lock()
        with pytest.raises(RuntimeError, match="locked"):
            store.use_credential("k")

    def test_use_wrong_passphrase_on_reopen(self, vault_dir):
        store = VaultStore(vault_dir)
        store.unlock("correct")
        store.add_credential(Credential(id="k", value="v"))
        store.lock()

        store2 = VaultStore(vault_dir)
        with pytest.raises(ValueError, match="wrong passphrase"):
            store2.unlock("wrong")


    def test_different_salts_different_ciphertexts(self, unlocked_store):
        """Defense-in-depth: same value, different entries = different encrypted blobs."""
        unlocked_store.add_credential(Credential(id="k1", value="same-secret"))
        unlocked_store.add_credential(Credential(id="k2", value="same-secret"))
        v1 = unlocked_store.use_credential("k1")
        v2 = unlocked_store.use_credential("k2")
        assert v1 == v2 == "same-secret"
        # The encrypted blobs on disk should differ.
        e1 = unlocked_store._find_entry("k1")
        e2 = unlocked_store._find_entry("k2")
        assert e1["encrypted_value"] != e2["encrypted_value"]
        assert e1["salt"] != e2["salt"]


class TestTemplates:
    def test_set_and_get_template(self, unlocked_store):
        unlocked_store.add_credential(Credential(id="gh", value="token"))
        tmpl = InjectionTemplate(name="env", env={"GITHUB_TOKEN": "$value"})
        unlocked_store.set_template("gh", tmpl)

        got = unlocked_store.get_template("gh", "env")
        assert got is not None
        assert got.name == "env"
        assert got.env == {"GITHUB_TOKEN": "$value"}

    def test_list_templates(self, unlocked_store):
        unlocked_store.add_credential(Credential(id="gh", value="token"))
        unlocked_store.set_template("gh", InjectionTemplate(name="env"))
        unlocked_store.set_template("gh", InjectionTemplate(name="file", file_path="/tmp/token"))
        templates = unlocked_store.list_templates("gh")
        assert len(templates) == 2
        names = {t.name for t in templates}
        assert names == {"env", "file"}

    def test_replace_template(self, unlocked_store):
        unlocked_store.add_credential(Credential(id="gh", value="token"))
        unlocked_store.set_template("gh", InjectionTemplate(name="env", description="old"))
        unlocked_store.set_template("gh", InjectionTemplate(name="env", description="new"))
        got = unlocked_store.get_template("gh", "env")
        assert got.description == "new"

    def test_remove_template(self, unlocked_store):
        unlocked_store.add_credential(Credential(id="gh", value="token"))
        unlocked_store.set_template("gh", InjectionTemplate(name="env"))
        unlocked_store.remove_template("gh", "env")
        assert unlocked_store.get_template("gh", "env") is None

    def test_template_on_missing_credential(self, unlocked_store):
        with pytest.raises(ValueError, match="not found"):
            unlocked_store.set_template("nope", InjectionTemplate(name="x"))


class TestAuditLog:
    def test_audit_on_add(self, vault_dir):
        store = VaultStore(vault_dir)
        store.unlock("pass")
        store.add_credential(Credential(id="k", value="v"))
        entries = store.audit_log()
        assert len(entries) == 1
        assert entries[0].credential == "k"
        assert entries[0].success is True

    def test_audit_on_use(self, vault_dir):
        store = VaultStore(vault_dir)
        store.unlock("pass")
        store.add_credential(Credential(id="k", value="v"))
        store.use_credential("k", caller="agent:test")
        entries = store.audit_log()
        assert len(entries) >= 2
        use_entry = [e for e in entries if e.caller == "agent:test"][0]
        assert use_entry.success is True

    def test_audit_filter_since(self, vault_dir):
        import time
        store = VaultStore(vault_dir)
        store.unlock("pass")
        store.add_credential(Credential(id="k", value="v"))
        cutoff = time.time() + 1  # after the add
        store.add_credential(Credential(id="k2", value="v2"))
        entries = store.audit_log(AuditOptions(since=cutoff))
        assert len(entries) == 0  # none after cutoff
        entries = store.audit_log(AuditOptions(since=0))
        assert len(entries) == 2

    def test_audit_filter_credential(self, vault_dir):
        store = VaultStore(vault_dir)
        store.unlock("pass")
        store.add_credential(Credential(id="a", value="v"))
        store.add_credential(Credential(id="b", value="v"))
        entries = store.audit_log(AuditOptions(credential="a"))
        assert len(entries) == 1
        assert entries[0].credential == "a"

    def test_audit_limit(self, vault_dir):
        store = VaultStore(vault_dir)
        store.unlock("pass")
        for i in range(5):
            store.add_credential(Credential(id=f"k{i}", value="v"))
        entries = store.audit_log(AuditOptions(limit=3))
        assert len(entries) == 3

    def test_audit_no_log_yet(self, vault_dir):
        store = VaultStore(vault_dir)
        assert store.audit_log() == []
