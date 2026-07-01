package main

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"github.com/spf13/cobra"
	"golang.org/x/term"

	"github.com/JamieDF/agentjam/internal/config"
	"github.com/JamieDF/agentjam/internal/errs"
	"github.com/JamieDF/agentjam/internal/vault"
	"github.com/JamieDF/agentjam/internal/vault/filestore"
)

func vaultCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "vault",
		Short: "Manage credentials",
		Long: `The credential vault stores secrets encrypted at rest. Agents reference
credentials by opaque URIs (vault://id) and never see the raw value. To use
a credential, the agent asks the vault to inject it via a template.

This command is the user-facing admin interface.`,
	}

	cmd.AddCommand(
		vaultInitCmd(),
		vaultUnlockCmd(),
		vaultLockCmd(),
		vaultListCmd(),
		vaultAddCmd(),
		vaultRemoveCmd(),
		vaultShowCmd(),
		vaultTemplateCmd(),
		vaultAuditCmd(),
	)

	return cmd
}

func openVault() (*filestore.FileStore, error) {
	return filestore.New(config.VaultPath())
}

// promptPassphrase asks the user for a passphrase without echoing.
func promptPassphrase(prompt string) (string, error) {
	fmt.Fprint(os.Stderr, prompt)
	fd := int(os.Stdin.Fd())
	b, err := term.ReadPassword(fd)
	fmt.Fprintln(os.Stderr)
	if err != nil {
		return "", errs.Wrap(err, "read passphrase")
	}
	return string(b), nil
}

func promptSecret(prompt string) (string, error) {
	fmt.Fprint(os.Stderr, prompt)
	fd := int(os.Stdin.Fd())
	b, err := term.ReadPassword(fd)
	fmt.Fprintln(os.Stderr)
	if err != nil {
		return "", errs.Wrap(err, "read secret")
	}
	return string(b), nil
}

func vaultInitCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "init",
		Short: "Initialize a new vault",
		RunE: func(cmd *cobra.Command, _ []string) error {
			v, err := openVault()
			if err != nil {
				return err
			}
			state, err := v.LockState(cmd.Context())
			if err != nil {
				return err
			}
			if state != vault.Uninitialized {
				return errs.Wrap(errs.ErrAlreadyExists, "vault already exists; use `unlock` instead")
			}
			pass, err := promptPassphrase("Choose a passphrase: ")
			if err != nil {
				return err
			}
			confirm, err := promptPassphrase("Confirm passphrase: ")
			if err != nil {
				return err
			}
			if pass != confirm {
				return errs.Wrap(errs.ErrInvalid, "passphrases do not match")
			}
			if len(pass) < 8 {
				return errs.Wrap(errs.ErrInvalid, "passphrase must be at least 8 characters")
			}
			if err := v.Unlock(cmd.Context(), pass); err != nil {
				return err
			}
			fmt.Fprintln(cmd.OutOrStdout(), "Vault initialized.")
			return nil
		},
	}
}

func vaultUnlockCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "unlock",
		Short: "Unlock the vault",
		RunE: func(cmd *cobra.Command, _ []string) error {
			v, err := openVault()
			if err != nil {
				return err
			}
			pass, err := promptPassphrase("Passphrase: ")
			if err != nil {
				return err
			}
			if err := v.Unlock(cmd.Context(), pass); err != nil {
				return err
			}
			fmt.Fprintln(cmd.OutOrStdout(), "Vault unlocked.")
			return nil
		},
	}
}

func vaultLockCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "lock",
		Short: "Lock the vault",
		RunE: func(cmd *cobra.Command, _ []string) error {
			v, err := openVault()
			if err != nil {
				return err
			}
			if err := v.Lock(cmd.Context()); err != nil {
				return err
			}
			fmt.Fprintln(cmd.OutOrStdout(), "Vault locked.")
			return nil
		},
	}
}

