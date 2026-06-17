"""Windmill integration package."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from .api import WindmillApi, WindmillDevice
from .const import DOMAIN
from .coordinator import WindmillDataUpdateCoordinator

__all__ = ("DOMAIN", "WindmillRuntimeData", "async_setup_entry", "async_unload_entry")

PLATFORMS = ("climate",)


@dataclass
class WindmillRuntimeData:
    """Runtime state stored for each config entry."""

    api: WindmillApi
    token: Optional[str] = None
    email: Optional[str] = None
    password_hash: Optional[str] = None
    org_id: Optional[int] = None
    entry_data: dict[str, Any] = field(default_factory=dict)
    coordinator: Optional[WindmillDataUpdateCoordinator] = None
    devices: List[WindmillDevice] = field(default_factory=list)
    discovery_listener: Optional[Callable[[], None]] = None
    tearing_down: bool = False


def _async_get_session(hass: Any) -> Any:
    """Return the Home Assistant shared aiohttp session."""

    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    return async_get_clientsession(hass)


async def async_setup_entry(hass: Any, entry: Any) -> bool:
    """Set up Windmill from a config entry."""

    domain_data = hass.data.setdefault(DOMAIN, {})
    session = _async_get_session(hass)
    token = entry.data.get("token")
    email = entry.data.get("email")
    password_hash = entry.data.get("password_hash")
    org_id = entry.data.get("org_id")
    if token:
        api = WindmillApi(token=str(token), session=session)
    else:
        api = WindmillApi(
            email=str(email or ""),
            password_hash=str(password_hash or ""),
            org_id=org_id,
            session=session,
        )
    coordinator = WindmillDataUpdateCoordinator(hass, api, entry.entry_id)
    runtime = None

    try:
        await coordinator.async_config_entry_first_refresh()
        runtime = WindmillRuntimeData(
            api=api,
            token=str(token) if token else None,
            email=str(email).strip().lower() if email else None,
            password_hash=str(password_hash) if password_hash else None,
            org_id=int(org_id) if org_id is not None else None,
            entry_data=dict(entry.data),
            coordinator=coordinator,
            devices=list(coordinator.devices),
        )
        domain_data[entry.entry_id] = runtime
        forward_ok = await hass.config_entries.async_forward_entry_setups(
            entry, PLATFORMS
        )
    except Exception:
        if runtime is not None and runtime.discovery_listener is not None:
            from contextlib import suppress

            with suppress(Exception):
                runtime.discovery_listener()
            runtime.discovery_listener = None
        domain_data.pop(entry.entry_id, None)
        if not domain_data:
            hass.data.pop(DOMAIN, None)
        raise

    if forward_ok is False:
        if runtime is not None and runtime.discovery_listener is not None:
            from contextlib import suppress

            with suppress(Exception):
                runtime.discovery_listener()
            runtime.discovery_listener = None
        domain_data.pop(entry.entry_id, None)
        if not domain_data:
            hass.data.pop(DOMAIN, None)
        return False

    return True


async def async_unload_entry(hass: Any, entry: Any) -> bool:
    """Unload a Windmill config entry."""

    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if runtime is not None:
        runtime.tearing_down = True

    try:
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    except Exception:
        if runtime is not None:
            runtime.tearing_down = False
        raise

    if not unload_ok:
        if runtime is not None:
            runtime.tearing_down = False
        return False

    if runtime is not None and runtime.discovery_listener is not None:
        from contextlib import suppress

        with suppress(Exception):
            runtime.discovery_listener()
        runtime.discovery_listener = None
    if runtime is not None:
        runtime.tearing_down = False

    domain_data = hass.data.get(DOMAIN)
    if domain_data is None:
        return True

    domain_data.pop(entry.entry_id, None)
    if not domain_data:
        hass.data.pop(DOMAIN, None)
    return True
