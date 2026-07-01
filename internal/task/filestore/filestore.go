// Package filestore implements task.Store on top of YAML files.
//
// Layout:
//
//	~/.agentjam/tasks/<project-id>/<task-id>.yaml
//	~/.agentjam/tasks/index.yaml         # task ID -> project + path lookup
//
// YAML is used so files are greppable, hand-editable, and version-controllable
// by users who want to commit their task history.
//
// Concurrency: all exported methods are safe for concurrent use. Internally,
// a per-file RWMutex is held briefly during read/write. Cross-file operations
// (index update) take the index mutex.
package filestore

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"gopkg.in/yaml.v3"

	"github.com/JamieDF/agentjam/internal/errs"
	"github.com/JamieDF/agentjam/internal/task"
)

// Store is a file-backed task.Store.
type Store struct {
	root string

	mu        sync.RWMutex
	indexMu   sync.Mutex
	index     map[task.ID]indexEntry
}

// indexEntry maps a task ID to its on-disk location.
type indexEntry struct {
	Project string `yaml:"project"`
	Path    string `yaml:"path"`
}

// New constructs a Store rooted at the given directory. The directory is
// created if absent.
func New(root string) (*Store, error) {
	if root == "" {
		return nil, errs.Wrap(errs.ErrInvalid, "task store root is required")
	}
	if err := os.MkdirAll(root, 0o700); err != nil {
		return nil, errs.Wrap(err, "create task dir %q", root)
	}
	s := &Store{
		root:  root,
		index: make(map[task.ID]indexEntry),
	}
	if err := s.loadIndex(); err != nil {
		return nil, err
	}
	return s, nil
}

func (s *Store) indexPath() string {
	return filepath.Join(s.root, "index.yaml")
}

func (s *Store) loadIndex() error {
	data, err := os.ReadFile(s.indexPath())
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		return errs.Wrap(err, "read task index")
	}
	var idx map[task.ID]indexEntry
	if err := yaml.Unmarshal(data, &idx); err != nil {
		return errs.Wrap(err, "parse task index")
	}
	if idx != nil {
		s.index = idx
	}
	return nil
}

func (s *Store) saveIndexLocked() error {
	data, err := yaml.Marshal(s.index)
	if err != nil {
		return errs.Wrap(err, "marshal task index")
	}
	tmp := s.indexPath() + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return errs.Wrap(err, "write task index tmp")
	}
	if err := os.Rename(tmp, s.indexPath()); err != nil {
		return errs.Wrap(err, "rename task index tmp")
	}
	return nil
}

