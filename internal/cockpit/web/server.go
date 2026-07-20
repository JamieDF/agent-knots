// Package web implements the web cockpit — the browser-accessible
// management surface for agentjam.
//
// The web cockpit binds to 127.0.0.1:<random-port> and serves an HTML
// UI with real-time event streaming via Server-Sent Events (SSE).
// Authentication is token-based: one token generated on first start,
// saved to ~/.agentjam/cockpit.token. The browser authenticates once
// and receives a cookie.
//
// Launch with: agentjam cockpit --web
package web

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// Server is the web cockpit HTTP server.
type Server struct {
	sessionsDir string
	tokenPath   string
	token       string
	srv         *http.Server
}

// New creates a web cockpit server. sessionsDir is where session
// .pid/.sock/.yaml files live. configDir is where the auth token is
// stored (typically ~/.agentjam).
func New(sessionsDir, configDir string) *Server {
	return &Server{
		sessionsDir: sessionsDir,
		tokenPath:   filepath.Join(configDir, "cockpit.token"),
	}
}

// ListenAndServe binds to 127.0.0.1:0 (random port) and starts serving.
// Returns the full URL (including token query param for one-click access).
func (s *Server) ListenAndServe() (string, error) {
	s.token = s.loadOrCreateToken()

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return "", fmt.Errorf("listen: %w", err)
	}

	s.srv = &http.Server{
		Handler:      s.authMiddleware(s.routes()),
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 0, // no write timeout — SSE keeps connections open
	}

	go func() {
		if err := s.srv.Serve(ln); err != nil && err != http.ErrServerClosed {
			log.Printf("cockpit web: serve error: %v", err)
		}
	}()

	addr := ln.Addr().String()
	return fmt.Sprintf("http://%s/?token=%s", addr, s.token), nil
}

// Shutdown gracefully stops the server.
func (s *Server) Shutdown(ctx context.Context) error {
	if s.srv == nil {
		return nil
	}
	return s.srv.Shutdown(ctx)
}

// routes returns the HTTP mux with all cockpit routes registered.
func (s *Server) routes() http.Handler {
	mux := http.NewServeMux()

	// Pages.
	mux.HandleFunc("GET /", s.handleIndex)
	mux.HandleFunc("GET /agent/{id}", s.handleAgentPage)
	mux.HandleFunc("GET /login", s.handleLoginPage)
	mux.HandleFunc("POST /login", s.handleLoginPost)

	// HTMX fragments.
	mux.HandleFunc("GET /api/agents", s.handleAgentsFragment)

	// SSE event stream.
	mux.HandleFunc("GET /api/agent/{id}/events", s.handleSSE)

	// Control actions.
	mux.HandleFunc("POST /api/agent/{id}/assume", s.handleControlAction("set-mode", "assistant"))
	mux.HandleFunc("POST /api/agent/{id}/relinquish", s.handleControlAction("set-mode", "agent"))
	mux.HandleFunc("POST /api/agent/{id}/send", s.handleSend)

	return mux
}

// authMiddleware validates the auth cookie or ?token= query param on
// every request. Login endpoints are exempt.
func (s *Server) authMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Login endpoints are always accessible.
		if r.URL.Path == "/login" {
			next.ServeHTTP(w, r)
			return
		}

		// Check ?token= query param (for CLI-launched one-click URLs).
		if q := r.URL.Query().Get("token"); q != "" {
			if subtleEqual(q, s.token) {
				s.setAuthCookie(w)
				// Redirect to same path without the token in the URL.
				http.Redirect(w, r, r.URL.Path, http.StatusSeeOther)
				return
			}
		}

		// Check cookie.
		cookie, err := r.Cookie("agentjam-session")
		if err != nil || !subtleEqual(cookie.Value, s.token) {
			// HTMX requests get 401 instead of redirect (so the
			// browser doesn't follow the redirect silently).
			if r.Header.Get("HX-Request") == "true" {
				http.Error(w, "Unauthorized", http.StatusUnauthorized)
				return
			}
			http.Redirect(w, r, "/login?return="+r.URL.RequestURI(), http.StatusSeeOther)
			return
		}

		next.ServeHTTP(w, r)
	})
}

func (s *Server) setAuthCookie(w http.ResponseWriter) {
	http.SetCookie(w, &http.Cookie{
		Name:     "agentjam-session",
		Value:    s.token,
		Path:     "/",
		HttpOnly: true,
		SameSite: http.SameSiteStrictMode,
		MaxAge:   86400 * 7, // 7 days
	})
}

// loadOrCreateToken loads the auth token from disk or generates a new one.
func (s *Server) loadOrCreateToken() string {
	if data, err := os.ReadFile(s.tokenPath); err == nil {
		tok := strings.TrimSpace(string(data))
		if tok != "" {
			return tok
		}
	}

	// Generate a 32-byte hex token (64 chars).
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		panic(fmt.Sprintf("cockpit web: generate token: %v", err))
	}
	tok := hex.EncodeToString(b)

	// Save with mode 0600.
	if err := os.WriteFile(s.tokenPath, []byte(tok), 0o600); err != nil {
		log.Printf("cockpit web: could not save token to %s: %v", s.tokenPath, err)
	}

	return tok
}

// subtleEqual does a constant-time string comparison.
func subtleEqual(a, b string) bool {
	if len(a) != len(b) {
		return false
	}
	var v byte
	for i := range a {
		v |= a[i] ^ b[i]
	}
	return v == 0
}
