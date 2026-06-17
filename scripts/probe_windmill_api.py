#!/usr/bin/env python3
"""Probe the reverse-engineered Windmill dashboard API without Home Assistant.

Usage:
  WINDMILL_EMAIL=... WINDMILL_PASSWORD=... WINDMILL_ORG_ID=1234 ./scripts/probe_windmill_api.py
  ./scripts/probe_windmill_api.py --email ... --password ... --org-id 1234

The password is never printed. This script performs read-only list/state calls.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ROOT / "custom_components"
WINDMILL_COMPONENT = COMPONENTS / "windmill"

# Load the API client without executing custom_components.windmill.__init__,
# which imports Home Assistant runtime modules that are unavailable in this
# standalone probe environment.
custom_components = types.ModuleType("custom_components")
custom_components.__path__ = [str(COMPONENTS)]
sys.modules.setdefault("custom_components", custom_components)
windmill_package = types.ModuleType("custom_components.windmill")
windmill_package.__path__ = [str(WINDMILL_COMPONENT)]
sys.modules["custom_components.windmill"] = windmill_package

from custom_components.windmill.api import WindmillApi, WindmillApiError  # noqa: E402


async def _run(
    *,
    email: str,
    password: str | None,
    password_hash: str | None,
    org_id: int,
    timeout: float,
) -> int:
    try:
        import aiohttp
    except ImportError as exc:
        raise RuntimeError(
            "aiohttp is required for the dashboard WebSocket probe. "
            "Install the test extras or run inside Home Assistant's environment."
        ) from exc

    timeout_config = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=timeout_config) as session:
        api = WindmillApi(
            email=email,
            password=password,
            password_hash=password_hash,
            org_id=org_id,
            session=session,
            request_timeout=timeout,
        )
        devices = await api.async_list_devices()
        print(f"devices={len(devices)}")
        for device in devices:
            print(f"device id={device.unique_id} name={device.name!r} can_set_temperature={device.can_set_temperature}")
            state = await api.async_get_device_state(device.unique_id)
            print(
                "state "
                f"id={state.unique_id} power={state.power} current={state.current_temperature} "
                f"target={state.target_temperature} mode={state.mode} fan={state.fan_speed}"
            )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Windmill read-only API access.")
    parser.add_argument("--email", default=os.environ.get("WINDMILL_EMAIL", ""), help="Windmill email; defaults to WINDMILL_EMAIL.")
    parser.add_argument("--password", default=os.environ.get("WINDMILL_PASSWORD", ""), help="Windmill password; defaults to WINDMILL_PASSWORD.")
    parser.add_argument("--password-hash", default=os.environ.get("WINDMILL_PASSWORD_HASH", ""), help="Precomputed dashboard password hash; defaults to WINDMILL_PASSWORD_HASH.")
    parser.add_argument("--org-id", default=os.environ.get("WINDMILL_ORG_ID", ""), help="Organization id from the dashboard URL; defaults to WINDMILL_ORG_ID.")
    parser.add_argument("--timeout", type=float, default=10.0, help="Request timeout in seconds.")
    args = parser.parse_args()
    email = str(args.email).strip().lower()
    password = str(args.password)
    password_hash = str(args.password_hash).strip()
    try:
        org_id = int(str(args.org_id).strip())
    except ValueError:
        org_id = 0
    if not email or not org_id or not (password or password_hash):
        print(
            "Missing credentials. Set WINDMILL_EMAIL, WINDMILL_PASSWORD or "
            "WINDMILL_PASSWORD_HASH, and WINDMILL_ORG_ID.",
            file=sys.stderr,
        )
        return 2
    try:
        return asyncio.run(
            _run(
                email=email,
                password=password or None,
                password_hash=password_hash or None,
                org_id=org_id,
                timeout=args.timeout,
            )
        )
    except (RuntimeError, WindmillApiError) as exc:
        print(f"Windmill probe failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