func vaultListCmd() *cobra.Command {
	return &cobra.Command{
		Use:     "list",
		Short:   "List credentials",
		Aliases: []string{"ls"},
		RunE: func(cmd *cobra.Command, _ []string) error {
			v, err := openVault()
			if err != nil {
				return err
			}
			creds, err := v.List(cmd.Context())
			if err != nil {
				return err
			}
			if len(creds) == 0 {
				fmt.Fprintln(cmd.OutOrStdout(), "No credentials. Add one with `agentjam vault add`.")
				return nil
			}
			fmt.Fprintf(cmd.OutOrStdout(), "%-30s %-10s %-10s %s\n", "ID", "USES", "TAGS", "DESCRIPTION")
			for _, c := range creds {
				tags := strings.Join(c.Tags, ",")
				fmt.Fprintf(cmd.OutOrStdout(), "%-30s %-10d %-10s %s\n",
					c.ID, c.UsesTotal, tags, c.Description)
			}
			return nil
		},
	}
}

func vaultAddCmd() *cobra.Command {
	var (
		desc string
		tags []string
	)
	cmd := &cobra.Command{
		Use:   "add <id>",
		Short: "Add a credential",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			v, err := openVault()
			if err != nil {
				return err
			}
			if unlocked, _ := v.IsUnlocked(cmd.Context()); !unlocked {
				return errs.Wrap(errs.ErrUnauthorized, "vault is locked; run `agentjam vault unlock`")
			}
			value, err := promptSecret("Value: ")
			if err != nil {
				return err
			}
			c := vault.Credential{
				ID:          vault.ID(args[0]),
				Description: desc,
				Tags:        tags,
				Value:       value,
			}
			if err := v.Add(cmd.Context(), c); err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "Added credential %q.\n", c.ID)
			return nil
		},
	}
	cmd.Flags().StringVar(&desc, "description", "", "Credential description")
	cmd.Flags().StringSliceVar(&tags, "tag", nil, "Tag (repeatable)")
	return cmd
}

func vaultRemoveCmd() *cobra.Command {
	return &cobra.Command{
		Use:     "remove <id>",
		Short:   "Remove a credential",
		Aliases: []string{"rm"},
		Args:    cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			v, err := openVault()
			if err != nil {
				return err
			}
			if err := v.Remove(cmd.Context(), vault.ID(args[0])); err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "Removed %q.\n", args[0])
			return nil
		},
	}
}

func vaultShowCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "show <id>",
		Short: "Show credential metadata and templates",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			v, err := openVault()
			if err != nil {
				return err
			}
			c, err := v.Get(cmd.Context(), vault.ID(args[0]))
			if err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "ID:          %s\n", c.ID)
			fmt.Fprintf(cmd.OutOrStdout(), "Description: %s\n", c.Description)
			fmt.Fprintf(cmd.OutOrStdout(), "Created:     %s\n", c.CreatedAt.Format("2006-01-02 15:04"))
			fmt.Fprintf(cmd.OutOrStdout(), "Last Used:   %s\n", c.LastUsed.Format("2006-01-02 15:04"))
			fmt.Fprintf(cmd.OutOrStdout(), "Uses Total:  %d\n", c.UsesTotal)
			if len(c.Tags) > 0 {
				fmt.Fprintf(cmd.OutOrStdout(), "Tags:        %s\n", strings.Join(c.Tags, ", "))
			}
			tmpls, err := v.ListTemplates(cmd.Context(), c.ID)
			if err != nil {
				return err
			}
			if len(tmpls) > 0 {
				fmt.Fprintln(cmd.OutOrStdout(), "\nTemplates:")
				for _, t := range tmpls {
					fmt.Fprintf(cmd.OutOrStdout(), "  - %s (%s)\n", t.Name, t.Injection.Mode())
				}
			}
			return nil
		},
	}
}

func vaultTemplateCmd() *cobra.Command {
	cmd := &cobra.Command{
		Use:   "template",
		Short: "Manage injection templates",
	}
	cmd.AddCommand(
		vaultTemplateListCmd(),
		vaultTemplateAddCmd(),
		vaultTemplateRemoveCmd(),
	)
	return cmd
}

func vaultTemplateListCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "list <cred-id>",
		Short: "List templates for a credential",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			v, err := openVault()
			if err != nil {
				return err
			}
			tmpls, err := v.ListTemplates(cmd.Context(), vault.ID(args[0]))
			if err != nil {
				return err
			}
			for _, t := range tmpls {
				fmt.Fprintf(cmd.OutOrStdout(), "%s (%s)\n", t.Name, t.Injection.Mode())
			}
			return nil
		},
	}
}

func vaultTemplateAddCmd() *cobra.Command {
	var (
		name        string
		envJSON     string
		wrapperTmpl string
		filePath    string
		stdin       bool
	)
	cmd := &cobra.Command{
		Use:   "add <cred-id>",
		Short: "Add an injection template to a credential",
		Long: `Add an injection template. Exactly one injection mode must be specified:

  --env '{"KEY": "$value"}'                      env vars
  --wrapper 'curl -H "Auth: $value" {original}' command wrapper
  --file /tmp/secrets.txt                        write to file
  --stdin                                        pipe to stdin

Example:
  agentjam vault template add github/work \
    --name gh_cli_env \
    --env '{"GH_TOKEN": "$value"}'`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			v, err := openVault()
			if err != nil {
				return err
			}
			inj := vault.Injection{}
			modes := 0
			if envJSON != "" {
				var env map[string]string
				if err := json.Unmarshal([]byte(envJSON), &env); err != nil {
					return errs.Wrap(err, "parse --env JSON")
				}
				inj.Env = env
				modes++
			}
			if wrapperTmpl != "" {
				inj.CommandWrapper = &vault.WrapperInjection{Template: wrapperTmpl}
				modes++
			}
			if filePath != "" {
				inj.File = &vault.FileInjection{Path: filePath}
				modes++
			}
			if stdin {
				inj.Stdin = &vault.StdinInjection{TrailingNewline: true}
				modes++
			}
			if modes != 1 {
				return errs.Wrap(errs.ErrInvalid, "exactly one injection mode required")
			}
			tmpl := vault.Template{Name: name, Injection: inj}
			if err := v.SetTemplate(cmd.Context(), vault.ID(args[0]), tmpl); err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "Added template %q.\n", name)
			return nil
		},
	}
	cmd.Flags().StringVar(&name, "name", "", "Template name (required)")
	cmd.Flags().StringVar(&envJSON, "env", "", "Env injection as JSON")
	cmd.Flags().StringVar(&wrapperTmpl, "wrapper", "", "Command wrapper template")
	cmd.Flags().StringVar(&filePath, "file", "", "File injection path")
	cmd.Flags().BoolVar(&stdin, "stdin", false, "Stdin injection")
	_ = cmd.MarkFlagRequired("name")
	return cmd
}

func vaultTemplateRemoveCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "remove <cred-id> <template-name>",
		Short: "Remove a template",
		Args:  cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			v, err := openVault()
			if err != nil {
				return err
			}
			if err := v.RemoveTemplate(cmd.Context(), vault.ID(args[0]), args[1]); err != nil {
				return err
			}
			fmt.Fprintln(cmd.OutOrStdout(), "Removed.")
			return nil
		},
	}
}

func vaultAuditCmd() *cobra.Command {
	var (
		cred  string
		limit int
	)
	return &cobra.Command{
		Use:   "audit",
		Short: "Show audit log",
		RunE: func(cmd *cobra.Command, _ []string) error {
			v, err := openVault()
			if err != nil {
				return err
			}
			entries, err := v.AuditLog(cmd.Context(), vault.AuditOptions{
				Credential: vault.ID(cred),
				Limit:      limit,
			})
			if err != nil {
				return err
			}
			for _, e := range entries {
				status := "✓"
				if !e.Success {
					status = "✗"
				}
				fmt.Fprintf(cmd.OutOrStdout(), "%s %s [%s] %s -> %s\n",
					e.Timestamp.Format("2006-01-02 15:04:05"),
					status, e.Credential, e.Template, e.Caller)
			}
			return nil
		},
	}
}
