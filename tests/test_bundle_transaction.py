"""Exercise bundle replacement on disk, without building or launching real apps."""

import shlex
from pathlib import Path

import pytest

from atbclone.core.bundle_transaction import replace_bundle
from atbclone.executor.runner import CloneError


@pytest.fixture
def bundle(tmp_path):
    dest = tmp_path / "Apps with spaces" / "ChatGPT's 2.app"
    dest.mkdir(parents=True)
    (dest / "original").write_text("working application")
    return dest


def build_script(dest):
    quoted = shlex.quote(str(dest))
    return f'mkdir -p {quoted}\nprintf replacement > {quoted}/replacement\n'


def assert_no_transaction_files(dest):
    assert not list(dest.parent.glob(".atbclone-backup.*"))
    assert not Path(str(dest) + ".atbclone-lock").exists()


@pytest.mark.parametrize("failure", ["false", "exit 23", "kill -TERM $$"])
def test_failed_replacement_restores_original_and_preserves_data(bundle, failure):
    data = bundle.parent / "Data"
    data.mkdir()
    (data / "config.toml").write_text("existing configuration")

    with pytest.raises(CloneError):
        replace_bundle(build_script(bundle) + failure, bundle)

    assert (bundle / "original").read_text() == "working application"
    assert not (bundle / "replacement").exists()
    assert (data / "config.toml").read_text() == "existing configuration"
    assert_no_transaction_files(bundle)


def test_successful_replacement_removes_backup(bundle):
    replace_bundle(build_script(bundle), bundle)
    assert (bundle / "replacement").read_text() == "replacement"
    assert not (bundle / "original").exists()
    assert_no_transaction_files(bundle)


def test_failed_first_creation_removes_incomplete_bundle(tmp_path):
    dest = tmp_path / "New.app"
    with pytest.raises(CloneError):
        replace_bundle(build_script(dest) + "exit 42", dest)
    assert not dest.exists()
    assert_no_transaction_files(dest)


def test_existing_lock_prevents_touching_original(bundle):
    lock = Path(str(bundle) + ".atbclone-lock")
    lock.mkdir()
    with pytest.raises(CloneError, match="Another clone operation"):
        replace_bundle(build_script(bundle), bundle)
    assert (bundle / "original").read_text() == "working application"
    assert lock.exists()  # A competing operation owns this lock.
    assert not list(bundle.parent.glob(".atbclone-backup.*"))


def test_failed_restore_retains_backup_and_reports_location(bundle):
    # Make only the rollback move fail, after the initial backup has succeeded.
    script = build_script(bundle) + "mv() { return 1; }\nexit 23"
    with pytest.raises(CloneError, match="backup retained at") as exc:
        replace_bundle(script, bundle)
    backups = list(bundle.parent.glob(".atbclone-backup.*"))
    assert len(backups) == 1
    assert str(backups[0]) in str(exc.value)
    assert (backups[0] / "original.app" / "original").read_text() == "working application"
    assert not Path(str(bundle) + ".atbclone-lock").exists()


def test_backup_move_failure_leaves_original_untouched(bundle, tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    failing_mv = bin_dir / "mv"
    failing_mv.write_text("#!/bin/sh\nexit 1\n")
    failing_mv.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    with pytest.raises(CloneError):
        replace_bundle(build_script(bundle), bundle)
    assert (bundle / "original").read_text() == "working application"
    assert_no_transaction_files(bundle)
