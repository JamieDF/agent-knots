// Package errs defines sentinel errors and helpers used across harness.
//
// Sentinel errors are returned by interfaces so callers can use errors.Is to
// branch on specific failure modes without coupling to concrete error types
// from upstream packages.
package errs

import (
	"errors"
	"fmt"
)

// Sentinel errors returned by harness interfaces. Callers should compare
// with errors.Is.
var (
	// ErrNotFound indicates a resource does not exist.
	ErrNotFound = errors.New("not found")

	// ErrAlreadyExists indicates an attempt to create a resource that already
	// exists.
	ErrAlreadyExists = errors.New("already exists")

	// ErrInvalid indicates a request failed validation.
	ErrInvalid = errors.New("invalid")

	// ErrUnauthorized indicates the vault is locked or credentials are wrong.
	ErrUnauthorized = errors.New("unauthorized")

	// ErrUnavailable indicates the requested runtime is not available (e.g.
	// Podman not installed).
	ErrUnavailable = errors.New("unavailable")

	// ErrTimeout indicates a deadline was exceeded.
	ErrTimeout = errors.New("timeout")

	// ErrCanceled indicates the operation was canceled by the caller.
	ErrCanceled = errors.New("canceled")

	// ErrUnsupported indicates the operation is not supported by the
	// implementation.
	ErrUnsupported = errors.New("unsupported")
)

// Wrap returns an error wrapping err with a formatted message. Use this
// everywhere instead of fmt.Errorf without %w so errors.Is continues to work
// against sentinels.
func Wrap(err error, format string, args ...any) error {
	if err == nil {
		return nil
	}
	return fmt.Errorf("%s: %w", fmt.Sprintf(format, args...), err)
}

// Is is a thin alias for errors.Is. Provided so callers can write errs.Is(err,
// errs.ErrFoo) without importing "errors" everywhere.
func Is(err, target error) bool {
	return errors.Is(err, target)
}