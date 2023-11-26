#!/usr/bin/env python3

import asyncio
import os
from typing import Any
from urllib.parse import ParseResult

from .loop_copier import LoopCopier
from .oid_mapper import OidMapper
from .parser import parse
from .util import str_bool


class LoopOidMapper(LoopCopier):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._output_dir = kwargs.pop("output_dir")
        self._full_map = kwargs.pop("full_map")
        super().__init__(*args, **kwargs)

    async def _execute(self, repo: ParseResult) -> None:
        target, owner, repo_name = await self._download_repo(repo)
        mapper = OidMapper(
            directory=str(target),
            owner=owner,
            repository=repo_name,
            output_dir=self._output_dir,
            full_map=self._full_map,
            branch_pattern=self._branch_pattern,
            temporary_branch=self._temporary_branch,
            report_file=self._report_file,
            original_lfs_url=self._original_lfs_url,
            lfs_base_url=self._lfs_base_url,
            lfs_base_write_url=self._lfs_base_write_url,
            migration_branch=self._migration_branch,
            source_branch=self._source_branch,
            dry_run=self._dry_run,
            quiet=self._quiet,
            debug=self._debug,
        )
        self._logger.debug(f"Performing OID map for {repo.geturl()}")
        await mapper.execute()
        m_rpt = f"OID map complete for {repo.geturl()}"
        if self._cleanup:
            await self._cleanup_target(target)
            m_rpt += f"; cleaned up {str(target)}"
        m_rpt += "."
        self._paragraphs.append(m_rpt)


def main() -> None:
    oid_mapper = _create_oid_mapper()
    asyncio.run(oid_mapper.loop())


def _create_oid_mapper() -> LoopOidMapper:
    parser = parse(description="Map OIDs across repositories")
    # Now the loop-specific ones
    parser.add_argument(
        "-f",
        "--file",
        "--input-file",
        default=os.environ.get("LFSMIGRATOR_INPUT_FILE", "-"),
        help="input file of repositories [env: LFSMIGRATOR_INPUT_FILE, '-']",
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
    #
    # And the copier-specific ones.
    #
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
    parser.add_argument(
        "--output-dir",
        default=os.environ.get("LFSMIGRATOR_OUTPUT_DIR", "."),
        help="output directory for OID data in JSON format",
    )
    parser.add_argument(
        "--full-map",
        action="store_true",
        default=str_bool(os.environ.get("LFSMIGRATOR_FULL_MAP", "")),
        help=(
            "generate full OID map for repo [env: "
            "LFSMIGRATOR_FULL_MAP, False]"
        ),
    )
    args = parser.parse_args()
    return LoopOidMapper(
        output_dir=args.output_dir,
        full_map=args.full_map,
        input_file=args.file,
        top_dir=args.top_dir,
        original_lfs_url=args.original_lfs_url,
        lfs_base_url=args.lfs_base_url,
        lfs_base_write_url=args.lfs_base_write_url,
        branch_pattern=args.branch_pattern,
        migration_branch=args.migration_branch,
        source_branch=args.source_branch,
        temporary_branch=args.temporary_branch,
        report_file=args.report_file,
        dry_run=args.dry_run,
        cleanup=args.cleanup,
        quiet=args.quiet,
        debug=args.debug,
    )


if __name__ == "__main__":
    main()
