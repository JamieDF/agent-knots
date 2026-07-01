// Package filestore implements project.Store on top of YAML files.
//
// Layout:
//
//	~/.agentjam/projects/<project-id>.yaml
//	~/.agentjam/projects/active.yaml     # active project ID
package filestore

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"gopkg.in/yaml.v3"

	"github.com/JamieDF/agentjam/internal/errs"
	"github.com/JamieDF/agentjam/internal/project"
)

// Store is a file-backed project.Store.
type Store struct {
	root string

	mu     sync.RWMutex
	active project.ID
}

// New constructs a Store rooted at the given directory. The directory is
// created if absent.
func New(root string) (*Store, error) {
	if root == "" {
		return nil, errs.Wrap(errs.ErrInvalid, "project store root is required")
	}
	if err := os.MkdirAll(root, 0o700); err != nil {
		return nil, errs.Wrap(err, "create project dir %q", root)
	}
	s := &Store{root: root}
	if err := s.loadActive(); err != nil {
		return nil, err
	}
	return s, nil
}

func (s *Store) activePath() string {
	return filepath.Join(s.root, "active.yaml")
}

func (s *Store) loadActive() error {
	data, err := os.ReadFile(s.activePath())
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		return errs.Wrap(err, "read active project")
	}
	var wrapper struct {
		Active project.ID `yaml:"active"`
	}
	if err := yaml.Unmarshal(data, &wrapper); err != nil {
		return errs.Wrap(err, "parse active project")
	}
	s.active = wrapper.Active
	return nil
}

func (s *Store) saveActive() error {
	wrapper := struct {
		Active project.ID `yaml:"active"`
	}{Active: s.active}
	data, err := yaml.Marshal(wrapper)
	if err != nil {
		return errs.Wrap(err, "marshal active project")
	}
	tmp := s.activePath() + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return errs.Wrap(err, "write active tmp")
	}
	return os.Rename(tmp, s.activePath())
}

// pathFor returns the on-disk path for a project.
func (s *Store) pathFor(id project.ID) string {
	return filepath.Join(s.root, string(id)+".yaml")
}

// Create implements project.Store.
func (s *Store) Create(p *project.Project) error {
	if err := s.validate(p); err != nil {
		return err
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	if _, err := os.Stat(s.pathFor(p.ID)); err == nil {
		return errs.Wrap(errs.ErrAlreadyExists, "project %q", p.ID)
	}

	p.CreatedAt = time.Now().UTC()
	if p.Models.Default == "" {
		p.Models.Default = "claude-sonnet-4"
	}
	if p.Models.Agent == "" {
		p.Models.Agent = "claude-sonnet-4"
	}
	if p.Models.Cheap == "" {
		p.Models.Cheap = "gpt-4o-mini"
	}

	data, err := yaml.Marshal(p)
	if err != nil {
		return errs.Wrap(err, "marshal project")
	}
	tmp := s.pathFor(p.ID) + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return errs.Wrap(err, "write project tmp")
	}
	if err := os.Rename(tmp, s.pathFor(p.ID)); err != nil {
		return errs.Wrap(err, "rename project tmp")
	}
	return nil
}

// Get implements project.Store.
func (s *Store) Get(id project.ID) (*project.Project, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	data, err := os.ReadFile(s.pathFor(id))
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, errs.Wrap(errs.ErrNotFound, "project %q", id)
		}
		return nil, errs.Wrap(err, "read project %q", id)
	}
	var p project.Project
	if err := yaml.Unmarshal(data, &p); err != nil {
		return nil, errs.Wrap(err, "parse project %q", id)
	}
	return &p, nil
}

// List implements project.Store.
func (s *Store) List(opts project.ListOptions) ([]*project.Project, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	entries, err := os.ReadDir(s.root)
	if err != nil {
		return nil, errs.Wrap(err, "read project dir")
	}

	var projects []*project.Project
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".yaml") || e.Name() == "active.yaml" {
			continue
		}
		data, err := os.ReadFile(filepath.Join(s.root, e.Name()))
		if err != nil {
			continue
		}
		var p project.Project
		if err := yaml.Unmarshal(data, &p); err != nil {
			continue
		}
		projects = append(projects, &p)
	}
	return projects, nil
}

// Update implements project.Store.
func (s *Store) Update(p *project.Project) error {
	if err := s.validate(p); err != nil {
		return err
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	if _, err := os.Stat(s.pathFor(p.ID)); err != nil {
		return errs.Wrap(errs.ErrNotFound, "project %q", p.ID)
	}

	data, err := yaml.Marshal(p)
	if err != nil {
		return errs.Wrap(err, "marshal project")
	}
	tmp := s.pathFor(p.ID) + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return errs.Wrap(err, "write project tmp")
	}
	return os.Rename(tmp, s.pathFor(p.ID))
}

// Delete implements project.Store.
func (s *Store) Delete(id project.ID) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if _, err := os.Stat(s.pathFor(id)); err != nil {
		return errs.Wrap(errs.ErrNotFound, "project %q", id)
	}
	if err := os.Remove(s.pathFor(id)); err != nil {
		return errs.Wrap(err, "delete project %q", id)
	}
	if s.active == id {
		s.active = ""
		_ = s.saveActive()
	}
	return nil
}

// Touch implements project.Store.
func (s *Store) Touch(id project.ID) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	p, err := s.getLocked(id)
	if err != nil {
		return err
	}
	p.LastOpenedAt = time.Now().UTC()

	data, err := yaml.Marshal(p)
	if err != nil {
		return errs.Wrap(err, "marshal project")
	}
	return os.WriteFile(s.pathFor(id), data, 0o600)
}

// Active implements project.Store.
func (s *Store) Active() (project.ID, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.active, nil
}

// SetActive implements project.Store.
func (s *Store) SetActive(id project.ID) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if id != "" {
		if _, err := os.Stat(s.pathFor(id)); err != nil {
			return errs.Wrap(errs.ErrNotFound, "project %q", id)
		}
	}
	s.active = id
	return s.saveActive()
}

func (s *Store) getLocked(id project.ID) (*project.Project, error) {
	data, err := os.ReadFile(s.pathFor(id))
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, errs.Wrap(errs.ErrNotFound, "project %q", id)
		}
		return nil, errs.Wrap(err, "read project %q", id)
	}
	var p project.Project
	if err := yaml.Unmarshal(data, &p); err != nil {
		return nil, errs.Wrap(err, "parse project %q", id)
	}
	return &p, nil
}

func (s *Store) validate(p *project.Project) error {
	if p == nil {
		return errs.Wrap(errs.ErrInvalid, "project is nil")
	}
	if strings.TrimSpace(string(p.ID)) == "" {
		return errs.Wrap(errs.ErrInvalid, "project ID is required")
	}
	if strings.TrimSpace(p.Name) == "" {
		return errs.Wrap(errs.ErrInvalid, "project name is required")
	}
	return nil
}

// Compile-time check.
var _ project.Store = (*Store)(nil)