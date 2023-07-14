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

    # Run the migration steps
    await migrator.execute()

    # Check that we're on "migration" branch now
    assert repo.active_branch == repo.create_head("migration")

    # Check that we found one LFS-managed file
    assert len(migrator._lfs_files) == 1
    # Check that it's the right one
    assert migrator._lfs_files[0] == Path(directory / "assets" / "foo.txt")

    # Check that we have made three new commits
    commits = list(repo.iter_commits("migration"))
    assert len(commits) == 1 + 3

    # Read the URL from .lfsconfig
    lfscfgblob = repo.head.commit.tree / ".lfsconfig"
    lfscfgpath = lfscfgblob.abspath
    cfg = GitConfigParser(lfscfgpath)
    url = cfg.get("lfs", "url")
    # Check that it's been updated
    assert url == "https://git-lfs-dev.lsst.cloud/owner/testrepo"

    # Read the URL from .git/config
    cfg = repo.config_reader(config_level="repository")
    url = cfg.get("lfs", "url")
    # Check that it is now our write URL
    assert url == "https://git-lfs-dev-rw.lsst.cloud/owner/testrepo"

    # Read the output
    expected = (
        """
LFS migration has been performed on the `migration`branch of the
owner/testrepo repository.

Changes to remove and re-add the Git LFS objects, to update the LFS
read-only pull URL, and to disable lock verification have been
committed.

Additionally, `git config` has been run to set the LFS push endpoint
for read-write access; this is in .git/config in the repository root,
which is not under version control and therefore is not committed.

Please review the changes relative to the initial state, and if you
like what you see, prepare to do a `git push`.

In order to do the `git push`, you will need the Git LFS push token
you earlier acquired from Gafaelfawr.  When prompted, use the name you
authenticated to Gafaelfawr with as the username, and that token as
the password.

Probably as soon as you've successfully done the push, you want to PR
and merge the changes to your default branch, so that no one else does
a push to the old repository.

Note that collaborators (or you, if you do this from a different copy
of the repository) will need to manually run:

`git config lfs.url https://git-lfs-dev-rw.lsst.cloud/owner/testrepo`
before pushing.
"""
    ).lstrip()
    captured = capsys.readouterr()
    assert captured.out == expected
