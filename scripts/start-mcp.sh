#!/bin/bash
# Fetch a fresh JWT from the SIE gateway and launch the MCP server
export ANTHROPIC_API_KEY=$(/usr/local/bin/gimme-ai-creds --helper --org pfb --quiet)
export ANTHROPIC_BASE_URL="https://ai-gateway.dspprod.bis.sie.sony.com/pfb/claude-code"
exec "$(dirname "$0")/../.venv/bin/python" -m mem0_enhanced.mcp_server
