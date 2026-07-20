> **Note:** Captured under the prior project name "harness"; see CHANGELOG for the rename.
> The template/injection design described here still holds in the Python
> rebuild, but the implementation is `src/agent_knots/vault/` rather than
> `internal/vault/filestore/`.

# ADR 0002: Vault uses injection templates, not direct value retrieval

**Status:** Accepted
**Date:** 2026-06-30

## Context

The agent needs to use credentials (GitHub PAT, JIRA API token, Tavily
key, etc.) to perform work. The naive approach — give the agent the
raw value — leaks the secret into the agent's context, where it can be
echoed into logs, transcripts, or training data.

We need a way for the agent to *use* credentials without *seeing*
them.

## Options considered

1. **Direct value retrieval.** Agent asks for the credential, gets the
   raw value, uses it however it wants. Simple but insecure.
2. **Env var injection only.** Set the credential as an env var on
   the agent's process. Limited — doesn't work for SSH keys, stdin
   input, etc.
3. **Proxy execution only.** Vault runs the command itself with the
   credential injected. Most secure, but requires the agent to ask
   for specific commands (not just "give me the value").
4. **Injection templates.** Declarative JSON saying "for credential X,
   here is how to expose it." Templates support multiple injection
   modes (env, file, ssh, stdin, command wrapper, plugin).

## Decision

We chose **option 4**: declarative injection templates.

Reasons:

- **Flexibility.** Different tools need different injection modes.
  `gh` wants env vars. SSH wants a key file. `jira-cli` wants stdin.
  Curl wants a command wrapper. One mechanism, all cases.
- **User-editable.** Templates are JSON, version-controllable,
  inspectable. No code changes to add support for a new tool.
- **Auditable.** Every use is recorded: which credential, which
  template, which command, which caller, success/failure.
- **Secure by construction.** The credential value never crosses
  the vault boundary except into the spawned process.
- **Pluggable.** Custom injection modes via plugins for things we
  didn't anticipate.

## How it works

A template is a JSON-serializable struct:

```json
{
  "name": "gh_cli_env",
  "injection": {
    "env": {
      "GH_TOKEN": "$value"
    }
  }
}
```

The agent calls:

```go
vault.Use(ctx, vault.UseRequest{
    Credential: "github/work",
    Template:   "gh_cli_env",
    Command:    "gh",
    Args:       []string{"pr", "create", "--fill"},
})
```

The vault:
1. Looks up the credential.
2. Looks up the template.
3. Decrypts the value (in-memory only).
4. Applies the injection (env vars in this case).
5. Spawns the command with the injected env.
6. Captures stdout/stderr.
7. Scrubs the credential value from the output.
8. Returns the scrubbed result.
9. Writes an audit entry.

The agent sees:
```go
UseResult{
    Stdout:   "https://github.com/...",  // no token
    Stderr:   "",
    ExitCode: 0,
    Duration: 1.2 * time.Second,
}
```

## Consequences

Positive:
- Credentials never reach the agent's context.
- Output is automatically scrubbed.
- Comprehensive audit log.
- New tools added via template JSON, no code.

Negative:
- Templates add a layer of indirection.
- Plugin mode requires user code (escape hatch).

Mitigations:
- Templates are simple JSON, easy to inspect.
- We ship a starter library of common templates.
- "Direct use" is possible if needed (the agent gets the env var
  names, not the values, and sets them itself).