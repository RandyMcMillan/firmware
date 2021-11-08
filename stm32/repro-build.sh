#!/bin/sh
#
# NOTE: Executes inside the docker container.
# - assumes $WORK_SRC is a git checkout
# - will copy certain files (build products) back to $WORK_BUILT
#
set -ex

# arguments, all required
VERSION_STRING=$1
MK_NUM=$2

MAKE="make -f MK$MK_NUM-Makefile"

TARGETS="firmware-signed.bin firmware-signed.dfu production.bin dev.dfu firmware.lss firmware.elf"

BYPRODUCTS="check-fw.bin check-bootrom.bin repro-got.txt repro-want.txt file_time.c"

cd $WORK_SRC/stm32

if ! touch repro-build.sh ; then
    # If we seem to be on a R/O filesystem:
    # - do a local checkout of HEAD, build from that
    mkdir /tmp/checkout
    mount -t tmpfs tmpfs /tmp/checkout
    cd /tmp/checkout
    git clone $WORK_SRC/.git firmware
    cd firmware/external
    git submodule update --init
    cd ../stm32
    rsync --ignore-missing-args -av /work/src/releases/20*.dfu ../releases
fi

# need signit.py in path
cd ../cli
python -m pip install -r requirements.txt
python -m pip install --editable .
cd ../stm32

cd ../releases
if [ -f *-v$VERSION_STRING-mk$MK_NUM-coldcard.dfu ]; then
    echo "Using existing binary in ../releases, not downloading."
    PUBLISHED_BIN=`realpath *-v$VERSION_STRING-mk$MK_NUM-coldcard.dfu`
else
    # fetch a copy of the required binary
    PUBLISHED_BIN=`grep -F v$VERSION_STRING-mk$MK_NUM-coldcard.dfu signatures.txt | dd bs=66 skip=1`
    if [ -z "$PUBLISHED_BIN" ]; then
        # may indicate first attempt to build this release
        echo "Cannot determine release date / full file name."
    else
        wget -S https://coldcard.com/downloads/$PUBLISHED_BIN
        PUBLISHED_BIN=`realpath "$PUBLISHED_BIN"`
    fi
fi
cd ../stm32

if [ -z "$SOURCE_DATE_EPOCH" ] && [ -n "$PUBLISHED_BIN" ]; then
    DT=$(basename $PUBLISHED_BIN | cut -d "-" -f1,2,3)
    export SOURCE_DATE_EPOCH=$(python -c 'import datetime, sys; sys.stdout.write(str(int(datetime.datetime.strptime(sys.argv[1], "%Y-%m-%dT%H%M").timestamp())))' "$DT")
fi

$MAKE setup
$MAKE DEBUG_BUILD=0 all
$MAKE $TARGETS

if [ $PWD != '$WORK_SRC/stm32' ]; then
    # Copy back build products.
    rsync -av --ignore-missing-args $TARGETS $WORK_BUILT
fi

set +e
$MAKE "PUBLISHED_BIN=$PUBLISHED_BIN" check-repro

set +ex
if [ $PWD != '$WORK_SRC/stm32' ]; then
    # Copy back byproducts
    rsync -a --ignore-missing-args $BYPRODUCTS $WORK_BUILT
fi

if [ $CR_EXITCODE -ne 0 ]; then
    echo "FAILURE."
    echo "Exit code $CR_EXITCODE from 'make check-repro'"
    exit 1
fi
