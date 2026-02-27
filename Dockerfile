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
    "qdrant-client"

# Copy source
COPY src/ src/
RUN uv pip install --system -e .

# Pre-download the reranker model so it's baked into the image
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

CMD ["python", "-m", "mem0_enhanced.mcp_server"]
