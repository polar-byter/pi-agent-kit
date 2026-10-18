#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PI_KIT_RUNTIME_HOME="${PI_KIT_RUNTIME_HOME:-$root/.tools/python-runtime}"
exec sh "$root/kit/runtime/desktop.sh" "$root/install.py" "$@"
