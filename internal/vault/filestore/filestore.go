package filestore

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"golang.org/x/crypto/argon2"

	"github.com/JamieDF/agentjam/internal/errs"
	"github.com/JamieDF/agentjam/internal/vault"
)

// entry is the on-disk representation of a credential. The value is
// encrypted; everything else is in cleartext.
type entry struct {
	ID          vault.ID            `json:"id"`
	Description string              `json:"description,omitempty"`
	Tags        []string            `json:"tags,omitempty"`
	CreatedAt   time.Time           `json:"created_at"`
	LastUsed    time.Time           `json:"last_used,omitempty"`
	UsesTotal   int64               `json:"uses_total"`
	Encrypted   []byte              `json:"encrypted_value"`
	Salt        []byte              `json:"salt"`
	Templates   []vault.Template    `json:"templates,omitempty"`
}

// file is the on-disk JSON document persisted to vault.enc.
type file struct {
	Version  int     `json:"version"`
	Entries  []entry `json:"entries"`
	Modified time.Time `json:"modified"`
}

// FileStore is a file-backed vault. See package doc for layout.
//
// Zero value is not usable; construct with New.
type FileStore struct {
	path string

	mu       sync.RWMutex
	unlocked bool
	key      []byte // derived key; nil when locked
	file     file
}

// New constructs a FileStore rooted at the given directory. The directory is
// created if absent. If a vault already exists at this path, it is loaded.
func New(path string) (*FileStore, error) {
	if path == "" {
		return nil, errs.Wrap(errs.ErrInvalid, "vault path is required")
	}

	if err := os.MkdirAll(path, 0o700); err != nil {
		return nil, errs.Wrap(err, "create vault dir %q", path)
	}

	fs := &FileStore{path: filepath.Join(path, "vault.enc")}
	if err := fs.load(); err != nil && !errors.Is(err, os.ErrNotExist) {
		return nil, err
	}
	return fs, nil
}

// load reads the vault from disk into memory. Missing file is not an error —
// it means the vault is being created for the first time.
func (f *FileStore) load() error {
	data, err := os.ReadFile(f.path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			f.file = file{Version: 1, Modified: time.Now()}
			return nil
		}
		return errs.Wrap(err, "read vault %q", f.path)
	}

	var doc file
	if err := json.Unmarshal(data, &doc); err != nil {
		return errs.Wrap(err, "parse vault %q", f.path)
	}
	if doc.Version != 1 {
		return errs.Wrap(errs.ErrInvalid, "unsupported vault version %d", doc.Version)
	}
	f.file = doc
	return nil
}

// save persists the in-memory state to disk atomically (write to temp,
// rename).
func (f *FileStore) save() error {
	f.file.Modified = time.Now()
	data, err := json.MarshalIndent(f.file, "", "  ")
	if err != nil {
		return errs.Wrap(err, "marshal vault")
	}

	tmp := f.path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return errs.Wrap(err, "write vault tmp")
	}
	if err := os.Rename(tmp, f.path); err != nil {
		return errs.Wrap(err, "rename vault tmp")
	}
	return nil
}

// LockState implements Vault.LockState.
func (f *FileStore) LockState(_ context.Context) (vault.LockState, error) {
	f.mu.RLock()
	defer f.mu.RUnlock()

	if !fileExists(f.path) {
		return vault.Uninitialized, nil
	}
	if f.unlocked {
		return vault.Unlocked, nil
	}
	return vault.Locked, nil
}

// Lock implements Vault.Lock.
func (f *FileStore) Lock(_ context.Context) error {
	f.mu.Lock()
	defer f.mu.Unlock()

	if f.key != nil {
		// Zero key bytes for hygiene.
		for i := range f.key {
			f.key[i] = 0
		}
		f.key = nil
	}
	f.unlocked = false
	return nil
}

