package web

import (
	"encoding/json"
	"fmt"
	"html/template"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"gopkg.in/yaml.v3"

	"github.com/JamieDF/agentjam/internal/agent/driver"
	"github.com/JamieDF/agentjam/internal/session"
	"github.com/JamieDF/agentjam/internal/session/live"
)

// sessionInfo combines live session liveness with YAML metadata.
type sessionInfo struct {
	ID         string
	Mode       string
	Task       string
	Status     string
	Alive      bool
	Tokens     int64
	Cost       float64
	StartedAgo string
}

// loadSessionInfo reads the session YAML and checks liveness.
func (s *Server) loadSessionInfo(ls *live.Session) sessionInfo {
	info := sessionInfo{
		ID:     ls.SessionID,
		Alive:  ls.IsAlive(),
		Status: "stopped",
	}

	// Read YAML metadata.
	yamlPath := filepath.Join(s.sessionsDir, ls.SessionID+".yaml")
	if data, err := os.ReadFile(yamlPath); err == nil {
		var sess session.Session
		if yaml.Unmarshal(data, &sess) == nil {
			info.Mode = string(sess.Mode)
			info.Task = sess.Task
			info.Tokens = sess.TokensUsed
			info.Cost = sess.CostUSD
			if info.Alive {
				info.Status = string(sess.Status)
				if info.Status == "" {
					info.Status = "running"
				}
			}
			if !sess.StartedAt.IsZero() {
				info.StartedAgo = formatDuration(time.Since(sess.StartedAt))
			}
		}
	}

	if !info.Alive {
		info.Status = "stopped"
	}

	return info
}

// handleIndex renders the cockpit SPA. The SPA handles routing internally via hash fragments.
func (s *Server) handleIndex(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	fmt.Fprint(w, cockpitHTML)
}

// handleAgentPage renders the cockpit SPA. The SPA handles routing internally via hash fragments.
func (s *Server) handleAgentPage(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	fmt.Fprint(w, cockpitHTML)
}

// handleAgentsFragment returns an HTML fragment of agent cards for HTMX.
func (s *Server) handleAgentsFragment(w http.ResponseWriter, r *http.Request) {
	sessions, err := live.List(s.sessionsDir)
	if err != nil {
		http.Error(w, "failed to list sessions", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "text/html; charset=utf-8")

	if len(sessions) == 0 {
		fmt.Fprint(w, `<div style="text-align:center;padding:60px 0;color:var(--muted)">
			<p style="font-size:18px;margin-bottom:8px">No active agents</p>
			<p style="margin-bottom:12px">Start one:</p>
			<code style="font:12px 'DM Mono',monospace;background:var(--surface);padding:8px 14px;border-radius:6px;display:inline-block;color:var(--fg-soft)">agentjam session start --driver mock --detach</code>
		</div>`)
		return
	}

	for _, ls := range sessions {
		info := s.loadSessionInfo(ls)
		statusClass := statusDotClass(info.Status)
		modeClass := modePillClass(info.Mode)
		modeLabel := info.Mode
		if modeLabel == "" {
			modeLabel = "agent"
		}
		tokenStr := formatTokens(info.Tokens)
		if tokenStr == "—" {
			tokenStr = "0"
		}
		costStr := fmt.Sprintf("$%.3f", info.Cost)
		if info.Cost == 0 {
			costStr = "$0.000"
		}

		fmt.Fprintf(w, `<div class="agent-card" onclick="location.href='#agent/%s'" data-tokens="%d" data-cost="%.6f">
	<div class="agent-card-head">
		<div class="agent-card-id">
			<span class="status-pip %s"></span>
			%s
		</div>
		<span class="mode-pill %s"><span class="pill-dot"></span>%s</span>
	</div>
	<div class="agent-card-meta">
		<span>Status<span class="val">%s</span></span>
		<span>Uptime<span class="val">%s</span></span>
		<span>Tokens<span class="val">%s</span></span>
		<span>Cost<span class="val">%s</span></span>
	</div>
	<div class="agent-card-action">%s</div>
</div>
`, info.ID, info.Tokens, info.Cost,
			statusClass, info.ID,
			modeClass, modeLabel,
			info.Status, info.StartedAgo, tokenStr, costStr,
			statusText(info))
	}
}

// handleControlAction returns an http.HandlerFunc that sends a control
// command (set-mode, send) to a session.
func (s *Server) handleControlAction(action, value string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id")
		ls, err := live.Get(s.sessionsDir, id)
		if err != nil {
			http.Error(w, "session not found", http.StatusNotFound)
			return
		}

		ctrl, err := ls.Control()
		if err != nil {
			http.Error(w, "cannot connect to session", http.StatusInternalServerError)
			return
		}
		defer ctrl.Close()

		switch action {
		case "set-mode":
			if err := ctrl.SetMode(value); err != nil {
				http.Error(w, err.Error(), http.StatusInternalServerError)
				return
			}
		}
		w.WriteHeader(http.StatusOK)
	}
}

