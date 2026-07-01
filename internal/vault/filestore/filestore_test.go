package filestore

import (
	"context"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/harness/harness/internal/errs"
	"github.com/harness/harness/internal/vault"
)

// newTestStore returns a fresh FileStore in a temp dir.
func newTestStore(t *testing.T) (*FileStore, string) {
	t.Helper()
	dir := t.TempDir()
	fs, err := New(dir)
	if err != nil {
		t.Fatalf("New: %v", err)
	}
	return fs, dir
}

func TestNew_CreatesDir(t *testing.T) {
	dir := t.TempDir()
	target := filepath.Join(dir, "subdir", "vault")
	fs, err := New(target)
	if err != nil {
		t.Fatal(err)
	}
	if fs == nil {
		t.Fatal("nil fs")
	}
	info, err := os.Stat(target)
	if err != nil || !info.IsDir() {
		t.Fatalf("vault dir not created: %v", err)
	}
	perms := info.Mode().Perm()
	if perms != 0o700 {
		t.Errorf("dir perms = %o, want 0700", perms)
	}
}

func TestNew_RejectsEmptyPath(t *testing.T) {
	_, err := New("")
	if err == nil {
		t.Fatal("expected error for empty path")
	}
	if !errs.Is(err, errs.ErrInvalid) {
		t.Errorf("expected ErrInvalid, got %v", err)
	}
}

