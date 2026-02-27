"""Allow running the MCP server with: python -m mem0_enhanced"""
from .mcp_server import main
import asyncio

asyncio.run(main())
