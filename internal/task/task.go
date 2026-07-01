// Package task defines the Task system — persistent work records that survive
// context compaction, session restarts, agent crashes, and mode swaps.
//
// A Task is a structured object in the orchestrator's database, NOT a string
// in the agent's context. The agent reads from and writes to a Task via the
// TaskStore interface; it does not contain the Task.
//
// Tasks form the contract between the user and the agent: the acceptance
// criteria define "done", and the progress log records every meaningful
// action the agent takes. Without the progress log, tasks get abandoned
// when context is lost; with it, any agent (or human) can pick up exactly
// where the previous one left off.
package task

import (
	"fmt"
	"time"
)

// Status is the task's lifecycle state.
type Status string

const (
	// StatusDraft means the task has been started but not committed.
	StatusDraft Status = "draft"

	// StatusOpen means the task is committed but not yet being worked on.
	StatusOpen Status = "open"

	// StatusPlanned means an agent has drafted a plan but not started.
	StatusPlanned Status = "planned"

	// StatusInProgress means an agent is actively working on the task.
	StatusInProgress Status = "in_progress"

	// StatusBlocked means the task is waiting on user input or external
	// resolution.
	StatusBlocked Status = "blocked"

	// StatusReview means the work is done and awaiting review.
	StatusReview Status = "review"

	// StatusDone means the task is complete and verified.
	StatusDone Status = "done"

	// StatusAbandoned means the task was given up on. Not "done" but
	// deliberately not pursued further.
	StatusAbandoned Status = "abandoned"
)

// Priority is the task's urgency.
type Priority string

const (
	PriorityLow      Priority = "low"
	PriorityMedium   Priority = "medium"
	PriorityHigh     Priority = "high"
	PriorityUrgent   Priority = "urgent"
)

// ID is a globally unique task identifier (project-scoped). Format:
// "P:<project-id>/T-<date>-<seq>".
type ID string

// Step is a sub-step within a task's plan. Steps are hierarchical (can have
// their own sub-steps).
type Step struct {
	ID          string  `yaml:"id" json:"id"`
	Title       string  `yaml:"title" json:"title"`
	Status      Status  `yaml:"status" json:"status"`
	Notes       string  `yaml:"notes,omitempty" json:"notes,omitempty"`
	SubSteps    []Step  `yaml:"sub_steps,omitempty" json:"sub_steps,omitempty"`
}

// Task is a unit of work tracked by the orchestrator.
//
// Tasks are owned by a project, may be assigned to an agent, and have a
// structured progress log. See package doc for the rationale.
type Task struct {
	// ID is the unique identifier (see ID type).
	ID ID `yaml:"id" json:"id"`

	// Project is the owning project ID. Empty means the task is global
	// (not yet associated with a project).
	Project string `yaml:"project" json:"project"`

	// Title is a short human-readable summary.
	Title string `yaml:"title" json:"title"`

	// Description is optional longer-form context.
	Description string `yaml:"description,omitempty" json:"description,omitempty"`

	// Status is the current lifecycle state.
	Status Status `yaml:"status" json:"status"`

	// Priority is the urgency.
	Priority Priority `yaml:"priority" json:"priority"`

	// Tags are free-form labels for filtering.
	Tags []string `yaml:"tags,omitempty" json:"tags,omitempty"`

	// AcceptanceCriteria define what "done" means. Each criterion must be
	// verifiable (a test, a command, an inspection).
	AcceptanceCriteria []string `yaml:"acceptance_criteria" json:"acceptance_criteria"`

	// OutOfScope explicitly enumerates things the task does NOT cover.
	OutOfScope []string `yaml:"out_of_scope,omitempty" json:"out_of_scope,omitempty"`

	// Steps is the structured plan, broken down by the agent (or user).
	Steps []Step `yaml:"steps,omitempty" json:"steps,omitempty"`

	// Dependencies lists task IDs that must be done before this task can
	// proceed.
	Dependencies []ID `yaml:"dependencies,omitempty" json:"dependencies,omitempty"`

	// RequiredCredentials lists vault credentials the task will need.
	RequiredCredentials []string `yaml:"required_credentials,omitempty" json:"required_credentials,omitempty"`

	// AssignedTo is the agent ID currently working this task, if any.
	AssignedTo string `yaml:"assigned_to,omitempty" json:"assigned_to,omitempty"`

	// CreatedAt is when the task was created.
	CreatedAt time.Time `yaml:"created_at" json:"created_at"`

	// CreatedBy identifies the creator ("user" or "agent:<id>").
	CreatedBy string `yaml:"created_by" json:"created_by"`

	// UpdatedAt is the last modification timestamp.
	UpdatedAt time.Time `yaml:"updated_at" json:"updated_at"`

	// Progress is the structured progress log. See ProgressEntry.
	Progress []ProgressEntry `yaml:"progress,omitempty" json:"progress,omitempty"`
}