func TestLockState_Empty(t *testing.T) {
	fs, _ := newTestStore(t)
	state, err := fs.LockState(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if state != vault.Uninitialized {
		t.Errorf("state = %q, want uninitialized", state)
	}
}

func TestUnlock_InitThenReopen(t *testing.T) {
	fs, dir := newTestStore(t)
	ctx := context.Background()

	// First unlock initializes.
	if err := fs.Unlock(ctx, "correct horse battery staple"); err != nil {
		t.Fatalf("first Unlock: %v", err)
	}

	// Re-open the store from disk and unlock with the same passphrase.
	fs2, err := New(dir)
	if err != nil {
		t.Fatal(err)
	}
	if err := fs2.Unlock(ctx, "correct horse battery staple"); err != nil {
		t.Fatalf("second Unlock: %v", err)
	}

	// Wrong passphrase should fail.
	fs3, err := New(dir)
	if err != nil {
		t.Fatal(err)
	}
	err = fs3.Unlock(ctx, "wrong passphrase")
	if err == nil {
		t.Fatal("expected error with wrong passphrase")
	}
	if !errs.Is(err, errs.ErrUnauthorized) {
		t.Errorf("expected ErrUnauthorized, got %v", err)
	}
}

func TestAddAndGet(t *testing.T) {
	fs, _ := newTestStore(t)
	ctx := context.Background()
	if err := fs.Unlock(ctx, "passphrase"); err != nil {
		t.Fatal(err)
	}

	cred := vault.Credential{
		ID:          "github/work",
		Description: "GitHub work account",
		Tags:        []string{"github", "work"},
		Value:       "ghp_secrettoken",
	}
	if err := fs.Add(ctx, cred); err != nil {
		t.Fatal(err)
	}

	got, err := fs.Get(ctx, "github/work")
	if err != nil {
		t.Fatal(err)
	}
	if got.ID != cred.ID {
		t.Errorf("ID = %q", got.ID)
	}
	if got.Description != cred.Description {
		t.Errorf("Description = %q", got.Description)
	}
	if got.Value != "" {
		t.Errorf("Get leaked value: %q", got.Value)
	}

	// List should also not leak the value.
	list, err := fs.List(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if len(list) != 1 {
		t.Fatalf("List len = %d", len(list))
	}
	if list[0].Value != "" {
		t.Errorf("List leaked value: %q", list[0].Value)
	}
}

func TestAdd_Duplicate(t *testing.T) {
	fs, _ := newTestStore(t)
	ctx := context.Background()
	_ = fs.Unlock(ctx, "p")
	if err := fs.Add(ctx, vault.Credential{ID: "x", Value: "v"}); err != nil {
		t.Fatal(err)
	}
	err := fs.Add(ctx, vault.Credential{ID: "x", Value: "v2"})
	if err == nil {
		t.Fatal("expected error")
	}
	if !errs.Is(err, errs.ErrAlreadyExists) {
		t.Errorf("expected ErrAlreadyExists, got %v", err)
	}
}

func TestAdd_RequiresUnlock(t *testing.T) {
	fs, _ := newTestStore(t)
	ctx := context.Background()
	err := fs.Add(ctx, vault.Credential{ID: "x", Value: "v"})
	if err == nil {
		t.Fatal("expected error")
	}
	if !errs.Is(err, errs.ErrUnauthorized) {
		t.Errorf("expected ErrUnauthorized, got %v", err)
	}
}

func TestAdd_EmptyValue(t *testing.T) {
	fs, _ := newTestStore(t)
	ctx := context.Background()
	_ = fs.Unlock(ctx, "p")
	err := fs.Add(ctx, vault.Credential{ID: "x"})
	if err == nil {
		t.Fatal("expected error")
	}
	if !errs.Is(err, errs.ErrInvalid) {
		t.Errorf("expected ErrInvalid, got %v", err)
	}
}

func TestRemove(t *testing.T) {
	fs, _ := newTestStore(t)
	ctx := context.Background()
	_ = fs.Unlock(ctx, "p")
	_ = fs.Add(ctx, vault.Credential{ID: "x", Value: "v"})

	if err := fs.Remove(ctx, "x"); err != nil {
		t.Fatal(err)
	}

	_, err := fs.Get(ctx, "x")
	if !errs.Is(err, errs.ErrNotFound) {
		t.Errorf("expected ErrNotFound, got %v", err)
	}

	err = fs.Remove(ctx, "x")
	if !errs.Is(err, errs.ErrNotFound) {
		t.Errorf("second remove: expected ErrNotFound, got %v", err)
	}
}

func TestUpdate_MetadataOnly(t *testing.T) {
	fs, _ := newTestStore(t)
	ctx := context.Background()
	_ = fs.Unlock(ctx, "p")
	_ = fs.Add(ctx, vault.Credential{ID: "x", Value: "v1", Description: "old"})

	// Update description only.
	if err := fs.Update(ctx, vault.Credential{ID: "x", Description: "new", Tags: []string{"a"}}); err != nil {
		t.Fatal(err)
	}
	got, _ := fs.Get(ctx, "x")
	if got.Description != "new" {
		t.Errorf("Description = %q", got.Description)
	}

	// Value should be preserved (unchanged from v1) — verify by using Use.
	if err := fs.SetTemplate(ctx, "x", vault.Template{
		Name:      "echo_env",
		Injection: vault.Injection{Env: map[string]string{"X": "$value"}},
	}); err != nil {
		t.Fatal(err)
	}
	outFile := filepath.Join(t.TempDir(), "out.txt")
	if _, err := fs.Use(ctx, vault.UseRequest{
		Credential: "x",
		Template:   "echo_env",
		Command:    "sh",
		Args:       []string{"-c", "echo $X > " + outFile},
	}, "test"); err != nil {
		t.Fatal(err)
	}
	written, _ := os.ReadFile(outFile)
	if !strings.Contains(string(written), "v1") {
		t.Errorf("expected v1 in file, got %q", written)
	}
}

func TestTemplates(t *testing.T) {
	fs, _ := newTestStore(t)
	ctx := context.Background()
	_ = fs.Unlock(ctx, "p")
	_ = fs.Add(ctx, vault.Credential{ID: "x", Value: "v"})

	tmpl := vault.Template{
		Name:      "gh_cli_env",
		Injection: vault.Injection{Env: map[string]string{"GH_TOKEN": "$value"}},
	}
	if err := fs.SetTemplate(ctx, "x", tmpl); err != nil {
		t.Fatal(err)
	}

	// Replace.
	tmpl2 := vault.Template{
		Name:      "gh_cli_env",
		Injection: vault.Injection{Env: map[string]string{"GH_TOKEN": "$value", "GH_USER": "x"}},
	}
	if err := fs.SetTemplate(ctx, "x", tmpl2); err != nil {
		t.Fatal(err)
	}
	got, err := fs.GetTemplate(ctx, "x", "gh_cli_env")
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Injection.Env) != 2 {
		t.Errorf("expected 2 env vars, got %d", len(got.Injection.Env))
	}

	// List.
	list, err := fs.ListTemplates(ctx, "x")
	if err != nil {
		t.Fatal(err)
	}
	if len(list) != 1 {
		t.Errorf("expected 1 template, got %d", len(list))
	}

	// Remove.
	if err := fs.RemoveTemplate(ctx, "x", "gh_cli_env"); err != nil {
		t.Fatal(err)
	}
	_, err = fs.GetTemplate(ctx, "x", "gh_cli_env")
	if !errs.Is(err, errs.ErrNotFound) {
		t.Errorf("expected ErrNotFound, got %v", err)
	}
}

func TestUse_EnvInjection(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("shell not available")
	}
	fs, _ := newTestStore(t)
	ctx := context.Background()
	_ = fs.Unlock(ctx, "p")
	_ = fs.Add(ctx, vault.Credential{ID: "x", Value: "sup3rsecret"})
	_ = fs.SetTemplate(ctx, "x", vault.Template{
		Name:      "echo",
		Injection: vault.Injection{Env: map[string]string{"X": "$value"}},
	})

	// Have the command write the secret to a file we control, so we can
	// verify injection without relying on stdout (which is scrubbed).
	outFile := filepath.Join(t.TempDir(), "out.txt")

	res, err := fs.Use(ctx, vault.UseRequest{
		Credential: "x",
		Template:   "echo",
		Command:    "sh",
		Args:       []string{"-c", "echo $X > " + outFile},
	}, "test")
	if err != nil {
		t.Fatal(err)
	}
	if res.ExitCode != 0 {
		t.Errorf("exit code = %d, want 0", res.ExitCode)
	}
	written, err := os.ReadFile(outFile)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(written), "sup3rsecret") {
		t.Errorf("expected secret in file, got %q", written)
	}
	// Stdout should still be scrubbed (the redirection ate the line).
	if strings.Contains(res.Stdout, "sup3rsecret") {
		t.Errorf("stdout leaked secret: %q", res.Stdout)
	}
}

