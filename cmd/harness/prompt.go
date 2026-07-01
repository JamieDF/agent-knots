package main

import (
	"fmt"
	"strings"

	"github.com/harness/harness/internal/task"
)

// buildTaskPrompt constructs a structured prompt from a task for sending to
// an agent.
func buildTaskPrompt(t *task.Task) string {
	var sb strings.Builder
	sb.WriteString(fmt.Sprintf("# Task: %s\n\n", t.Title))
	if t.Description != "" {
		sb.WriteString(t.Description)
		sb.WriteString("\n\n")
	}
	if len(t.AcceptanceCriteria) > 0 {
		sb.WriteString("## Acceptance criteria\n")
		for i, c := range t.AcceptanceCriteria {
			sb.WriteString(fmt.Sprintf("%d. %s\n", i+1, c))
		}
		sb.WriteString("\n")
	}
	if len(t.OutOfScope) > 0 {
		sb.WriteString("## Out of scope\n")
		for _, c := range t.OutOfScope {
			sb.WriteString(fmt.Sprintf("- %s\n", c))
		}
		sb.WriteString("\n")
	}
	if len(t.Steps) > 0 {
		sb.WriteString("## Plan\n")
		for _, s := range t.Steps {
			marker := "[ ]"
			if s.Status == task.StatusDone {
				marker = "[x]"
			}
			sb.WriteString(fmt.Sprintf("- %s %s\n", marker, s.Title))
		}
		sb.WriteString("\n")
	}
	sb.WriteString("Work the task to spec. Use task_log_progress after every meaningful action.\n")
	return sb.String()
}
