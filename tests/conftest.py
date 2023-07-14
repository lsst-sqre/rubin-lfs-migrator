import tarfile
from pathlib import Path

import pytest

from rubin_lfs_migrator import Migrator


@pytest.fixture
def directory(tmp_path_factory: pytest.TempPathFactory) -> Path:
    tmpdir = tmp_path_factory.mktemp("repo")
    contents = Path(Path(__file__).parent / "inputs" / "testrepo.tar.gz")
    repotar = tarfile.open(contents)
    repotar.extractall(tmpdir)
    return Path(tmpdir / "testrepo")


@pytest.fixture
def migrator(directory: Path) -> Migrator:
    mgr = Migrator(
        directory=str(directory),
        lfs_base_url="https://git-lfs-dev.lsst.cloud",
        lfs_base_write_url="https://git-lfs-dev-rw.lsst.cloud",
        dry_run=False,
        quiet=False,
        debug=True,
    )
    return mgr
