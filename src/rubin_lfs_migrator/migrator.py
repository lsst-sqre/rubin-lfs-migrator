import argparse
import asyncio
import logging
import os
import textwrap
from pathlib import Path
from urllib.parse import ParseResult, urlparse

from git import GitConfigParser, Repo  # type: ignore [attr-defined]
from git.exc import InvalidGitRepositoryError


class Migrator:
    """The class that modifies LFS config to migrate LFS contents to a new
    git-LFS backend.
    """

    def __init__(
        self,
        directory: str,
        lfs_base_url: str,
        lfs_base_write_url: str,
        dry_run: bool,
        quiet: bool,
        debug: bool,
    ) -> None:
        self._dir = Path(directory)
        self._dry_run = dry_run
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
        if self._debug:
            self._logger.setLevel("DEBUG")
            self._logger.debug("Debugging enabled for Migrator")
        self._check_repo()
        self._url = f"{lfs_base_url}/{self._owner}/{self._name}"
        self._write_url = f"{lfs_base_write_url}/{self._owner}/{self._name}"

        self._lfs_files: list[Path] = []

    def _check_repo(self) -> None:
        try:
            repo = Repo(self._dir)
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
        self._repo = repo
        # Set owner and name too
        self._owner = repo.remotes.origin.url.split(".git")[0].split("/")[-2]
        self._name = repo.remotes.origin.url.split(".git")[0].split("/")[-1]

    async def execute(self) -> None:
        """execute() is the only public method.  It performs the git
        operations necessary to migrate the Git LFS content (or, if
        dry_run is enabled, just logs the operations).
        """
        await self._checkout_migration_branch()
        await self._get_lfs_file_list()
        if not self._lfs_files:
            self._logger.warning("No LFS-managed files found")
            return
        await self._remove_and_readd()
        await self._update_lfsconfig()
        await self._update_config()
        await self._report()

    async def _checkout_migration_branch(self) -> None:
        """We will perform changes on the "migration" branch.  If that is
        already the current branch, complain vociferously and exit."""
        repo = self._repo
        mig_br = repo.create_head("migration")
        if repo.active_branch == mig_br:
            raise RuntimeError("'migration' branch is already current")
        self._logger.debug("Checking out 'migration' branch")
        mig_br.checkout()

    async def _get_lfs_file_list(self) -> None:
        """Assemble the list of LFS-managed files by interpreting the
        .gitattributes file in the repo root."""
        files: list[Path] = []
        attrblob = self._repo.head.commit.tree / ".gitattributes"
        attrpath = attrblob.abspath
        with open(attrpath, "r") as f:
            for line in f:
                fields = line.strip().split()
                if not await self._is_lfs_attribute(fields):
                    continue
                files.extend(await self._find_lfs_files(fields[0]))
        self._lfs_files = files

    async def _is_lfs_attribute(self, fields: list[str]) -> bool:
        """
        It's not clear that this is ever really formalized, but in
        each case I've seen, "filter", "diff", and "merge" are set
        to "lfs", and it's not a binary file ("-text").  I think that's
        just  what `git lfs track` does, but whether it's documented, I
        don't know.
        """
        notext = fields[-1]
        if notext != "-text":
            self._logger.debug(f"{' '.join(fields)} does not end with '-text'")
            return False
        mids = fields[1:-1]
        ok_flds = ("filter", "diff", "merge")
        for m in mids:
            k, v = m.split("=")
            if k not in ok_flds:
                self._logger.debug(f"{k} not in {ok_flds}")
                return False
            if v != "lfs":
                self._logger.debug(f"{k} is '{v}', not 'lfs'")
                return False
        return True

    async def _find_lfs_files(self, match: str) -> list[Path]:
        """
        The .gitattributes file is defined at:
        https://git-scm.com/docs/gitattributes

        Those can be in arbitrary directories and only concern things at
        or below their own directory.

        We're going to initially use a simpler heuristic, which I
        think is true for all Rubin repositories using LFS, and
        quite possibly for LFS repos in general.

        We assume that there is only one gitattributes file and it is in
        <repo_root>.gitattributes

        If it starts with "**/" we leave it alone, and if it starts
        with "/" we strip the slash (and find the glob just in the current
        directory), and if anything else, we prepend "**/" to it.

        This might be wrong and may need tweaking.
        """
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
                f"Would remove/readd the following {num_files} "
                + f"files: {self._lfs_files}"
            )
            return
        self._logger.debug(f"Removing {num_files} files from index")
        idx.remove(self._lfs_files, cached=True)
        msg = f"Removed {num_files} LFS files from index"
        self._logger.debug("Committing removal change")
        idx.commit(msg)
        self._logger.debug(f"Adding {num_files} files to index")
        idx.add(self._lfs_files)
        msg = f"Added {num_files} LFS files to index"
        self._logger.debug("Committing re-add change")
        idx.commit(msg)

    async def _report(self) -> None:
        if self._quiet:
            return
        text = (
            """
            LFS migration has been performed on the `migration`
            branch of the {self._owner}/{self._name} repository.
            Changes to remove and re-add the Git LFS objects, to
            update the LFS read-only pull URL, and to disable lock
            verification have been committed.

            Additionally, `git config` has been run to set the LFS
            push endpoint for read-write access; this is in
            .git/config in the repository root, which is not under
            version control and therefore is not committed.

            Please review the changes relative to the initial state,
            and if you like what you see, prepare to do a `git push`.

            You will have to install Git LFS locally: see
            """
            + "https://docs.github.com/en/repositories/working-with-files/"
            + "managing-large-files/installing-git-large-file-storage"
            + """
            In order to do the `git push`, you will need the Git LFS
            push token you earlier acquired from Gafaelfawr.  When
            prompted, use the name you authenticated to Gafaelfawr
            with as the username, and that token as the password.

            Probably as soon as you've successfully done the push, you
            want to PR and merge the changes to your default branch,
            so that no one else does a push to the old repository.

            Note that collaborators (or you, if you do this from a
            different copy of the repository) will need to manually
            run `git config lfs.url {self._write_url}` before pushing.
            """
        )
        print(textwrap.fill(f"{text}"))

    async def _update_lfsconfig(self) -> None:
        """Set read URL for LFS objects and disable lock verification."""
        if self._dry_run:
            self._logger.info("Would set .lfsconfig lfs.url to {read_url}")
            self._logger.info("Would set .lfsconfig lfs.locksverify to False")
            return
        lfscfgblob = self._repo.head.commit.tree / ".lfsconfig"
        lfscfgpath = lfscfgblob.abspath
        cfg = GitConfigParser(lfscfgpath, read_only=False)
        cfg.set("lfs", "url", self._url)
        cfg.set("lfs", "locksverify", "false")
        idx = self._repo.index
        idx.commit(f"Set lfs.url to {self._url} and disable lock verification")

    async def _update_config(self) -> None:
        """Set URL for pushing in .git/config (which is not under
        version control, hence not commitable)."""
        if self._dry_run:
            self._logger.info("Would set .git/config lfs.url to {write_url}")
            return
        cfgblob = self._repo.head.commit.tree / ".git" / "config"
        cfgpath = cfgblob.abspath
        cfg = GitConfigParser(cfgpath, read_only=False)
        cfg.set("lfs", "url", self._write_url)
        # No commit: see above