// ProgressEntry is a single entry in the task's progress log.
//
// The agent MUST call LogProgress after every meaningful action. The log is
// the recovery point — if context is lost or the agent crashes, the next
// agent reads this log to resume.
type ProgressEntry struct {
	// Timestamp is when the entry was logged.
	Timestamp time.Time `yaml:"timestamp" json:"timestamp"`

	// Status is the task status at the time of the entry.
	Status Status `yaml:"status" json:"status"`

	// Entry is the human-readable description of what happened.
	Entry string `yaml:"entry" json:"entry"`

	// ActionsTaken is a list of tool invocations or significant events.
	ActionsTaken []string `yaml:"actions_taken,omitempty" json:"actions_taken,omitempty"`

	// Blocker describes what is blocking progress, if Status is blocked.
	Blocker *Blocker `yaml:"blocker,omitempty" json:"blocker,omitempty"`

	// Resolution describes how a blocker was resolved.
	Resolution string `yaml:"resolution,omitempty" json:"resolution,omitempty"`

	// NextStep describes what the agent plans to do next.
	NextStep string `yaml:"next_step,omitempty" json:"next_step,omitempty"`

	// Caller identifies who logged the entry (e.g. "agent:auth-fix").
	Caller string `yaml:"caller" json:"caller"`
}

// Blocker describes a state where the task cannot proceed without external
// input.
type Blocker struct {
	// Description is what's blocking progress.
	Description string `yaml:"description" json:"description"`

	// Question is what to ask the user (if any).
	Question string `yaml:"question,omitempty" json:"question,omitempty"`

	// Options are the choices the user can pick from (if structured).
	Options []string `yaml:"options,omitempty" json:"options,omitempty"`

	// Awaiting is who/what is needed to unblock ("user", "external system").
	Awaiting string `yaml:"awaiting" json:"awaiting"`
}

// IsTerminal reports whether the status is a terminal state (done or
// abandoned). Tasks in terminal states should not be moved back to active
// states without explicit user override.
func (s Status) IsTerminal() bool {
	return s == StatusDone || s == StatusAbandoned
}

// IsActive reports whether the status represents active work.
func (s Status) IsActive() bool {
	return s == StatusInProgress || s == StatusPlanned
}

// Valid reports whether the status is one of the defined values.
func (s Status) Valid() bool {
	switch s {
	case StatusDraft, StatusOpen, StatusPlanned,
		StatusInProgress, StatusBlocked, StatusReview,
		StatusDone, StatusAbandoned:
		return true
	}
	return false
}

// ListOptions filters task queries.
type ListOptions struct {
	// Project filters to tasks in a specific project. Empty = all.
	Project string

	// Status filters to a specific status. Empty = all.
	Status Status

	// AssignedTo filters to tasks assigned to a specific agent. Empty = all.
	AssignedTo string

	// Tags filters to tasks with all of the specified tags. Empty = no filter.
	Tags []string

	// Limit caps the number of results. Zero = no limit.
	Limit int
}

// Store is the interface for task persistence.
//
// Implementations live under internal/task/ (e.g. filestore for the YAML
// file-backed implementation).
//
// All methods are safe for concurrent use.
type Store interface {
	// Create persists a new task. The Task's ID must be unique; if not,
	// returns ErrAlreadyExists.
	Create(task *Task) error

	// Get returns the task by ID. Returns ErrNotFound if absent.
	Get(id ID) (*Task, error)

	// List returns tasks matching opts, ordered by UpdatedAt descending.
	List(opts ListOptions) ([]*Task, error)

	// Update replaces the task at id. The caller is responsible for
	// preserving fields they don't want to change. Use LogProgress for
	// appending progress entries.
	Update(task *Task) error

	// Delete removes the task. Returns ErrNotFound if absent.
	Delete(id ID) error

	// LogProgress appends an entry to the task's progress log and bumps
	// UpdatedAt. Use this for every meaningful action the agent takes.
	LogProgress(id ID, entry ProgressEntry) error

	// Assign sets the AssignedTo field on the task. Pass empty string to
	// unassign.
	Assign(id ID, agentID string) error

	// SetStatus transitions the task to a new status. Returns ErrInvalid
	// for invalid transitions.
	SetStatus(id ID, status Status) error

	// CheckAcceptance verifies all acceptance criteria are marked
	// satisfied. Returns ErrInvalid if any are not.
	CheckAcceptance(id ID, satisfied []bool) error

	// AddStep adds a step to the task's plan.
	AddStep(id ID, step Step) error

	// UpdateStep modifies a step in place.
	UpdateStep(id ID, step Step) error
}

// Mutation is a functional update passed to Store.Mutate. It receives the
// current task and may modify it in place.
type Mutation func(*Task)

// Mutate applies a series of mutations atomically. Convenience over Update +
// error checking. Implementations may optimize by holding a lock for the
// duration of all mutations.
type Mutator interface {
	Mutate(id ID, fns ...Mutation) error
}

// NewID returns a fresh task ID. Format: "T-YYYY-MM-DD-NNNN-<project>"
// where NNNN is a random 4-digit suffix. The project suffix is optional
// (empty if no project). Note: callers should verify uniqueness via the
// Store; this is for convenience only.
func NewID(projectID string) ID {
	now := time.Now().UTC()
	suffix := now.Format("150405") // HHMMSS
	if projectID != "" {
		return ID(fmt.Sprintf("T-%s-%s-%s", now.Format("2006-01-02"), suffix, projectID))
	}
	return ID(fmt.Sprintf("T-%s-%s", now.Format("2006-01-02"), suffix))
}