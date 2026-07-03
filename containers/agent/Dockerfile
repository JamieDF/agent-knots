# agentjam agent base image — Pi installed, ready to run.
# Used by the podman container runtime for containerized sessions.
#
# Build: podman build -t agentjam-agent-node:20 -f containers/agent/Dockerfile .
# Run manually: podman run --rm agentjam-agent-node:20 pi --mode rpc
#
# This image is for running AI coding agents. The agent's system prompt
# and worktree are mounted at /workspace. Extensions mount at /extensions.
FROM node:20-bookworm-slim

LABEL io.agentjam.managed=true

# Install Pi globally (skip lifecycle scripts for supply-chain safety).
RUN npm install -g --ignore-scripts @earendil-works/pi-coding-agent && \
    rm -rf /tmp/* /root/.npm

# Create workspace directory for worktree mounts.
RUN mkdir -p /workspace /extensions

WORKDIR /workspace

# Pi is the entrypoint, but podman overrides with the full command.
ENTRYPOINT ["pi"]
