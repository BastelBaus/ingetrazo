#!/bin/bash
# runfiles.sh <srcdir> <log> files... : one pytest process per file, failures summarized
cd ~/ingetrazo-test/$1; LOG=$HOME/ingetrazo-test/$2; shift 2; : > $LOG
export LD_LIBRARY_PATH=$HOME/ingetrazo-test/sysroot/usr/lib/x86_64-linux-gnu QT_QPA_PLATFORM=offscreen FONTCONFIG_FILE=$HOME/ingetrazo-test/fonts.conf
for f in "$@"; do
  out=$(../venv/bin/python -m pytest -q -p no:cacheprovider --tb=line -rf "$f" 2>&1 | grep -E "^FAILED|^ERROR|passed|failed|error" | tail -15)
  echo "== $f :: $out" >> $LOG
done
echo ALLDONE >> $LOG
