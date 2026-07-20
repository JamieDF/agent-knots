# Vault Templates

A starter library of injection templates for common tools. Copy and adapt
to your needs.

## How to use

```bash
# 1. Add a credential (interactive)
agent-knots vault add github/work
# Value: <paste your token>

# 2. Add a template from this library
agent-knots vault template add github/work \
  --name gh_cli_env \
  --env '{"GH_TOKEN": "$value"}'

# 3. The agent can now use it via vault://github/work?template=gh_cli_env
# The credential value is never returned to the agent.
```

## Files

- **`github.json`** — GitHub Personal Access Token templates for `gh` CLI,
  SSH key auth, and curl-based APIs
- **`aws.json`** — AWS credential templates for CLI and SDK use
- **`jira.json`** — Atlassian / Jira templates for CLI and API use
- **`tavily.json`** — Tavily search API key for web search integrations
- **`openai.json`** — OpenAI / OpenAI-compatible API keys
- **`anthropic.json`** — Anthropic API key

Each file shows the same template in JSON form (which you can hand-edit
in your vault's `vault.enc`) and as CLI flags for `agent-knots vault template add`.

## Variables

All templates use `$value` as the substitution marker. When the template
fires, `$value` is replaced with the decrypted credential value *inside
the spawned process's environment* — never in the orchestrator or agent.

Command wrapper templates also support `{original}`, which is replaced
with the agent's original command + arguments.

## Adding custom templates

The fastest path is `agent-knots vault template add` with the right flags.
The library files here are reference; they're not auto-loaded.

If you want a template the agent can use for a tool not in this library,
either:
1. Pick the closest generic template (`curl_bearer`, `env`, `stdin`)
2. Write a new template JSON in your vault directly