def _str_bool(inp: str) -> bool:
    inp = inp.upper()
    if not inp or inp == "0" or inp.startswith("F") or inp.startswith("N"):
        return False
    return True


def _path(str_path: str) -> Path:
    # Gets us syntactic validation for free, except that there's not much
    # that would be an illegal path other than 0x00 as a character in it.
    return Path(str_path)


def _url(str_url: str) -> ParseResult:
    # Again, gets us syntactic validation for free
    return urlparse(str_url)


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
        default=os.environ.get("LFSMIGRATOR_DIR", "."),
        help="directory of repo to migrate [env: LFSMIGRATOR_DIR, '.']",
    )
    parser.add_argument(
        "-b",
        "--lfs-base-url",
        default=os.environ.get(
            "LFSMIGRATOR_BASE_URL", "https://git-lfs-dev.lsst.cloud"
        ),
        help=(
            "base URL of new Git LFS implementation "
            + "[env: LFSMIGRATOR_BASE_URL, 'https://git-lfs-dev.lsst.cloud']"
        ),
    )
    parser.add_argument(
        "-w",
        "--lfs-base-write-url",
        default=os.environ.get(
            "LFSMIGRATOR_BASE_WRITE_URL",
            "https://git-lfs-dev-rw.lsst.cloud",
        ),
        help=(
            "base URL of write endpoint of new Git LFS implementation "
            + "[env: LFSMIGRATOR_BASE_WRITE_URL, "
            + "'https://git-lfs-dev-rw.lsst.cloud']"
        ),
    )
    parser.add_argument(
        "-x",
        "--dry-run",
        action="store_true",
        default=_str_bool(os.environ.get("LFSMIGRATOR_DRY_RUN", "")),
        help="dry run (do not execute) [env: LFSMIGRATOR_DRY_RUN, False]",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=_str_bool(os.environ.get("LFSMIGRATOR_QUIET", "")),
        help="enable debugging [env: LFSMIGRATOR_QUIET, False]",
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
        dry_run=args.dry_run,
        debug=args.debug,
    )


def main() -> None:
    mgr = get_migrator()
    asyncio.run(mgr.execute())


if __name__ == "__main__":
    main()
