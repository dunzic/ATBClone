"""CLI and GUI updates must preserve the existing bundle and registry on failure."""

import asyncio
import shlex

import pytest
from click.testing import CliRunner

from atbclone.cli.main import cli
from atbclone.core.app_inspector import AppInspector
from atbclone.core.bundle_transaction import replace_bundle
from atbclone.core.engines import HardCloneEngine, SoftCloneEngine
from atbclone.core.models import AppInfo
from atbclone.core.state import CloneRecord, StateManager
from atbclone.executor.runner import CloneError
from atbclone.gui.services.clone_service import CloneService
from atbclone.recipes.loader import RecipeLoader
from atbclone.recipes.models import Recipe


@pytest.mark.parametrize("entrypoint", ["cli", "gui"])
@pytest.mark.parametrize("strategy", ["hard_clone", "soft_clone"])
@pytest.mark.parametrize("failure", ["inspection", "construction"])
def test_update_failure_keeps_bundle_data_and_record(tmp_path, monkeypatch, entrypoint, strategy, failure):
    source = tmp_path / "Source.app"
    source.mkdir()
    dest = tmp_path / "Clone.app"
    dest.mkdir()
    (dest / "original").write_text("working bundle")
    data = tmp_path / "Data"
    data.mkdir()
    (data / "config.toml").write_text("existing settings")
    state_file = tmp_path / "clones.yaml"
    sm = StateManager(state_file)
    sm.add(CloneRecord(
        clone_name="Clone", source_app="Source", source_path=str(source),
        bundle_id="com.test.source", strategy=strategy, dest_path=str(dest),
        data_dir=str(data), created_at="2026-09-08T00:00:00Z",
        new_bundle_id="com.test.source.atbclone.2",
    ))
    original_state = state_file.read_bytes()
    monkeypatch.setattr("atbclone.cli.cmd_update.StateManager", lambda: sm)
    monkeypatch.setattr(RecipeLoader, "match", lambda *a, **kw: Recipe(
        bundle_id="com.test.source", app_name="Source", strategy=strategy,
    ))

    def inspect(*args):
        if failure == "inspection":
            raise CloneError("inspection failed")
        return AppInfo(source, "com.test.source", "Source", source / "Contents/MacOS/Source", False)

    def execute(task, needs_admin):
        # Even before the engine starts, neither entrypoint may delete the bundle.
        assert (dest / "original").read_text() == "working bundle"
        quoted = shlex.quote(str(task.dest_path))
        replace_bundle(f'mkdir -p {quoted}\ntouch {quoted}/partial\nexit 23', task.dest_path)

    monkeypatch.setattr(AppInspector, "inspect", inspect)
    engine = SoftCloneEngine if strategy == "soft_clone" else HardCloneEngine
    monkeypatch.setattr(engine, "execute", execute)
    if entrypoint == "cli":
        result = CliRunner().invoke(cli, ["update", "Clone"])
        assert result.exit_code == 1
        assert "inspection failed" in result.output if failure == "inspection" else "exit 23" in result.output
    else:
        service = CloneService(state_file)
        with pytest.raises(CloneError):
            asyncio.run(service.update_clone("Clone"))
        assert "Clone" not in service._busy_clones

    assert (dest / "original").read_text() == "working bundle"
    assert not (dest / "partial").exists()
    assert (data / "config.toml").read_text() == "existing settings"
    assert state_file.read_bytes() == original_state
