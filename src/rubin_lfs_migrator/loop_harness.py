#!/usr/bin/env python3
import logging
import os
from pathlib import Path

from .parser import parse
from .util import str_bool


class Looper:
    def __init__(
        self,
        input_file: str,
        top_dir: str,
        original_lfs_url: str,
        lfs_base_url: str,
        lfs_base_write_url: str,
        dry_run: bool,
        cleanup: bool,
        quiet: bool,
        debug: bool,
    ) -> None:
        self._dir = Path(top_dir).resolve()
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
            self._logger.debug("Debugging enabled for Loop Harness")


def main() -> None:
    pass


def _primary_loop() -> None:
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
    looper = Looper(
        input_file=args.file,
        top_dir=args.top_dir,
        original_lfs_url=args.original.lfs_url,
        lfs_base_url=args.lfs_base_url,
        lfs_base_write_url=args.lfs_base_write_url,
        dry_run=args.dry_run,
        cleanup=args.cleanup,
        quiet=args.quiet,
        debug=args.debug,
    )
    _ = looper


if __name__ == "__main__":
    main()
