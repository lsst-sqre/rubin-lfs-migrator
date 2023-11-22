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
usage: migrate_lfs [-h] [-m MIGRATION_BRANCH] [-s SOURCE_BRANCH]
                   [-b LFS_BASE_URL] [-w LFS_BASE_WRITE_URL]
                   [-o ORIGINAL_LFS_URL] [-x] [-q] [-d] [-i DIRECTORY]
                   [-u OWNER] [-r REPOSITORY]

Migrate a Git LFS repo

options:
  -h, --help            show this help message and exit
  -m MIGRATION_BRANCH, --migration-branch MIGRATION_BRANCH
                        migration git branch [env:
                        LFSMIGRATOR_MIGRATION_BRANCH, 'lfs-migration']
  -s SOURCE_BRANCH, --source-branch SOURCE_BRANCH
                        source git branch [env: LFSMIGRATOR_SOURCE_BRANCH,
                        <repo default branch>]
  -b LFS_BASE_URL, --lfs-base-url LFS_BASE_URL
                        base URL of new Git LFS implementation [env:
                        LFSMIGRATOR_BASE_URL, 'https://git-lfs.lsst.cloud']
  -w LFS_BASE_WRITE_URL, --lfs-base-write-url LFS_BASE_WRITE_URL
                        base URL of write endpoint of new Git LFS
                        implementation [env: LFSMIGRATOR_BASE_WRITE_URL,
                        'https://git-lfs-rw.lsst.cloud']
  -o ORIGINAL_LFS_URL, --original-lfs-url ORIGINAL_LFS_URL, --orig-lfs-url ORIGINAL_LFS_URL
                        Original Git LFS URL [env: LFSMIGRATOR_ORIGINAL_URL,
                        'https://git-lfs.lsst.codes']
  -x, --dry-run         dry run (do not execute) [env: LFSMIGRATOR_DRY_RUN,
                        False]
  -q, --quiet           enable debugging [env: LFSMIGRATOR_QUIET, False]
  -d, --debug           enable debugging [env: LFSMIGRATOR_DEBUG, False]
  -i DIRECTORY, --directory DIRECTORY, --input-dir DIRECTORY
                        directory of repo to migrate [env: LFSMIGRATOR_DIR,
                        '.']
  -u OWNER, --owner OWNER, --user OWNER
                        owner (usually organization) for repository
  -r REPOSITORY, --repository REPOSITORY
                        repository name
```

A more useful tool may be `lfs_looper`, which takes as its input a list
of repositories on GitHub (in the form `https://github.comowner/repo`),
and migrates each of those in turn:

```
usage: lfs_looper [-h] [-m MIGRATION_BRANCH] [-s SOURCE_BRANCH]
                  [-b LFS_BASE_URL] [-w LFS_BASE_WRITE_URL]
                  [-o ORIGINAL_LFS_URL] [-x] [-q] [-d] [-f FILE] [-t TOP_DIR]
                  [-c]

Migrate multiple repositories

options:
  -h, --help            show this help message and exit
  -m MIGRATION_BRANCH, --migration-branch MIGRATION_BRANCH
                        migration git branch [env:
                        LFSMIGRATOR_MIGRATION_BRANCH, 'lfs-migration']
  -s SOURCE_BRANCH, --source-branch SOURCE_BRANCH
                        source git branch [env: LFSMIGRATOR_SOURCE_BRANCH,
                        <repo default branch>]
  -b LFS_BASE_URL, --lfs-base-url LFS_BASE_URL
                        base URL of new Git LFS implementation [env:
                        LFSMIGRATOR_BASE_URL, 'https://git-lfs.lsst.cloud']
  -w LFS_BASE_WRITE_URL, --lfs-base-write-url LFS_BASE_WRITE_URL
                        base URL of write endpoint of new Git LFS
                        implementation [env: LFSMIGRATOR_BASE_WRITE_URL,
                        'https://git-lfs-rw.lsst.cloud']
  -o ORIGINAL_LFS_URL, --original-lfs-url ORIGINAL_LFS_URL, --orig-lfs-url ORIGINAL_LFS_URL
                        Original Git LFS URL [env: LFSMIGRATOR_ORIGINAL_URL,
                        'https://git-lfs.lsst.codes']
  -x, --dry-run         dry run (do not execute) [env: LFSMIGRATOR_DRY_RUN,
                        False]
  -q, --quiet           enable debugging [env: LFSMIGRATOR_QUIET, False]
  -d, --debug           enable debugging [env: LFSMIGRATOR_DEBUG, False]
  -f FILE, --file FILE, --input-file FILE
                        input file of repositories [env:
                        LFSMIGRATOR_INPUT_FILE, '']
  -t TOP_DIR, --top-dir TOP_DIR
                        top directory for repo checkout [env:
                        LFSMIGRATOR_TOP_DIR, '.']
  -c, --cleanup         clean up repo directories [env: LFSMIGRATOR_CLEANUP,
                        False]
```