// Unlock implements Vault.Unlock. The passphrase is used to derive the
// encryption key via argon2id. If the vault is empty, Unlock initializes it
// with the given passphrase.
func (f *FileStore) Unlock(_ context.Context, passphrase string) error {
	if passphrase == "" {
		return errs.Wrap(errs.ErrInvalid, "passphrase is required")
	}

	f.mu.Lock()
	defer f.mu.Unlock()

	if len(f.file.Entries) == 0 && !fileExists(f.path) {
		// First-time init: create the first entry's salt, encrypt an empty
		// marker, save. Future Unlocks will derive the key from passphrase
		// + that salt.
		salt, err := newSalt()
		if err != nil {
			return err
		}
		key := deriveKey(passphrase, salt)
		marker, err := encrypt(key, []byte("harness-vault-marker-v1"))
		if err != nil {
			return err
		}
		f.file.Entries = append(f.file.Entries, entry{
			ID:        "_vault_marker_",
			CreatedAt: time.Now(),
			Salt:      salt,
			Encrypted: marker,
		})
		if err := f.save(); err != nil {
			return err
		}
		f.key = key
		f.unlocked = true
		return nil
	}

	// Find the marker entry to get the salt.
	var marker *entry
	for i := range f.file.Entries {
		if f.file.Entries[i].ID == "_vault_marker_" {
			marker = &f.file.Entries[i]
			break
		}
	}
	if marker == nil {
		return errs.Wrap(errs.ErrInvalid, "vault has no marker; cannot unlock")
	}

	key := deriveKey(passphrase, marker.Salt)
	plain, err := decrypt(key, marker.Encrypted)
	if err != nil {
		return errs.Wrap(errs.ErrUnauthorized, "wrong passphrase or corrupted vault")
	}
	if string(plain) != "harness-vault-marker-v1" {
		return errs.Wrap(errs.ErrInvalid, "vault marker mismatch")
	}

	f.key = key
	f.unlocked = true
	return nil
}

// IsUnlocked implements Vault.IsUnlocked.
func (f *FileStore) IsUnlocked(_ context.Context) (bool, error) {
	f.mu.RLock()
	defer f.mu.RUnlock()
	return f.unlocked, nil
}

// List implements Vault.List.
func (f *FileStore) List(_ context.Context) ([]vault.Credential, error) {
	f.mu.RLock()
	defer f.mu.RUnlock()

	out := make([]vault.Credential, 0, len(f.file.Entries))
	for _, e := range f.file.Entries {
		if e.ID == "_vault_marker_" {
			continue
		}
		out = append(out, vault.Credential{
			ID:          e.ID,
			Description: e.Description,
			Tags:        e.Tags,
			CreatedAt:   e.CreatedAt,
			LastUsed:    e.LastUsed,
			UsesTotal:   e.UsesTotal,
		})
	}
	return out, nil
}

// Get implements Vault.Get.
func (f *FileStore) Get(_ context.Context, id vault.ID) (vault.Credential, error) {
	f.mu.RLock()
	defer f.mu.RUnlock()

	e, ok := f.find(id)
	if !ok {
		return vault.Credential{}, errs.Wrap(errs.ErrNotFound, "credential %q", id)
	}
	return vault.Credential{
		ID:          e.ID,
		Description: e.Description,
		Tags:        e.Tags,
		CreatedAt:   e.CreatedAt,
		LastUsed:    e.LastUsed,
		UsesTotal:   e.UsesTotal,
	}, nil
}

