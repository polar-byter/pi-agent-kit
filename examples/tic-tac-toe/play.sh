#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
kit_root=$(CDPATH= cd -- "$root/../.." && pwd)
export PI_KIT_RUNTIME_HOME="${PI_KIT_RUNTIME_HOME:-$kit_root/.tools/python-runtime}"
cd "$root"
exec sh "$kit_root/kit/python.sh" -B server.py "$@"
