"""Tests for the VaultStore."""

import tempfile
from pathlib import Path

import pytest

from agent_knots.vault.store import (
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

    def test_duration_is_recorded(self, unlocked_store):
        unlocked_store.add_credential(Credential(id="k", value="v"))
        unlocked_store.use_credential("k")
        entries = unlocked_store.audit_log()
        assert entries[-1].duration >= 0.0


class TestRenderEnv:
    def test_substitutes_value_placeholder(self):
        from agent_knots.vault.store import render_env
        tmpl = InjectionTemplate(name="env", env={"GH_TOKEN": "$value"})
        assert render_env(tmpl, "secret123") == {"GH_TOKEN": "secret123"}

    def test_substitutes_within_a_larger_string(self):
        from agent_knots.vault.store import render_env
        tmpl = InjectionTemplate(name="env", env={"AUTH": "Bearer $value"})
        assert render_env(tmpl, "tok") == {"AUTH": "Bearer tok"}

    def test_multiple_env_vars(self):
        from agent_knots.vault.store import render_env
        tmpl = InjectionTemplate(name="env", env={"A": "$value", "B": "static"})
        assert render_env(tmpl, "x") == {"A": "x", "B": "static"}

    def test_non_env_template_raises(self):
        from agent_knots.vault.store import render_env
        tmpl = InjectionTemplate(name="file", file_path="/tmp/x")
        with pytest.raises(ValueError, match="not an env-mode template"):
            render_env(tmpl, "secret")


class TestResolveEnv:
    def test_resolves_single_credential(self, unlocked_store):
        unlocked_store.add_credential(Credential(id="gh", value="ghp_abc123456"))
        unlocked_store.set_template("gh", InjectionTemplate(name="e", env={"GH_TOKEN": "$value"}))

        env, problems = unlocked_store.resolve_env(["gh"])

        assert env == {"GH_TOKEN": "ghp_abc123456"}
        assert problems == []

    def test_merges_multiple_credentials(self, unlocked_store):
        unlocked_store.add_credential(Credential(id="gh", value="gh-secret"))
        unlocked_store.set_template("gh", InjectionTemplate(name="e", env={"GH_TOKEN": "$value"}))
        unlocked_store.add_credential(Credential(id="npm", value="npm-secret"))
        unlocked_store.set_template("npm", InjectionTemplate(name="e", env={"NPM_TOKEN": "$value"}))

        env, problems = unlocked_store.resolve_env(["gh", "npm"])

        assert env == {"GH_TOKEN": "gh-secret", "NPM_TOKEN": "npm-secret"}
        assert problems == []

    def test_missing_credential_is_a_problem_not_an_exception(self, unlocked_store):
        env, problems = unlocked_store.resolve_env(["does-not-exist"])
        assert env == {}
        assert len(problems) == 1
        assert "does-not-exist" in problems[0]
        assert "not found" in problems[0]

    def test_credential_with_no_env_template_is_a_problem(self, unlocked_store):
        unlocked_store.add_credential(Credential(id="gh", value="v"))
        unlocked_store.set_template("gh", InjectionTemplate(name="f", file_path="/tmp/x"))

        env, problems = unlocked_store.resolve_env(["gh"])

        assert env == {}
        assert "no env-mode injection template" in problems[0]

    def test_locked_vault_is_a_problem_not_an_exception(self, vault_dir):
        store = VaultStore(vault_dir)
        store.unlock("pass")
        store.add_credential(Credential(id="gh", value="v"))
        store.set_template("gh", InjectionTemplate(name="e", env={"T": "$value"}))
        store.lock()

        env, problems = store.resolve_env(["gh"])

        assert env == {}
        assert "gh" in problems[0]

    def test_partial_success_still_returns_the_good_credentials(self, unlocked_store):
        unlocked_store.add_credential(Credential(id="gh", value="gh-secret"))
        unlocked_store.set_template("gh", InjectionTemplate(name="e", env={"GH_TOKEN": "$value"}))

        env, problems = unlocked_store.resolve_env(["gh", "missing"])

        assert env == {"GH_TOKEN": "gh-secret"}
        assert len(problems) == 1
        assert "missing" in problems[0]

    def test_never_leaks_value_into_problem_strings(self, unlocked_store):
        unlocked_store.add_credential(Credential(id="gh", value="super-secret-value"))
        unlocked_store.set_template("gh", InjectionTemplate(name="f", file_path="/tmp/x"))

        _, problems = unlocked_store.resolve_env(["gh"])

        assert "super-secret-value" not in problems[0]


class TestCrossProcessRefresh:
    """Regression coverage for a real bug found testing this live: a
    VaultStore is long-lived (the web server keeps one for its whole
    process lifetime), but template management is CLI-only by design —
    a completely separate process. Without refreshing from disk before
    each operation, a template added via the CLI while the server was
    already running was invisible to it until restart: resolve_env kept
    reporting "no env-mode injection template" even though the template
    existed on disk, because the server's in-memory copy predated it."""

    def test_template_added_by_a_second_instance_is_visible(self, vault_dir):
        server_store = VaultStore(vault_dir)
        server_store.unlock("pass")
        server_store.add_credential(Credential(id="gh", value="secret-value"))

        # A second VaultStore pointed at the same directory — standing
        # in for the CLI process that's the only way to add templates.
        cli_store = VaultStore(vault_dir)
        cli_store.unlock("pass")
        cli_store.set_template("gh", InjectionTemplate(name="e", env={"TOK": "$value"}))

        # The first instance never re-constructed — this is the part
        # that broke: it must still see the template the other process
        # just wrote.
        assert server_store.list_templates("gh") != []
        env, problems = server_store.resolve_env(["gh"])
        assert env == {"TOK": "secret-value"}
        assert problems == []

    def test_credential_added_by_a_second_instance_is_visible(self, vault_dir):
        store_a = VaultStore(vault_dir)
        store_a.unlock("pass")

        store_b = VaultStore(vault_dir)
        store_b.unlock("pass")
        store_b.add_credential(Credential(id="new-cred", value="v"))

        assert store_a.get_credential("new-cred") is not None
        assert any(c.id == "new-cred" for c in store_a.list_credentials())
