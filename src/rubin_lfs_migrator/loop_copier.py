#!/usr/bin/env python3

import asyncio
import os
from typing import Any
from urllib.parse import ParseResult

from .looper import Looper
from .obj_copier import ObjectCopier
from .parser import parse
from .util import str_bool


class LoopCopier(Looper):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._branch_pattern = kwargs.pop("branch_pattern")
        self._temporary_branch = kwargs.pop("temporary_branch")
        super().__init__(*args, **kwargs)

    async def _migrate_repo(self, repo: ParseResult) -> None:
        """Failure to anticipate extension; want to use superclass loop()."""
        await self._copy_repo(repo)

    async def _copy_repo(self, repo: ParseResult) -> None:
        target, owner, repo_name = await self._download_repo(repo)
        copier = ObjectCopier(
            directory=str(target),
            owner=owner,
            repository=repo_name,
            branch_pattern=self._branch_pattern,
            temporary_branch=self._temporary_branch,
            original_lfs_url=self._original_lfs_url,
            lfs_base_url=self._lfs_base_url,
            lfs_base_write_url=self._lfs_base_write_url,
            migration_branch=self._migration_branch,
            source_branch=self._source_branch,
            dry_run=self._dry_run,
            quiet=self._quiet,
            debug=self._debug,
        )
        self._logger.debug(f"Performing object copy for {repo.geturl()}")
        await copier.execute()
        m_rpt = f"Object copy complete for {repo.geturl()}"
        if self._cleanup:
            await self._cleanup_target(target)
            m_rpt += f"; cleaned up {str(target)}"
        m_rpt += "."
        self._paragraphs.append(m_rpt)


def main() -> None:
    looper = _create_looper()
    asyncio.run(looper.loop())


def _create_looper() -> Looper:
    parser = parse(description="Migrate multiple repositories")
    # Now the loop-specific ones
    parser.add_argument(
        "-f",
        "--file",
        "--input-file",
        default=os.environ.get("LFSMIGRATOR_INPUT_FILE", "-"),
        help="input file of repositories [env: LFSMIGRATOR_INPUT_FILE, '']",
    )
    parser.add_argument(
        "-t",
        "--top-dir",
        default=os.environ.get("LFSMIGRATOR_TOP_DIR", "."),
        help="top directory for repo checkout [env: LFSMIGRATOR_TOP_DIR, '.']",
    )
    parser.add_argument(
        "-c",
        "--cleanup",
        default=str_bool(os.environ.get("LFSMIGRATOR_CLEANUP", "")),
        action="store_true",
        help="clean up repo directories [env: LFSMIGRATOR_CLEANUP, False]",
    )
    parser.add_argument(
        "--branch-pattern",
        default=os.environ.get("LFSMIGRATOR_BRANCH_PATTERN", r"V\d\d.*"),
        help=(
            "branch pattern to match for copy [env: "
            "LFSMIGRATOR_BRANCH_PATTERN, '"
            r"v\d\d.*"
            "']"
        ),
    )
    parser.add_argument(
        "--temporary-branch",
        default=os.environ.get(
            "LFSMIGRATOR_TEMPORARY_BRANCH", "trash-never-merge"
        ),
        help=(
            "branch for temporary changes to push LFS contents [env: "
            "LFSMIGRATOR_TEMPORARY_BRANCH, 'trash-never-merge']"
        ),
    )
    args = parser.parse_args()
    return Looper(
        input_file=args.file,
        top_dir=args.top_dir,
        original_lfs_url=args.original_lfs_url,
        lfs_base_url=args.lfs_base_url,
        lfs_base_write_url=args.lfs_base_write_url,
        migration_branch=args.migration_branch,
        source_branch=args.source_branch,
        dry_run=args.dry_run,
        cleanup=args.cleanup,
        quiet=args.quiet,
        debug=args.debug,
    )


if __name__ == "__main__":
    main()
