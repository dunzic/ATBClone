#!/usr/bin/env python3
"""Opt in a Codex clone to ordinary Responses function tools (Python >= 3.11).

For gateways that drop Responses Lite's additional_tools or custom code-mode
calls. This does not add gateway support for custom tools such as apply_patch.
Quit the clone first. No auth files are read, copied, or modified.
"""
import argparse
import json
import mmap
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import tomllib


def compatible_catalog(executable: Path) -> dict:
    # Use the installed version's own catalog; do not freeze model names/prompts
    # from one release into ATBClone or download a third-party catalog.
    with executable.open("rb") as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as blob:
        for match in re.finditer(rb'\{\s*"models"\s*:\s*\[', blob):
            try:
                catalog, _ = json.JSONDecoder().raw_decode(
                    blob[match.start():match.start() + 8_000_000].decode("utf-8", errors="replace")
                )
                models = catalog["models"]
                if not models or not all(isinstance(m, dict) and isinstance(m.get("slug"), str) for m in models):
                    continue
            except (ValueError, KeyError, TypeError):
                continue
            for model in models:
                model["use_responses_lite"] = False
                model["tool_mode"] = "standard"
            return catalog
    raise ValueError("No supported embedded model catalog found; configuration was not changed.")


def atomic_write(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def configure(executable: Path, codex_home: Path) -> Path | None:
    config_path = codex_home / "config.toml"
    if config_path.is_symlink():
        raise ValueError("Refusing to replace a symlinked config.toml.")
    original = config_path.read_text(encoding="utf-8")
    config = tomllib.loads(original)
    provider = config.get("model_providers", {}).get(config.get("model_provider"), {})
    if not provider.get("base_url") or provider.get("wire_api") != "responses":
        raise ValueError("This opt-in workaround requires a custom Responses API provider.")
    catalog_path = codex_home.resolve() / "models-api-compat.json"
    existing = config.get("model_catalog_json")
    if existing is not None and existing != str(catalog_path):
        raise ValueError("A custom model catalog is already configured; merge it manually.")
    catalog = compatible_catalog(executable)
    selected = {config[k] for k in ("model", "review_model") if config.get(k)}
    if selected - {m["slug"] for m in catalog["models"]}:
        raise ValueError("Configured model is absent from the bundled catalog; configuration was not changed.")
    updated = original if existing else f"model_catalog_json = {json.dumps(str(catalog_path))}\n" + original
    tomllib.loads(updated)
    backup = None
    if not existing:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = config_path.with_name(f"config.toml.before-atb-api-compat-{stamp}")
        shutil.copy2(config_path, backup)
        backup.chmod(0o600)
    atomic_write(catalog_path, json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    if updated != original:
        atomic_write(config_path, updated)
    return backup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, type=Path, help="Path to the cloned .app")
    parser.add_argument("--codex-home", required=True, type=Path, help="The clone's isolated CODEX_HOME")
    args = parser.parse_args()
    try:
        backup = configure(args.app / "Contents/Resources/codex", args.codex_home)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")
    print("Standard function tools configured. Restart the clone and verify a terminal command.")
    if backup:
        print(f"Configuration backup: {backup}")
    print("Custom tools still require gateway support. Regenerate this catalog after a Codex update.")


if __name__ == "__main__":
    main()
