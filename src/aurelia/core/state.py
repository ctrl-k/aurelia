from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TypeVar

import anyio.to_thread
from pydantic import BaseModel

from aurelia.core.models import Candidate, RuntimeConfig, RuntimeState, Task

T = TypeVar("T", bound=BaseModel)

_MAX_BACKUPS = 3


class StateStore:
    """Atomic JSON state store with backup rotation and corruption recovery."""

    def __init__(self, aurelia_dir: Path) -> None:
        self._aurelia_dir = aurelia_dir
        self._state_dir = aurelia_dir / "state"

    # -- Public API ----------------------------------------------------------

    async def load_runtime(self) -> RuntimeState:
        data = await self._load_file(self._state_dir / "runtime.json")
        if data is None:
            return RuntimeState()
        return RuntimeState.model_validate(data)

    async def save_runtime(self, state: RuntimeState) -> None:
        await self._save_file(
            self._state_dir / "runtime.json",
            state.model_dump(mode="json"),
        )

    async def load_tasks(self) -> list[Task]:
        data = await self._load_file(self._state_dir / "tasks.json")
        if data is None:
            return []
        return [Task.model_validate(item) for item in data]

    async def save_tasks(self, tasks: list[Task]) -> None:
        await self._save_file(
            self._state_dir / "tasks.json",
            [t.model_dump(mode="json") for t in tasks],
        )

    async def load_candidates(self) -> list[Candidate]:
        data = await self._load_file(self._state_dir / "candidates.json")
        if data is None:
            return []
        return [Candidate.model_validate(item) for item in data]

    async def save_candidates(self, candidates: list[Candidate]) -> None:
        await self._save_file(
            self._state_dir / "candidates.json",
            [c.model_dump(mode="json") for c in candidates],
        )

    async def initialize(self, config: RuntimeConfig) -> None:  # noqa: ARG002
        subdirs = ["state", "logs", "cache", "reports", "config"]
        for name in subdirs:
            d = self._aurelia_dir / name
            await anyio.to_thread.run_sync(lambda p=d: p.mkdir(parents=True, exist_ok=True))

    # -- Internals -----------------------------------------------------------

    async def _load_file(self, path: Path) -> dict | list | None:
        """Load JSON from *path*, falling back to backups on missing/corrupt files."""
        candidates = [
            path,
            *(path.parent / f"{path.name}.bak.{i}" for i in range(1, _MAX_BACKUPS + 1)),
        ]
        for candidate in candidates:
            data = await self._try_read_json(candidate)
            if data is not None:
                return data
        return None

    @staticmethod
    async def _try_read_json(path: Path) -> dict | list | None:
        def _read() -> dict | list | None:
            try:
                raw = path.read_text(encoding="utf-8")
            except (OSError, FileNotFoundError):
                return None
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return None

        return await anyio.to_thread.run_sync(_read)

    async def _save_file(self, path: Path, data: dict | list) -> None:
        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)

            # Rotate backups: .bak.3 is dropped, .bak.2 -> .bak.3, .bak.1 -> .bak.2, file -> .bak.1
            for i in range(_MAX_BACKUPS, 1, -1):
                src = path.parent / f"{path.name}.bak.{i - 1}"
                dst = path.parent / f"{path.name}.bak.{i}"
                if src.exists():
                    os.replace(src, dst)

            if path.exists():
                os.replace(path, path.parent / f"{path.name}.bak.1")

            # Atomic write via tmp + fsync + replace
            tmp_path = path.parent / f"{path.name}.tmp"
            content = json.dumps(data, indent=2, ensure_ascii=False)
            fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            try:
                os.write(fd, content.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)

            os.replace(tmp_path, path)

        await anyio.to_thread.run_sync(_write)
