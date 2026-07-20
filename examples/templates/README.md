# Vault Templates

A starter library of injection templates for common tools. Copy and adapt
to your needs.

## How to use

```bash
# 1. Add a credential (interactive)
agent-knots vault add github/work
# Credential value: <paste your token>

# 2. Add a template from this library
agent-knots vault template add github/work \
  --name gh_cli_env \
  --env '{"GH_TOKEN": "$value"}'

# 3. Inspect what you've stored
agent-knots vault template list github/work
agent-knots vault template show github/work gh_cli_env
```

> **Note:** the CLI/web/TUI can store and manage templates today (this
> page), but there's no agent-callable `vault_use` tool yet that actually
> spawns a command with the template's injection applied and scrubs the
> output — that's still on the [roadmap](../../roadmap.md). Right now
> templates are metadata attached to a credential; nothing consumes them
> automatically during a session.

## Files

- **`github.json`** — GitHub Personal Access Token templates for `gh` CLI,
  SSH key auth, and curl-based APIs
- **`aws.json`** — AWS credential templates for CLI and SDK use
- **`jira.json`** — Atlassian / Jira templates for CLI and API use
- **`tavily.json`** — Tavily search API key for web search integrations
- **`openai.json`** — OpenAI / OpenAI-compatible API keys
- **`anthropic.json`** — Anthropic API key

Each file shows the same template as JSON (for reference — `vault.enc` is
encrypted and isn't meant to be hand-edited) and as the equivalent CLI
flags for `agent-knots vault template add`.

## Variables

Templates use `$value` as the substitution marker and (for command
wrapper templates) `{original}` for the agent's original command +
arguments. These are how the injection is *meant* to work once a
consuming tool applies the template — see the note above about what's
implemented today.

## Adding custom templates

The fastest path is `agent-knots vault template add` with the right flags.
The library files here are reference; they're not auto-loaded.

If you want a template the agent can use for a tool not in this library,
either:
1. Pick the closest generic template (`curl_bearer`, `env`, `stdin`)
2. Write a new template JSON in your vault directly