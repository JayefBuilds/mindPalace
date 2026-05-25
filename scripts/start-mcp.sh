#!/bin/bash
set -euo pipefail

# Launch the Mind Palace MCP server without inheriting host-specific Anthropic
# gateways. Auth should come from this repo's .env or explicit MCP env.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

if [ -n "${MINDPALACE_ANTHROPIC_BASE_URL:-}" ]; then
  export ANTHROPIC_BASE_URL="$MINDPALACE_ANTHROPIC_BASE_URL"
elif [ "${MINDPALACE_ALLOW_ANTHROPIC_BASE_URL:-false}" != "true" ]; then
  unset ANTHROPIC_BASE_URL
fi

if [ "${MEM0_LLM_PROVIDER:-anthropic}" = "anthropic" ] \
  && [ -z "${ANTHROPIC_API_KEY:-}" ] \
  && [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] \
  && [ -z "${PERSONAL_ANTHROPIC_API_KEY:-}" ]; then
  echo "Mind Palace MCP: no Anthropic auth found. Set ANTHROPIC_API_KEY, CLAUDE_CODE_OAUTH_TOKEN, PERSONAL_ANTHROPIC_API_KEY, or MEM0_LLM_PROVIDER=ollama." >&2
fi

exec "$ROOT/.venv/bin/python" -m mem0_enhanced.mcp_server
