"""Tests for built-in tools and the tool registry."""



from aurelia.tools.builtin import read_file, run_command, write_file


class TestReadFile:
    async def test_reads_existing_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\n")
        result = await read_file(str(f))
        assert "line1" in result
        assert "line2" in result
        assert "line3" in result

    async def test_missing_file_returns_error(self, tmp_path):
        result = await read_file(str(tmp_path / "nonexistent.txt"))
        assert "Error" in result
        assert "not found" in result

    async def test_offset_and_limit(self, tmp_path):
        f = tmp_path / "lines.txt"
        f.write_text("line0\nline1\nline2\nline3\nline4\n")
        result = await read_file(str(f), offset=1, limit=2)
        assert "line1" in result
        assert "line2" in result
        assert "line0" not in result
        assert "line3" not in result


class TestWriteFile:
    async def test_creates_file(self, tmp_path):
        target = tmp_path / "output.txt"
        result = await write_file(str(target), "hello world")
        assert "Successfully wrote" in result
        assert target.read_text() == "hello world"

    async def test_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "sub" / "dir" / "file.txt"
        await write_file(str(target), "nested")
        assert target.read_text() == "nested"


class TestRunCommand:
    async def test_returns_output(self):
        result = await run_command("echo hello")
        assert "hello" in result

    async def test_handles_timeout(self):
        result = await run_command("sleep 10", timeout_s=1)
        assert "timed out" in result
