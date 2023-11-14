import asyncio
import contextlib
import logging
import os
import textwrap
from pathlib import Path

from git import GitConfigParser, Repo

from .parser import parse


class Migrator:
    """The class that modifies LFS config and workflows to migrate LFS
    contents to a new git-LFS backend.  It expects to start with the
    repository contents in an already-cloned directory on the default branch.

    The `Looper` class will do that clone, running against a list of
    repositories to migrate.
    """

    def __init__(
        self,
        directory: str,
        owner: str,
        repository: str,
        lfs_base_url: str,
        lfs_base_write_url: str,
        original_lfs_url: str,
        migration_branch: str,
        dry_run: bool,
        quiet: bool,
        debug: bool,
    ) -> None:
        self._dir = Path(directory).resolve()
        if not Path(self._dir / ".git").is_dir():
            raise RuntimeError(
                f"{directory} must contain a cloned git repository"
            )
        self._repo = Repo(self._dir)
        self._owner = owner
        self._name = repository
        self._original_lfs_url = original_lfs_url
        self._migration_branch = migration_branch
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

        self._url = f"{lfs_base_url}/{self._owner}/{self._name}"
        self._write_url = f"{lfs_base_write_url}/{self._owner}/{self._name}"

        self._lfs_files: list[Path] = []
        self._wf_files: list[Path] = []

    async def execute(self) -> None:
        """execute() is the only public method.  It performs the git
        operations necessary to migrate the Git LFS content (or, if
        dry_run is enabled, just logs the operations).
        """
        with contextlib.chdir(self._dir):
            await self._get_lfs_file_list()
            await self._get_wf_files()
            if not self._lfs_files and not self._wf_files:
                self._logger.warning(
                    "Neither LFS-managed files nor workflows referencing "
                    + "LFS objects found.  Nothing to do."
                )
                return
            await self._checkout_migration_branch()
            if self._lfs_files:
                await self._update_lfsconfig()
                await self._remove_and_readd()
            if self._wf_files:
                await self._update_workflow_files()
            await self._report()

    async def _checkout_migration_branch(self) -> None:
        """We will perform changes on the migration branch.  If that is
        already the current branch, complain vociferously and exit."""
        if self._dry_run:
            self._logger.info(
                f"Would check out '{self._migration_branch}' branch."
            )
            return
        repo = self._repo
        mig_br = repo.create_head(self._migration_branch)
        if repo.active_branch == mig_br:
            raise RuntimeError(
                f"'{self._migration_branch}' branch is already current"
            )
        self._logger.debug(f"Checking out '{self._migration_branch}' branch")
        mig_br.checkout()

    async def _get_lfs_file_list(self) -> None:
        """Assemble the list of LFS-managed files by interpreting the
        .gitattributes file in the repo root."""
        files: list[Path] = []
        with open(".gitattributes", "r") as f:
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
        client = self._repo.git
        num_files = len(self._lfs_files)
        if self._dry_run:
            self._logger.info(
                f"Would remove/readd the following {num_files} "
                + f"files: {self._lfs_files}"
            )
            return
        orig_dir = Path(os.getcwd())
        if orig_dir != self._dir:
            self._logger.debug(f"Changing directory to {str(self._dir)}")
            os.chdir(self._dir)
        self._logger.debug(f"Removing {num_files} files from index")
        self._logger.debug(f"Setting LFS URL to {self._write_url}")
        cfg = self._repo.config_writer()
        cfg.set("lfs", "url", self._write_url)
        str_files = [str(x) for x in self._lfs_files]
        client.rm("--cached", *str_files)
        msg = f"Removed {num_files} LFS files from index"
        self._logger.debug("Committing removal change")
        client.commit("-m", msg)
        self._logger.debug("Pushing removal change")
        client.push("--set-upstream", "origin", self._migration_branch)
        self._logger.debug(f"Adding {num_files} files to index")
        client.add(*str_files)
        msg = f"Added {num_files} LFS files to index"
        self._logger.debug("Committing re-add change")
        client.commit("-m", msg)
        self._logger.debug("Pushing re-add change")
        resp = client.push()
        self._logger.debug(f"LFS files uploaded: {resp}")
        self._logger.debug(f"Resetting LFS URL to {self._url}")
        cfg.set("lfs", "url", self._url)
        if orig_dir != self._dir:
            self._logger.debug(f"Changing directory to {str(self._dir)}")
            os.chdir(self._dir)

    async def _report(self) -> None:
        if self._quiet:
            return
        paragraphs = [
            (
                "LFS migration has been performed on the "
                + f"`{self._migration_branch}` branch of the "
                + f"{self._owner}/{self._name} repository."
            )
        ]
        if self._lfs_files:
            paragraphs += [
                (
                    f"The LFS read-only pull URL is now {self._url}, "
                    + f"changed from {self._original_lfs_url}, and "
                    + f"{len(self._lfs_files)} files have been uploaded to "
                    + "their new location.  Lock verification has also "
                    + "been disabled."
                )
            ]
        if self._wf_files:
            paragraphs += [
                (
                    "The following GitHub workflow files have been updated: "
                    + f"{', '.join([f.name for f in self._wf_files])}."
                )
            ]
        paragraphs += [
            (
                f"You should immediately PR the `{self._migration_branch}` "
                + "branch to your default branch and merge that PR, so that "
                + "so that no one uses the now-obsolete old LFS repository."
            )
        ]
        if self._lfs_files:
            paragraphs += [
                (
                    "You will need to run `git config lfs.url "
                    + f"{self._write_url}` before pushing, and you will "
                    + "need the Git LFS push token you used to push to "
                    + f"{self._write_url} just now, and its corresponding "
                    + "name."
                ),
                """
                Since this becomes quite painful to do repeatedly, use of a
                credential manager is highly encouraged.
                """,
            ]
        if self._dry_run:
            paragraphs.insert(0, "***DRY RUN: the following DID NOT HAPPEN***")
            paragraphs.append("***DRY RUN: the preceding DID NOT HAPPEN***")
        alignedps = [textwrap.dedent(x) for x in paragraphs]
        text = "\n\n".join([textwrap.fill(x).lstrip() for x in alignedps])
        print(text)

    async def _update_lfsconfig(self) -> None:
        """Set read URL for LFS objects and disable lock verification."""
        if self._dry_run:
            self._logger.info(f"Would set .lfsconfig lfs.url to {self._url}")
            self._logger.info("Would set .lfsconfig lfs.locksverify to False")
            return
        lfscfgblob = self._repo.head.commit.tree / ".lfsconfig"
        lfscfgpath = lfscfgblob.abspath
        cfg = GitConfigParser(lfscfgpath, read_only=False)
        cfg.set("lfs", "url", self._url)
        cfg.set("lfs", "locksverify", "false")
        client = self._repo.git
        client.add(lfscfgpath)
        client.commit(
            "-m", f"Set lfs.url to {self._url} and disable lock verification"
        )

    async def _update_config(self) -> None:
        """Set URL for pushing in .git/config (which is not under
        version control, hence not commitable)."""
        if self._dry_run:
            self._logger.info(
                f"Would set .git/config lfs.url to {self._write_url}"
            )
            return
        cfg = self._repo.config_writer(config_level="repository")
        cfg.set("lfs", "url", self._write_url)
        # No commit: see above

    async def _get_wf_files(self) -> None:
        w_dir = Path(self._dir / ".github" / " workflows")
        candidates: list[Path] = []
        if not w_dir.is_dir():
            return
        for suf in ("yaml", "yml"):
            candidates.extend(w_dir.glob(f"*.{suf}"))
        for c in candidates:
            with open(c, "r") as f:
                contents = f.read()  # These files are all small.
            if contents.find(self._original_lfs_url) == -1:
                continue
            self._wf_files.append(c)

    async def _update_workflow_files(self) -> None:
        for fn in self._wf_files:
            if self._dry_run:
                self._logger.info(
                    f"Would replace {self._original_lfs_url} with "
                    + f"{self._url} in '{fn}' ."
                )
                continue
            with open(fn, "r") as f:
                contents = f.read()
            with open(fn, "w") as f:
                f.write(contents.replace(self._original_lfs_url, self._url))


def _get_migrator() -> Migrator:
    """
    Parse arguments and return the migrator for that repository.
    """
    parser = parse(description="Migrate a Git LFS repo")
    parser.add_argument(
        "-i",
        "--directory",
        "--input-dir",
        default=os.environ.get("LFSMIGRATOR_DIR", "."),
        help="directory of repo to migrate [env: LFSMIGRATOR_DIR, '.']",
    )
    parser.add_argument(
        "-u",
        "--owner",
        "--user",
        help="owner (usually organization) for repository",
    )
    parser.add_argument("-r", "--repository", help="repository name")
    args = parser.parse_args()
    if not args.owner or not args.repository:
        raise RuntimeError("Both owner and repository must be specified")
    return Migrator(
        owner=args.owner,
        repository=args.repository,
        directory=args.directory,
        lfs_base_url=args.lfs_base_url,
        lfs_base_write_url=args.lfs_base_write_url,
        original_lfs_url=args.original_lfs_url,
        migration_branch=args.original_migration_branch,
        dry_run=args.dry_run,
        quiet=args.quiet,
        debug=args.debug,
    )


def main() -> None:
    mgr = _get_migrator()
    asyncio.run(mgr.execute())


if __name__ == "__main__":
    main()
