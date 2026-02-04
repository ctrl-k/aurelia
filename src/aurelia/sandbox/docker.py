"""Async Docker client using subprocess commands."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from aurelia.core.models import SandboxConfig

logger = logging.getLogger(__name__)


class DockerNotAvailableError(RuntimeError):
    """Raised when Docker daemon is not reachable."""


class ImageBuildError(RuntimeError):
    """Raised when a Docker image build fails."""


@dataclass
class ContainerResult:
    """Result of running a Docker container."""

    exit_code: int
    stdout: str
    stderr: str


class DockerClient:
    """Async wrapper around Docker CLI commands."""

    async def check_available(self) -> None:
        """Verify Docker daemon is running.

        Runs `docker info` and raises DockerNotAvailableError on failure.
        """
        try:
            returncode, _, stderr = await self._run("info")
            if returncode != 0:
                raise DockerNotAvailableError(
                    f"Docker not available: {stderr}"
                )
        except FileNotFoundError:
            raise DockerNotAvailableError(
                "Docker CLI not found on PATH"
            ) from None

    async def image_exists(self, image: str) -> bool:
        """Check if a Docker image exists locally.

        Runs `docker image inspect <image>` and returns True if exit 0.
        """
        returncode, _, _ = await self._run("image", "inspect", image)
        return returncode == 0

    async def build_image(
        self,
        dockerfile_path: Path,
        image_tag: str,
        context_dir: Path | None = None,
    ) -> None:
        """Build a Docker image from a Dockerfile.

        Raises ImageBuildError on failure.
        """
        ctx = str(context_dir or dockerfile_path.parent)
        returncode, stdout, stderr = await self._run(
            "build",
            "-f",
            str(dockerfile_path),
            "-t",
            image_tag,
            ctx,
            timeout_s=600,  # image builds can be slow
        )
        if returncode != 0:
            raise ImageBuildError(
                f"Failed to build image {image_tag}: {stderr or stdout}"
            )
        logger.info("Built Docker image %s", image_tag)

    async def run_container(
        self,
        image: str,
        command: list[str],
        sandbox_config: SandboxConfig,
        workdir: str = "/workspace",
        env: dict[str, str] | None = None,
        mounts: list[tuple[str, str, bool]] | None = None,
        timeout_s: int | None = None,
    ) -> ContainerResult:
        """Run a Docker container and capture output.

        Args:
            image: Docker image to run.
            command: Command and arguments to run in the container.
            sandbox_config: Resource limits and config.
            workdir: Working directory inside the container.
            env: Environment variables to set.
            mounts: List of (host_path, container_path, read_only) tuples.
            timeout_s: Override sandbox_config.timeout_s.

        Returns:
            ContainerResult with exit code, stdout, and stderr.
        """
        args = ["run", "--rm"]

        # Resource limits
        args.extend(["--memory", sandbox_config.memory_limit])
        args.extend(["--cpus", str(sandbox_config.cpu_limit)])

        # Network
        if not sandbox_config.network:
            args.extend(["--network", "none"])

        # Working directory
        args.extend(["-w", workdir])

        # Environment variables
        if env:
            for key, value in env.items():
                args.extend(["-e", f"{key}={value}"])

        # Volume mounts
        if mounts:
            for host_path, container_path, read_only in mounts:
                mount_str = f"{host_path}:{container_path}"
                if read_only:
                    mount_str += ":ro"
                args.extend(["-v", mount_str])

        # Image and command
        args.append(image)
        args.extend(command)

        effective_timeout = timeout_s or sandbox_config.timeout_s

        logger.debug("Running container: docker %s", " ".join(args))

        try:
            returncode, stdout_str, stderr_str = await self._run(
                *args, timeout_s=effective_timeout
            )
        except TimeoutError:
            return ContainerResult(
                exit_code=-1,
                stdout="",
                stderr=f"Container timed out after {effective_timeout}s",
            )

        return ContainerResult(
            exit_code=returncode,
            stdout=stdout_str,
            stderr=stderr_str,
        )

    async def _run(
        self, *args: str, timeout_s: int = 120
    ) -> tuple[int, str, str]:
        """Run a docker command, return (exit_code, stdout, stderr)."""
        cmd = ["docker", *args]
        logger.debug("docker command: %s", " ".join(cmd))

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_s
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise

        return (
            proc.returncode or 0,
            stdout_bytes.decode(errors="replace"),
            stderr_bytes.decode(errors="replace"),
        )
