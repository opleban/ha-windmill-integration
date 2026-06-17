"""Manifest and packaging checks for Windmill."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "custom_components" / "windmill" / "manifest.json"
STRINGS = ROOT / "custom_components" / "windmill" / "strings.json"
TRANSLATION = ROOT / "custom_components" / "windmill" / "translations" / "en.json"


def test_manifest_declares_config_flow() -> None:
    manifest = json.loads(MANIFEST.read_text())

    assert manifest["domain"] == "windmill"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "cloud_polling"
    assert manifest["integration_type"] == "hub"


def test_config_flow_strings_are_present() -> None:
    strings = json.loads(STRINGS.read_text())
    translation = json.loads(TRANSLATION.read_text())

    assert strings["config"]["step"]["user"]["data"]["email"] == "Email"
    assert strings["config"]["step"]["user"]["data"]["password"] == "Password"
    assert strings["config"]["step"]["user"]["data"]["org_id"] == "Organization id"
    assert "invalid_auth" in strings["config"]["error"]
    assert translation == strings
