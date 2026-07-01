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
		fmt.Fprint(w, `<p><em>No active agents. Start one with:</em></p>`)
		fmt.Fprint(w, `<pre><code>agentjam session start --driver mock --detach</code></pre>`)
		return
	}

	for _, ls := range sessions {
		info := s.loadSessionInfo(ls)
		fmt.Fprintf(w, `<details data-id="%s">
	<summary><strong>%s</strong> &nbsp;<mark>%s</mark> &nbsp;<small>%s</small></summary>
	<p>Mode: <code>%s</code> &middot; Tokens: %s &middot; Uptime: %s</p>
	<a href="/agent/%s" role="button">View &rarr;</a>
</details>
`, info.ID, info.ID, info.Status, info.StartedAgo, info.Mode,
			formatTokens(info.Tokens), info.StartedAgo, info.ID)
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

// formatEventHTML renders a driver.Event as an HTML fragment for SSE.
func formatEventHTML(ev driver.Event) template.HTML {
	ts := ev.Timestamp.Format("15:04:05")
	msg := ev.Message
	if msg == "" && ev.ToolCall != nil {
		args, _ := json.Marshal(ev.ToolCall.Args)
		msg = fmt.Sprintf("🔧 %s(%s)", ev.ToolCall.Name, string(args))
	}
	if msg == "" {
		msg = string(ev.Type)
	}
	return template.HTML(fmt.Sprintf(
		`<small>%s</small> &middot; <span>%s</span>`,
		template.HTMLEscapeString(ts),
		template.HTMLEscapeString(msg),
	))
}
