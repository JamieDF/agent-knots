// Package plugin defines the interface for vault injection plugins and
// provides a loader for Go-native plugins.
//
// Plugins extend the vault's injection modes beyond the built-in
// (env, file, ssh, stdin, wrapper). They're useful for tool-specific
// behavior that's hard to express declaratively — e.g., fetching a
// short-lived token from an SSO endpoint, signing a request with a
// private key, etc.
//
// # Defining a plugin
//
// A plugin is a Go type that implements the Plugin interface:
//
//   type MyPlugin struct{}
//
//   func (p *MyPlugin) Name() string { return "my-plugin" }
//   func (p *MyPlugin) Inject(ctx context.Context, req InjectRequest) (InjectResult, error) {
//       // Use req.Value to do something.
//       // Return the injected value (env vars, file path, stdin, etc.)
//   }
//
// Then register it at startup:
//
//   loader := plugin.NewLoader()
//   loader.Register("my-plugin", &MyPlugin{})
//
// Or load dynamically from a Go plugin (.so file):
//
//   p, err := loader.LoadShared("/path/to/plugin.so", "MyPlugin")
//
// # Using a plugin
//
// In a template, reference the plugin by URI:
//
//   {
//     "name": "aws_sso_temp",
//     "injection": {
//       "plugin": {
//         "uri": "plugin://aws-sso",
//         "args": {
//           "profile": "prod"
//         }
//       }
//     }
//   }
//
// When the agent calls vault.Use with this template, the vault loads the
// plugin and calls Inject to obtain the actual injection (env vars,
// file path, etc.).
package plugin

import (
	"context"
	"fmt"
	"plugin"
	"sync"

	"github.com/harness/harness/internal/errs"
)

// Plugin is the interface vault injection plugins must implement.
type Plugin interface {
	// Name returns the plugin's short identifier. Must be unique within
	// the loader. Used to match the URI in injection templates.
	Name() string

	// Inject performs the injection and returns the result. Implementations
	// typically:
	//   - use req.Value to fetch a fresh short-lived token
	//   - return env vars to set on the spawned command
	//   - OR return a file path to write req.Value to
	//   - OR return stdin data to pipe to the command
	//
	// The vault runs the actual command after receiving the InjectResult,
	// applying the injection exactly as if the template had specified it
	// directly.
	Inject(ctx context.Context, req InjectRequest) (InjectResult, error)
}

// InjectRequest is the input to Plugin.Inject.
type InjectRequest struct {
	// Value is the decrypted credential value from the vault. Plugins
	// may use it directly (e.g., as a refresh token) or ignore it.
	Value string

	// Args are template-specific arguments (key-value strings).
	Args map[string]string

	// Command is the command the agent wants to run.
	Command string

	// CommandArgs are the agent's command arguments.
	CommandArgs []string

	// Dir is the working directory for the spawned command.
	Dir string
}

// InjectResult is the output of Plugin.Inject. Exactly one of Env, File,
// or Stdin should be non-nil (matching the built-in injection modes).
type InjectResult struct {
	// Env are environment variables to set on the spawned command.
	Env map[string]string

	// File is the path to a file containing the secret (for file/ssh
	// injection modes). The vault will unlink the file after the command
	// completes.
	File string

	// Stdin is data to pipe to the command's stdin.
	Stdin string
}

// Loader manages a registry of plugins by name.
type Loader struct {
	mu      sync.RWMutex
	plugins map[string]Plugin
}

// NewLoader constructs an empty Loader.
func NewLoader() *Loader {
	return &Loader{plugins: make(map[string]Plugin)}
}

// Register adds a plugin to the registry. Errors if a plugin with the
// same name is already registered.
func (l *Loader) Register(p Plugin) error {
	if p == nil {
		return errs.Wrap(errs.ErrInvalid, "plugin is nil")
	}
	name := p.Name()
	if name == "" {
		return errs.Wrap(errs.ErrInvalid, "plugin name is empty")
	}

	l.mu.Lock()
	defer l.mu.Unlock()

	if _, exists := l.plugins[name]; exists {
		return errs.Wrap(errs.ErrAlreadyExists, "plugin %q", name)
	}
	l.plugins[name] = p
	return nil
}

// MustRegister is like Register but panics on error. Use at program
// startup where registration failure is fatal.
func (l *Loader) MustRegister(p Plugin) {
	if err := l.Register(p); err != nil {
		panic(err)
	}
}

// Get returns the plugin registered under name, or an error if not found.
func (l *Loader) Get(name string) (Plugin, error) {
	l.mu.RLock()
	defer l.mu.RUnlock()

	p, ok := l.plugins[name]
	if !ok {
		return nil, errs.Wrap(errs.ErrNotFound, "plugin %q", name)
	}
	return p, nil
}

