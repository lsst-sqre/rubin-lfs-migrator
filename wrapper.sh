#!/bin/bash
#
# Install this as "migrate_lfs" somewhere on your $PATH.  You will need the
# pip and venv modules for your python3 in order to use it.  This will
# create a virtualenv for rubin_lfs_migrator and source it before use,
# which will keep your system python environment clean.

# If you want your virtualenv
# somewhere other than /usr/local/share/venv/rubin_lfs_migrator, put that
# into the $LFSMIGRATOR_VENV environment variable.
#
venv="${LFSMIGRATOR_VENV:=/usr/local/share/venv/rubin_lfs_migrator}"
if [ ! -d "${venv}" ]; then
    python3 -m venv ${venv}
fi
if [ ! -d "${venv}" ]; then
    echo "No virtualenv at ${venv}; giving up" 1>&2
    exit 1
fi
source ${venv}/bin/activate || exit 2
if [ "$(which migrate_lfs)" != "${venv}/bin/migrate_lfs" ]; then
    python3 -m pip install rubin_lfs_migrator
fi
if [ "$(which migrate_lfs)" != "${venv}/bin/migrate_lfs" ]; then
    cwd=$(pwd)
    mkdir -p "${venv}/src"
    cd "${venv}/src"
    if [ -d rubin_lfs_migrator ]; then
        cd rubin_lfs_migrator
        git checkout main
        git pull
    else
        git clone https://github.com/lsst-sqre/rubin_lfs_migrator
        cd rubin_lfs_migrator
    fi
    python3 -m pip install -e .
    cd "${cwd}"
fi
if [ "$(which migrate_lfs)" != "${venv}/bin/migrate_lfs" ]; then
    echo "No migrate_lfs in virtualenv; giving up" 1>&2
    exit 3
fi

migrate_lfs $*
