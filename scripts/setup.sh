#!/bin/bash
set -e

echo "=== Enhanced Mem0 Setup ==="

# 1. Start infrastructure
echo "Starting Docker services..."
docker compose up -d

# 2. Wait for services
echo "Waiting for services to be ready..."
sleep 5

# Check Qdrant
until curl -s http://localhost:6333/healthz > /dev/null 2>&1; do
    echo "  Waiting for Qdrant..."
    sleep 2
done
echo "  ✓ Qdrant ready"

# Check Neo4j
until curl -s http://localhost:7474 > /dev/null 2>&1; do
    echo "  Waiting for Neo4j..."
    sleep 2
done
echo "  ✓ Neo4j ready"

# Check Ollama
until curl -s http://localhost:11434/api/tags > /dev/null 2>&1; do
    echo "  Waiting for Ollama..."
    sleep 2
done
echo "  ✓ Ollama ready"

# 3. Pull models
echo "Pulling Ollama models..."
docker exec ollama ollama pull nomic-embed-text
docker exec ollama ollama pull phi3:mini

# 4. Install Python package
echo "Installing mem0_enhanced..."
pip install -e ".[dev]"

echo ""
echo "=== Setup Complete ==="
echo "Infrastructure: Qdrant :6333 | Neo4j :7474/:7687 | Ollama :11434"
echo ""
echo "Quick test:"
echo "  python -c \"from mem0_enhanced import EnhancedMemory; m = EnhancedMemory(); print('OK')\""
echo ""
echo "Start MCP server:"
echo "  python -m mem0_enhanced.mcp_server"
