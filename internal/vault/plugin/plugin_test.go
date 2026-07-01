package plugin

import (
	"context"
	"testing"

	"github.com/JamieDF/agentjam/internal/errs"
)

func TestLoader_Register(t *testing.T) {
	l := NewLoader()
	p := &ExampleAWSSSOPlugin{}
	if err := l.Register(p); err != nil {
		t.Fatal(err)
	}
	if !contains(l.List(), "aws-sso") {
		t.Error("plugin not in list")
	}
}

func TestLoader_RegisterNil(t *testing.T) {
	l := NewLoader()
	if err := l.Register(nil); !errs.Is(err, errs.ErrInvalid) {
		t.Errorf("expected ErrInvalid, got %v", err)
	}
}

func TestLoader_RegisterDuplicate(t *testing.T) {
	l := NewLoader()
	p := &ExampleAWSSSOPlugin{}
	_ = l.Register(p)
	err := l.Register(p)
	if !errs.Is(err, errs.ErrAlreadyExists) {
		t.Errorf("expected ErrAlreadyExists, got %v", err)
	}
}

func TestLoader_Get(t *testing.T) {
	l := NewLoader()
	_ = l.Register(&ExampleAWSSSOPlugin{})

	p, err := l.Get("aws-sso")
	if err != nil {
		t.Fatal(err)
	}
	if p.Name() != "aws-sso" {
		t.Errorf("Name = %q", p.Name())
	}
}

func TestLoader_GetNotFound(t *testing.T) {
	l := NewLoader()
	_, err := l.Get("nonexistent")
	if !errs.Is(err, errs.ErrNotFound) {
		t.Errorf("expected ErrNotFound, got %v", err)
	}
}

func TestLoader_Multiple(t *testing.T) {
	l := NewLoader()
	_ = l.Register(&ExampleAWSSSOPlugin{})
	_ = l.Register(&ExampleJWTSignerPlugin{})

	got := l.List()
	if len(got) != 2 {
		t.Errorf("got %d plugins, want 2", len(got))
	}
}

func TestExampleAWSSSOPlugin_Inject(t *testing.T) {
	p := &ExampleAWSSSOPlugin{}
	res, err := p.Inject(context.Background(), InjectRequest{
		Value: "long-lived-refresh-token",
		Args:  map[string]string{"profile": "prod"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if res.Env["AWS_PROFILE"] != "prod" {
		t.Errorf("AWS_PROFILE = %q", res.Env["AWS_PROFILE"])
	}
	if res.Env["AWS_SSO_TOKEN_FROM_VAULT"] == "" {
		t.Error("expected AWS_SSO_TOKEN_FROM_VAULT to be set")
	}
}

func TestExampleJWTSignerPlugin_Inject(t *testing.T) {
	p := &ExampleJWTSignerPlugin{}
	res, err := p.Inject(context.Background(), InjectRequest{
		Value: "private-key-content",
		Args: map[string]string{
			"subject":  "[email protected]",
			"audience": "my-api",
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if res.Env["JWT_SUBJECT"] != "[email protected]" {
		t.Errorf("JWT_SUBJECT = %q", res.Env["JWT_SUBJECT"])
	}
	if res.Env["JWT_AUDIENCE"] != "my-api" {
		t.Errorf("JWT_AUDIENCE = %q", res.Env["JWT_AUDIENCE"])
	}
}

func TestMustRegister(t *testing.T) {
	defer func() {
		if r := recover(); r == nil {
			t.Error("expected panic for nil plugin")
		}
	}()
	l := NewLoader()
	l.MustRegister(nil)
}

func TestMustRegister_DuplicatePanics(t *testing.T) {
	defer func() {
		if r := recover(); r == nil {
			t.Error("expected panic for duplicate")
		}
	}()
	l := NewLoader()
	p := &ExampleAWSSSOPlugin{}
	l.MustRegister(p)
	l.MustRegister(p)
}

func contains(haystack []string, needle string) bool {
	for _, s := range haystack {
		if s == needle {
			return true
		}
	}
	return false
}