import asyncio
import json
import os
from pathlib import Path
from typing import Any

from .obj_copier import ObjectCopier
from .parser import parse
from .util import str_bool


class OidMapper(ObjectCopier):
    """This class relies on **not** having Git LFS installed: it walks
    through the stub files on each branch, extracts the OIDs, and constructs
    a map of which oids belong to which repository.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._output_dir = kwargs.pop("output_dir")
        self._full_map = kwargs.pop("full_map")
        super().__init__(*args, **kwargs)
        self._oids: dict[str, bool] = {}

    async def _loop_over_item(self, co: str) -> None:
        client = self._repo.git
        client.checkout(co)
        self._logger.debug(f"Checking out/fetching '{co}'")
        client.fetch()
        client.reset("--hard")
        git_attributes = await self._locate_co_gitattributes()
        if git_attributes is None:
            self._logger.warning(
                f"No .gitattributes file for checkout '{co}' "
                " -- nothing to check"
            )
            return
        lfs_files = await self._get_co_lfs_file_list(git_attributes)
        if not lfs_files:
            self._logger.warning(
                f"No LFS files managed in checkout '{co}' "
                " -- nothing to check"
            )
            return
        for path in lfs_files:
            fn = str(path)
            if co not in self._checkout_lfs_files:
                self._checkout_lfs_files[co] = {}
            self._checkout_lfs_files[co][fn] = ""
        await self._update_oids(co, lfs_files)

    async def _update_oids(self, checkout: str, files: list[Path]) -> None:
        for fn in files:
            if fn.is_symlink():
                # A symlink either points elsewhere into someplace inside the
                # repo, in which case we'll check it there, or it points
                # somewhere else entirely, in which case we can't check it.
                self._logger.warning(
                    f"Skipping symlink {str(fn)} -> {fn.resolve()}"
                )
                del self._checkout_lfs_files[checkout][str(fn)]
                continue
            with open(fn, "r") as f:
                try:
                    for ln in f:
                        line = ln.strip()
                        fields = line.split()
                        if not fields:
                            continue
                        if fields[0] != "oid":
                            continue
                        oid = fields[1]
                        self._checkout_lfs_files[checkout][str(fn)] = oid
                        self._oids[oid] = True
                        self._logger.debug(
                            f"oid '{oid}' @ [{checkout}] -> {str(fn)}"
                        )
                        break
                except UnicodeDecodeError:
                    self._logger.warning(
                        f"Failed to decode {str(fn)} as text; skipping "
                        "(probably stored directly, not in LFS)"
                    )

    async def _report(self) -> None:
        filename = Path(f"oids--{self._owner}--{self._name}.json")
        out = {
            f"{self._owner}/{self._name}": [
                x.split(":")[1] for x in self._oids.keys()
            ]
        }
        with open(self._output_dir / filename, "w") as f:
            json.dump(out, f, sort_keys=True, indent=2)
        if not self._full_map:
            return
        filename = Path(f"fullmap--{self._owner}--{self._name}.json")
        out2 = {f"{self._owner}/{self._name}": self._checkout_lfs_files}
        with open(self._output_dir / filename, "w") as f:
            json.dump(out2, f, sort_keys=True, indent=2)


def _get_oid_mapper() -> OidMapper:
    """
    Parse arguments and return the OID mapper for that repository.
    """
    parser = parse(description="Map all LFS OIDs for a repository")
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
    if not args.owner or not args.repository:
        raise RuntimeError("Both owner and repository must be specified")
    return OidMapper(
        output_dir=args.output_dir,
        full_map=args.full_map,
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
    om = _get_oid_mapper()
    asyncio.run(om.execute())


if __name__ == "__main__":
    main()
