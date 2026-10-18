#!/bin/sh
# Native first stage for Debian / Ubuntu / Mint. Never replace system Python.
set -eu
umask 077
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
fail() { printf 'OpenCode Kit: %s\n' "$*" >&2; exit 1; }
manifest=$script_dir/python.lock
# Parse data only: do not source/eval a downloaded configuration file.
value() { awk -F= -v key="$1" '$1 == key { print substr($0, index($0,"=")+1); count++ } END { if(count != 1) exit 1 }' "$manifest"; }
version=$(value version) || fail 'Invalid Python runtime manifest.'
case "$version" in 3.*.*) ;; *) fail 'Invalid Python version.' ;; esac
printf '%s\n' "$version" | grep -Eq '^3\.[0-9]+\.[0-9]+$' || fail 'Invalid Python version.'
url=$(value linux_source_url) || fail 'Missing source URL.'
digest=$(value linux_source_sha256) || fail 'Missing source checksum.'
[ "$url" = "https://www.python.org/ftp/python/$version/Python-$version.tar.xz" ] || fail 'Invalid Python source URL.'
printf '%s\n' "$digest" | grep -Eq '^[a-f0-9]{64}$' || fail 'Invalid Python checksum.'
[ "$(uname -s)" = Linux ] || fail 'This bootstrap supports Linux. See docs/kit/PYTHON_RUNTIME.ru.md for other systems.'
architecture=$(uname -m)
case "$architecture" in x86_64|aarch64) ;; *) fail 'Linux x86_64 and aarch64 are supported.' ;; esac
cache=${PI_KIT_RUNTIME_HOME:-${OPENCODE_KIT_RUNTIME_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/opencode-kit/runtimes}}
case "$cache" in /*) ;; *) fail 'Runtime cache must be an absolute path.' ;; esac
# Resolve and reject links before any temporary cleanup.
check=$cache
while [ "$check" != / ]; do
    [ ! -L "$check" ] || fail 'Runtime cache cannot contain symbolic links.'
    check=$(dirname -- "$check")
done
mkdir -p -- "$cache"
cache=$(CDPATH= cd -- "$cache" && pwd -P)
target=$cache/cpython-$version-linux-$architecture
[ ! -L "$target" ] || fail 'Runtime folder cannot be a symbolic link.'
python=$target/bin/python${version%.*}
unset PYTHONHOME PYTHONPATH TCL_LIBRARY TK_LIBRARY
export PYTHONIOENCODING=utf-8
probe() {
    [ -x "$1" ] && "$1" -I -c "import sys,ssl,sqlite3,tkinter,venv,ensurepip; assert sys.version.split()[0] == '$version'; assert tkinter.Tcl().eval('info patchlevel')" >/dev/null 2>&1
}
command -v flock >/dev/null || fail 'Missing build dependencies. Install the OpenCode Kit .deb with the system Software installer.'
# Kernel lock is released even if setup is killed. Children do not inherit it on exec below.
exec 9>"$cache/$version-linux-$architecture.lock"
flock -w 1800 9 || fail 'Another Python setup is still running. Try again later.'
stage=
build=
cleanup() {
    if [ -n "$stage" ] && [ "$(dirname -- "$stage")" = "$cache" ]; then
        case "$(basename -- "$stage")" in .setup-*) rm -rf -- "$stage" ;; esac
    fi
    if [ -n "$build" ] && [ "$(dirname -- "$build")" = /tmp ]; then
        case "$(basename -- "$build")" in opencode-kit-python.*) rm -rf -- "$build" ;; esac
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if ! { [ -f "$target/.kit-runtime-ready" ] && probe "$python"; }; then
    [ ! -e "$target" ] && [ ! -L "$target" ] || fail "The private Python runtime is damaged: $target. Rename that folder and try again."
    for tool in curl tar xz make cc pkg-config sha256sum; do
        command -v "$tool" >/dev/null || fail 'Missing build dependencies. Install the OpenCode Kit .deb with the system Software installer.'
    done
    for lib in openssl sqlite3 tk zlib libffi liblzma; do
        pkg-config --exists "$lib" || fail "Missing development library $lib. Install the OpenCode Kit .deb with the system Software installer."
    done
    printf 'OpenCode Kit: downloading Python %s from python.org...\n' "$version" >&2
    stage=$(mktemp -d "$cache/.setup-XXXXXXXXXX")
    # CPython's make install does not quote prefix / DESTDIR paths consistently.
    # Configure for the final location, but override make's installation prefix
    # with whitespace-free staging. The generated development metadata then
    # points to the real cache, not the temporary build directory.
    build=$(mktemp -d /tmp/opencode-kit-python.XXXXXXXXXX)
    curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 --connect-timeout 30 --max-time 600 \
        --output "$stage/python.tar.xz" "$url" >&2
    printf '%s  %s\n' "$digest" "$stage/python.tar.xz" | sha256sum -c - >&2 || fail 'Python checksum mismatch. Nothing was installed. Try again.'
    tar -xJf "$stage/python.tar.xz" -C "$build"
    printf 'OpenCode Kit: building Python %s with Tk / SSL / SQLite. This may take several minutes.\n' "$version" >&2
    (
        cd "$build/Python-$version"
        ./configure --prefix="$target" --with-ensurepip=no
        jobs=$(getconf _NPROCESSORS_ONLN 2>/dev/null || printf 2)
        [ "$jobs" -le 4 ] || jobs=4
        make -j "$jobs"
        make altinstall prefix="$build/install" exec_prefix="$build/install"
    ) >"$stage/build.log" 2>&1 || { tail -n 35 "$stage/build.log" >&2; fail 'Python build failed. Check free disk space and the dependencies from docs/kit/PYTHON_RUNTIME.ru.md.'; }
    cp -a -- "$build/install" "$stage/runtime"
    staged=$stage/runtime
    probe "$staged/bin/python${version%.*}" || fail 'Downloaded Python failed its version / Tk / SSL / SQLite check.'
    [ ! -e "$target" ] || fail 'The runtime location changed during setup. Nothing was replaced.'
    mv -T -- "$staged" "$target"
    probe "$python" || fail 'Installed Python runtime could not be started.'
    # Only now may ensurepip write into the final configured prefix. It uses
    # the bundled wheel (no network) and creates shebangs for this exact path.
    "$python" -I -m ensurepip --altinstall >&2
    printf '%s\n' "$version" >"$target/.kit-runtime-ready"
fi
flock -u 9
exec 9>&-
cleanup
stage=
build=
export OPENCODE_KIT_PYTHON=$python
PATH=$target/bin:$PATH
export PATH
if [ "$#" -eq 1 ] && [ "$1" = --kit-runtime-path ]; then
    printf '%s\n' "$python"
    exit 0
fi
exec "$python" "$@"
