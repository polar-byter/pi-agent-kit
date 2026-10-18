#!/bin/sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export PI_KIT_RUNTIME_HOME="${PI_KIT_RUNTIME_HOME:-$project_root/.tools/python-runtime}"
cd "$project_root"
exec sh "$project_root/kit/python.sh" -m kit.run_pi "$@"
