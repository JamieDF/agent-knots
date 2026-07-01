package vault

import (
	"errors"
	"testing"

	"github.com/harness/harness/internal/errs"
)

func TestCredentialValidate(t *testing.T) {
	cases := []struct {
		name    string
		c       Credential
		wantErr bool
	}{
		{name: "valid", c: Credential{ID: "github/work"}, wantErr: false},
		{name: "empty id", c: Credential{ID: ""}, wantErr: true},
		{name: "whitespace id", c: Credential{ID: "   "}, wantErr: true},
		{name: "space in id", c: Credential{ID: "github work"}, wantErr: true},
		{name: "hierarchical id", c: Credential{ID: "github/work/sub"}, wantErr: false},
		{name: "backslashes", c: Credential{ID: `github\work`}, wantErr: true},
		{name: "double quote", c: Credential{ID: `github"work`}, wantErr: true},
		{name: "colon ok", c: Credential{ID: "aws:prod"}, wantErr: false},
		{name: "with description", c: Credential{ID: "x", Description: "ok"}, wantErr: false},
		{name: "tags ok", c: Credential{ID: "x", Tags: []string{"a", "b"}}, wantErr: false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			err := c.c.Validate()
			if c.wantErr && err == nil {
				t.Fatalf("expected error, got nil")
			}
			if !c.wantErr && err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
		})
	}
}

func TestInjectionValidate(t *testing.T) {
	cases := []struct {
		name    string
		inj     Injection
		wantErr bool
	}{
		{name: "env ok", inj: Injection{Env: map[string]string{"K": "v"}}, wantErr: false},
		{name: "file ok", inj: Injection{File: &FileInjection{}}, wantErr: false},
		{name: "ssh ok", inj: Injection{SSHKey: &FileInjection{}}, wantErr: false},
		{name: "stdin ok", inj: Injection{Stdin: &StdinInjection{}}, wantErr: false},
		{name: "wrapper ok", inj: Injection{CommandWrapper: &WrapperInjection{Template: "x {original}"}}, wantErr: false},
		{name: "wrapper missing {original}", inj: Injection{CommandWrapper: &WrapperInjection{Template: "no placeholder"}}, wantErr: true},
		{name: "plugin ok", inj: Injection{Plugin: &PluginInjection{URI: "plugin://x"}}, wantErr: false},
		{name: "no mode", inj: Injection{}, wantErr: true},
		{name: "two modes", inj: Injection{Env: map[string]string{"K": "v"}, Stdin: &StdinInjection{}}, wantErr: true},
		{name: "three modes", inj: Injection{Env: map[string]string{"K": "v"}, File: &FileInjection{}, Stdin: &StdinInjection{}}, wantErr: true},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			err := c.inj.validate()
			if c.wantErr && err == nil {
				t.Fatalf("expected error, got nil")
			}
			if !c.wantErr && err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
		})
	}
}

func TestInjectionMode(t *testing.T) {
	cases := []struct {
		inj  Injection
		want string
	}{
		{Injection{Env: map[string]string{"K": "v"}}, "env"},
		{Injection{File: &FileInjection{}}, "file"},
		{Injection{SSHKey: &FileInjection{}}, "ssh"},
		{Injection{Stdin: &StdinInjection{}}, "stdin"},
		{Injection{CommandWrapper: &WrapperInjection{Template: "x {original}"}}, "wrapper"},
		{Injection{Plugin: &PluginInjection{}}, "plugin"},
		{Injection{}, "none"},
	}
	for _, c := range cases {
		if got := c.inj.Mode(); got != c.want {
			t.Errorf("Mode() = %q, want %q", got, c.want)
		}
	}
}

func TestTemplateValidate(t *testing.T) {
	t.Run("valid", func(t *testing.T) {
		tmpl := Template{Name: "gh_cli_env", Injection: Injection{Env: map[string]string{"GH_TOKEN": "$value"}}}
		if err := tmpl.Validate(); err != nil {
			t.Fatal(err)
		}
	})
	t.Run("empty name", func(t *testing.T) {
		tmpl := Template{Injection: Injection{Env: map[string]string{"K": "v"}}}
		if err := tmpl.Validate(); err == nil {
			t.Fatal("expected error")
		} else if !errors.Is(err, errs.ErrInvalid) {
			t.Errorf("expected ErrInvalid, got %v", err)
		}
	})
	t.Run("whitespace name", func(t *testing.T) {
		tmpl := Template{Name: "  ", Injection: Injection{Env: map[string]string{"K": "v"}}}
		if err := tmpl.Validate(); err == nil {
			t.Fatal("expected error")
		}
	})
	t.Run("missing injection", func(t *testing.T) {
		tmpl := Template{Name: "x"}
		if err := tmpl.Validate(); err == nil {
			t.Fatal("expected error")
		}
	})
}

func TestCredentialString(t *testing.T) {
	c := Credential{ID: "github/work", Tags: []string{"github"}, UsesTotal: 5}
	s := c.String()
	if s != `Credential{ID="github/work", Tags=[github], Uses=5}` {
		t.Errorf("String() = %q", s)
	}
}