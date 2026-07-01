// Package vault_test demonstrates end-to-end use of the vault with the file
// store. These examples show up in godoc and pkg.go.dev.
package vault_test

import (
	"context"
	"fmt"
	"log"
	"os"
	"path/filepath"

	"github.com/JamieDF/agentjam/internal/vault"
	"github.com/JamieDF/agentjam/internal/vault/filestore"
)

// ExampleFileStore_endToEnd shows the full lifecycle: create, unlock, add a
// credential with a template, use it, lock.
func ExampleFileStore_endToEnd() {
	dir, _ := os.MkdirTemp("", "vault-example-*")
	defer os.RemoveAll(dir)

	v, err := filestore.New(filepath.Join(dir, "vault"))
	if err != nil {
		log.Fatal(err)
	}

	ctx := context.Background()

	// Initialize.
	if err := v.Unlock(ctx, "my secret passphrase"); err != nil {
		log.Fatal(err)
	}

	// Add credential.
	if err := v.Add(ctx, vault.Credential{
		ID:    "github/work",
		Value: "ghp_secret",
		Tags:  []string{"github"},
	}); err != nil {
		log.Fatal(err)
	}

	// Add template.
	if err := v.SetTemplate(ctx, "github/work", vault.Template{
		Name:      "gh_cli_env",
		Injection: vault.Injection{Env: map[string]string{"GH_TOKEN": "$value"}},
	}); err != nil {
		log.Fatal(err)
	}

	// Use it.
	res, err := v.Use(ctx, vault.UseRequest{
		Credential: "github/work",
		Template:   "gh_cli_env",
		Command:    "echo",
		Args:       []string{"$GH_TOKEN"},
	}, "agent:example")
	if err != nil {
		log.Fatal(err)
	}
	fmt.Println("exit:", res.ExitCode)

	// Lock.
	if err := v.Lock(ctx); err != nil {
		log.Fatal(err)
	}

	// Output:
	// exit: 0
}

// ExampleTemplate_validate shows how to validate a Template before use.
func ExampleTemplate_validate() {
	tmpl := vault.Template{
		Name:      "jira_cli_env",
		Injection: vault.Injection{Env: map[string]string{"JIRA_API_TOKEN": "$value"}},
	}
	if err := tmpl.Validate(); err != nil {
		log.Fatal(err)
	}
	fmt.Println("valid")
	// Output: valid
}