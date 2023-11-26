import asyncio
import contextlib
import logging
import os
import textwrap
from pathlib import Path

from git import GitConfigParser, Repo

from .parser import parse
from .util import str_now


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
        original_lfs_url: str,
        lfs_base_url: str,
        lfs_base_write_url: str,
        migration_branch: str,
        source_branch: str | None,
        report_file: str,
        dry_run: bool,
        quiet: bool,
        debug: bool,
    ) -> None:
        self._dir = Path(directory).resolve()
        if not Path(self._dir / ".git").is_dir():
            if not dry_run:
                raise RuntimeError(
                    f"{directory} must contain a cloned git repository"
                )
        self._repo = Repo(self._dir)
        self._owner = owner
        self._name = repository
        self._original_lfs_url = original_lfs_url
        self._migration_branch = migration_branch
        self._source_branch = source_branch
        self._report_file = report_file
        self._dry_run = dry_run
        self._quiet = quiet
        self._debug = debug
        self._logger = logging.getLogger(__name__)
        ch = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        ch.setFormatter(formatter)
        if ch not in self._logger.handlers:
            self._logger.addHandler(ch)
        self._logger.setLevel("INFO")
        if self._quiet:
            self._logger.setLevel("CRITICAL")
        if self._debug:
            self._logger.setLevel("DEBUG")
            self._logger.debug("Debugging enabled for Migrator")

        self._url = f"{lfs_base_url}/{self._owner}/{self._name}"
        self._write_url = f"{lfs_base_write_url}/{self._owner}/{self._name}"

        self._lfs_files: list[Path] = []
        self._wf_files: list[Path] = []

        self._gitattributes: Path | None = None
        self._lfsconfig: Path | None = None

        self._report_text: str = ""

    async def execute(self) -> None:
        """execute() is the only public method.  It performs the git
        operations necessary to migrate the Git LFS content (or, if
        dry_run is enabled, just logs the operations).
        """
        with contextlib.chdir(self._dir):
            await self._locate_gitattributes()
            await self._locate_lfsconfig()
            if self._lfsconfig is not None:
                await self._get_lfs_file_list()
            await self._get_wf_files()
            if self._lfsconfig is None and not self._wf_files:
                self._logger.warning(
                    "Neither LFS configuration nor workflows referencing "
                    + "LFS objects found.  Nothing to do."
                )
                return
            await self._checkout_migration_branch()
            if self._lfsconfig is not None:
                await self._update_lfsconfig()
            if self._lfs_files:
                await self._remove_and_readd()
            if self._wf_files:
                await self._update_workflow_files()
            await self._prepare_report()
            await self._report()

    async def _locate_gitattributes(self) -> None:
        ga = list(self._dir.glob("**/.gitattributes"))
        if not ga:
            return
        if len(ga) > 1:
            raise RuntimeError(f"Multiple .gitattributes files found: {ga}")
        self._gitattributes = ga[0]

    async def _locate_lfsconfig(self) -> None:
        lfscfgpath = self._dir / ".lfsconfig"
        if lfscfgpath.is_file():
            self._lfsconfig = lfscfgpath

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
        .gitattributes file we found."""
        files: list[Path] = []
        if self._gitattributes is None:
            return  # self._lfs_files begins as None
        with open(self._gitattributes, "r") as f:
            for line in f:
                fields = line.strip().split()
                if not await self._is_lfs_attribute(fields):
                    continue
                files.extend(await self._find_lfs_files(fields[0]))
        fileset = set(files)
        self._logger.debug(f"Included files: {fileset}")
        excluded_files = await self._get_excluded_file_list()
        excset = set(excluded_files)
        self._logger.debug(f"Excluded files: {excset}")
        resolved_fileset = fileset - excset
        lfsfiles = list(resolved_fileset)
        self._logger.debug(f"LFS Files: {lfsfiles}")
        if lfsfiles:
            self._logger.debug(f"LFS file list for {self._url} -> {lfsfiles}")
        self._lfs_files = lfsfiles

    async def _is_lfs_attribute(self, fields: list[str]) -> bool:
        """It's not clear that this is ever really formalized, but in
        each case I've seen, "filter", "diff", and "merge" are set to
        "lfs", and it's almost always not a binary file ("-text").  I
        think that's just what `git lfs track` does, but whether it's
        documented, I don't know.

        Apparently not quite, since we have one repo which uses "-crlf"
        (lsst-dm/phosim_psf_tests).
        """
        if not fields:
            return False
        notext = fields[-1]
        if notext != "-text" and notext != "-crlf":
            self._logger.debug(
                f"{' '.join(fields)} does not end with '-text' or '-crlf'"
            )
            return False
        mids = fields[1:-1]
        ok_flds = ("filter", "diff", "merge")
        for m in mids:
            if m.find("=") == -1:
                continue  # Definitely not right
            k, v = m.split("=")
            if k not in ok_flds:
                self._logger.debug(f"{k} not in {ok_flds}")
                return False
            if v != "lfs":
                self._logger.debug(f"{k} is '{v}', not 'lfs'")
                return False
        return True

    async def _find_lfs_files(self, match: str) -> list[Path]:
        """The .gitattributes file is defined at:
        https://git-scm.com/docs/gitattributes

        Those can be in arbitrary directories and only concern things
        at or below their own directory.

        In Rubin Git LFS repositories, there is only one
        .gitattributes file, but it may not be at the root of the
        repo.

        Our strategy is pretty simple: do "**/" prepended to the
        match, starting with the directory in which the .gitattributes
        file was found.
        """
        if self._gitattributes is None:
            return []
        pdir = self._gitattributes.parent
        match = "**/" + match
        files = list(pdir.glob(match))
        self._logger.debug(f"{match} -> {[ str(x) for x in files]}")
        return files

    async def _get_excluded_file_list(self) -> list[Path]:
        """Assemble the list of LFS-managed files by interpreting the
        .gitattributes file we found."""
        files: list[Path] = []
        if self._gitattributes is None:
            return files
        pdir = self._gitattributes.parent
        with open(self._gitattributes, "r") as f:
            for line in f:
                # There's probably something better than this, but....
                # it'll do for the Rubin case.
                if line.find("!filter !diff !merge") != -1:
                    match = "**/" + line.split()[0]
                    exf = list(pdir.glob(match))
                    files.extend(exf)
                    self._logger.debug(f"Excluded file {match} -> {exf}")
        return files

    async def _remove_and_readd(self) -> None:
        client = self._repo.git
        num_files = len(self._lfs_files)
        str_files = [str(x) for x in self._lfs_files]
        if self._dry_run:
            self._logger.info(
                f"Would remove/readd the following {num_files} "
                + f"files: {str_files}"
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
        resp = client.push("--set-upstream", "origin", self._migration_branch)
        self._logger.debug(f"LFS files uploaded: {resp}")
        self._logger.debug(f"Resetting LFS URL to {self._url}")
        cfg.set("lfs", "url", self._url)
        cfg.release()
        if orig_dir != self._dir:
            self._logger.debug(f"Changing directory to {str(self._dir)}")
            os.chdir(self._dir)

    async def _prepare_report(self) -> None:
        paragraphs = [
            (
                "LFS migration has been performed on the "
                + f"`{self._migration_branch}` branch of the "
                + f"{self._owner}/{self._name} repository."
            )
        ]
        if self._lfsconfig is not None:
            paragraphs += [
                f"The LFS read-only pull URL is now {self._url}, "
                + f"changed from {self._original_lfs_url}, and "
                + "LFS lock verification has been disabled."
            ]
        if self._lfs_files:
            paragraphs += [
                (
                    f"{len(self._lfs_files)} files have been uploaded to "
                    + "their new location."
                )
            ]
        if self._wf_files:
            paragraphs += [
                (
                    "The following GitHub workflow files have been updated: "
                    + f"{', '.join([str(f) for f in self._wf_files])}."
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
        self._report_text = "\n\n".join(
            [textwrap.fill(x).lstrip() for x in alignedps]
        )

    async def _report(self) -> None:
        if self._quiet:
            return
        text = (
            f"{str_now()} : {self.__class__.__name__}\n------\n"
            + self._report_text
        )
        if self._report_file != "-":
            fh = open(self._report_file, "a")
            print(text, file=fh)
            fh.close()
        else:
            print(text)

    async def _update_lfsconfig(self) -> None:
        """Set read URL for LFS objects and disable lock verification."""
        if self._lfsconfig is None:
            self._logger.info("No .lfsconfig found; can't update.")
            return
        if self._dry_run:
            self._logger.info(f"Would set .lfsconfig lfs.url to {self._url}")
            self._logger.info("Would set .lfsconfig lfs.locksverify to False")
            return
        lfscfgpath = self._lfsconfig.resolve()
        cfg = GitConfigParser(lfscfgpath, read_only=False)
        cfg.set("lfs", "url", self._url)
        cfg.set("lfs", "locksverify", "false")
        cfg.release()
        client = self._repo.git
        client.add(lfscfgpath)
        client.commit(
            "-m", f"Set lfs.url to {self._url} and disable lock verification"
        )
        client.push("--set-upstream", "origin", self._migration_branch)

    async def _get_wf_files(self) -> None:
        w_dir = Path(self._dir / ".github" / "workflows")
        candidates: list[Path] = []
        if not w_dir.is_dir():
            return
        for suf in ("yaml", "yml"):
            candidates.extend(w_dir.glob(f"*.{suf}"))
        for c in candidates:
            self._logger.debug(f"Considering candidate workflow file {str(c)}")
            with open(c, "r") as f:
                contents = f.read()  # These files are all small.
            self._logger.debug(
                f"Looking for string '{self._original_lfs_url}'"
            )
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
        await self._push_workflow_files()

    async def _push_workflow_files(self) -> None:
        client = self._repo.git
        self._logger.debug("Committing workflow file changes")
        client.add(self._wf_files)
        client.commit("-m", "Updated workflow files")
        self._logger.debug("Pushing workflow file changes")
        if not self._dry_run:
            client.push("--set-upstream", "origin", self._migration_branch)


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
        source_branch=args.source_branch,
        migration_branch=args.migration_branch,
        report_file=args.report_file,
        dry_run=args.dry_run,
        quiet=args.quiet,
        debug=args.debug,
    )


def main() -> None:
    mgr = _get_migrator()
    asyncio.run(mgr.execute())


if __name__ == "__main__":
    main()