// List returns the names of all registered plugins.
func (l *Loader) List() []string {
	l.mu.RLock()
	defer l.mu.RUnlock()

	out := make([]string, 0, len(l.plugins))
	for name := range l.plugins {
		out = append(out, name)
	}
	return out
}

// LoadShared loads a Go plugin from a shared object file (.so). The
// plugin's New function is looked up by the symbol name "New" (matching
// the convention used by the standard library's plugin package).
//
// The shared object must export:
//
//   func New() plugin.Plugin
//
// Note: Go's plugin package is only supported on Linux and macOS. On
// Windows, plugins must be compiled in.
func (l *Loader) LoadShared(path, name string) error {
	p, err := plugin.Open(path)
	if err != nil {
		return errs.Wrap(err, "open plugin %q", path)
	}

	sym, err := p.Lookup("New")
	if err != nil {
		return errs.Wrap(err, "lookup New in %q", path)
	}

	// The New symbol must be a function returning a Plugin.
	newFn, ok := sym.(func() Plugin)
	if !ok {
		// Try with pointer return.
		if newFnPtr, ok := sym.(func() *concretePlugin); ok {
			_ = newFnPtr
		}
		return errs.Wrap(errs.ErrInvalid,
			"plugin %q: New has unexpected signature %T", path, sym)
	}

	inst := newFn()
	inst.Name() // ensure name is non-empty; Register will validate
	if err := l.Register(inst); err != nil {
		return err
	}
	if inst.Name() != name {
		// Not fatal — just a hint.
		_ = name
	}
	return nil
}

// concretePlugin is a placeholder for the LoadShared type assertion above.
// It's not actually instantiated; we keep it for documentation.
type concretePlugin struct{}

// --- Example plugin: AWS SSO short-lived credentials ---

// ExampleAWSSSOPlugin shows how to implement a plugin that fetches
// short-lived AWS credentials from an SSO endpoint using a long-lived
// refresh token stored in the vault.
//
// This is illustrative — production implementations would integrate with
// the AWS SDK or aws-vault.
type ExampleAWSSSOPlugin struct{}

// Name implements Plugin.
func (p *ExampleAWSSSOPlugin) Name() string { return "aws-sso" }

// Inject implements Plugin. Fetches short-lived credentials and returns
// them as env vars.
func (p *ExampleAWSSSOPlugin) Inject(_ context.Context, req InjectRequest) (InjectResult, error) {
	profile := req.Args["profile"]
	if profile == "" {
		profile = "default"
	}

	// In a real implementation:
	//   creds, err := aws.FetchSSOCredentials(req.Value, profile)
	//   if err != nil { return InjectResult{}, err }
	//   return InjectResult{Env: map[string]string{
	//       "AWS_ACCESS_KEY_ID":     creds.AccessKeyID,
	//       "AWS_SECRET_ACCESS_KEY": creds.SecretAccessKey,
	//       "AWS_SESSION_TOKEN":     creds.SessionToken,
	//   }}, nil

	// Stub for the example.
	return InjectResult{
		Env: map[string]string{
			"AWS_PROFILE":            profile,
			"AWS_SSO_TOKEN_FROM_VAULT": "[would be fetched from SSO using vault value]",
			"EXAMPLE_NOTE":            fmt.Sprintf("This is a stub. Use req.Value (%d chars) to fetch SSO creds.", len(req.Value)),
		},
	}, nil
}

// --- Example plugin: JWT signer ---

// ExampleJWTSignerPlugin shows how to implement a plugin that signs
// JWTs with a private key stored in the vault.
type ExampleJWTSignerPlugin struct{}

// Name implements Plugin.
func (p *ExampleJWTSignerPlugin) Name() string { return "jwt-signer" }

// Inject implements Plugin. Signs a JWT for the requested claims using
// the private key from the vault.
func (p *ExampleJWTSignerPlugin) Inject(_ context.Context, req InjectRequest) (InjectResult, error) {
	subject := req.Args["subject"]
	audience := req.Args["audience"]

	// In a real implementation:
	//   token, err := jwt.SignWithKey(req.Value, claims)
	//   if err != nil { return InjectResult{}, err }
	//   return InjectResult{Env: map[string]string{"JWT_TOKEN": token}}, nil

	// Stub for the example.
	return InjectResult{
		Env: map[string]string{
			"JWT_SUBJECT":   subject,
			"JWT_AUDIENCE":  audience,
			"JWT_TOKEN":     "[would be signed with vault key]",
			"EXAMPLE_NOTE":  fmt.Sprintf("Stub: would sign JWT for sub=%s aud=%s", subject, audience),
		},
	}, nil
}