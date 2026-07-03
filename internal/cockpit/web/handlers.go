package web

import (
	"encoding/json"
	"fmt"
	"html/template"
	"net/http"
	"os"
	"path/filepath"
	"strings"
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

// handleIndex renders the agent list page.
func (s *Server) handleIndex(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" {
		http.NotFound(w, r)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	fmt.Fprint(w, indexHTML)
}

// handleAgentPage renders the single-agent detail page with SSE client.
func (s *Server) handleAgentPage(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	tmpl := template.Must(template.New("agent").Parse(agentHTML))
	if err := tmpl.Execute(w, map[string]string{"ID": id}); err != nil {
		http.Error(w, "render error", http.StatusInternalServerError)
	}
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
		modeBadge := modeBadgeHTML(info.Mode)
		actionIcon, actionText := actionInfo(info)
		tokenStr := formatTokens(info.Tokens)
		if tokenStr == "—" {
			tokenStr = "0"
		}
		costStr := fmt.Sprintf("$%.3f", info.Cost)
		if info.Cost == 0 {
			costStr = "$0.000"
		}

		fmt.Fprintf(w, `<a href="/agent/%s" class="card" data-tokens="%d" data-cost="%.6f">
	<div class="card-row">
		<div style="display:flex;align-items:center;gap:8px">
			<span class="dot %s"></span>
			<span class="card-id">%s</span>
		</div>
		<span class="badge %s">%s</span>
	</div>
	<div class="card-meta">
		<span>Status<span class="val">%s</span></span>
		<span>Uptime<span class="val mono">%s</span></span>
		<span>Tokens<span class="val mono">%s</span></span>
		<span>Cost<span class="val mono">%s</span></span>
	</div>
	<div class="card-action">%s %s</div>
</a>
`, info.ID, info.Tokens, info.Cost,
			statusClass, info.ID,
			modeBadge, info.Mode,
			info.Status, info.StartedAgo, tokenStr, costStr,
			actionIcon, actionText)
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

// modeBadgeHTML returns badge HTML for a mode.
func modeBadgeHTML(mode string) string {
	switch mode {
	case "agent":
		return "badge-agent"
	case "assistant":
		return "badge-assistant"
	default:
		return "badge-stopped"
	}
}

// actionIcon returns the icon HTML for the last action.
func actionInfo(info sessionInfo) (string, string) {
	if !info.Alive {
		return "&#9679;", "stopped"
	}
	switch info.Status {
	case "blocked":
		return "&#9888;", "needs input"
	case "running", "starting":
		return "&#9679;", "running"
	default:
		return "&#9679;", info.Status
	}
}

// formatEventHTML renders a driver.Event as an HTML fragment for SSE.
func formatEventHTML(ev driver.Event) template.HTML {
	ts := ev.Timestamp.Format("15:04:05")
	icon := "&#9679;"
	cssClass := "event-message"
	msg := ev.Message

	switch ev.Type {
	case driver.EventThinking:
		icon = "&#9670;"
		cssClass = "event-thinking"
	case driver.EventToolCall:
		icon = "&#9881;"
		cssClass = "event-tool"
		if ev.ToolCall != nil {
			msg = fmt.Sprintf(`<span class="tool-name">%s</span> %s`, ev.ToolCall.Name, formatArgs(ev.ToolCall.Args))
		}
	case driver.EventToolResult:
		icon = "&#10003;"
		cssClass = "event-tool"
	case driver.EventError:
		icon = "&#9888;"
		cssClass = "event-error"
		if ev.Error != "" {
			msg = ev.Error
		}
	case driver.EventStateChange:
		icon = "&#9889;"
		cssClass = "event-state"
	case driver.EventProgress:
		icon = "&#9776;"
		cssClass = "event-progress"
	}

	if msg == "" && ev.Type == driver.EventMessage {
		msg = ev.Message
	}
	if msg == "" && ev.Type != driver.EventToolCall && ev.Type != driver.EventToolResult {
		msg = string(ev.Type)
	}

	return template.HTML(fmt.Sprintf(
		`<span class="ts">%s</span><span class="icon %s">%s</span><span class="content %s">%s</span>`,
		ts, cssClass, icon, cssClass, msg,
	))
}

// formatArgs formats tool call arguments as a compact string.
func formatArgs(args map[string]any) string {
	if len(args) == 0 {
		return ""
	}
	parts := make([]string, 0, len(args))
	for k, v := range args {
		var s string
		switch val := v.(type) {
		case string:
			if len(val) > 40 {
				val = val[:37] + "..."
			}
			s = val
		case float64:
			s = fmt.Sprintf("%v", val)
		default:
			s = fmt.Sprintf("%v", val)
		}
		parts = append(parts, fmt.Sprintf("%s=%s", k, s))
	}
	return strings.Join(parts, ", ")
}
