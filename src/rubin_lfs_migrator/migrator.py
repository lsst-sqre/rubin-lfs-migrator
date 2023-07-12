import argparse
import asyncio
import logging
import os
#import shlex
#import shutil
import subprocess
#import time
from git.exc import InvalidGitRepositoryError
from pathlib import Path
from typing import Union
from urllib.parse import urlparse, ParseResult

class Migrator:
    """The class that modifies LFS config to migrate LFS contents to a new
    git-LFS backend.
    """

    def __init__(self, directory: Path, lfs_base_url: ParseResult,
                 lfs_base_write_url: ParseResult, dry_run: bool,
                 debug: bool) -> None:
        self._dir = directory
        self._url = lfs_base_url
        self._write_url = lfs_base_write_url
        self._dry_run = dry_run
        self._debug = debug
        self._logger = logging.getLogger(__name__)
        ch = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        ch.setFormatter(formatter)
        self._logger.addHandler(ch)
        self._logger.setLevel("INFO")
        if self._debug:
            self._logger.setLevel("DEBUG")
            self._logger.debug("Debugging enabled for Migrator")
        self.commands: list[str] = []  # Exposed for testing

        self._repo=_check_repo(directory)
        self._lfs_files: list[Path] = []

    def _check_repo(self) -> git.Repo:
        try:
            repo = git.Repo(self._dir)
        except InvalidGitRepositoryError:
            raise RuntimeError(f"{self._dir} is not a git repository")
        tree = repo.head.commit.tree
        try:
            _ = tree / ".gitattributes"
        except KeyError:
            raise RuntimeError(f"{self._dir}/.gitattributes not found")
        try:
            _ = tree / ".lfsconfig"
        except KeyError:
            raise RuntimeError(f"{self._dir}/.lfsconfig not found")
        return repo
    
    async def execute(self) -> None:
        """execute() is the only public method.  It performs the git
        operations necessary to migrate the Git LFS content (or, if
        dry_run is enabled, just logs the operations).
        """
        await self._checkout_migration_branch()
        await self._get_lfs_file_list()
        if not self._lfs_files:
            self._logger._warning("No LFS-managed files found")
            return
        await self._remove_and_readd()
        await self._rewrite_lfsconfig()

        

    async def _checkout_migration_branch(self) -> None:
        repo = self._repo
        ref = repo.head.ref
        # Create a new branch, and error if that branch was already current.
        mig_br = repo.create_head("migration")
        if r.active_branch == mig_br:
            raise RuntimeError(f"'migration' branch is already current")
        self._logger.debug("Checking out 'migration' branch")
        mig_br.checkout()

    async def _get_config(self) -> None:
        pass

    async def _update_lfsconfig(self) -> None:
        pass

    async def _get_lfs_file_list(self) -> list[Path]:
        files: list[Path] = []
        lfscfgblob = self._repo.head.commit.tree / ".gitattributes"
        lfscfgpath = lfscfgblob.abspath
        with open(lfscfgpath, "r") as f:
            for l in f:
                fields = l.strip().split()
                if not await self._is_lfs_attribute(fields):
                    continue
                files.extend(await self._find_lfs_files(fields[0]))
        self._lfs_files = files
                    
    async def _is_lfs_attribute(fields: list[str]) -> bool:
        # It's not clear that this is ever really formalized, but in
        # each case I've seen, "filter", "diff", and "merge" are set
        # to "lfs", and it's not a binary file ("-text").
        # This might need changing sometime?
        notext = fields[-1]
        if notext != "-text":
            self._logger.debug(f"{' '.join(fields)} does not end with '-text'")
            return False
        mids = fields[1:-1]
        ok_flds = ( "filter", "diff", "merge")
        for m in mids:
            k, v = m.split("=")
            if k not in ok_flds:
                self._logger.debug(f"{k} not in {ok_flds}")
                return False
            if v != "lfs":
                self._logger.debug(f"{k} is '{v}', not 'lfs'")
                return False
        return True
            
    async def _find_lfs_files(match: str) -> list[Path]:
        # The .gitattributes file is defined at:
        # https://git-scm.com/docs/gitattributes
        #
        # Those can be in arbitrary directories and only concern things at
        # or below their own directory.
        #
        # We're going to initially use a simpler heuristic, which I
        # think is true for all Rubin repositories using LFS, and
        # quite possibly for LFS repos in general.
        #
        # We assume that you have only one gitattributes file and it is in
        # <repo_root>.gitattributes
        #
        # So...if it starts with "**/" we leave it alone, and if it starts
        # with "/" we strip the slash (and find the glob just in the current
        # directory), and if anything else, we prepend "**/" to it.
        #
        # This might be wrong and may need tweaking.
        if not match.startswith("/") and not match.startswith("**/"):
            match = "**/" + match
        files = list(self._dir.glob(match))
        self._logger.debug(f"{match} -> {files}")
        return files

    async def _remove_and_readd(self) -> None:
        idx = self._repo.index
        num_files = len(self._lfs_files)
        if self._dry_run:
            self._logger.info(
                f"Would remove/readd the following {num_files} files: {self._lfs_files}"
            )
            return
        self._logger.debug(f"Removing {num_files} files from index")
        idx.remove(self._lfs_files, cached=True)
        msg = f"Removed {num_files} LFS files from index"
        self._logger.debug(f"Committing change")
        idx.commit(msg)
        self._logger.debug(f"Adding {num_files} files to index")
        idx.add(self._lfs_files)
        msg = f"Added {num_files} LFS files to index"
        idx.commit(msg)
        
    
    async def _run(
        self, args: list[str], check: bool = False, dry_run: bool = False
    ) -> subprocess.CompletedProcess:
        """Not clear how much is going to be handled in GitPython versus
        CLI yet.
        """
        cmd = " ".join(args)
        self.commands.append(args)
        if dry_run:
            self._logger.info(f"Would run command '{cmd}'")
            # Pretend it succeeded
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=None,
                stderr=None,
            )
        self._logger.debug(f"Running command '{cmd}'")
        proc = subprocess.run(args, capture_output=True, check=check)
        if proc.returncode != 0:
            self._logger.warning(
                f"Command '{cmd}' failed: rc {proc.returncode}\n"
                + f" -> stdout: {proc.stdout.decode()}\n"
                f" -> stderr: {proc.stderr.decode()}"
            )
        else:
            self._logger.debug(
                f"Command '{cmd}' succeeded\n"
                + f" -> stdout: {proc.stdout.decode()}\n"
                f" -> stderr: {proc.stderr.decode()}"
            )
        return proc

    async def _rewrite_lfsconfig(self) -> None:
        tree = self._repo.head.commit.tree
        lfscfgblob = tree / ".lfsconfig"
        lfscfgfile = lfscfgblob.abspath
        cfg_writer = git.config.GitConfigParser(lfscfgfile, read_only=False)
        url = self.
        

