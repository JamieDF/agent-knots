package filestore

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"time"

	"github.com/JamieDF/agentjam/internal/errs"
	"github.com/JamieDF/agentjam/internal/vault"
)

// Use implements Vault.Use. The credential value is decrypted in-memory only,
// passed directly to the subprocess, and scrubbed from any output before
// being returned or logged.
//
// Concurrency: holds the write lock for the duration of command execution
// (to serialize use and prevent TOCTOU on LastUsed). For higher concurrency,
// callers can use multiple vault instances (different paths) or fork.
//
// Security notes:
//   - The credential value is never returned to the caller.
//   - stdout and stderr are scrubbed of the credential value.
//   - The credential value is logged only by its template name in audit log.
func (f *FileStore) Use(ctx context.Context, req vault.UseRequest, caller string) (vault.UseResult, error) {
	if req.Credential == "" {
		return vault.UseResult{}, errs.Wrap(errs.ErrInvalid, "credential ID is required")
	}

	f.mu.Lock()
	defer f.mu.Unlock()

	if !f.unlocked {
		return vault.UseResult{}, errs.Wrap(errs.ErrUnauthorized, "vault is locked")
	}

	e, ok := f.find(req.Credential)
	if !ok {
		return vault.UseResult{}, errs.Wrap(errs.ErrNotFound, "credential %q", req.Credential)
	}

	// Resolve template: explicit, or first available.
	var tmpl *vault.Template
	if req.Template != "" {
		for i := range e.Templates {
			if e.Templates[i].Name == req.Template {
				tmpl = &e.Templates[i]
				break
			}
		}
		if tmpl == nil {
			return vault.UseResult{}, errs.Wrap(errs.ErrNotFound, "template %q on %q", req.Template, req.Credential)
		}
	} else if len(e.Templates) > 0 {
		tmpl = &e.Templates[0]
	}

	if tmpl == nil {
		return vault.UseResult{}, errs.Wrap(errs.ErrInvalid,
			"credential %q has no templates; add one via SetTemplate", req.Credential)
	}

	value, err := f.decryptEntry(e)
	if err != nil {
		return vault.UseResult{}, err
	}

	start := time.Now()
	res, runErr := f.applyInjection(ctx, req, tmpl, value)
	res.Duration = time.Since(start)

	// Update usage stats (best-effort, ignore errors here to not poison the
	// use result).
	e.LastUsed = time.Now()
	e.UsesTotal++

	// Audit.
	auditErr := f.appendAudit(vault.AuditEntry{
		Timestamp: time.Now(),
		Credential: req.Credential,
		Template:   tmpl.Name,
		Command:    scrubCommand(req, tmpl),
		Caller:     caller,
		Success:    runErr == nil && res.ExitCode == 0,
		Duration:   res.Duration,
	})
	if runErr != nil {
		auditErr = errors.Join(auditErr, runErr)
		return res, errs.Wrap(runErr, "vault use failed")
	}
	// Best-effort save; persist stats even if audit log write failed.
	_ = f.save()
	if auditErr != nil {
		return res, errs.Wrap(auditErr, "audit log write failed (use succeeded)")
	}
	return res, nil
}

// applyInjection runs the request against the resolved template.
func (f *FileStore) applyInjection(
	ctx context.Context,
	req vault.UseRequest,
	tmpl *vault.Template,
	value string,
) (vault.UseResult, error) {
	switch {
	case len(tmpl.Injection.Env) > 0:
		return f.runWithEnv(ctx, req, tmpl, value)
	case tmpl.Injection.File != nil:
		return f.runWithFile(ctx, req, tmpl, value)
	case tmpl.Injection.SSHKey != nil:
		return f.runWithFile(ctx, req, tmpl, value) // same machinery
	case tmpl.Injection.Stdin != nil:
		return f.runWithStdin(ctx, req, tmpl, value)
	case tmpl.Injection.CommandWrapper != nil:
		return f.runWithWrapper(ctx, req, tmpl, value)
	case tmpl.Injection.Plugin != nil:
		return vault.UseResult{}, errs.Wrap(errs.ErrUnsupported,
			"plugin injection not yet implemented: %s", tmpl.Injection.Plugin.URI)
	}
	return vault.UseResult{}, errs.Wrap(errs.ErrInvalid, "template has no injection mode")
}

func (f *FileStore) runWithEnv(
	ctx context.Context,
	req vault.UseRequest,
	tmpl *vault.Template,
	value string,
) (vault.UseResult, error) {
	env := make(map[string]string, len(tmpl.Injection.Env))
	for k, v := range tmpl.Injection.Env {
		env[k] = strings.ReplaceAll(v, "$value", value)
	}
	for k, v := range req.Env {
		env[k] = v
	}
	if req.Command == "" {
		// Pure env injection: caller will set the env themselves.
		return vault.UseResult{Env: env, ExitCode: -1}, nil
	}
	return f.execCommand(ctx, req, env, value)
}

