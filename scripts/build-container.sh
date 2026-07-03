#!/bin/sh
# Build the agentjam agent container image with Pi installed.
# Default tag: agentjam-agent-node:20

set -e

TAG="${1:-agentjam-agent-node:20}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "Building agentjam agent image: $TAG"
cd "$ROOT_DIR"
podman build -t "$TAG" -f containers/agent/Dockerfile .
echo "Done: $TAG"