// handleSend delivers a user message to the agent.
func (s *Server) handleSend(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	ls, err := live.Get(s.sessionsDir, id)
	if err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}

	msg := r.PostFormValue("message")
	if msg == "" {
		// Also accept JSON body.
		var body struct {
			Message string `json:"message"`
		}
		if json.NewDecoder(r.Body).Decode(&body) == nil {
			msg = body.Message
		}
	}
	if msg == "" {
		http.Error(w, "message required", http.StatusBadRequest)
		return
	}

	ctrl, err := ls.Control()
	if err != nil {
		http.Error(w, "cannot connect to session", http.StatusInternalServerError)
		return
	}
	defer ctrl.Close()

	if err := ctrl.Send(msg); err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	w.WriteHeader(http.StatusOK)
}

// handleLoginPage renders the token-entry form.
func (s *Server) handleLoginPage(w http.ResponseWriter, r *http.Request) {
	returnURL := r.URL.Query().Get("return")
	if returnURL == "" {
		returnURL = "/"
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	tmpl := template.Must(template.New("login").Parse(loginHTML))
	tmpl.Execute(w, map[string]string{"Return": returnURL})
}

// handleLoginPost validates the submitted token and sets a cookie.
func (s *Server) handleLoginPost(w http.ResponseWriter, r *http.Request) {
	tok := r.PostFormValue("token")
	returnURL := r.PostFormValue("return")
	if returnURL == "" {
		returnURL = "/"
	}

	if !subtleEqual(tok, s.token) {
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.WriteHeader(http.StatusUnauthorized)
		fmt.Fprint(w, `<article><p>Invalid token. <a href="/login?return=/', '">Try again</a></p></article>`)
		return
	}

	s.setAuthCookie(w)
	http.Redirect(w, r, returnURL, http.StatusSeeOther)
}

// --- Helpers ---

// formatDuration returns a human-readable duration string.
func formatDuration(d time.Duration) string {
	if d < time.Minute {
		return fmt.Sprintf("%ds", int(d.Seconds()))
	}
	if d < time.Hour {
		return fmt.Sprintf("%dm", int(d.Minutes()))
	}
	return fmt.Sprintf("%dh%dm", int(d.Hours()), int(d.Minutes())%60)
}

// formatTokens formats large token counts with commas.
func formatTokens(n int64) string {
	if n == 0 {
		return "—"
	}
	if n < 1000 {
		return fmt.Sprintf("%d", n)
	}
	return fmt.Sprintf("%.1fk", float64(n)/1000)
}

// statusDotClass returns the CSS class for a status dot.
func statusDotClass(status string) string {
	switch status {
	case "running", "starting":
		return "dot-running"
	case "blocked":
		return "dot-blocked"
	case "paused", "assumed":
		return "dot-assumed"
	case "stopped", "error":
		return "dot-stopped"
	default:
		return "dot-stopped"
	}
}

// modePillClass returns the CSS class for the mode pill.
func modePillClass(mode string) string {
	switch mode {
	case "assistant":
		return "assumed"
	default:
		return ""
	}
}

// statusText returns a human-readable status description.
func statusText(info sessionInfo) string {
	if !info.Alive {
		return "stopped"
	}
	switch info.Status {
	case "blocked":
		return "needs input"
	case "running", "starting":
		return "active"
	default:
		return info.Status
	}
}

// formatEventHTML renders a driver.Event as an HTML fragment matching the mockup style.
// Events are rendered as prose rows (messages, thinking, state changes) or
// tool cards (read_file, edit_file, bash, etc.).
func formatEventHTML(ev driver.Event) template.HTML {
	ts := ev.Timestamp.Format("15:04:05")

	switch ev.Type {
	case driver.EventThinking:
		return template.HTML(fmt.Sprintf(
			`<div class="prose-row prose-thinking"><div class="prose-avatar thinking">T</div><div class="prose-content"><div class="prose-thinking-text">%s</div></div><div class="prose-ts">%s</div></div>`,
			template.HTMLEscapeString(ev.Message), ts))

	case driver.EventMessage:
		return template.HTML(fmt.Sprintf(
			`<div class="prose-row"><div class="prose-avatar agent">A</div><div class="prose-content"><div class="prose-text">%s</div></div><div class="prose-ts">%s</div></div>`,
			template.HTMLEscapeString(ev.Message), ts))

	case driver.EventStateChange:
		return template.HTML(fmt.Sprintf(
			`<div class="prose-row"><div class="prose-avatar thinking">⚡</div><div class="prose-content"><div class="prose-text">%s</div></div><div class="prose-ts">%s</div></div>`,
			template.HTMLEscapeString(ev.Message), ts))

	case driver.EventToolCall:
		if ev.ToolCall != nil {
			toolIcon, toolClass := toolIconClass(ev.ToolCall.Name)
			args := formatToolArgs(ev.ToolCall.Args)
			return template.HTML(fmt.Sprintf(
				`<div class="tool-card"><div class="tool-card-head"><div class="tool-icon %s">%s</div><div class="tool-label">%s <span class="tool-sub">%s</span></div><div class="tool-ts">%s</div></div></div>`,
				toolClass, toolIcon, ev.ToolCall.Name, args, ts))
		}
		return template.HTML(fmt.Sprintf(
			`<div class="prose-row"><div class="prose-content"><div class="prose-text">Tool call</div></div><div class="prose-ts">%s</div></div>`, ts))

	case driver.EventToolResult:
		return template.HTML(fmt.Sprintf(
			`<div class="prose-row"><div class="prose-avatar" style="color:var(--running);background:oklch(72%% 0.16 155 / 0.15);border:1px solid oklch(72%% 0.16 155 / 0.3);font-size:11px">✓</div><div class="prose-content"><div class="prose-text">Tool result</div></div><div class="prose-ts">%s</div></div>`, ts))

	case driver.EventError:
		errMsg := ev.Error
		if errMsg == "" {
			errMsg = ev.Message
		}
		return template.HTML(fmt.Sprintf(
			`<div class="prose-row"><div class="prose-avatar" style="color:oklch(65%% 0.16 20);background:oklch(65%% 0.16 20 / 0.12);border:1px solid oklch(65%% 0.16 20 / 0.25)">!</div><div class="prose-content"><div class="prose-text" style="color:oklch(65%% 0.16 20)">%s</div></div><div class="prose-ts">%s</div></div>`,
			template.HTMLEscapeString(errMsg), ts))

	case driver.EventProgress:
		return template.HTML(fmt.Sprintf(
			`<div class="prose-row"><div class="prose-content"><div class="prose-text" style="color:var(--muted);font-size:12px">%s</div></div><div class="prose-ts">%s</div></div>`,
			template.HTMLEscapeString(ev.Message), ts))

	default:
		msg := ev.Message
		if msg == "" {
			msg = string(ev.Type)
		}
		return template.HTML(fmt.Sprintf(
			`<div class="prose-row"><div class="prose-content"><div class="prose-text" style="color:var(--muted)">%s</div></div><div class="prose-ts">%s</div></div>`,
			template.HTMLEscapeString(msg), ts))
	}
}

// toolIconClass returns the icon letter and CSS class for a tool name.
func toolIconClass(name string) (string, string) {
	switch name {
	case "read_file", "read":
		return "R", "read"
	case "edit_file", "edit", "write_file", "write":
		return "E", "edit"
	case "bash", "shell", "run":
		return "⌘", "run"
	default:
		return "●", "other"
	}
}

// formatToolArgs formats tool call arguments for display.
func formatToolArgs(args map[string]any) string {
	if len(args) == 0 {
		return ""
	}
	var first string
	for _, v := range args {
		s := fmt.Sprintf("%v", v)
		if len(s) > 60 {
			s = s[:57] + "..."
		}
		first = s
		break
	}
	return "— " + first
}