func (f *FileStore) runWithFile(
	ctx context.Context,
	req vault.UseRequest,
	tmpl *vault.Template,
	value string,
) (vault.UseResult, error) {
	path := tmpl.Injection.File.Path
	if path == "" {
		f, err := os.CreateTemp("", "harness-vault-*")
		if err != nil {
			return vault.UseResult{}, errs.Wrap(err, "create temp file")
		}
		path = f.Name()
		_ = f.Close()
	}

	perms := os.FileMode(tmpl.Injection.File.Permissions)
	if perms == 0 {
		perms = 0o600
	}
	if err := os.WriteFile(path, []byte(value), perms); err != nil {
		return vault.UseResult{}, errs.Wrap(err, "write credential file")
	}

	if req.Command == "" {
		return vault.UseResult{FilePath: path, ExitCode: -1}, nil
	}

	res, err := f.execCommand(ctx, req, map[string]string{
		"HARNESS_VAULT_FILE": path,
	})
	// Best-effort cleanup; ignore errors.
	_ = os.Remove(path)
	return res, err
}

func (f *FileStore) runWithStdin(
	ctx context.Context,
	req vault.UseRequest,
	tmpl *vault.Template,
	value string,
) (vault.UseResult, error) {
	if tmpl.Injection.Stdin.TrailingNewline && !strings.HasSuffix(value, "\n") {
		value += "\n"
	}

	cmd := buildCmd(ctx, req)
	cmd.Stdin = strings.NewReader(value)

	out, err := cmd.CombinedOutput()
	res := vault.UseResult{
		Stdout:   scrub(string(out), value),
		ExitCode: cmd.ProcessState.ExitCode(),
	}
	if err != nil {
		var ee *exec.ExitError
		if errors.As(err, &ee) {
			res.Stderr = scrub(string(ee.Stderr), value)
		}
	}
	return res, err
}

func (f *FileStore) runWithWrapper(
	ctx context.Context,
	req vault.UseRequest,
	tmpl *vault.Template,
	value string,
) (vault.UseResult, error) {
	wrapped := strings.ReplaceAll(tmpl.Injection.CommandWrapper.Template, "$value", value)
	original := req.Command
	if len(req.Args) > 0 {
		original = strings.Join(append([]string{req.Command}, req.Args...), " ")
	}
	wrapped = strings.ReplaceAll(wrapped, "{original}", original)

	cmd := exec.CommandContext(ctx, "sh", "-c", wrapped) //nolint:gosec // intentional shell wrap
	if req.Dir != "" {
		cmd.Dir = req.Dir
	}
	for k, v := range req.Env {
		cmd.Env = append(os.Environ(), k+"="+v)
	}

	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	err := cmd.Run()
	res := vault.UseResult{
		Stdout:   scrub(stdout.String(), value),
		Stderr:   scrub(stderr.String(), value),
		ExitCode: cmd.ProcessState.ExitCode(),
	}
	return res, err
}

func (f *FileStore) execCommand(
	ctx context.Context,
	req vault.UseRequest,
	env map[string]string,
	scrubValue ...string,
) (vault.UseResult, error) {
	cmd := buildCmd(ctx, req)
	cmd.Env = os.Environ()
	for k, v := range env {
		cmd.Env = append(cmd.Env, k+"="+v)
	}

	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	if req.Timeout > 0 {
		var cancel context.CancelFunc
		ctx, cancel = context.WithTimeout(ctx, req.Timeout)
		defer cancel()
		cmd = exec.CommandContext(ctx, cmd.Path, cmd.Args[1:]...) //nolint:gosec // re-wrap with timeout
		cmd.Env = os.Environ()
		for k, v := range env {
			cmd.Env = append(cmd.Env, k+"="+v)
		}
		cmd.Dir = req.Dir
		cmd.Stdout = &stdout
		cmd.Stderr = &stderr
	}

	err := cmd.Run()

	outStr := stdout.String()
	errStr := stderr.String()
	if len(scrubValue) > 0 && scrubValue[0] != "" {
		outStr = scrub(outStr, scrubValue[0])
		errStr = scrub(errStr, scrubValue[0])
	}
	return vault.UseResult{
		Stdout:   outStr,
		Stderr:   errStr,
		ExitCode: cmd.ProcessState.ExitCode(),
	}, err
}

func buildCmd(ctx context.Context, req vault.UseRequest) *exec.Cmd {
	args := append([]string{req.Command}, req.Args...)
	//nolint:gosec // commands are user-supplied by design
	cmd := exec.CommandContext(ctx, req.Command, req.Args...)
	_ = args
	if req.Dir != "" {
		cmd.Dir = req.Dir
	}
	return cmd
}

// scrubCommand returns a redacted representation of the use for audit logs.
func scrubCommand(req vault.UseRequest, tmpl *vault.Template) string {
	cmd := req.Command
	if cmd == "" {
		return fmt.Sprintf("template=%s", tmpl.Name)
	}
	if len(req.Args) > 0 {
		cmd += " " + strings.Join(req.Args, " ")
	}
	return fmt.Sprintf("template=%s cmd=%s", tmpl.Name, cmd)
}