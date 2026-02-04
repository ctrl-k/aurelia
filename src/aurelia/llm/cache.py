from __future__ import annotations

import hashlib
import json
from pathlib import Path

import anyio.to_thread


class LLMCache:
    """LLM response cache for deterministic replay."""

    def __init__(self, cache_dir: Path) -> None:
        self._cache_dir = cache_dir

    def request_hash(
        self,
        model: str,
        contents: list,
        config: dict,
        tools: list,
    ) -> str:
        """Compute SHA-256 hash of canonical JSON representation of the request."""
        canonical = json.dumps(
            {"model": model, "contents": contents, "config": config, "tools": tools},
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    async def lookup(self, request_hash: str) -> dict | None:
        """Look up a cached response by request hash. Returns None on miss."""
        path = self._cache_dir / f"{request_hash}.json"

        def _read() -> dict | None:
            if not path.exists():
                return None
            return json.loads(path.read_text(encoding="utf-8"))

        entry = await anyio.to_thread.run_sync(_read)
        if entry is None:
            return None
        return entry.get("response")

    async def store(
        self,
        request_hash: str,
        response: dict,
        metadata: dict,
    ) -> None:
        """Store a response in the cache."""
        path = self._cache_dir / f"{request_hash}.json"
        entry = json.dumps(
            {
                "request_hash": request_hash,
                "response": response,
                "metadata": metadata,
            },
            sort_keys=True,
            indent=2,
        )

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(entry, encoding="utf-8")

        await anyio.to_thread.run_sync(_write)
