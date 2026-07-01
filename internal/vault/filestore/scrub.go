package filestore

import (
	"strings"
)

// scrub removes any occurrence of secret from s. Used to ensure secret values
// never appear in command output that is logged or returned.
//
// The match is exact substring; for stronger guarantees, the vault could
// hash the secret once at unlock time and search for the hash instead, but
// exact-substring scrubbing catches the common case where a tool echoes the
// env var or stdin contents back.
func scrub(s, secret string) string {
	if secret == "" {
		return s
	}
	return strings.ReplaceAll(s, secret, "[REDACTED]")
}

// scrubMap applies scrub to every value in m, using the same secret.
func scrubMap(m map[string]string, secret string) map[string]string {
	if m == nil {
		return nil
	}
	out := make(map[string]string, len(m))
	for k, v := range m {
		out[k] = scrub(v, secret)
	}
	return out
}