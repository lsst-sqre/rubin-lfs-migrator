Rubin Git LFS migrator
======================

This is a tool to migrate Git LFS contents from one location to another.

To use it, `pip install rubin-lfs-migrator` and then run `migrate_lfs`.
You will need to have cloned the repository you want to migrate
(complete with LFS objects) into some directory, which will become the
object of the `-i` option.

If you are using this in a Rubin Observatory context, you will probably
not need to change anything except the input directory.  However,
`migrate_lfs -h` will show you the options available:

```
usage: migrate_lfs [-h] [-i DIRECTORY] [-b LFS_BASE_URL]
                   [-w LFS_BASE_WRITE_URL] [-x] [-q] [-d]

Migrate a Git LFS repo

options:
  -h, --help            show this help message and exit
  -i DIRECTORY, --directory DIRECTORY, --input-dir DIRECTORY
                        directory of repo to migrate [env: LFSMIGRATOR_DIR,
                        '.']
  -b LFS_BASE_URL, --lfs-base-url LFS_BASE_URL
                        base URL of new Git LFS implementation [env:
                        LFSMIGRATOR_BASE_URL, 'https://git-lfs-
                        dev.lsst.cloud']
  -w LFS_BASE_WRITE_URL, --lfs-base-write-url LFS_BASE_WRITE_URL
                        base URL of write endpoint of new Git LFS
                        implementation [env: LFSMIGRATOR_BASE_WRITE_URL,
                        'https://git-lfs-dev-rw.lsst.cloud']
  -x, --dry-run         dry run (do not execute) [env: LFSMIGRATOR_DRY_RUN,
                        False]
  -q, --quiet           enable debugging [env: LFSMIGRATOR_QUIET, False]
  -d, --debug           enable debugging [env: LFSMIGRATOR_DEBUG, False]
```