func TestUse_ScrubsOutput(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("shell not available")
	}
	fs, _ := newTestStore(t)
	ctx := context.Background()
	_ = fs.Unlock(ctx, "p")
	_ = fs.Add(ctx, vault.Credential{ID: "x", Value: "topsecret"})
	_ = fs.SetTemplate(ctx, "x", vault.Template{
		Name:      "echo",
		Injection: vault.Injection{Env: map[string]string{"X": "$value"}},
	})

	res, err := fs.Use(ctx, vault.UseRequest{
		Credential: "x",
		Template:   "echo",
		Command:    "sh",
		Args:       []string{"-c", "echo $X 1>&2; echo done"},
	}, "test")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(res.Stdout, "topsecret") {
		t.Errorf("stdout leaked secret: %q", res.Stdout)
	}
	if strings.Contains(res.Stderr, "topsecret") {
		t.Errorf("stderr leaked secret: %q", res.Stderr)
	}
	if !strings.Contains(res.Stderr, "[REDACTED]") {
		t.Errorf("stderr not redacted: %q", res.Stderr)
	}
}

func TestUse_DefaultTemplate(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("shell not available")
	}
	fs, _ := newTestStore(t)
	ctx := context.Background()
	_ = fs.Unlock(ctx, "p")
	_ = fs.Add(ctx, vault.Credential{ID: "x", Value: "v"})
	_ = fs.SetTemplate(ctx, "x", vault.Template{
		Name:      "default_tmpl",
		Injection: vault.Injection{Env: map[string]string{"X": "$value"}},
	})

	outFile := filepath.Join(t.TempDir(), "out.txt")

	// No template specified — should pick the first one.
	if _, err := fs.Use(ctx, vault.UseRequest{
		Credential: "x",
		Command:    "sh",
		Args:       []string{"-c", "echo $X > " + outFile},
	}, "test"); err != nil {
		t.Fatal(err)
	}
	written, _ := os.ReadFile(outFile)
	if !strings.Contains(string(written), "v") {
		t.Errorf("expected v in file, got %q", written)
	}
}

