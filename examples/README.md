# Examples

Practical examples to copy and adapt. Each example is self-contained — read
the comments, copy what you need.

## Layout

```
examples/
├── tasks/
│   ├── bug-fix.yaml          # Single bug-fix task
│   ├── feature-add.yaml      # New feature with acceptance criteria
│   ├── refactor.yaml         # Refactor task with risk assessment
│   └── multi-step-plan.yaml  # Complex task with sub-tasks
├── projects/
│   ├── monorepo.yaml           # Single-repo project setup
│   └── polyrepo-monorepo.yaml  # Multi-repo project setup
├── templates/
│   ├── README.md             # How to use vault templates
│   ├── github.json           # GitHub PAT templates
│   ├── aws.json               # AWS credential templates
│   ├── jira.json              # JIRA API templates
│   ├── tavily.json            # Tavily search API templates
│   ├── openai.json            # OpenAI / OpenAI-compatible API key templates
│   └── anthropic.json         # Anthropic API key templates
└── sessions/
    └── sample.jsonl          # Example event stream from a session
```

## Quickstart

```bash
# Copy a task into your tasks dir — tasks live flat as <id>.yaml,
# named after the task's own `id` field, not nested per project.
cp examples/tasks/feature-add.yaml ~/.agent-knots/tasks/T-2026-06-30-002.yaml

# Create a project
agent-knots project create my-app \
    --name "My App" \
    --repo "[email protected]:me/web.git"

# Add a vault template from this library
agent-knots vault template add github/personal --name gh_cli_env \
    --env "$(jq -c '.templates.gh_cli_env.injection.env' examples/templates/github.json)"
```

See [`docs/quickstart.md`](../docs/quickstart.md) for the full CLI
walkthrough, and [`templates/README.md`](templates/README.md) for what
vault templates can and can't do today.
