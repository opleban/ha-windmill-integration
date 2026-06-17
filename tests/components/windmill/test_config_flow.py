"""Tests for the Windmill config flow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

DOMAIN = "windmill"
CONFIG_FLOW_MODULE = "custom_components.windmill.config_flow"
API_MODULE = "custom_components.windmill.api"

windmill_config_flow = None


@dataclass
class FakeWindmillDevice:
    """Small stand-in for the Windmill device dataclass."""

    unique_id: str
    name: str
    can_set_temperature: bool = True


@dataclass
class FakeWindmillDeviceState:
    """Small stand-in for the Windmill device state dataclass."""

    unique_id: str
    power: bool | None
    current_temperature: float | None
    target_temperature: float | None
    mode: str | None
    fan_speed: str | None


class FakeWindmillApiError(Exception):
    """Base error for the Windmill API stub."""


class FakeWindmillAuthError(FakeWindmillApiError):
    """Raised when the credentials are rejected."""


class FakeWindmillResponseError(FakeWindmillApiError):
    """Raised when the stubbed API returns an unexpected response."""


class FakeWindmillApi:
    """Minimal Windmill API stub for config flow tests."""

    def __init__(
        self,
        *,
        email: str,
        password_hash: str,
        org_id: int,
        session: object,
    ) -> None:
        self._email = email
        self._password_hash = password_hash
        self._org_id = org_id
        self._session = session

    async def async_list_devices(self):
        if self._email in self._session.invalid_emails:
            raise FakeWindmillAuthError("invalid credentials")

        key = (self._email, self._org_id)
        if key not in self._session.devices_by_account:
            raise FakeWindmillResponseError("unknown account")

        return self._session.devices_by_account[key]


class FakeSchema:
    """Small voluptuous.Schema replacement."""

    def __init__(self, schema):
        self.schema = schema

    def __call__(self, value):
        return value


def _install_stubs() -> None:
    """Install minimum module stubs needed to import the config flow."""

    sys.modules.pop(CONFIG_FLOW_MODULE, None)
    sys.modules.pop(API_MODULE, None)
    sys.modules.pop("custom_components.windmill", None)

    api_module = ModuleType(API_MODULE)
    api_module.WindmillApi = FakeWindmillApi
    api_module.WindmillApiError = FakeWindmillApiError
    api_module.WindmillAuthError = FakeWindmillAuthError
    api_module.WindmillResponseError = FakeWindmillResponseError
    api_module.WindmillDevice = FakeWindmillDevice
    api_module.WindmillDeviceState = FakeWindmillDeviceState
    api_module._hash_password = lambda email, password: f"hash:{email}:{password}"
    sys.modules[API_MODULE] = api_module

    homeassistant_module = ModuleType("homeassistant")
    config_entries_module = ModuleType("homeassistant.config_entries")
    core_module = ModuleType("homeassistant.core")
    helpers_module = ModuleType("homeassistant.helpers")
    aiohttp_client_module = ModuleType("homeassistant.helpers.aiohttp_client")
    update_coordinator_module = ModuleType("homeassistant.helpers.update_coordinator")
    voluptuous_module = ModuleType("voluptuous")

    class FakeConfigFlow:
        """Tiny ConfigFlow stand-in."""

        def __init_subclass__(cls, domain=None, **kwargs):
            super().__init_subclass__(**kwargs)
            cls._domain = domain

        def __init__(self):
            self.hass = None

        def async_show_form(self, *, step_id, data_schema, errors):
            return {
                "type": "form",
                "step_id": step_id,
                "data_schema": data_schema,
                "errors": errors,
            }

        def async_create_entry(self, *, title, data):
            entry = SimpleNamespace(
                domain=self._domain,
                title=title,
                data=data,
                unique_id=None,
            )
            if self.hass is not None:
                self.hass.config_entries.add_entry(entry)
            return {
                "type": "create_entry",
                "title": title,
                "data": data,
            }

        def async_abort(self, *, reason):
            return {"type": "abort", "reason": reason}

    config_entries_module.ConfigFlow = FakeConfigFlow
    core_module.callback = lambda func: func
    aiohttp_client_module.async_get_clientsession = lambda hass: hass.session
    update_coordinator_module.CoordinatorEntity = object
    update_coordinator_module.DataUpdateCoordinator = object
    update_coordinator_module.UpdateFailed = Exception
    voluptuous_module.Schema = FakeSchema
    voluptuous_module.Required = lambda key: key

    sys.modules["homeassistant"] = homeassistant_module
    sys.modules["homeassistant.config_entries"] = config_entries_module
    sys.modules["homeassistant.core"] = core_module
    sys.modules["homeassistant.helpers"] = helpers_module
    sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client_module
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator_module
    sys.modules["voluptuous"] = voluptuous_module


def setUpModule() -> None:
    """Prepare stubs and import the config flow once for this module."""

    global windmill_config_flow

    _install_stubs()
    import custom_components.windmill.config_flow as imported_module

    windmill_config_flow = imported_module


def tearDownModule() -> None:
    """Clean up the import stubs after the tests finish."""

    for name in (
        CONFIG_FLOW_MODULE,
        API_MODULE,
        "custom_components.windmill",
        "homeassistant.config_entries",
        "homeassistant.core",
        "homeassistant",
        "homeassistant.helpers.update_coordinator",
        "voluptuous",
    ):
        sys.modules.pop(name, None)


class FakeConfigEntryCollection:
    """Track config entries for the fake Home Assistant instance."""

    def __init__(self) -> None:
        self.entries = []

    def async_entries(self, domain):
        return [entry for entry in self.entries if entry.domain == domain]

    def add_entry(self, entry):
        self.entries.append(entry)


class FakeHass:
    """Minimal Home Assistant stand-in for config flow tests."""

    def __init__(self, session: object) -> None:
        self.session = session
        self.config_entries = FakeConfigEntryCollection()


class WindmillConfigFlowTest(unittest.IsolatedAsyncioTestCase):
    """Validate config flow behavior without Home Assistant installed."""

    def setUp(self) -> None:
        self.session = SimpleNamespace(
            devices_by_account={},
            invalid_emails=set(),
        )
        self.hass = FakeHass(self.session)

    def _make_flow(self):
        flow = windmill_config_flow.WindmillConfigFlow()
        flow.hass = self.hass
        return flow

    async def test_successful_submission_creates_entry(self) -> None:
        self.session.devices_by_account[("user@example.com", 1234)] = [
            FakeWindmillDevice(
                unique_id="device-abc123",
                name="Living Room AC",
            ),
            FakeWindmillDevice(
                unique_id="secondary-device",
                name="Bedroom AC",
            ),
        ]

        flow = self._make_flow()
        result = await flow.async_step_user(
            {
                "email": "User@Example.COM ",
                "password": "secret",
                "org_id": "1234",
            }
        )

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["title"], "Living Room AC")
        self.assertEqual(result["data"]["email"], "user@example.com")
        self.assertEqual(result["data"]["password_hash"], "hash:user@example.com:secret")
        self.assertEqual(result["data"]["org_id"], 1234)
        self.assertNotIn("password", result["data"])
        self.assertEqual(len(result["data"]["devices"]), 2)
        self.assertEqual(result["data"]["devices"][0]["unique_id"], "device-abc123")
        self.assertEqual(len(self.hass.config_entries.entries), 1)

    async def test_invalid_credentials_return_invalid_auth(self) -> None:
        self.session.invalid_emails.add("bad@example.com")

        flow = self._make_flow()
        result = await flow.async_step_user(
            {"email": "bad@example.com", "password": "wrong", "org_id": "1234"}
        )

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"], {"base": "invalid_auth"})
        self.assertEqual(self.hass.config_entries.entries, [])

    async def test_duplicate_submission_returns_already_configured(self) -> None:
        self.session.devices_by_account[("user@example.com", 1234)] = [
            FakeWindmillDevice(
                unique_id="device-abc123",
                name="Living Room AC",
            )
        ]

        first_flow = self._make_flow()
        first_result = await first_flow.async_step_user(
            {"email": "user@example.com", "password": "secret", "org_id": "1234"}
        )
        self.assertEqual(first_result["type"], "create_entry")
        self.assertEqual(len(self.hass.config_entries.entries), 1)

        second_flow = self._make_flow()
        second_result = await second_flow.async_step_user(
            {"email": "user@example.com", "password": "secret", "org_id": "1234"}
        )

        self.assertEqual(second_result["type"], "abort")
        self.assertEqual(second_result["reason"], "already_configured")
        self.assertEqual(len(self.hass.config_entries.entries), 1)


if __name__ == "__main__":
    unittest.main()
