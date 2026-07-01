package vault

import (
	"fmt"
	"strings"

	"github.com/harness/harness/internal/errs"
)

// Validate checks a Credential for structural validity before storage.
func (c Credential) Validate() error {
	if strings.TrimSpace(string(c.ID)) == "" {
		return errs.Wrap(errs.ErrInvalid, "credential ID is required")
	}
	// Disallow whitespace, path separators on Windows, and other dangerous
	// characters. Forward slash and colon are allowed for hierarchical IDs
	// like "github/work" or "aws:prod".
	if strings.ContainsAny(string(c.ID), " \t\n\\\"'*?<>|") {
		return errs.Wrap(errs.ErrInvalid, "credential ID %q contains invalid characters", c.ID)
	}
	return nil
}

// Validate checks a Template for structural validity.
func (t Template) Validate() error {
	if strings.TrimSpace(t.Name) == "" {
		return errs.Wrap(errs.ErrInvalid, "template name is required")
	}
	if strings.ContainsAny(t.Name, " \t\n") {
		return errs.Wrap(errs.ErrInvalid, "template name %q contains whitespace", t.Name)
	}
	if err := t.Injection.validate(); err != nil {
		return err
	}
	return nil
}

// validate checks an Injection has exactly one mode set.
func (i Injection) validate() error {
	set := 0
	if len(i.Env) > 0 {
		set++
	}
	if i.File != nil {
		set++
	}
	if i.SSHKey != nil {
		set++
	}
	if i.Stdin != nil {
		set++
	}
	if i.CommandWrapper != nil {
		set++
	}
	if i.Plugin != nil {
		set++
	}
	if set == 0 {
		return errs.Wrap(errs.ErrInvalid, "injection mode is required")
	}
	if set > 1 {
		return errs.Wrap(errs.ErrInvalid, "exactly one injection mode allowed, got %d", set)
	}
	if i.CommandWrapper != nil {
		if !strings.Contains(i.CommandWrapper.Template, "{original}") {
			return errs.Wrap(errs.ErrInvalid, "command wrapper must contain {original}")
		}
	}
	return nil
}

// Mode returns the name of the injection mode (env, file, ssh, stdin,
// wrapper, plugin). Used in error messages and logs.
func (i Injection) Mode() string {
	switch {
	case len(i.Env) > 0:
		return "env"
	case i.File != nil:
		return "file"
	case i.SSHKey != nil:
		return "ssh"
	case i.Stdin != nil:
		return "stdin"
	case i.CommandWrapper != nil:
		return "wrapper"
	case i.Plugin != nil:
		return "plugin"
	}
	return "none"
}

// String returns a redacted representation of the credential. Safe for logs.
func (c Credential) String() string {
	return fmt.Sprintf("Credential{ID=%q, Tags=%v, Uses=%d}", c.ID, c.Tags, c.UsesTotal)
}