def _str_bool(inp: str) -> bool:
    inp = inp.upper()
    if not inp or inp == "0" or inp.startswith("F") or inp.startswith("N"):
        return False
    return True

def _path(str_path: str) -> Path:
    # Gets us syntactic validation for free, except that there's not much
    # that would be an illegal path other than 0x00 as a character in it.
    return Path(str)

def _url(str_url: str) -> ParseResult:
    # Again, gets us syntactic validation for free
    return parse(str_url)

def get_migrator() -> Migrator:
    """
    Parse arguments and return the migrator for that repository.  Exposed for
    testing.
    """
    parser = argparse.ArgumentParser(description="Migrate a Git LFS repo")
    parser.add_argument(
        "-i",
        "--directory",
        "--input-dir",
        type=_path,
        default=_path(os.environ.get("LFSMIGRATOR_DIR", ".")),
        help="directory of repo to migrate [env: LFSMIGRATOR_DIR, '.']",
    )
    parser.add_argument(
        "-b",
        "--lfs-base-url",
        type=_url,
        default=_url(os.environ.get("LFSMIGRATOR_BASE_URL",
                               "https://git-lfs-dev.lsst.cloud")),
        help="base URL of new Git LFS implementation [env: LFSMIGRATOR_BASE_URL, 'https://git-lfs-dev.lsst.cloud']",
    )
    parser.add_argument(
        "-w",
        "--lfs-base-write-url",
        type=_url,
        default=_url(os.environ.get("LFSMIGRATOR_BASE_WRITE_URL",
                                    "https://git-lfs-dev-rw.lsst.cloud")),
        help="base URL of write endpoint of new Git LFS implementation [env: LFSMIGRATOR_BASE_WRITE_URL, 'https://git-lfs-dev-rw.lsst.cloud']",
    )
    parser.add_argument(
        "-x",
        "--dry-run",
        action="store_true",
        default=_str_bool(os.environ.get("LFSMIGRATOR_DRY_RUN", "")),
        help="dry run (do not execute) [env: LFSMIGRATOR_DRY_RUN, False]",
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        default=_str_bool(os.environ.get("LFSMIGRATOR_DEBUG", "")),
        help="enable debugging [env: LFSMIGRATOR_DEBUG, False]",
    )
    args = parser.parse_args()

    return Migrator(
        directory=args.directory,
        lfs_base_url=args.lfs_base_url,
        lfs_base_write_url=args.lfs_base_write_url,
        dry_run=args.lfs_dry_run,
        debug=args.debug,
    )

def main():
    mgr = get_migrator()
    asyncio.run(mgr.execute())

if __name__ == "__main__":
    main()
