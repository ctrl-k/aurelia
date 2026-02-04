"""Git worktree management for parallel candidate branches.

Each active candidate gets its own worktree so that multiple components can
operate on different branches simultaneously without checkout conflicts.
"""

from __future__ import annotations

import logging
from pathlib import Path

from aurelia.git.repo import GitRepo

logger = logging.getLogger(__name__)


class WorktreeManager:
    """Create, remove, and enumerate git worktrees for a repository."""

    def __init__(self, repo: GitRepo, worktree_base: Path) -> None:
        self.repo = repo
        self.worktree_base = worktree_base

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create(self, branch: str) -> Path:
        """Create a worktree for *branch* and return its path.

        The worktree is placed at ``<worktree_base>/<branch>``.
        """
        wt_path = self.worktree_base / branch
        wt_path.parent.mkdir(parents=True, exist_ok=True)

        await self.repo._run("worktree", "add", str(wt_path), branch)
        logger.info("Created worktree for branch '%s' at %s", branch, wt_path)
        return wt_path

    async def remove(self, branch: str) -> None:
        """Remove the worktree associated with *branch*."""
        wt_path = self.worktree_base / branch
        await self.repo._run("worktree", "remove", str(wt_path))
        logger.info("Removed worktree for branch '%s'", branch)

    async def list_active(self) -> list[tuple[str, Path]]:
        """Return a list of ``(branch, path)`` tuples for active worktrees."""
        raw = await self.repo._run("worktree", "list", "--porcelain")

        results: list[tuple[str, Path]] = []
        current_path: Path | None = None

        for line in raw.splitlines():
            if line.startswith("worktree "):
                current_path = Path(line.removeprefix("worktree ").strip())
            elif line.startswith("branch "):
                ref = line.removeprefix("branch ").strip()
                # ref looks like "refs/heads/my-branch"
                branch_name = ref.removeprefix("refs/heads/")
                if current_path is not None:
                    results.append((branch_name, current_path))
                current_path = None

        return results
