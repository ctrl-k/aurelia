"""Tests for git repository operations.

Every test initialises a fresh git repo in a temp directory via repo.init().
"""

from datetime import UTC, datetime

import pytest

from aurelia.core.models import GitNote
from aurelia.git.repo import GitRepo

NOW = datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
async def repo(tmp_path):
    """Create and initialise a fresh GitRepo in tmp_path."""
    r = GitRepo(tmp_path)
    await r.init()
    # Configure git identity for commits
    await r._run("config", "user.email", "test@test.com")
    await r._run("config", "user.name", "Test User")
    return r


class TestInit:
    async def test_creates_repo_with_initial_commit(self, repo, tmp_path):
        assert (tmp_path / ".git").is_dir()
        log_entries = await repo.log("main", n=1)
        assert len(log_entries) == 1
        assert log_entries[0]["message"] == "Initial commit"


class TestBranch:
    async def test_create_branch(self, repo):
        await repo.create_branch("feature-1")
        log_entries = await repo.log("feature-1", n=1)
        assert len(log_entries) >= 1


class TestCommit:
    async def test_commit_returns_sha(self, repo, tmp_path):
        # Create a file and commit it
        test_file = tmp_path / "hello.txt"
        test_file.write_text("hello world")
        sha = await repo.commit("main", "Add hello.txt", [test_file])
        assert len(sha) == 40
        assert all(c in "0123456789abcdef" for c in sha)

    async def test_commit_appears_in_log(self, repo, tmp_path):
        test_file = tmp_path / "file.txt"
        test_file.write_text("content")
        await repo.commit("main", "Test commit message", [test_file])
        log_entries = await repo.log("main", n=1)
        assert log_entries[0]["message"] == "Test commit message"


class TestDiff:
    async def test_diff_between_branches(self, repo, tmp_path):
        await repo.create_branch("feature-2")
        # Add a file on the feature branch
        await repo._run("checkout", "feature-2")
        test_file = tmp_path / "new_file.txt"
        test_file.write_text("new content")
        await repo._run("add", str(test_file))
        await repo._run("commit", "-m", "Add new_file on feature")
        await repo._run("checkout", "main")

        diff_output = await repo.diff("feature-2", "main")
        assert "new content" in diff_output


class TestNotes:
    async def test_add_and_read_note(self, repo, tmp_path):
        # Get the HEAD SHA
        sha = await repo._run("rev-parse", "HEAD")
        note = GitNote(
            author_component="planner",
            note_type="observation",
            content="This commit looks good",
            timestamp=NOW,
            metadata={"confidence": 0.9},
        )
        await repo.add_note(sha, note)

        notes = await repo.read_notes(sha)
        assert len(notes) == 1
        assert notes[0].author_component == "planner"
        assert notes[0].content == "This commit looks good"

    async def test_multiple_notes_append(self, repo, tmp_path):
        sha = await repo._run("rev-parse", "HEAD")
        note1 = GitNote(
            author_component="planner",
            note_type="observation",
            content="First note",
            timestamp=NOW,
        )
        note2 = GitNote(
            author_component="reviewer",
            note_type="review",
            content="Second note",
            timestamp=NOW,
        )
        await repo.add_note(sha, note1)
        await repo.add_note(sha, note2)

        notes = await repo.read_notes(sha)
        assert len(notes) == 2

    async def test_read_notes_no_notes_returns_empty(self, repo):
        sha = await repo._run("rev-parse", "HEAD")
        notes = await repo.read_notes(sha)
        assert notes == []


class TestShow:
    async def test_show_file_content(self, repo, tmp_path):
        test_file = tmp_path / "show_test.txt"
        test_file.write_text("file content for show")
        await repo.commit("main", "Add show_test", [test_file])

        content = await repo.show("main", "show_test.txt")
        assert content == "file content for show"
