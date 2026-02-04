"""Built-in MCP tool server for Aurelia.

Provides filesystem and shell tools via FastMCP.
"""

from __future__ import annotations

import asyncio
import os

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("aurelia-tools")


@mcp.tool()
async def read_file(path: str, offset: int = 0, limit: int = 2000) -> str:
    """Read a file from the filesystem. Returns up to `limit` lines starting from `offset`."""
    try:
        with open(path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    selected = lines[offset : offset + limit]
    return "".join(selected)


@mcp.tool()
async def write_file(path: str, content: str) -> str:
    """Write content to a file, creating parent directories if needed."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        f.write(content)
    return f"Successfully wrote {len(content)} bytes to {path}"


@mcp.tool()
async def run_command(command: str, timeout_s: int = 60) -> str:
    """Run a shell command and return combined stdout/stderr."""
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        return stdout.decode(errors="replace")
    except TimeoutError:
        proc.kill()  # type: ignore[union-attr]
        return f"Error: command timed out after {timeout_s}s"