func TestUse_NoTemplate(t *testing.T) {
	fs, _ := newTestStore(t)
	ctx := context.Background()
	_ = fs.Unlock(ctx, "p")
	_ = fs.Add(ctx, vault.Credential{ID: "x", Value: "v"})

	_, err := fs.Use(ctx, vault.UseRequest{Credential: "x"}, "test")
	if err == nil {
		t.Fatal("expected error when credential has no templates")
	}
}

func TestUse_RecordsAudit(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("shell not available")
	}
	fs, _ := newTestStore(t)
	ctx := context.Background()
	_ = fs.Unlock(ctx, "p")
	_ = fs.Add(ctx, vault.Credential{ID: "x", Value: "v"})
	_ = fs.SetTemplate(ctx, "x", vault.Template{
		Name:      "echo",
		Injection: vault.Injection{Env: map[string]string{"X": "$value"}},
	})

	_, err := fs.Use(ctx, vault.UseRequest{
		Credential: "x",
		Template:   "echo",
		Command:    "sh",
		Args:       []string{"-c", "echo hi"},
	}, "test-agent")
	if err != nil {
		t.Fatal(err)
	}

	entries, err := fs.AuditLog(ctx, vault.AuditOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 {
		t.Fatalf("expected 1 audit entry, got %d", len(entries))
	}
	if entries[0].Credential != "x" {
		t.Errorf("Credential = %q", entries[0].Credential)
	}
	if entries[0].Caller != "test-agent" {
		t.Errorf("Caller = %q", entries[0].Caller)
	}
	if entries[0].Duration < 0 {
		t.Errorf("Duration = %v", entries[0].Duration)
	}
}

func TestUse_UpdatesLastUsed(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("shell not available")
	}
	fs, _ := newTestStore(t)
	ctx := context.Background()
	_ = fs.Unlock(ctx, "p")
	_ = fs.Add(ctx, vault.Credential{ID: "x", Value: "v"})
	_ = fs.SetTemplate(ctx, "x", vault.Template{
		Name:      "echo",
		Injection: vault.Injection{Env: map[string]string{"X": "$value"}},
	})

	before, _ := fs.Get(ctx, "x")
	_, _ = fs.Use(ctx, vault.UseRequest{
		Credential: "x",
		Template:   "echo",
		Command:    "sh",
		Args:       []string{"-c", "true"},
	}, "test")

	after, _ := fs.Get(ctx, "x")
	if !after.LastUsed.After(before.CreatedAt) {
		t.Errorf("LastUsed not updated: before=%v after=%v", before.LastUsed, after.LastUsed)
	}
	if after.UsesTotal != 1 {
		t.Errorf("UsesTotal = %d, want 1", after.UsesTotal)
	}
}

func TestLock(t *testing.T) {
	fs, _ := newTestStore(t)
	ctx := context.Background()
	_ = fs.Unlock(ctx, "p")
	_ = fs.Add(ctx, vault.Credential{ID: "x", Value: "v"})

	if err := fs.Lock(ctx); err != nil {
		t.Fatal(err)
	}

	unlocked, _ := fs.IsUnlocked(ctx)
	if unlocked {
		t.Error("still unlocked after Lock")
	}

	err := fs.Add(ctx, vault.Credential{ID: "y", Value: "v"})
	if !errs.Is(err, errs.ErrUnauthorized) {
		t.Errorf("expected ErrUnauthorized, got %v", err)
	}
}

func TestCrypto_RoundTrip(t *testing.T) {
	key := make([]byte, KeyLen)
	for i := range key {
		key[i] = byte(i)
	}
	plain := []byte("hello, world! this is a test")

	enc, err := encrypt(key, plain)
	if err != nil {
		t.Fatal(err)
	}
	if string(enc) == string(plain) {
		t.Error("ciphertext equals plaintext")
	}

	dec, err := decrypt(key, enc)
	if err != nil {
		t.Fatal(err)
	}
	if string(dec) != string(plain) {
		t.Errorf("decrypted = %q, want %q", dec, plain)
	}
}

func TestCrypto_TamperDetection(t *testing.T) {
	key := make([]byte, KeyLen)
	enc, err := encrypt(key, []byte("secret"))
	if err != nil {
		t.Fatal(err)
	}
	enc[len(enc)-1] ^= 0xff // flip last bit
	_, err = decrypt(key, enc)
	if err == nil {
		t.Fatal("expected tamper detection error")
	}
}

