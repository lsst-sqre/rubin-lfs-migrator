#!/usr/bin/env python3
import asyncio
import contextlib
import fileinput
import logging
import os
import textwrap
from pathlib import Path
from shutil import rmtree
from urllib.parse import ParseResult

from git import Repo

from .external import check_exe, run
from .migrator import Migrator
from .parser import parse
from .util import str_bool, url


class Looper:
    def __init__(
        self,
        input_file: str,
        top_dir: str,
        original_lfs_url: str,
        lfs_base_url: str,
        lfs_base_write_url: str,
        migration_branch: str,
        source_branch: str | None,
        dry_run: bool,
        cleanup: bool,
        quiet: bool,
        debug: bool,
    ) -> None:
        self._dir = Path(top_dir).resolve()
        self._file = input_file
        self._original_lfs_url = original_lfs_url
        self._lfs_base_url = lfs_base_url
        self._lfs_base_write_url = lfs_base_write_url
        self._migration_branch = migration_branch
        self._source_branch = source_branch
        self._dry_run = dry_run
        self._cleanup = cleanup
        self._quiet = quiet
        self._debug = debug
        self._logger = logging.getLogger(__name__)
        ch = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        ch.setFormatter(formatter)
        self._logger.addHandler(ch)
        self._logger.setLevel("INFO")
        if self._quiet:
            self._logger.setLevel("CRITICAL")
        if self._debug:
            self._logger.setLevel("DEBUG")
            self._logger.debug("Debugging enabled for Looper")
        self._has_gh = check_exe("gh")
        self._paragraphs: list[str] = []

    async def loop(self) -> None:
        inputs: tuple[str, ...] | None = None
        if self._file != "-":
            inputs = tuple([self._file])
        with fileinput.input(inputs) as f:
            for ln in f:
                # Look for comments and ignore anything after '#'
                m_p = ln.find("#")
                if m_p != -1:
                    ln = ln[:m_p]
                # Strip whitespace
                ln = ln.strip()
                # Strip '.git' from end if it's there
                if ln.endswith(".git"):
                    ln = ln[:-4]
                # Anything left?
                if not ln:
                    continue
                repo_url = url(ln)
                if repo_url.scheme != "https":
                    self._logger.warning(
                        "Repository URL scheme must be 'https', not "
                        + f"{repo_url.scheme}; skipping {repo_url}"
                    )
                    continue
                await self._migrate_repo(repo_url)
        await self._report()

    async def _migrate_repo(self, repo: ParseResult) -> None:
        target, owner, repo_name = await self._download_repo(repo)
        migrator = Migrator(
            directory=str(target),
            owner=owner,
            repository=repo_name,
            original_lfs_url=self._original_lfs_url,
            lfs_base_url=self._lfs_base_url,
            lfs_base_write_url=self._lfs_base_write_url,
            migration_branch=self._migration_branch,
            source_branch=self._source_branch,
            dry_run=self._dry_run,
            quiet=self._quiet,
            debug=self._debug,
        )
        self._logger.debug(f"Performing migration for {repo.geturl()}")
        await migrator.execute()
        m_rpt = f"Migration complete for {repo.geturl()}"
        if self._has_gh:
            self._logger.debug(f"Creating PR for {repo.geturl()}")
            pr_rpt = await self._create_pr(repo, target)
            m_rpt += f"; PR available at {pr_rpt}"
        if self._cleanup:
            await self._cleanup_target(target)
            m_rpt += f"; cleaned up {str(target)}"
        m_rpt += "."
        self._paragraphs.append(m_rpt)

    async def _download_repo(self, repo: ParseResult) -> tuple[Path, str, str]:
        path_parts = repo.path.split("/")
        repo_name = path_parts[-1]
        owner = path_parts[-2]
        target = await self._create_target_dir(owner, repo_name)
        # Do the actual clone
        await self._clone_repo(repo.geturl(), target)
        return target, owner, repo_name

    async def _clone_repo(self, repo: str, target: Path) -> None:
        if self._dry_run:
            self._logger.info(f"Would clone '{repo}' to '{target}'")
            return
        self._logger.debug(f"Cloning '{repo}' to '{target}'")
        if self._source_branch is None:
            Repo.clone_from(repo, target)
        else:
            Repo.clone_from(repo, target, branch=self._source_branch)

    async def _create_target_dir(self, owner: str, repo_name: str) -> Path:
        target = Path(self._dir / owner / repo_name)
        if self._dry_run:
            self._logger.info(f"Would create directory '{target}'")
            return target
        self._logger.debug(f"Creating directory '{target}'")
        if not Path(self._dir / owner).is_dir():
            Path.mkdir(self._dir / owner)
        # Explode if target is already there
        Path.mkdir(target)
        return target

    async def _create_pr(self, repo: ParseResult, target: Path) -> str:
        with contextlib.chdir(target):
            url = repo.geturl()
            self._logger.debug("Creating PR for LFS migration changes.")
            cmd = ["gh", "repo", "set-default", url]
            result = run(cmd, logger=self._logger, timeout=60)
            if result.rc != 0:
                raise RuntimeError(
                    f"Repo default setting failed with rc={result.rc}: "
                    + f"{result.stderr}"
                )
            cmd = ["gh", "pr", "create", "-t", "Git LFS migration", "-b", ""]
            if self._source_branch is not None:
                cmd.extend(["-B", self._source_branch])
            result = run(cmd, logger=self._logger, timeout=60)
            if result.rc != 0:
                raise RuntimeError(
                    f"PR creation failed, rc={result.rc}: {result.stderr}"
                )
            rlines = [
                y for y in [x.strip() for x in result.stdout.split("\n")] if y
            ]
            lastline = rlines[-1]
            self._logger.info(f"PR for {url} succeeded: {lastline}.")
            return lastline

    async def _cleanup_target(self, target: Path) -> None:
        if self._dry_run:
            self._logger.info(f"Would remove '{target}'")
        else:
            self._logger.debug(f"Removing '{target}'")
            rmtree(target)

    async def _report(self) -> None:
        alignedps = [textwrap.dedent(x) for x in self._paragraphs]
        text = "\n\n".join([textwrap.fill(x).lstrip() for x in alignedps])
        print(text)


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
        help="clean up repo directories [env: LFSMIGRATOR_CLEANUP, False]",
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
