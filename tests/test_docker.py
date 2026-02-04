"""Tests for DockerClient (mocked subprocess)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from aurelia.core.models import SandboxConfig
from aurelia.sandbox.docker import (
    ContainerResult,
    DockerClient,
    DockerNotAvailableError,
    ImageBuildError,
)


def _mock_process(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""):
    """Create a mock asyncio.Process with communicate()."""
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.kill = AsyncMock()
    proc.wait = AsyncMock()
    return proc


class TestCheckAvailable:
    async def test_success(self):
        client = DockerClient()
        proc = _mock_process(returncode=0)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            await client.check_available()  # should not raise

    async def test_failure(self):
        client = DockerClient()
        proc = _mock_process(returncode=1, stderr=b"Cannot connect to Docker daemon")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            with pytest.raises(DockerNotAvailableError, match="Cannot connect"):
                await client.check_available()

    async def test_docker_not_on_path(self):
        client = DockerClient()
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("docker not found"),
        ):
            with pytest.raises(DockerNotAvailableError, match="not found on PATH"):
                await client.check_available()


class TestImageExists:
    async def test_image_exists_true(self):
        client = DockerClient()
        proc = _mock_process(returncode=0)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            assert await client.image_exists("myimage:latest") is True

    async def test_image_exists_false(self):
        client = DockerClient()
        proc = _mock_process(returncode=1)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            assert await client.image_exists("myimage:latest") is False


class TestBuildImage:
    async def test_build_success(self, tmp_path):
        client = DockerClient()
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM scratch")

        proc = _mock_process(returncode=0)
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            await client.build_image(dockerfile, "myimage:latest")

    async def test_build_failure(self, tmp_path):
        client = DockerClient()
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM scratch")

        proc = _mock_process(returncode=1, stderr=b"build error")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            with pytest.raises(ImageBuildError, match="build error"):
                await client.build_image(dockerfile, "myimage:latest")


class TestRunContainer:
    async def test_run_success(self):
        client = DockerClient()
        sandbox = SandboxConfig(image="test:latest", network=True)

        proc = _mock_process(returncode=0, stdout=b"output here")
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            result = await client.run_container(
                image="test:latest",
                command=["echo", "hello"],
                sandbox_config=sandbox,
                workdir="/workspace",
                env={"FOO": "bar"},
                mounts=[("/host/path", "/container/path", False)],
            )

        assert isinstance(result, ContainerResult)
        assert result.exit_code == 0
        assert result.stdout == "output here"

        # Verify docker run args were passed correctly
        call_args = mock_exec.call_args[0]
        assert call_args[0] == "docker"
        assert "run" in call_args
        assert "--rm" in call_args
        assert "test:latest" in call_args
        assert "echo" in call_args

    async def test_run_with_network_disabled(self):
        client = DockerClient()
        sandbox = SandboxConfig(image="test:latest", network=False)

        proc = _mock_process(returncode=0)
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await client.run_container(
                image="test:latest",
                command=["ls"],
                sandbox_config=sandbox,
            )

        call_args = mock_exec.call_args[0]
        # Should have --network none when network=False
        assert "--network" in call_args
        idx = list(call_args).index("--network")
        assert call_args[idx + 1] == "none"

    async def test_run_with_mounts_and_env(self):
        client = DockerClient()
        sandbox = SandboxConfig(image="test:latest")

        proc = _mock_process(returncode=0)
        with patch("asyncio.create_subprocess_exec", return_value=proc) as mock_exec:
            await client.run_container(
                image="test:latest",
                command=["ls"],
                sandbox_config=sandbox,
                env={"KEY": "val"},
                mounts=[
                    ("/host", "/container", False),
                    ("/ro_host", "/ro_container", True),
                ],
            )

        call_args = list(mock_exec.call_args[0])
        assert "-e" in call_args
        env_idx = call_args.index("-e")
        assert call_args[env_idx + 1] == "KEY=val"

        # Check volume mounts
        v_indices = [i for i, x in enumerate(call_args) if x == "-v"]
        assert len(v_indices) == 2
        mount_args = [call_args[i + 1] for i in v_indices]
        assert "/host:/container" in mount_args
        assert "/ro_host:/ro_container:ro" in mount_args

    async def test_run_timeout(self):
        client = DockerClient()
        sandbox = SandboxConfig(image="test:latest", timeout_s=1)

        proc = AsyncMock()
        proc.returncode = None
        proc.kill = AsyncMock()
        proc.wait = AsyncMock()

        async def slow_communicate():
            await asyncio.sleep(10)
            return (b"", b"")

        proc.communicate = slow_communicate

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await client.run_container(
                image="test:latest",
                command=["sleep", "100"],
                sandbox_config=sandbox,
                timeout_s=1,
            )

        assert result.exit_code == -1
        assert "timed out" in result.stderr

    async def test_run_nonzero_exit(self):
        client = DockerClient()
        sandbox = SandboxConfig(image="test:latest")

        proc = _mock_process(returncode=1, stderr=b"error output")
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await client.run_container(
                image="test:latest",
                command=["false"],
                sandbox_config=sandbox,
            )

        assert result.exit_code == 1
        assert result.stderr == "error output"