func TestCrypto_WrongKey(t *testing.T) {
	key1 := make([]byte, KeyLen)
	key2 := make([]byte, KeyLen)
	key2[0] = 1
	enc, _ := encrypt(key1, []byte("x"))
	_, err := decrypt(key2, enc)
	if err == nil {
		t.Fatal("expected error with wrong key")
	}
}

func TestDeriveKey_Deterministic(t *testing.T) {
	salt := []byte("1234567890123456")
	k1 := deriveKey("passphrase", salt)
	k2 := deriveKey("passphrase", salt)
	if string(k1) != string(k2) {
		t.Error("deriveKey not deterministic")
	}
	k3 := deriveKey("different", salt)
	if string(k1) == string(k3) {
		t.Error("deriveKey should differ for different passphrases")
	}
}

func TestScrub(t *testing.T) {
	cases := []struct {
		in, secret, want string
	}{
		{"hello world", "world", "hello [REDACTED]"},
		{"no match here", "missing", "no match here"},
		{"", "x", ""},
		{"repeat x x x", "x", "repeat [REDACTED] [REDACTED] [REDACTED]"},
	}
	for _, c := range cases {
		got := scrub(c.in, c.secret)
		if got != c.want {
			t.Errorf("scrub(%q, %q) = %q, want %q", c.in, c.secret, got, c.want)
		}
	}
}

func TestScrubMap(t *testing.T) {
	m := map[string]string{"a": "secret", "b": "ok"}
	out := scrubMap(m, "secret")
	if out["a"] != "[REDACTED]" {
		t.Errorf("a = %q", out["a"])
	}
	if out["b"] != "ok" {
		t.Errorf("b = %q", out["b"])
	}
}

// TestEndToEnd demonstrates the full flow: init, unlock, add credential with
// template, use it, verify audit log.
func TestEndToEnd(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("shell not available")
	}
	dir := t.TempDir()

	// Create + initialize.
	fs, err := New(dir)
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	if err := fs.Unlock(ctx, "my secret passphrase"); err != nil {
		t.Fatal(err)
	}

	// Add credential + template.
	if err := fs.Add(ctx, vault.Credential{
		ID:          "github/work",
		Description: "GitHub PAT for work",
		Value:       "ghp_xxxxxxxxxxxxxxxxxxxx",
		Tags:        []string{"github"},
	}); err != nil {
		t.Fatal(err)
	}
	if err := fs.SetTemplate(ctx, "github/work", vault.Template{
		Name: "gh_cli_env",
		Injection: vault.Injection{Env: map[string]string{
			"GH_TOKEN": "$value",
		}},
	}); err != nil {
		t.Fatal(err)
	}

	// Reopen from disk.
	fs2, err := New(dir)
	if err != nil {
		t.Fatal(err)
	}
	if err := fs2.Unlock(ctx, "my secret passphrase"); err != nil {
		t.Fatal(err)
	}

	// Use it.
	outFile := filepath.Join(t.TempDir(), "token.txt")
	res, err := fs2.Use(ctx, vault.UseRequest{
		Credential: "github/work",
		Template:   "gh_cli_env",
		Command:    "sh",
		Args:       []string{"-c", `echo "$GH_TOKEN" > ` + outFile},
	}, "agent-test")
	if err != nil {
		t.Fatal(err)
	}
	written, _ := os.ReadFile(outFile)
	if !strings.Contains(string(written), "ghp_xxxxxxxxxxxxxxxxxxxx") {
		t.Errorf("expected token in file, got %q", written)
	}
	if strings.Contains(res.Stdout, "ghp_xxxxxxxxxxxxxxxxxxxx") {
		t.Errorf("stdout leaked token: %q", res.Stdout)
	}

	// Audit.
	entries, err := fs2.AuditLog(ctx, vault.AuditOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 {
		t.Errorf("audit entries = %d, want 1", len(entries))
	}

	// Lock.
	if err := fs2.Lock(ctx); err != nil {
		t.Fatal(err)
	}
}

// Suppress unused import warning when running with -short.
var _ = time.Second