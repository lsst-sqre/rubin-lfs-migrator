import asyncio
import contextlib
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from .migrator import Migrator
from .parser import parse


class ObjectCopier(Migrator):
    """This class copies all objects from all branches matching a particular
    pattern and all tags from the old LFS repository to the new one.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._branch_pattern = kwargs.pop("branch_pattern")
        self._temporary_branch = kwargs.pop("temporary_branch")
        super().__init__(*args, **kwargs)
        self._selected_branches: list[str] = []
        self._tags: list[str] = []
        self._checkout_lfs_files: dict[str, dict[str, str]] = {}
        self._have_oid: dict[str, dict[str, str]] = {}

    async def execute(self) -> None:
        """execute() is the only public method.  It performs the git
        operations necessary to migrate the Git LFS content (or, if
        dry_run is enabled, just logs the operations).
        """
        with contextlib.chdir(self._dir):
            await self._select_branches()
            await self._select_tags()

            await self._loop()

    async def _loop(self) -> None:
        checkouts = self._selected_branches.copy()
        if self._tags:
            checkouts.extend(self._tags)
        self._logger.debug(f"Checkouts to attempt: {checkouts}")
        for co in checkouts:
            await self._loop_over_item(co)
        await self._report()

    async def _loop_over_item(self, co: str) -> None:
        client = self._repo.git
        client.checkout(co)
        self._logger.debug(f"Checking out/fetching '{co}'")
        client.fetch()
        lfs_config = await self._locate_co_lfsconfig()
        if lfs_config is None:
            self._logger.warning(
                f"No .lfsconfig file for checkout '{co}' -- nothing to do"
            )
            return
        self._logger.debug(f"Reset Git LFS URL to {self._original_lfs_url}")
        cfg = self._repo.config_writer()
        cfg.set("lfs", "url", self._original_lfs_url)
        cfg.release()
        git_attributes = await self._locate_co_gitattributes()
        if git_attributes is None:
            self._logger.warning(
                f"No .gitattributes file for checkout '{co}' "
                " -- no files to update"
            )
            return
        lfs_files = await self._get_co_lfs_file_list(git_attributes)
        if not lfs_files:
            self._logger.warning(
                f"No LFS files managed in checkout '{co}' "
                " -- no files to update"
            )
            return
        for path in lfs_files:
            fn = str(path)
            if co not in self._checkout_lfs_files:
                self._checkout_lfs_files[co] = {}
            self._checkout_lfs_files[co][fn] = ""
        await self._update_oids(co, lfs_files)
        needed_files = await self._check_for_needed_files(co, lfs_files)
        if not needed_files:
            self._logger.debug(
                f"All LFS objects in checkout '{co}' are already present"
            )
            return
        await self._copy_lfs_files_for_co(co, needed_files)
        self._logger.debug(
            f"{len(needed_files)} LFS objects for " f"checkout '{co}' uploaded"
        )

    async def _check_for_needed_files(
        self, checkout: str, lfs_files: list[Path]
    ) -> list[Path]:
        needed: list[Path] = []
        for path in lfs_files:
            fn = str(path)
            oid = self._checkout_lfs_files[checkout][fn]
            if not oid:
                raise RuntimeError(
                    f"File '{fn}' in checkout '{checkout}' has no oid"
                )
            if oid not in self._have_oid:
                needed.append(path)
        return needed

    async def _select_branches(self) -> None:
        origin = "origin/"
        l_o = len(origin)
        mpat = "^" + origin + self._branch_pattern
        self._selected_branches = [
            x.name[l_o:]
            for x in self._repo.remote().refs
            if re.match(mpat, x.name) is not None
        ]
        self._logger.debug(f"Selected branches: {self._selected_branches}")

    async def _select_tags(self) -> None:
        client = self._repo.git
        client.fetch("--tags")
        self._tags = [x for x in client.tag("-l").split("\n") if x]
        self._logger.debug(f"Tags: {self._tags}")

    async def _locate_co_gitattributes(self) -> Path | None:
        ga = list(self._dir.glob("**/.gitattributes"))
        if not ga:
            return None
        if len(ga) > 1:
            raise RuntimeError(f"Multiple .gitattributes files found: {ga}")
        return ga[0]

    async def _locate_co_lfsconfig(self) -> Path | None:
        lfscfgpath = self._dir / ".lfsconfig"
        if lfscfgpath.is_file():
            return lfscfgpath
        return None

    async def _get_co_lfs_file_list(self, git_attributes: Path) -> list[Path]:
        """Assemble the list of LFS-managed files by interpreting the
        .gitattributes file we found."""
        files: list[Path] = []
        with open(git_attributes, "r") as f:
            for line in f:
                fields = line.strip().split()
                if not await self._is_lfs_attribute(fields):
                    continue
                files.extend(
                    await self._find_co_lfs_files(git_attributes, fields[0])
                )
        fileset = set(files)
        self._logger.debug(f"Included files: {fileset}")
        excluded_files = await self._get_co_excluded_file_list(git_attributes)
        excset = set(excluded_files)
        self._logger.debug(f"Excluded files: {excset}")
        resolved_fileset = fileset - excset
        lfsfiles = list(resolved_fileset)
        self._logger.debug(f"LFS Files: {lfsfiles}")
        if lfsfiles:
            self._logger.debug(f"LFS file list for {self._url} -> {lfsfiles}")
        return lfsfiles

    async def _find_co_lfs_files(
        self, git_attributes: Path, match: str
    ) -> list[Path]:
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
        pdir = git_attributes.parent
        match = "**/" + match
        files = list(pdir.glob(match))
        self._logger.debug(f"{match} -> {[ str(x) for x in files]}")
        return files

    async def _get_co_excluded_file_list(
        self, git_attributes: Path
    ) -> list[Path]:
        """Assemble the list of LFS-managed files by interpreting the
        .gitattributes file we found."""
        files: list[Path] = []
        pdir = git_attributes.parent
        with open(git_attributes, "r") as f:
            for line in f:
                # There's probably something better than this, but....
                # it'll do for the Rubin case.
                if line.find("!filter !diff !merge") != -1:
                    match = "**/" + line.split()[0]
                    exf = list(pdir.glob(match))
                    files.extend(exf)
                    self._logger.debug(f"Excluded file {match} -> {exf}")
        return files

    async def _copy_lfs_files_for_co(
        self, co: str, lfs_files: list[Path]
    ) -> None:
        client = self._repo.git
        # Check out temporary branch
        t_br = self._repo.create_head(self._temporary_branch)
        try:
            if self._repo.active_branch == t_br:
                raise RuntimeError(
                    f"'{self._temporary_branch}' branch is already current"
                )
        except TypeError:
            # We expect a detached HEAD -- completely normal
            pass
        self._logger.debug(f"Creating branch '{self._temporary_branch}'")
        t_br.checkout()
        num_files = len(lfs_files)
        str_files = [str(x) for x in lfs_files]
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
        self._logger.debug(f"Setting LFS URL to {self._write_url}")
        cfg = self._repo.config_writer()
        cfg.set("lfs", "url", self._write_url)
        cfg.set("lfs", "locksverify", "false")
        cfg.release()
        self._logger.debug(f"Removing {num_files} files from index")
        client.rm("--cached", *str_files)
        msg = f"Removed {num_files} LFS files from index"
        self._logger.debug("Committing removal change")
        client.commit("-m", msg)
        self._logger.debug("Pushing removal change")
        client.push("--set-upstream", "origin", self._temporary_branch)
        self._logger.debug(f"Adding {num_files} files to index")
        client.add(*str_files)
        msg = f"Added {num_files} LFS files to index"
        self._logger.debug("Committing re-add change (copying contents)")
        client.commit("-m", msg)
        self._logger.debug("Pushing re-add change")
        resp = client.push("--set-upstream", "origin", self._temporary_branch)
        self._logger.debug(f"LFS files uploaded: {resp}")
        self._logger.debug("Updating map of uploaded OIDs")
        for fn in str_files:
            oid = self._checkout_lfs_files[co][fn]
            self._have_oid[oid] = {"checkout": co, "file": fn}
        self._logger.debug(f"Reset Git LFS URL to {self._original_lfs_url}")
        cfg = self._repo.config_writer()
        cfg.set("lfs", "url", self._original_lfs_url)
        cfg.release()
        if orig_dir != self._dir:
            self._logger.debug(f"Changing directory to {str(self._dir)}")
            os.chdir(self._dir)
        self._logger.debug("Deleting remote temporary branch")
        remote = self._repo.remote(name="origin")
        remote.push(refspec=(f":{self._temporary_branch}"))
        co_br = self._repo.create_head(co)
        co_br.checkout()
        self._logger.debug("Deleting local temporary branch")
        client.branch("-d", self._temporary_branch)

    async def _update_oids(self, checkout: str, files: list[Path]) -> None:
        for fn in files:
            with open(fn, "rb") as f:
                digest = hashlib.file_digest(f, "sha256")
            s_digest = f"sha256:{digest.hexdigest()}"
            self._logger.debug(
                f"Checkout {checkout}: file {str(fn)} -> {s_digest}"
            )
            self._checkout_lfs_files[checkout][str(fn)] = s_digest

    async def _report(self) -> None:
        if self._quiet:
            return
        text = "Migrated LFS objects:\n\n"
        text += json.dumps(self._have_oid, sort_keys=True, indent=2)
        print(text)


def _get_object_copier() -> ObjectCopier:
    """
    Parse arguments and return the object copier for that repository.
    """
    parser = parse(
        description="Copy tag and branch-tip objects for a Git LFS repo"
    )
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
    if not args.owner or not args.repository:
        raise RuntimeError("Both owner and repository must be specified")
    return ObjectCopier(
        branch_pattern=args.branch_pattern,
        temporary_branch=args.temporary_branch,
        owner=args.owner,
        repository=args.repository,
        directory=args.directory,
        lfs_base_url=args.lfs_base_url,
        lfs_base_write_url=args.lfs_base_write_url,
        original_lfs_url=args.original_lfs_url,
        source_branch=args.source_branch,
        migration_branch=args.migration_branch,
        dry_run=args.dry_run,
        quiet=args.quiet,
        debug=args.debug,
    )


def main() -> None:
    oc = _get_object_copier()
    asyncio.run(oc.execute())


if __name__ == "__main__":
    main()
