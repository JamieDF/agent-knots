package web

import (
	"fmt"
	"net/http"
	"time"

	"github.com/JamieDF/agentjam/internal/session/live"
)

// handleSSE streams events from a session's event socket to the browser
// via Server-Sent Events. Each browser tab gets its own socket
// connection (live.Session.Events() opens a fresh connection).
func (s *Server) handleSSE(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")

	ls, err := live.Get(s.sessionsDir, id)
	if err != nil {
		http.Error(w, "session not found", http.StatusNotFound)
		return
	}

	events, err := ls.Events()
	if err != nil {
		http.Error(w, "cannot connect to session event stream", http.StatusInternalServerError)
		return
	}

	// SSE headers. Flush immediately so the browser knows the stream is open.
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache, no-transform")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no") // disable nginx buffering if proxied

	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming not supported", http.StatusInternalServerError)
		return
	}

	// Send initial comment to flush headers.
	fmt.Fprintf(w, ": connected\n\n")
	flusher.Flush()

	ctx := r.Context()
	ticker := time.NewTicker(15 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return

		case <-ticker.C:
			// Keep-alive comment (browsers close idle SSE after ~30s
			// on some proxies).
			fmt.Fprintf(w, ": keepalive\n\n")
			flusher.Flush()

		case ev, ok := <-events:
			if !ok {
				// Channel closed — session ended or socket disconnected.
				fmt.Fprintf(w, "event: close\ndata: session ended\n\n")
				flusher.Flush()
				return
			}
			html := formatEventHTML(ev)
			fmt.Fprintf(w, "data: %s\n\n", html)
			flusher.Flush()
		}
	}
}
