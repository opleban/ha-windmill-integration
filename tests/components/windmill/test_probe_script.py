"""Probe script checks."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_probe_script_requires_credentials() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "probe_windmill_api.py")],
        cwd=ROOT,
        env={},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "Missing credentials" in result.stderr
