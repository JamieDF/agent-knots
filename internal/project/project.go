// Package project defines the Project system — multi-repo workspaces that
// bundle N git repos into one logical unit, with project-level settings,
// vault scope, and conventions.
//
// A Project is a directory containing N git repos, each with its own
// remote, branch, and role label. Projects also carry:
//
//   - Default model, agent model, cheap model per project
//   - Build/test/lint/format commands
//   - Ignored paths (agent should never touch)
//   - Risk policies (require approval, blocked commands, max files per edit)
//   - Vault credential scope (allowed/denied per project)
//   - Mode persona + extras
//
// Projects are the unit of switching: `harness project switch <name>` makes
// that project the active context for all subsequent commands.
package project

import (
	"time"
)

// ID is a project identifier (e.g. "my-cool-app"). IDs are unique within a
// harness workspace.
type ID string

// Repo is a single git repository that belongs to a project.
type Repo struct {
	// Path is the path to the repo, relative to the project root or absolute.
	// Used by the orchestrator when running file/shell operations.
	Path string `yaml:"path" json:"path"`

	// Remote is the git remote URL (e.g. "[email protected]:org/repo.git").
	// Optional — projects can have local-only repos.
	Remote string `yaml:"remote,omitempty" json:"remote,omitempty"`

	// Branch is the default branch (e.g. "main").
	Branch string `yaml:"branch,omitempty" json:"branch,omitempty"`

	// Role is a human-readable label for what this repo is for
	// (e.g. "frontend", "backend", "shared library").
	Role string `yaml:"role,omitempty" json:"role,omitempty"`
}

// Commands lists the build/test/lint commands for the project.
type Commands struct {
	Test       string `yaml:"test,omitempty" json:"test,omitempty"`
	Lint       string `yaml:"lint,omitempty" json:"lint,omitempty"`
	Build      string `yaml:"build,omitempty" json:"build,omitempty"`
	Format     string `yaml:"format,omitempty" json:"format,omitempty"`
	Install    string `yaml:"install,omitempty" json:"install,omitempty"`
	Typecheck  string `yaml:"typecheck,omitempty" json:"typecheck,omitempty"`
}

// RiskPolicies governs what actions the agent can take without approval.
type RiskPolicies struct {
	// RequireApprovalFor lists command patterns that require user approval
	// even in agent mode (e.g. "rm -rf", "git push --force").
	RequireApprovalFor []string `yaml:"require_approval_for,omitempty" json:"require_approval_for,omitempty"`

	// BlockedCommands lists command patterns that are never allowed.
	BlockedCommands []string `yaml:"blocked_commands,omitempty" json:"blocked_commands,omitempty"`

	// MaxFilesPerEdit caps the number of files an agent can modify in a
	// single tool call. Zero = unlimited.
	MaxFilesPerEdit int `yaml:"max_files_per_edit,omitempty" json:"max_files_per_edit,omitempty"`
}

// VaultScope restricts which vault credentials are usable in this project.
type VaultScope struct {
	// AllowedCredentials lists vault:// URIs that may be used in this
	// project. Empty = all credentials allowed.
	AllowedCredentials []string `yaml:"allowed_credentials,omitempty" json:"allowed_credentials,omitempty"`

	// DeniedCredentials explicitly forbids these vault:// URIs even if
	// allowed elsewhere.
	DeniedCredentials []string `yaml:"denied_credentials,omitempty" json:"denied_credentials,omitempty"`
}

// Prompts holds the system prompt configuration for the project.
type Prompts struct {
	// Mode is the default mode name (matches a file in modes/).
	Mode string `yaml:"mode,omitempty" json:"mode,omitempty"`

	// Extras is appended to the mode's system prompt. Project-specific
	// instructions, conventions, etc.
	Extras string `yaml:"extras,omitempty" json:"extras,omitempty"`
}

// Project is a multi-repo workspace.
type Project struct {
	// ID is the project's unique identifier.
	ID ID `yaml:"id" json:"id"`

	// Name is a human-readable display name.
	Name string `yaml:"name" json:"name"`

	// Description is optional longer-form context.
	Description string `yaml:"description,omitempty" json:"description,omitempty"`

	// WorkspaceRoot is the directory containing the project's repos.
	WorkspaceRoot string `yaml:"workspace_root" json:"workspace_root"`

	// Repos lists the git repositories in this project.
	Repos []Repo `yaml:"repos" json:"repos"`

	// Models configures default models for different roles.
	Models Models `yaml:"models" json:"models"`

	// Commands lists the build/test/lint commands.
	Commands Commands `yaml:"commands,omitempty" json:"commands,omitempty"`

	// IgnoredPaths lists glob patterns the agent should never touch
	// (e.g. "node_modules", "*.lock").
	IgnoredPaths []string `yaml:"ignored_paths,omitempty" json:"ignored_paths,omitempty"`

	// Conventions is a free-form note describing project conventions
	// (language, framework, style).
	Conventions string `yaml:"conventions,omitempty" json:"conventions,omitempty"`

	// RiskPolicies governs risky actions.
	RiskPolicies RiskPolicies `yaml:"risk_policies,omitempty" json:"risk_policies,omitempty"`

	// VaultScope restricts credential access.
	VaultScope VaultScope `yaml:"vault_scope,omitempty" json:"vault_scope,omitempty"`

	// Prompts configures the default system prompt.
	Prompts Prompts `yaml:"prompts,omitempty" json:"prompts,omitempty"`

	// CreatedAt is when the project was created.
	CreatedAt time.Time `yaml:"created_at" json:"created_at"`

	// LastOpenedAt is when the project was last made active.
	LastOpenedAt time.Time `yaml:"last_opened_at,omitempty" json:"last_opened_at,omitempty"`
}

// Models holds model preferences for different roles.
type Models struct {
	// Default is the model for general chat.
	Default string `yaml:"default,omitempty" json:"default,omitempty"`

	// Agent is the model for autonomous agent mode.
	Agent string `yaml:"agent,omitempty" json:"agent,omitempty"`

	// Cheap is the model for summarization, classification, and other
	// background tasks.
	Cheap string `yaml:"cheap,omitempty" json:"cheap,omitempty"`
}

// ListOptions filters project queries.
type ListOptions struct {
	// Tags filters to projects with all of the specified tags.
	Tags []string
}

// Store is the interface for project persistence.
//
// Implementations live under internal/project/filestore.
type Store interface {
	// Create persists a new project. Errors with ErrAlreadyExists if the ID
	// is taken.
	Create(p *Project) error

	// Get returns the project by ID. Errors with ErrNotFound if absent.
	Get(id ID) (*Project, error)

	// List returns projects matching opts.
	List(opts ListOptions) ([]*Project, error)

	// Update replaces the project. Errors with ErrNotFound if absent.
	Update(p *Project) error

	// Delete removes the project. Errors with ErrNotFound if absent.
	Delete(id ID) error

	// Touch updates LastOpenedAt to now. Called by `harness project switch`.
	Touch(id ID) error

	// Active returns the currently active project ID, or empty if none.
	Active() (ID, error)

	// SetActive sets the currently active project.
	SetActive(id ID) error
}