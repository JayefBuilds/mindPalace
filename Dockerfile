FROM python:3.11-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install dependencies first (cached layer)
COPY pyproject.toml .
RUN uv pip install --system \
    "mem0ai>=1.0" \
    "sentence-transformers>=3.0" \
    "httpx>=0.27" \
    "mcp>=1.0" \
    "anthropic>=0.80" \
    "ollama" \
    "qdrant-client" \
    "langchain-neo4j" \
    "rank-bm25"

# Apply patches to mem0ai for Anthropic API compatibility
# Fixes: temperature+top_p conflict, tool format (function→custom), tool_choice dict format, tool_use response format
COPY patches/mem0_anthropic_llm.py .
RUN cp mem0_anthropic_llm.py $(python -c "import mem0.llms.anthropic as m; print(m.__file__)")

# Copy source
COPY src/ src/
RUN uv pip install --system -e .

# Pre-download the reranker model so it's baked into the image
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

CMD ["python", "-m", "mem0_enhanced.mcp_server"]