// Create implements task.Store.
func (s *Store) Create(t *task.Task) error {
	if err := s.validate(t); err != nil {
		return err
	}
	if t.ID == "" {
		return errs.Wrap(errs.ErrInvalid, "task ID is required")
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	s.indexMu.Lock()
	defer s.indexMu.Unlock()

	if _, exists := s.index[t.ID]; exists {
		return errs.Wrap(errs.ErrAlreadyExists, "task %q", t.ID)
	}

	t.CreatedAt = time.Now().UTC()
	t.UpdatedAt = t.CreatedAt
	if t.Status == "" {
		t.Status = task.StatusDraft
	}
	if t.Priority == "" {
		t.Priority = task.PriorityMedium
	}

	if err := s.writeTask(t); err != nil {
		return err
	}
	s.index[t.ID] = indexEntry{
		Project: t.Project,
		Path:    s.pathFor(t),
	}
	return s.saveIndexLocked()
}

// Get implements task.Store.
func (s *Store) Get(id task.ID) (*task.Task, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	entry, ok := s.index[id]
	if !ok {
		return nil, errs.Wrap(errs.ErrNotFound, "task %q", id)
	}
	return s.readTask(entry.Path)
}

// List implements task.Store.
func (s *Store) List(opts task.ListOptions) ([]*task.Task, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	var tasks []*task.Task
	for _, entry := range s.index {
		if opts.Project != "" && entry.Project != opts.Project {
			continue
		}
		t, err := s.readTask(entry.Path)
		if err != nil {
			continue // skip corrupted entries silently
		}
		if opts.Status != "" && t.Status != opts.Status {
			continue
		}
		if opts.AssignedTo != "" && t.AssignedTo != opts.AssignedTo {
			continue
		}
		if len(opts.Tags) > 0 && !hasAllTags(t.Tags, opts.Tags) {
			continue
		}
		tasks = append(tasks, t)
		if opts.Limit > 0 && len(tasks) >= opts.Limit {
			break
		}
	}

	// Sort by UpdatedAt descending.
	sort.Slice(tasks, func(i, j int) bool {
		return tasks[i].UpdatedAt.After(tasks[j].UpdatedAt)
	})
	return tasks, nil
}

// Update implements task.Store.
func (s *Store) Update(t *task.Task) error {
	if err := s.validate(t); err != nil {
		return err
	}
	if t.ID == "" {
		return errs.Wrap(errs.ErrInvalid, "task ID is required")
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	entry, ok := s.index[t.ID]
	if !ok {
		return errs.Wrap(errs.ErrNotFound, "task %q", t.ID)
	}
	t.UpdatedAt = time.Now().UTC()
	if err := s.writeTaskTo(entry.Path, t); err != nil {
		return err
	}
	return nil
}

// Delete implements task.Store.
func (s *Store) Delete(id task.ID) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.indexMu.Lock()
	defer s.indexMu.Unlock()

	entry, ok := s.index[id]
	if !ok {
		return errs.Wrap(errs.ErrNotFound, "task %q", id)
	}
	if err := os.Remove(entry.Path); err != nil {
		return errs.Wrap(err, "delete task file")
	}
	delete(s.index, id)
	return s.saveIndexLocked()
}

// LogProgress implements task.Store.
func (s *Store) LogProgress(id task.ID, entry task.ProgressEntry) error {
	if entry.Entry == "" {
		return errs.Wrap(errs.ErrInvalid, "progress entry body is required")
	}
	if entry.Timestamp.IsZero() {
		entry.Timestamp = time.Now().UTC()
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	idxEntry, ok := s.index[id]
	if !ok {
		return errs.Wrap(errs.ErrNotFound, "task %q", id)
	}
	t, err := s.readTask(idxEntry.Path)
	if err != nil {
		return err
	}
	t.Progress = append(t.Progress, entry)
	t.UpdatedAt = time.Now().UTC()
	if entry.Status != "" && entry.Status != t.Status {
		t.Status = entry.Status
	}
	return s.writeTaskTo(idxEntry.Path, t)
}

// Assign implements task.Store.
func (s *Store) Assign(id task.ID, agentID string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	idxEntry, ok := s.index[id]
	if !ok {
		return errs.Wrap(errs.ErrNotFound, "task %q", id)
	}
	t, err := s.readTask(idxEntry.Path)
	if err != nil {
		return err
	}
	t.AssignedTo = agentID
	t.UpdatedAt = time.Now().UTC()
	return s.writeTaskTo(idxEntry.Path, t)
}

// SetStatus implements task.Store.
func (s *Store) SetStatus(id task.ID, status task.Status) error {
	if !status.Valid() {
		return errs.Wrap(errs.ErrInvalid, "invalid status %q", status)
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	idxEntry, ok := s.index[id]
	if !ok {
		return errs.Wrap(errs.ErrNotFound, "task %q", id)
	}
	t, err := s.readTask(idxEntry.Path)
	if err != nil {
		return err
	}

	// Validate transition.
	if t.Status.IsTerminal() && status != t.Status {
		return errs.Wrap(errs.ErrInvalid,
			"cannot transition from terminal status %q to %q", t.Status, status)
	}

	t.Status = status
	t.UpdatedAt = time.Now().UTC()
	return s.writeTaskTo(idxEntry.Path, t)
}

// CheckAcceptance implements task.Store.
func (s *Store) CheckAcceptance(id task.ID, satisfied []bool) error {
	s.mu.RLock()
	defer s.mu.RUnlock()

	idxEntry, ok := s.index[id]
	if !ok {
		return errs.Wrap(errs.ErrNotFound, "task %q", id)
	}
	t, err := s.readTask(idxEntry.Path)
	if err != nil {
		return err
	}
	if len(satisfied) != len(t.AcceptanceCriteria) {
		return errs.Wrap(errs.ErrInvalid,
			"expected %d satisfied flags, got %d", len(t.AcceptanceCriteria), len(satisfied))
	}
	for i, ok := range satisfied {
		if !ok {
			return errs.Wrap(errs.ErrInvalid,
				"criterion %d not satisfied: %q", i+1, t.AcceptanceCriteria[i])
		}
	}
	return nil
}

// AddStep implements task.Store.
func (s *Store) AddStep(id task.ID, step task.Step) error {
	if step.Title == "" {
		return errs.Wrap(errs.ErrInvalid, "step title is required")
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	idxEntry, ok := s.index[id]
	if !ok {
		return errs.Wrap(errs.ErrNotFound, "task %q", id)
	}
	t, err := s.readTask(idxEntry.Path)
	if err != nil {
		return err
	}
	if step.ID == "" {
		step.ID = fmt.Sprintf(".%d", len(t.Steps)+1)
	}
	t.Steps = append(t.Steps, step)
	t.UpdatedAt = time.Now().UTC()
	return s.writeTaskTo(idxEntry.Path, t)
}

// UpdateStep implements task.Store.
func (s *Store) UpdateStep(id task.ID, step task.Step) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	idxEntry, ok := s.index[id]
	if !ok {
		return errs.Wrap(errs.ErrNotFound, "task %q", id)
	}
	t, err := s.readTask(idxEntry.Path)
	if err != nil {
		return err
	}
	for i, s2 := range t.Steps {
		if s2.ID == step.ID {
			t.Steps[i] = step
			t.UpdatedAt = time.Now().UTC()
			return s.writeTaskTo(idxEntry.Path, t)
		}
	}
	return errs.Wrap(errs.ErrNotFound, "step %q", step.ID)
}

// pathFor returns the on-disk path for a task.
func (s *Store) pathFor(t *task.Task) string {
	project := t.Project
	if project == "" {
		project = "_global"
	}
	return filepath.Join(s.root, project, string(t.ID)+".yaml")
}

// writeTask writes t to its canonical path and updates the index.
func (s *Store) writeTask(t *task.Task) error {
	return s.writeTaskTo(s.pathFor(t), t)
}

// writeTaskTo writes t to path, creating parent directories as needed.
func (s *Store) writeTaskTo(path string, t *task.Task) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return errs.Wrap(err, "create task dir")
	}
	data, err := yaml.Marshal(t)
	if err != nil {
		return errs.Wrap(err, "marshal task")
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return errs.Wrap(err, "write task tmp")
	}
	if err := os.Rename(tmp, path); err != nil {
		return errs.Wrap(err, "rename task tmp")
	}
	return nil
}

// readTask reads a task from path.
func (s *Store) readTask(path string) (*task.Task, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, errs.Wrap(err, "read task %q", path)
	}
	var t task.Task
	if err := yaml.Unmarshal(data, &t); err != nil {
		return nil, errs.Wrap(err, "parse task %q", path)
	}
	return &t, nil
}

// validate checks a task for required fields.
func (s *Store) validate(t *task.Task) error {
	if t == nil {
		return errs.Wrap(errs.ErrInvalid, "task is nil")
	}
	if strings.TrimSpace(string(t.ID)) == "" {
		return errs.Wrap(errs.ErrInvalid, "task ID is required")
	}
	if strings.TrimSpace(t.Title) == "" {
		return errs.Wrap(errs.ErrInvalid, "task title is required")
	}
	return nil
}

// hasAllTags reports whether haystack contains every tag in needles.
func hasAllTags(haystack, needles []string) bool {
	have := make(map[string]bool, len(haystack))
	for _, t := range haystack {
		have[t] = true
	}
	for _, n := range needles {
		if !have[n] {
			return false
		}
	}
	return true
}

// Compile-time check.
var _ task.Store = (*Store)(nil)