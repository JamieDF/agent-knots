#!/bin/sh
# Build the agent-knots agent container image with Pi installed.
# Default tag: agent-knots-agent-node:20

set -e

TAG="${1:-agent-knots-agent-node:20}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "Building agent-knots agent image: $TAG"
cd "$ROOT_DIR"
podman build -t "$TAG" -f containers/agent/Dockerfile .
echo "Done: $TAG"
