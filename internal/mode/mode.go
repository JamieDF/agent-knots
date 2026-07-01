// Package mode loads Mode definitions from markdown files.
//
// A Mode is a system prompt that controls agent behavior. Modes live in
// ~/.harness/modes/<name>.md as plain markdown. The first line is treated
// as the mode's display name; the rest is the system prompt body.
//
// Users can add custom modes by dropping a markdown file into the modes
// directory. The mode loader picks them up automatically.
package mode

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"

	"github.com/harness/harness/internal/errs"
)

// Mode is a named system prompt definition.
type Mode struct {
	// Name is the file-derived identifier (e.g. "agent").
	Name string

	// DisplayName is the first heading in the markdown, if present.
	DisplayName string

	// Description is a short summary, parsed from the first non-heading
	// line if available.
	Description string

	// Body is the full system prompt content (the entire file).
	Body string

	// Path is the on-disk path the mode was loaded from.
	Path string
}

// Loader loads modes from a directory.
type Loader struct {
	root string

	mu    sync.RWMutex
	cache map[string]Mode
}

// NewLoader constructs a Loader rooted at the given directory.
func NewLoader(root string) (*Loader, error) {
	if root == "" {
		return nil, errs.Wrap(errs.ErrInvalid, "mode root is required")
	}
	if err := os.MkdirAll(root, 0o700); err != nil {
		return nil, errs.Wrap(err, "create mode dir %q", root)
	}
	return &Loader{
		root:  root,
		cache: make(map[string]Mode),
	}, nil
}

// Root returns the loader's root directory.
func (l *Loader) Root() string {
	return l.root
}

// Load returns the mode with the given name. Cached after first load; use
// Reload to force a re-read from disk.
func (l *Loader) Load(name string) (Mode, error) {
	if name == "" {
		return Mode{}, errs.Wrap(errs.ErrInvalid, "mode name is required")
	}

	l.mu.RLock()
	m, ok := l.cache[name]
	l.mu.RUnlock()
	if ok {
		return m, nil
	}

	return l.loadFromDisk(name)
}

// loadFromDisk reads and parses a mode file.
func (l *Loader) loadFromDisk(name string) (Mode, error) {
	path := filepath.Join(l.root, name+".md")
	f, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) {
			return Mode{}, errs.Wrap(errs.ErrNotFound, "mode %q", name)
		}
		return Mode{}, errs.Wrap(err, "open mode %q", name)
	}
	defer f.Close()

	var lines []string
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		lines = append(lines, scanner.Text())
	}
	if err := scanner.Err(); err != nil {
		return Mode{}, errs.Wrap(err, "read mode %q", name)
	}

	body := strings.Join(lines, "\n")
	m := Mode{
		Name: name,
		Body: body,
		Path: path,
	}

	// Parse first heading as DisplayName, first paragraph as Description.
	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		if trimmed == "" {
			continue
		}
		if strings.HasPrefix(trimmed, "# ") {
			m.DisplayName = strings.TrimPrefix(trimmed, "# ")
			continue
		}
		// Skip sub-headings for description parsing.
		if strings.HasPrefix(trimmed, "#") {
			continue
		}
		m.Description = trimmed
		break
	}

	l.mu.Lock()
	l.cache[name] = m
	l.mu.Unlock()
	return m, nil
}

// List returns all available modes, sorted alphabetically by name.
func (l *Loader) List() ([]Mode, error) {
	entries, err := os.ReadDir(l.root)
	if err != nil {
		return nil, errs.Wrap(err, "read mode dir")
	}

	var modes []Mode
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".md") {
			continue
		}
		name := strings.TrimSuffix(e.Name(), ".md")
		// Skip dotfiles.
		if strings.HasPrefix(name, ".") {
			continue
		}
		m, err := l.Load(name)
		if err != nil {
			continue // skip malformed
		}
		modes = append(modes, m)
	}

	sort.Slice(modes, func(i, j int) bool {
		return modes[i].Name < modes[j].Name
	})
	return modes, nil
}

// Reload clears the cache, forcing subsequent Load calls to re-read from disk.
func (l *Loader) Reload() {
	l.mu.Lock()
	l.cache = make(map[string]Mode)
	l.mu.Unlock()
}

// SystemPrompt returns the mode body with optional extras appended. Used by
// drivers to construct the full system prompt for a session.
func (l *Loader) SystemPrompt(name string, extras ...string) (string, error) {
	m, err := l.Load(name)
	if err != nil {
		return "", err
	}
	prompt := m.Body
	for _, e := range extras {
		e = strings.TrimSpace(e)
		if e != "" {
			prompt += "\n\n" + e
		}
	}
	return prompt, nil
}

// Write persists a mode to disk and invalidates the cache.
func (l *Loader) Write(m Mode) error {
	if m.Name == "" {
		return errs.Wrap(errs.ErrInvalid, "mode name is required")
	}
	if m.Body == "" {
		return errs.Wrap(errs.ErrInvalid, "mode body is required")
	}

	path := filepath.Join(l.root, m.Name+".md")
	if err := os.WriteFile(path, []byte(m.Body), 0o600); err != nil {
		return errs.Wrap(err, "write mode %q", m.Name)
	}

	// Invalidate cache so the next Load re-parses DisplayName / Description
	// from disk.
	l.mu.Lock()
	delete(l.cache, m.Name)
	l.mu.Unlock()
	return nil
}

// Exists reports whether a mode file exists on disk.
func (l *Loader) Exists(name string) bool {
	_, err := os.Stat(filepath.Join(l.root, name+".md"))
	return err == nil
}

// String returns a short representation of the mode.
func (m Mode) String() string {
	if m.DisplayName != "" {
		return fmt.Sprintf("Mode{Name=%q, Display=%q}", m.Name, m.DisplayName)
	}
	return fmt.Sprintf("Mode{Name=%q}", m.Name)
}