// Add implements Vault.Add.
func (f *FileStore) Add(_ context.Context, cred vault.Credential) error {
	if err := cred.Validate(); err != nil {
		return err
	}
	if cred.Value == "" {
		return errs.Wrap(errs.ErrInvalid, "credential value is required")
	}

	f.mu.Lock()
	defer f.mu.Unlock()
	if !f.unlocked {
		return errs.Wrap(errs.ErrUnauthorized, "vault is locked")
	}
	if _, exists := f.find(cred.ID); exists {
		return errs.Wrap(errs.ErrAlreadyExists, "credential %q", cred.ID)
	}

	// Encrypt the value. Each credential gets its own salt for defense in
	// depth.
	salt, err := newSalt()
	if err != nil {
		return err
	}
	// Use the vault's derived key as input keying material, then mix with
	// the per-entry salt to derive a per-entry key.
	entryKey := derivePerEntryKey(f.key, salt)
	encrypted, err := encrypt(entryKey, []byte(cred.Value))
	if err != nil {
		return err
	}

	f.file.Entries = append(f.file.Entries, entry{
		ID:          cred.ID,
		Description: cred.Description,
		Tags:        cred.Tags,
		CreatedAt:   time.Now(),
		Encrypted:   encrypted,
		Salt:        salt,
	})
	return f.save()
}

// Remove implements Vault.Remove.
func (f *FileStore) Remove(_ context.Context, id vault.ID) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if !f.unlocked {
		return errs.Wrap(errs.ErrUnauthorized, "vault is locked")
	}

	for i, e := range f.file.Entries {
		if e.ID == id {
			f.file.Entries = append(f.file.Entries[:i], f.file.Entries[i+1:]...)
			return f.save()
		}
	}
	return errs.Wrap(errs.ErrNotFound, "credential %q", id)
}

// Update implements Vault.Update. Only metadata (description, tags) can be
// updated; rotate via Add+Remove for the value.
func (f *FileStore) Update(_ context.Context, cred vault.Credential) error {
	if err := cred.Validate(); err != nil {
		return err
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	if !f.unlocked {
		return errs.Wrap(errs.ErrUnauthorized, "vault is locked")
	}

	e, ok := f.find(cred.ID)
	if !ok {
		return errs.Wrap(errs.ErrNotFound, "credential %q", cred.ID)
	}
	e.Description = cred.Description
	e.Tags = cred.Tags
	return f.save()
}

// SetTemplate implements Vault.SetTemplate.
func (f *FileStore) SetTemplate(_ context.Context, credID vault.ID, tmpl vault.Template) error {
	if err := tmpl.Validate(); err != nil {
		return err
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	if !f.unlocked {
		return errs.Wrap(errs.ErrUnauthorized, "vault is locked")
	}

	e, ok := f.find(credID)
	if !ok {
		return errs.Wrap(errs.ErrNotFound, "credential %q", credID)
	}

	// Replace if exists, append otherwise.
	for i, t := range e.Templates {
		if t.Name == tmpl.Name {
			e.Templates[i] = tmpl
			return f.save()
		}
	}
	e.Templates = append(e.Templates, tmpl)
	return f.save()
}

// GetTemplate implements Vault.GetTemplate.
func (f *FileStore) GetTemplate(_ context.Context, credID vault.ID, name string) (vault.Template, error) {
	f.mu.RLock()
	defer f.mu.RUnlock()

	e, ok := f.find(credID)
	if !ok {
		return vault.Template{}, errs.Wrap(errs.ErrNotFound, "credential %q", credID)
	}
	for _, t := range e.Templates {
		if t.Name == name {
			return t, nil
		}
	}
	return vault.Template{}, errs.Wrap(errs.ErrNotFound, "template %q on %q", name, credID)
}

// ListTemplates implements Vault.ListTemplates.
func (f *FileStore) ListTemplates(_ context.Context, credID vault.ID) ([]vault.Template, error) {
	f.mu.RLock()
	defer f.mu.RUnlock()

	e, ok := f.find(credID)
	if !ok {
		return nil, errs.Wrap(errs.ErrNotFound, "credential %q", credID)
	}
	out := make([]vault.Template, len(e.Templates))
	copy(out, e.Templates)
	return out, nil
}

// RemoveTemplate implements Vault.RemoveTemplate.
func (f *FileStore) RemoveTemplate(_ context.Context, credID vault.ID, name string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if !f.unlocked {
		return errs.Wrap(errs.ErrUnauthorized, "vault is locked")
	}

	e, ok := f.find(credID)
	if !ok {
		return errs.Wrap(errs.ErrNotFound, "credential %q", credID)
	}
	for i, t := range e.Templates {
		if t.Name == name {
			e.Templates = append(e.Templates[:i], e.Templates[i+1:]...)
			return f.save()
		}
	}
	return errs.Wrap(errs.ErrNotFound, "template %q on %q", name, credID)
}

// AuditLog implements Vault.AuditLog. Reads from vault.log.
func (f *FileStore) AuditLog(_ context.Context, opts vault.AuditOptions) ([]vault.AuditEntry, error) {
	path := filepath.Join(filepath.Dir(f.path), "vault.log")
	data, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, nil
		}
		return nil, errs.Wrap(err, "read audit log")
	}

	var entries []vault.AuditEntry
	for _, line := range splitLines(data) {
		var e vault.AuditEntry
		if err := json.Unmarshal(line, &e); err != nil {
			continue // skip malformed lines
		}
		if !opts.Since.IsZero() && e.Timestamp.Before(opts.Since) {
			continue
		}
		if opts.Credential != "" && e.Credential != opts.Credential {
			continue
		}
		entries = append(entries, e)
		if opts.Limit > 0 && len(entries) >= opts.Limit {
			break
		}
	}
	return entries, nil
}

