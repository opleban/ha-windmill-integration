"""Config flow for the Windmill integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Iterable, Set

import voluptuous as vol
from homeassistant import config_entries

from . import DOMAIN
from .api import WindmillApi, WindmillAuthError, WindmillResponseError, _hash_password

CONF_DEVICES = "devices"
CONF_EMAIL = "email"
CONF_ORG_ID = "org_id"
CONF_PASSWORD = "password"
CONF_PASSWORD_HASH = "password_hash"
CONF_TOKEN = "token"

_DEFAULT_TITLE = "Windmill AC"

_STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Required(CONF_ORG_ID): str,
    }
)


def _async_get_session(hass: Any) -> Any:
    """Return the Home Assistant shared aiohttp session."""

    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    return async_get_clientsession(hass)


def _device_ids(devices: Iterable[Any]) -> Set[str]:
    """Extract stable unique IDs from discovered devices."""

    device_ids: Set[str] = set()
    for device in devices:
        unique_id = getattr(device, "unique_id", None)
        if unique_id:
            device_ids.add(str(unique_id))
    return device_ids


def _entry_device_ids(entry_data: Dict[str, Any]) -> Set[str]:
    """Extract stored device unique IDs from an existing config entry."""

    stored_devices = entry_data.get(CONF_DEVICES, [])
    if not isinstance(stored_devices, list):
        return set()

    device_ids: Set[str] = set()
    for device in stored_devices:
        if not isinstance(device, dict):
            continue
        unique_id = device.get("unique_id")
        if unique_id:
            device_ids.add(str(unique_id))
    return device_ids


def _device_title(devices: Iterable[Any]) -> str:
    """Return a human-readable title for the config entry."""

    for device in devices:
        name = getattr(device, "name", None)
        if name:
            return str(name)
    return _DEFAULT_TITLE


def _is_already_configured(
    hass: Any, email: str, discovered_device_ids: Set[str]
) -> bool:
    """Check whether an equivalent Windmill setup already exists."""

    config_entries = getattr(hass, "config_entries", None)
    if config_entries is None or not hasattr(config_entries, "async_entries"):
        return False

    for entry in config_entries.async_entries(DOMAIN):
        entry_data = getattr(entry, "data", {})
        if not isinstance(entry_data, dict):
            continue

        existing_email = str(entry_data.get(CONF_EMAIL, "")).strip().lower()
        if existing_email == email:
            return True

        if _entry_device_ids(entry_data) & discovered_device_ids:
            return True

    return False


class WindmillConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Windmill config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: Dict[str, Any] | None = None):
        """Handle the initial setup step."""

        errors: Dict[str, str] = {}

        if user_input is not None:
            email = str(user_input.get(CONF_EMAIL, "")).strip().lower()
            password = str(user_input.get(CONF_PASSWORD, ""))
            org_id_text = str(user_input.get(CONF_ORG_ID, "")).strip()
            try:
                org_id = int(org_id_text)
            except ValueError:
                org_id = None

            if not email:
                errors[CONF_EMAIL] = "required"
            if not password:
                errors[CONF_PASSWORD] = "required"
            if org_id is None:
                errors[CONF_ORG_ID] = "required"

            if not errors:
                assert org_id is not None
                password_hash = _hash_password(email, password)
                session = _async_get_session(self.hass)
                api = WindmillApi(
                    email=email,
                    password_hash=password_hash,
                    org_id=org_id,
                    session=session,
                )
                try:
                    devices = await api.async_list_devices()
                except WindmillAuthError:
                    errors["base"] = "invalid_auth"
                except WindmillResponseError:
                    errors["base"] = "cannot_connect"
                else:
                    discovered_device_ids = _device_ids(devices)
                    if not discovered_device_ids:
                        errors["base"] = "cannot_connect"
                    elif _is_already_configured(
                        self.hass, email, discovered_device_ids
                    ):
                        return self.async_abort(reason="already_configured")
                    else:
                        return self.async_create_entry(
                            title=_device_title(devices),
                            data={
                                CONF_EMAIL: email,
                                CONF_PASSWORD_HASH: password_hash,
                                CONF_ORG_ID: org_id,
                                CONF_DEVICES: [asdict(device) for device in devices],
                            },
                        )

        return self.async_show_form(
            step_id="user",
            data_schema=_STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
