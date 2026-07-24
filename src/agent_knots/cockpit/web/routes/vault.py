"""Vault API — metadata only, values never leave the store."""

from fastapi import APIRouter, HTTPException, Query

from agent_knots.cockpit.web.decorators import raises_as
from agent_knots.cockpit.web.models import AddCredentialRequest, UnlockVaultRequest
from agent_knots.vault.store import Credential, VaultStore


def _credential_to_response(c) -> dict:
    """Metadata only — deliberately does not reference c.value at all,
    even though the store never populates it from list_credentials()."""
    return {
        "id": c.id, "description": c.description, "tags": c.tags,
        "created_at": c.created_at, "last_used": c.last_used, "uses_total": c.uses_total,
        "templates": [
            {"name": t.name, "description": t.description, "env": t.env, "file_path": t.file_path,
             "stdin": t.stdin, "command_wrapper": t.command_wrapper}
            for t in c.templates
        ],
    }


def create_router(vault: VaultStore) -> APIRouter:
    router = APIRouter()

    @router.get("/api/vault/status")
    async def vault_status():
        return {"lock_state": vault.lock_state.value}

    @router.post("/api/vault/unlock")
    @raises_as(400)
    async def vault_unlock(body: UnlockVaultRequest):
        vault.unlock(body.passphrase)
        return {"lock_state": vault.lock_state.value}

    @router.post("/api/vault/lock")
    async def vault_lock():
        vault.lock()
        return {"lock_state": vault.lock_state.value}

    @router.get("/api/vault/credentials")
    async def list_credentials():
        if not vault.unlocked:
            raise HTTPException(status_code=403, detail="Vault is locked")
        return {"credentials": [_credential_to_response(c) for c in vault.list_credentials()]}

    @router.post("/api/vault/credentials")
    async def add_credential(body: AddCredentialRequest):
        cred = Credential(id=body.id, description=body.description, tags=body.tags, value=body.value)
        try:
            vault.add_credential(cred)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"status": "ok", "id": cred.id}

    @router.delete("/api/vault/credentials/{cred_id}")
    async def delete_credential(cred_id: str):
        try:
            vault.remove_credential(cred_id)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"status": "ok"}

    @router.get("/api/vault/audit")
    async def vault_audit(limit: int = Query(50)):
        from agent_knots.vault.store import AuditOptions
        entries = vault.audit_log(AuditOptions(limit=limit))
        return {"entries": [
            {
                "timestamp": e.timestamp, "credential": e.credential, "template": e.template,
                "command": e.command, "caller": e.caller, "success": e.success, "error": e.error,
            }
            for e in entries
        ]}

    return router
