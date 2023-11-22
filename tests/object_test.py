import contextlib
import tempfile
from pathlib import Path

import pytest
from git import GitConfigParser, Repo
from git.exc import GitCommandError, InvalidGitRepositoryError

from rubin_lfs_migrator import Migrator


def test_not_git() -> None:
    """This directory isn't a git repository."""
    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(InvalidGitRepositoryError) as exc:
            _ = Migrator(
                owner="owner",
                repository="badrepo",
                directory=d,
                migration_branch="lfs-migration",
                source_branch=None,
                original_lfs_url="https://git-lfs.lsst.codes",
                lfs_base_url="https://git-lfs-dev.lsst.cloud",
                lfs_base_write_url="https://git-lfs-dev-rw.lsst.cloud",
                dry_run=True,
                quiet=False,
                debug=True,
            )
            assert str(exc).endswith(" must contain a cloned git repository")


def test_object(directory: Path) -> None:
    """Does the migrator get created?"""
    mgr = Migrator(
        owner="owner",
        repository="testrepo",
        directory=str(directory),
        migration_branch="lfs-migration",
        source_branch=None,
        original_lfs_url="https://git-lfs.lsst.codes",
        lfs_base_url="https://git-lfs-dev.lsst.cloud",
        lfs_base_write_url="https://git-lfs-dev-rw.lsst.cloud",
        dry_run=True,
        quiet=False,
        debug=True,
    )
    assert mgr._owner == "owner"
    assert mgr._name == "testrepo"
    assert mgr._url == "https://git-lfs-dev.lsst.cloud/owner/testrepo"
    assert mgr._write_url == "https://git-lfs-dev-rw.lsst.cloud/owner/testrepo"


@pytest.mark.asyncio
async def test_execution(
    directory: Path, migrator: Migrator, capsys: pytest.CaptureFixture
) -> None:
    with contextlib.chdir(directory):
        await migrator._locate_gitattributes()
        await migrator._locate_lfsconfig()

        # Get a repo view
        repo = Repo(directory)

        # Check we're on main
        assert repo.active_branch == repo.create_head("main")

        # Check that we have one commit
        commits = list(repo.iter_commits("main"))
        assert len(commits) == 1

        # Check we have no LFS files identified yet
        assert len(migrator._lfs_files) == 0

        # Read the URL from .lfsconfig
        cfg = GitConfigParser(migrator._lfsconfig)
        url = cfg.get("lfs", "url")
        # Check that it's correct
        assert url == "https://www.example.com/owner/testrepo"

        # Find LFS-managed files
        await migrator._get_lfs_file_list()

        # Check that we found one LFS-managed file
        assert len(migrator._lfs_files) == 1
        # Check that it's the right one
        assert migrator._lfs_files[0] == Path(directory / "assets" / "foo.txt")

        # Check that we're on "lfs-migration" branch now
        await migrator._checkout_migration_branch()
        assert repo.active_branch == repo.create_head("lfs-migration")

        # Update LFS config
        with pytest.raises(GitCommandError):
            # We can't actually push, so we'll get an error.
            await migrator._update_lfsconfig()

        # Check that we have made a new commit
        commits = list(repo.iter_commits("lfs-migration"))
        assert len(commits) == 1 + 1

        # Check that LFS config has been updated
        # Read the URL from .lfsconfig
        cfg = GitConfigParser(migrator._lfsconfig)
        url = cfg.get("lfs", "url")
        assert url == "https://git-lfs-dev.lsst.cloud/owner/testrepo"

        # Skip the remove-push-readd-push step, since we would have to mock
        # out a git repository and a git LFS server for that to work.
        #
        # Maybe do this later, because this is actually the tricky part.

        # Verify output.
        await migrator._report()

        # Read the output
        expected = "LFS migration has been performed on the `lfs-migration`"
        captured = capsys.readouterr()
        assert captured.out.startswith(expected)
