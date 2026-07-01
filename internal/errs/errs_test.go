package errs

import (
	"errors"
	"fmt"
	"testing"
)

func TestSentinels(t *testing.T) {
	for _, e := range []error{
		ErrNotFound,
		ErrAlreadyExists,
		ErrInvalid,
		ErrUnauthorized,
		ErrUnavailable,
		ErrTimeout,
		ErrCanceled,
		ErrUnsupported,
	} {
		if e == nil {
			t.Fatalf("sentinel is nil")
		}
		if e.Error() == "" {
			t.Fatalf("sentinel %v has empty message", e)
		}
	}
}

func TestWrap(t *testing.T) {
	base := ErrNotFound

	t.Run("nil error returns nil", func(t *testing.T) {
		if got := Wrap(nil, "ctx"); got != nil {
			t.Fatalf("Wrap(nil) = %v, want nil", got)
		}
	})

	t.Run("wraps with %w semantics", func(t *testing.T) {
		wrapped := Wrap(base, "loading %s", "user")
		if !errors.Is(wrapped, ErrNotFound) {
			t.Fatalf("errors.Is failed: %v", wrapped)
		}
		if got := wrapped.Error(); got != "loading user: not found" {
			t.Fatalf("unexpected message: %q", got)
		}
	})

	t.Run("chains with errors.Join style", func(t *testing.T) {
		wrapped := Wrap(fmt.Errorf("inner"), "outer")
		if !errors.Is(wrapped, wrapped) {
			t.Fatalf("not equal to itself")
		}
	})
}

// Example shows idiomatic use of errs.Wrap with errors.Is.
func ExampleWrap() {
	err := Wrap(ErrNotFound, "loading project %q", "my-app")
	if errors.Is(err, ErrNotFound) {
		fmt.Println("project does not exist")
	}
	// Output: project does not exist
}