"""Shared parser for migrator/loop"""
import argparse
import os

from .util import str_bool


def parse(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "-m",
        "--migration-branch",
        default=os.environ.get(
            "LFSMIGRATOR_MIGRATION_BRANCH", "lfs-migration"
        ),
        help=(
            "migration git branch [env: LFSMIGRATOR_MIGRATION_BRANCH, "
            + " 'lfs-migration']"
        ),
    ),
    parser.add_argument(
        "-s",
        "--source-branch",
        default=os.environ.get("LFSMIGRATOR_SOURCE_BRANCH", None),
        help=(
            "source git branch [env: LFSMIGRATOR_SOURCE_BRANCH, "
            + " <repo default branch>]"
        ),
    ),
    parser.add_argument(
        "-b",
        "--lfs-base-url",
        default=os.environ.get(
            "LFSMIGRATOR_BASE_URL", "https://git-lfs.lsst.cloud"
        ),
        help=(
            "base URL of new Git LFS implementation "
            + "[env: LFSMIGRATOR_BASE_URL, 'https://git-lfs.lsst.cloud']"
        ),
    )
    parser.add_argument(
        "-w",
        "--lfs-base-write-url",
        default=os.environ.get(
            "LFSMIGRATOR_BASE_WRITE_URL",
            "https://git-lfs-rw.lsst.cloud",
        ),
        help=(
            "base URL of write endpoint of new Git LFS implementation "
            + "[env: LFSMIGRATOR_BASE_WRITE_URL, "
            + "'https://git-lfs-rw.lsst.cloud']"
        ),
    )
    parser.add_argument(
        "-o",
        "--original-lfs-url",
        "--orig-lfs-url",
        default=os.environ.get(
            "LFSMIGRATOR_ORIGINAL_LFS_URL", "https://git-lfs.lsst.codes"
        ),
        help=(
            "Original Git LFS URL [env: LFSMIGRATOR_ORIGINAL_URL, "
            + "'https://git-lfs.lsst.codes']"
        ),
    )
    parser.add_argument(
        "--report-file",
        default=os.environ.get("LFSMIGRATOR_REPORT_FILE", "-"),
        help=("Report output file [env: LFSMIGRATOR_REPORT_FILE, '-']"),
    )
    parser.add_argument(
        "-x",
        "--dry-run",
        action="store_true",
        default=str_bool(os.environ.get("LFSMIGRATOR_DRY_RUN", "")),
        help="dry run (do not execute) [env: LFSMIGRATOR_DRY_RUN, False]",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=str_bool(os.environ.get("LFSMIGRATOR_QUIET", "")),
        help="enable debugging [env: LFSMIGRATOR_QUIET, False]",
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        default=str_bool(os.environ.get("LFSMIGRATOR_DEBUG", "")),
        help="enable debugging [env: LFSMIGRATOR_DEBUG, False]",
    )
    return parser
