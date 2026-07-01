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
│   └── polyrepo-monorepo.yaml  # Multi-repo project setup
├── templates/
│   ├── README.md             # How to use vault templates
│   ├── github.json           # GitHub PAT templates
│   ├── aws.json              # AWS credential templates
│   ├── jira.json             # JIRA API templates
│   └── tavily.json           # Tavily search API templates
└── sessions/
    └── sample.jsonl          # Example event stream from a session
```

## Quickstart

```bash
# Copy a task to your tasks dir and customize
cp examples/tasks/feature-add.yaml ~/.agentjam/tasks/my-app/

# Add vault templates
agentjam vault template add github/personal --name gh_cli_env \
    --env "$(cat examples/templates/github.json | jq -r '.templates.gh_cli_env.injection.env')"

# Create a project from the polyrepo example
agentjam project create my-app \
    --name "My App" \
    --repo "[email protected]:me/web.git"
```

See [`docs/quickstart.md`](../docs/quickstart.md) for the full walkthrough.