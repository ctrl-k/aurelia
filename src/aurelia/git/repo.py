"""Git repository operations using async subprocesses.

Provides branch management, commits, diffs, notes, and file inspection
without requiring gitpython — all operations go through ``git`` CLI so that
worktree and notes features work reliably.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from aurelia.core.models import GitNote

logger = logging.getLogger(__name__)


class GitRepo:
    """Async wrapper around a local git repository."""

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run(self, *args: str, cwd: Path | None = None) -> str:
        """Run a git command and return stdout.

        Raises ``RuntimeError`` on non-zero exit.
        """
        cmd = ["git", "-C", str(cwd or self.project_dir), *args]
        logger.debug("git command: %s", " ".join(cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        stdout = stdout_bytes.decode().strip()
        stderr = stderr_bytes.decode().strip()

        if proc.returncode != 0:
            raise RuntimeError(
                f"git command failed (exit {proc.returncode}): "
                f"{' '.join(cmd)}\nstderr: {stderr}"
            )
        return stdout

    # ------------------------------------------------------------------
    # Repository lifecycle
    # ------------------------------------------------------------------

    async def init(self) -> None:
        """Initialise a git repo with an initial commit on *main* if empty."""
        self.project_dir.mkdir(parents=True, exist_ok=True)

        await self._run("init", "-b", "main")

        # Create initial commit so that branches have a root.
        try:
            await self._run("rev-parse", "HEAD")
        except RuntimeError:
            # No commits yet — create an empty root commit.
            await self._run("commit", "--allow-empty", "-m", "Initial commit")

    # ------------------------------------------------------------------
    # Branch operations
    # ------------------------------------------------------------------

    async def create_branch(self, name: str, from_branch: str = "main") -> None:
        """Create a new branch from *from_branch*."""
        await self._run("branch", name, from_branch)

    # ------------------------------------------------------------------
    # Commit
    # ------------------------------------------------------------------

    async def commit(
        self, branch: str, message: str, paths: list[Path]
    ) -> str:
        """Stage *paths*, commit on *branch*, and return the commit SHA."""
        await self._run("checkout", branch)

        str_paths = [str(p) for p in paths]
        await self._run("add", "--", *str_paths)
        await self._run("commit", "-m", message)

        sha = await self._run("rev-parse", "HEAD")
        return sha

    # ------------------------------------------------------------------
    # Log
    # ------------------------------------------------------------------

    async def log(self, branch: str, n: int = 10) -> list[dict[str, Any]]:
        """Return the last *n* commits on *branch* as a list of dicts.

        Each dict contains keys: ``sha``, ``author``, ``date``, ``message``.
        """
        sep = "---AURELIA_RECORD_SEP---"
        fmt = f"%H%n%an%n%aI%n%s%n{sep}"
        raw = await self._run(
            "log", branch, f"-n{n}", f"--format={fmt}",
        )

        entries: list[dict[str, Any]] = []
        for block in raw.split(sep):
            block = block.strip()
            if not block:
                continue
            lines = block.splitlines()
            if len(lines) < 4:  # noqa: PLR2004
                continue
            entries.append({
                "sha": lines[0],
                "author": lines[1],
                "date": lines[2],
                "message": lines[3],
            })
        return entries

    # ------------------------------------------------------------------
    # Diff
    # ------------------------------------------------------------------

    async def diff(self, branch: str, base: str = "main") -> str:
        """Return the diff between *base* and *branch*."""
        return await self._run("diff", f"{base}...{branch}")

    # ------------------------------------------------------------------
    # Git notes
    # ------------------------------------------------------------------

    async def add_note(
        self,
        commit_sha: str,
        note: GitNote,
        namespace: str = "aurelia",
    ) -> None:
        """Attach a structured :class:`GitNote` to *commit_sha*."""
        # Read existing notes (if any) so we can append.
        existing = await self._read_notes_raw(commit_sha, namespace)
        existing.append(json.loads(note.model_dump_json()))

        payload = json.dumps(existing, default=str)
        await self._run(
            "notes", f"--ref={namespace}", "add", "-f", "-m", payload, commit_sha,
        )

    async def read_notes(
        self,
        commit_sha: str,
        namespace: str = "aurelia",
    ) -> list[GitNote]:
        """Read all :class:`GitNote` entries attached to *commit_sha*."""
        raw_list = await self._read_notes_raw(commit_sha, namespace)
        return [GitNote.model_validate(entry) for entry in raw_list]

    async def _read_notes_raw(
        self,
        commit_sha: str,
        namespace: str,
    ) -> list[dict[str, Any]]:
        """Return the raw JSON list stored in a git note, or ``[]``."""
        try:
            raw = await self._run(
                "notes", f"--ref={namespace}", "show", commit_sha,
            )
        except RuntimeError:
            return []

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []

        if isinstance(data, list):
            return data
        return [data]

    # ------------------------------------------------------------------
    # Show
    # ------------------------------------------------------------------

    async def show(self, branch: str, path: str) -> str:
        """Return the contents of *path* at the tip of *branch*."""
        return await self._run("show", f"{branch}:{path}")
