"""Regression checks for opt-in custom API tool compatibility."""
import importlib.util
import json
from pathlib import Path

import pytest

tomllib = pytest.importorskip("tomllib", reason="Compatibility script requires Python 3.11+")

spec = importlib.util.spec_from_file_location(
    "codex_api_compat", Path(__file__).parents[1] / "scripts/configure_codex_api_compat.py"
)
compat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compat)


@pytest.fixture
def installation(tmp_path):
    binary = tmp_path / "codex"
    catalog = {"models": [{"slug": "model-a", "use_responses_lite": True,
                           "tool_mode": "code_mode_only", "context_window": 12345}]}
    binary.write_bytes(b"\x00native\xff" + json.dumps(catalog).encode() + b"\x00trailer\xff")
    home = tmp_path / "isolated home"
    home.mkdir()
    (home / "config.toml").write_text('''# Keep this comment
model = "model-a"
model_provider = "custom"
[model_providers.custom]
base_url = "http://localhost:9999/v1"
wire_api = "responses"
[features]
shell_tool = true
''')
    return binary, home


def test_configure_preserves_config_and_auth_and_is_idempotent(installation):
    binary, home = installation
    config = home / "config.toml"
    original = config.read_text()
    auth = home / "auth.json"
    auth.write_text("do not touch")
    backup = compat.configure(binary, home)
    assert backup.read_text() == original
    assert config.read_text().endswith(original)
    parsed = tomllib.loads(config.read_text())
    models = json.loads(Path(parsed.pop("model_catalog_json")).read_text())["models"]
    assert parsed == tomllib.loads(original)
    assert models == [{"slug": "model-a", "use_responses_lite": False,
                       "tool_mode": "standard", "context_window": 12345}]
    assert config.stat().st_mode & 0o777 == 0o600
    assert auth.read_text() == "do not touch"
    assert compat.configure(binary, home) is None
    assert len(list(home.glob("config.toml.before-*"))) == 1


@pytest.mark.parametrize("failure", ["binary", "model", "catalog", "provider"])
def test_unsupported_configuration_is_untouched(installation, failure):
    binary, home = installation
    config = home / "config.toml"
    if failure == "binary":
        binary.write_bytes(b"different runtime layout")
    elif failure == "model":
        config.write_text(config.read_text().replace('model = "model-a"', 'model = "unknown"'))
    elif failure == "catalog":
        config.write_text('model_catalog_json = "/custom/catalog.json"\n' + config.read_text())
    else:
        config.write_text(config.read_text().replace('wire_api = "responses"', 'wire_api = "other"'))
    original = config.read_bytes()
    with pytest.raises(ValueError):
        compat.configure(binary, home)
    assert config.read_bytes() == original
    assert not (home / "models-api-compat.json").exists()
    assert not list(home.glob("config.toml.before-*"))


def test_symlinked_config_is_untouched(installation):
    binary, home = installation
    config = home / "config.toml"
    actual = home / "shared-config.toml"
    config.rename(actual)
    config.symlink_to(actual)
    with pytest.raises(ValueError, match="symlinked"):
        compat.configure(binary, home)
    assert config.is_symlink()
