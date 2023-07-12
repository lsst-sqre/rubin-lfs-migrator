import pytest

import rubin_lfs_migrator


def test_trivial() -> None:
    """The test directory isn't a git repo, and the parent repo isn't an
    LFS repository.
    """
    with pytest.raises(RuntimeError):
        _ = rubin_lfs_migrator.Migrator(
            directory=".",
            lfs_base_url="https://git-lfs-dev.lsst.cloud",
            lfs_base_write_url="https://git-lfs-dev-rw.lsst.cloud",
            dry_run=True,
            quiet=False,
            debug=True,
        )
