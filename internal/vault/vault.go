// Package vault defines the credential vault interface.
//
// The vault stores named credentials (secrets) encrypted at rest. Agents
// reference credentials by opaque URIs (vault://id) and never see the raw
// value. To use a credential, the agent asks the vault to either:
//
//   - Proxy-execute a command with the credential injected (preferred).
//   - Inject the credential as an env var, file, or stdin for the agent's
//     command, scrubbing the value from logs.
//
// Injection is configured via Templates — declarative JSON that says "for
// credential X, here is how to expose it when template Y is used." Templates
// are user-editable and live alongside the credential entry.
//
// All methods are safe for concurrent use.
package vault

import (
	"context"
	"time"
)

// ID is a credential identifier (e.g. "github/work", "tavily/search").
// IDs are case-sensitive and must be unique within a vault.
type ID string

// Credential is a stored secret. The Value field is only ever populated when
// the vault is explicitly asked to inject it; otherwise it is empty.
type Credential struct {
	// ID is the credential's unique identifier.
	ID ID

	// Description is an optional human-readable note (e.g. "Personal GitHub
	// account, used for OSS work").
	Description string

	// CreatedAt is when the credential was added.
	CreatedAt time.Time

	// LastUsed is when the credential was most recently used via Use.
	LastUsed time.Time

	// UsesTotal is the cumulative number of times this credential has been
	// used.
	UsesTotal int64

	// Tags is an optional set of free-form labels for filtering
	// (e.g. "github", "production").
	Tags []string

	// Value is populated only by Use — it is never persisted in plain text
	// and never returned by Get / List. Use Use to obtain the value, or
	// reference the credential by ID from injection templates.
	Value string
}

// Template is a named way to expose a credential when used. Multiple
// templates per credential are supported (e.g. "gh_cli_env", "ssh_key_path").
//
// A template is a JSON-serializable struct. See the Template type below.
type Template struct {
	// Name is the template's identifier within its credential (e.g.
	// "gh_cli_env"). Must be unique per credential.
	Name string

	// Description is a human-readable note about when to use this template.
	Description string

	// Injection specifies how the credential value is exposed. Exactly one of
	// the fields should be set.
	Injection Injection
}

// Injection is a discriminated union of ways to expose a credential value.
//
// The discriminator is determined by which field is non-nil. Validators
// (see validate.go) reject templates with multiple or zero injection modes.
type Injection struct {
	// Env sets environment variables on the spawned command.
	// Value can contain "$value" which is replaced with the credential value.
	Env map[string]string

	// File writes the value to a temp file (mode 0600) and exposes the path.
	File *FileInjection

	// SSHKey writes the value to a temp file and returns the path. Used by
	// SSH-based commands.
	SSHKey *FileInjection

	// Stdin pipes the value to the command's stdin.
	Stdin *StdinInjection

	// CommandWrapper wraps the original command with auth bits. {original}
	// is replaced with the original args.
	CommandWrapper *WrapperInjection

	// Plugin references a user-defined plugin by URL. The plugin's
	// implementation lives in internal/plugins/.
	Plugin *PluginInjection
}

// FileInjection writes a credential to a temp file and returns the path.
type FileInjection struct {
	// Path is the suggested path; if empty, the vault picks a temp path.
	Path string

	// Permissions is the file mode (default 0600).
	Permissions int
}

// StdinInjection pipes the credential value to a command's stdin.
type StdinInjection struct {
	// TrailingNewline ensures a newline is appended to the value before
	// piping to stdin. Useful for commands expecting line-delimited input.
	TrailingNewline bool
}

// WrapperInjection wraps a command with auth bits.
//
// Example: "curl -H 'Authorization: Bearer $value' {original}" — the agent's
// command is interpolated into {original}, $value is the credential.
type WrapperInjection struct {
	// Template is the wrapper template. {original} is replaced with the
	// original command line; $value is replaced with the credential value.
	Template string
}

// PluginInjection is reserved for user-defined injection modes.
type PluginInjection struct {
	// URI identifies the plugin, e.g. "plugin://mycompany/aws-sso".
	URI string

	// Args is plugin-specific configuration.
	Args map[string]string
}

// UseRequest is the input to Vault.Use. It specifies which credential, which
// template, and the command to run.
type UseRequest struct {
	// Credential is the vault:// URI of the credential to use.
	Credential ID

	// Template is the name of the injection template to apply. If empty,
	// the credential's default template is used (see Credential.Default).
	Template string

	// Command is the command line to run (or wrap, depending on template).
	// Empty when the use is purely for environment variable injection
	// (caller sets them themselves).
	Command string

	// Args are positional arguments to Command.
	Args []string

	// Dir is the working directory for the command. Empty = inherit.
	Dir string

	// Env are additional environment variables to set on the command.
	// These are merged with the template's injected env.
	Env map[string]string

	// Timeout bounds the command execution. Zero = no timeout.
	Timeout time.Duration
}

