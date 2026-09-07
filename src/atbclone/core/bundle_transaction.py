"""Keep the previous bundle recoverable while a clone script replaces it."""

import shlex
from pathlib import Path

from atbclone.executor.runner import Runner


def replace_bundle(script: str, dest_path: Path, needs_admin: bool = False) -> None:
    """Run construction and rollback in the same (possibly elevated) shell.

    The engine must finish signing and verifying before returning success.
    Data directories are deliberately outside the bundle transaction.
    """
    dest = shlex.quote(str(dest_path))
    parent = shlex.quote(str(dest_path.parent))
    lock = shlex.quote(str(dest_path) + ".atbclone-lock")
    template = shlex.quote(str(dest_path.parent / ".atbclone-backup.XXXXXX"))
    Runner.run(f"""set -e
mkdir -p {parent}
atb_dest={dest}
atb_lock={lock}
if ! mkdir "$atb_lock"; then
    echo "Another clone operation may be using $atb_dest (lock: $atb_lock)" >&2
    exit 1
fi
atb_backup=''
atb_ready=0
atb_finish() {{
    atb_status=$?
    trap - EXIT HUP INT TERM
    set +e
    if [ "$atb_status" -ne 0 ] && [ "$atb_ready" -eq 1 ]; then
        if rm -rf "$atb_dest"; then
            if [ -e "$atb_backup/original.app" ] || [ -L "$atb_backup/original.app" ]; then
                if ! mv "$atb_backup/original.app" "$atb_dest"; then
                    echo "Could not restore original bundle; backup retained at $atb_backup" >&2
                fi
            fi
        else
            echo "Could not remove incomplete bundle; backup retained at $atb_backup" >&2
        fi
    fi
    if [ -n "$atb_backup" ]; then
        if [ "$atb_status" -eq 0 ]; then
            rm -rf "$atb_backup" || echo "Could not remove old bundle backup: $atb_backup" >&2
        else
            # Only remove an empty backup directory; never discard a failed restore.
            rmdir "$atb_backup" 2>/dev/null || true
        fi
    fi
    rmdir "$atb_lock" || true
    exit "$atb_status"
}}
trap atb_finish EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
atb_backup=$(mktemp -d {template})
if [ -e "$atb_dest" ] || [ -L "$atb_dest" ]; then
    mv "$atb_dest" "$atb_backup/original.app"
fi
atb_ready=1
{script}
""", needs_admin)