// appendAudit writes one entry to vault.log atomically.
func (f *FileStore) appendAudit(e vault.AuditEntry) error {
	path := filepath.Join(filepath.Dir(f.path), "vault.log")
	data, err := json.Marshal(e)
	if err != nil {
		return err
	}
	data = append(data, '\n')

	fh, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o600)
	if err != nil {
		return errs.Wrap(err, "open audit log")
	}
	defer fh.Close()

	if _, err := fh.Write(data); err != nil {
		return errs.Wrap(err, "write audit log")
	}
	return nil
}

// find returns the entry for id. Must be called with at least the read lock
// held.
func (f *FileStore) find(id vault.ID) (*entry, bool) {
	for i := range f.file.Entries {
		if f.file.Entries[i].ID == id {
			return &f.file.Entries[i], true
		}
	}
	return nil, false
}

// decryptEntry returns the plaintext value for the given entry. Must be
// called with the write lock held.
func (f *FileStore) decryptEntry(e *entry) (string, error) {
	if !f.unlocked {
		return "", errs.Wrap(errs.ErrUnauthorized, "vault is locked")
	}
	entryKey := derivePerEntryKey(f.key, e.Salt)
	plain, err := decrypt(entryKey, e.Encrypted)
	if err != nil {
		return "", errs.Wrap(err, "decrypt credential %q", e.ID)
	}
	return string(plain), nil
}

// derivePerEntryKey derives a per-entry key from the vault's master key
// and the entry's salt. Defense-in-depth: compromising one entry's key
// doesn't expose the master.
func derivePerEntryKey(master, salt []byte) []byte {
	return argon2.IDKey(master, salt, 1, 8*1024, 1, KeyLen)
}

// fileExists reports whether path is a regular file.
func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.Mode().IsRegular()
}

// splitLines splits b on newlines, returning each non-empty line as a
// separate slice. The returned slices share memory with b.
func splitLines(b []byte) [][]byte {
	var out [][]byte
	start := 0
	for i, c := range b {
		if c == '\n' {
			if i > start {
				out = append(out, b[start:i])
			}
			start = i + 1
		}
	}
	if start < len(b) {
		out = append(out, b[start:])
	}
	return out
}

// Compile-time check.
var _ vault.Vault = (*FileStore)(nil)

// String implements fmt.Stringer for debugging.
func (f *FileStore) String() string {
	return fmt.Sprintf("filestore.FileStore{path=%q, entries=%d, unlocked=%v}",
		f.path, len(f.file.Entries), f.unlocked)
}