// UseResult is the outcome of a Vault.Use invocation.
type UseResult struct {
	// Stdout is the command's standard output, scrubbed of any credential
	// values.
	Stdout string

	// Stderr is the command's standard error, scrubbed.
	Stderr string

	// ExitCode is the command's exit code. -1 if the use was purely for
	// environment injection (no command executed).
	ExitCode int

	// Duration is how long the use took.
	Duration time.Duration

	// Env is set when the use is for env injection. The caller is
	// responsible for unsetting these after the command.
	Env map[string]string

	// FilePath is set when the use is for file / SSH key injection. The
	// caller is responsible for unlinking after use.
	FilePath string
}

// AuditEntry is one row in the append-only audit log.
type AuditEntry struct {
	// Timestamp is when the use occurred.
	Timestamp time.Time

	// Credential is the credential ID used.
	Credential ID

	// Template is the injection template used.
	Template string

	// Command is the command line run (if any). Scrubbed of any secret
	// values that may have appeared.
	Command string

	// Caller identifies who initiated the use (e.g. "agent:auth-fix" or
	// "user").
	Caller string

	// Success indicates whether the use completed without error.
	Success bool

	// Error is the error message if Success is false.
	Error string

	// Duration is how long the use took.
	Duration time.Duration
}

// AuditOptions filters audit log queries.
type AuditOptions struct {
	// Since filters to entries after this time. Zero = no lower bound.
	Since time.Time

	// Credential filters to a specific credential. Empty = all.
	Credential ID

	// Limit caps the number of entries returned. Zero = no limit.
	Limit int
}

// Vault is the interface for credential storage and injection.
//
// Implementations live under internal/vault/ (e.g. filestore for the
// AES-256-GCM file-backed implementation).
//
// All methods are safe for concurrent use.
type Vault interface {
	// LockState returns whether the vault is currently locked. A locked vault
	// can list and inspect credentials but cannot reveal values or use them.
	LockState(ctx context.Context) (LockState, error)

	// Lock secures the vault. After Lock, Use and Value are unavailable
	// until Unlock.
	Lock(ctx context.Context) error

	// Unlock secures the vault with a passphrase. After Unlock, Use is
	// available until the next Lock or process exit.
	Unlock(ctx context.Context, passphrase string) error

	// IsUnlocked reports whether the vault is currently usable.
	IsUnlocked(ctx context.Context) (bool, error)

	// List returns the IDs and metadata of all credentials. Values are
	// never populated.
	List(ctx context.Context) ([]Credential, error)

	// Get returns a credential's metadata by ID. Value is never populated;
	// use Use to obtain the value.
	Get(ctx context.Context, id ID) (Credential, error)

	// Add stores a new credential. Errors with ErrAlreadyExists if the ID is
	// taken.
	Add(ctx context.Context, cred Credential) error

	// Remove deletes a credential by ID. Errors with ErrNotFound if absent.
	Remove(ctx context.Context, id ID) error

	// Update modifies a credential's metadata (description, tags).
	// The value cannot be changed via Update; use Add + Remove to rotate.
	Update(ctx context.Context, cred Credential) error

	// SetTemplate adds or replaces a template on a credential.
	SetTemplate(ctx context.Context, credID ID, tmpl Template) error

	// GetTemplate returns a template by credential ID and template name.
	GetTemplate(ctx context.Context, credID ID, name string) (Template, error)

	// ListTemplates returns all templates defined for a credential.
	ListTemplates(ctx context.Context, credID ID) ([]Template, error)

	// RemoveTemplate deletes a template.
	RemoveTemplate(ctx context.Context, credID ID, name string) error

	// Use runs a command with a credential injected, per the specified
	// template. The credential value is never returned to the caller; it is
	// either injected into the command's environment, written to a file, or
	// piped to stdin.
	//
	// Use is the only way to obtain a credential's value. The value itself
	// never crosses the Vault boundary except into the spawned process.
	Use(ctx context.Context, req UseRequest, caller string) (UseResult, error)

	// AuditLog returns audit entries matching the filter.
	AuditLog(ctx context.Context, opts AuditOptions) ([]AuditEntry, error)
}

// LockState describes vault security state.
type LockState string

const (
	// Locked means the vault is locked and secrets are unavailable.
	Locked LockState = "locked"

	// Unlocked means the vault is unlocked and Use is available.
	Unlocked LockState = "unlocked"

	// Uninitialized means no vault has been created yet.
	Uninitialized LockState = "uninitialized"
)