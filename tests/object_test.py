import contextlib
from pathlib import Path

import pytest
from git import GitConfigParser, Repo  # type: ignore [attr-defined]

from rubin_lfs_migrator import Migrator


def test_not_gitlfs() -> None:
    """This repo isn't an LFS-enabled repository."""
    with pytest.raises(RuntimeError) as exc:
        _ = Migrator(
            directory=str(Path(__file__).parent.parent),
            lfs_base_url="https://git-lfs-dev.lsst.cloud",
            lfs_base_write_url="https://git-lfs-dev-rw.lsst.cloud",
            dry_run=True,
            quiet=False,
            debug=True,
        )
        assert str(exc).endswith("/.lfsconfig not found")


def test_object(directory: Path) -> None:
    """Does the migrator get created?"""
    mgr = Migrator(
        directory=str(directory),
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
        lfscfgblob = repo.head.commit.tree / ".lfsconfig"
        lfscfgpath = lfscfgblob.abspath
        cfg = GitConfigParser(lfscfgpath)
        url = cfg.get("lfs", "url")
        # Check that it's correct
        assert url == "https://www.example.com/owner/testrepo"

        # Find LFS-managed files
        await migrator._get_lfs_file_list()

        # Check that we found one LFS-managed file
        assert len(migrator._lfs_files) == 1
        # Check that it's the right one
        assert migrator._lfs_files[0] == Path(directory / "assets" / "foo.txt")

        # Check that we're on "migration" branch now
        await migrator._checkout_migration_branch()
        assert repo.active_branch == repo.create_head("migration")

        # Update LFS config
        await migrator._update_lfsconfig()

        # Check that we have made a new commit
        commits = list(repo.iter_commits("migration"))
        assert len(commits) == 1 + 1

        # Check that LFS config has been updated
        # Read the URL from .lfsconfig
        lfscfgblob = repo.head.commit.tree / ".lfsconfig"
        lfscfgpath = lfscfgblob.abspath
        cfg = GitConfigParser(lfscfgpath)
        url = cfg.get("lfs", "url")
        assert url == "https://git-lfs-dev.lsst.cloud/owner/testrepo"

        # Skip the remove-push-readd-push step, since we would have to mock
        # out a git repository and a git LFS server for that to work.
        #
        # Maybe do this later, because this is actually the tricky part.

        # Verify output.
        await migrator._report()

        # Read the output
        expected = (
            """
LFS migration has been performed on the `migration` branch of the
owner/testrepo repository.

The LFS read-only pull URL is now https://git-lfs-
dev.lsst.cloud/owner/testrepo, changed from
https://example.com/owner/testrepo, and 1 files have been uploaded to
their new location.  Lock verification has also been disabled.

You should immediately PR the `migration` branch to your default
branch and merge that PR, so that so that no one else pushes to the
old LFS repository.

You will need to run `git config lfs.url https://git-lfs-dev-
rw.lsst.cloud/owner/testrepo` before pushing, and you will need the
Git LFS push token you used to push to https://git-lfs-dev-
rw.lsst.cloud/owner/testrepo just now.

When prompted to authenticate on push, use the name you
authenticated to Gafaelfawr with as the username, and the
corresponding token as the password (as you just did).
"""
        ).lstrip()
        captured = capsys.readouterr()
        assert captured.out == expected
