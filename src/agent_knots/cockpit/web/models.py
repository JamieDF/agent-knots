"""Request body models for the cockpit web API.

Kept in one module (rather than split per-router) since several are
small and shared across more than one router (e.g. ToggleRequest is
used by both mcp.py and workflows.py) — module-level so FastAPI can
resolve them at import time regardless of which router imports them.
"""

from typing import Optional

from pydantic import BaseModel


class SaveSettingsRequest(BaseModel):
    default_model: str = "openai/gpt-4o-mini"
    api_key: str = ""
    base_url: str = ""
    default_mode: str = ""
    runtime: str = ""
    # None = preserve existing value. Unlike the string fields above,
    # 0 is a meaningful real value here (never auto-purge), so the
    # empty-string-means-preserve convention doesn't fit.
    wastebin_retention_days: int | None = None


class CreateSessionRequest(BaseModel):
    prompt: str = ""
    mode: str = "agent"
    task_id: Optional[str] = None
    project_id: Optional[str] = None


class CheckpointRequest(BaseModel):
    label: str = "checkpoint"


class AutonomousRequest(BaseModel):
    on: bool


class CreateTaskRequest(BaseModel):
    title: str
    description: str = ""
    priority: str = "medium"
    status: str = "draft"
    project: str = ""
    tags: list = []
    acceptance_criteria: list = []
    review_gate: str = "manual"
    dependencies: list = []


class UpdateTaskRequest(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    assign: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list] = None
    acceptance_criteria: Optional[list] = None
    steps: Optional[list] = None  # list of step title strings
    review_gate: Optional[str] = None
    dependencies: Optional[list] = None


class ToggleCriterionRequest(BaseModel):
    criterion: str
    met: bool


class DraftTaskRequest(BaseModel):
    title: str


class ToggleRequest(BaseModel):
    enabled: bool


class UpdateRoleRequest(BaseModel):
    model: Optional[str] = None
    provider: Optional[str] = None
    trigger: Optional[str] = None
    prompt: Optional[str] = None
    enabled: Optional[bool] = None


class ReviewApproveRequest(BaseModel):
    task_id: str
    file: Optional[str] = None  # omitted = every file still pending for this task


class ReviewRejectRequest(BaseModel):
    task_id: str
    file: Optional[str] = None  # omitted = every file still pending for this task
    reason: str
    # Files already approved (and committed) earlier in this same
    # review pass — the frontend already knows this from its own prior
    # approve calls. Folded into the feedback message sent back to the
    # agent so a mixed pass ("this one's fine, that one isn't") reads
    # as one coherent note instead of the agent only hearing about the
    # rejection.
    approved_files: list[str] = []


class UnlockVaultRequest(BaseModel):
    passphrase: str


class AddCredentialRequest(BaseModel):
    id: str
    description: str = ""
    tags: list = []
    value: str


class AddProviderRequest(BaseModel):
    name: str
    model: str = ""
    api_key: str = ""
    base_url: str = ""


class UpdatePolicyRequest(BaseModel):
    enabled: Optional[bool] = None
    value: Optional[str] = None


class AddMcpServerRequest(BaseModel):
    name: str
    url: str = ""


class SaveIntegrationsRequest(BaseModel):
    github_pr_on_review: Optional[bool] = None
    phone_push: Optional[bool] = None


class CreateToolRequest(BaseModel):
    name: str
    description: str = ""
    command: str
    parameters: list = []  # list of {name, type, description}


class UpdateToolRequest(BaseModel):
    description: Optional[str] = None
    command: Optional[str] = None
    parameters: Optional[list] = None


class CreateWorkspaceRequest(BaseModel):
    id: Optional[str] = None  # omitted = slugify from name, deduped
    name: str
    description: str = ""
    repository: str = ""
    runtime: str = ""
    provider: str = ""
    tags: list = []
    auto_assign: bool = False
    max_concurrent: int = 2


class UpdateWorkspaceRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    repository: Optional[str] = None
    runtime: Optional[str] = None
    provider: Optional[str] = None
    tags: Optional[list] = None
    auto_assign: Optional[bool] = None
    max_concurrent: Optional[int] = None
    archived: Optional[bool] = None
