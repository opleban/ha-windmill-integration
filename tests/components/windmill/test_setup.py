"""Tests for Windmill Home Assistant setup and unload."""

from __future__ import annotations

from dataclasses import is_dataclass
import sys
from types import SimpleNamespace
from pathlib import Path
from types import ModuleType
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

DOMAIN = "windmill"
WINDMILL_MODULE = "custom_components.windmill"
API_MODULE = "custom_components.windmill.api"
COORDINATOR_MODULE = "custom_components.windmill.coordinator"

windmill_module = None
WindmillApi = None
WindmillDevice = None
WindmillDeviceState = None
WindmillDataUpdateCoordinator = None
WindmillRuntimeData = None
async_setup_entry = None
async_unload_entry = None


class FakeHass:
    """Minimal Home Assistant stand-in for setup tests."""

    def __init__(
        self,
        *,
        forward_result: bool | None = None,
        unload_result: bool = True,
        on_forward=None,
    ) -> None:
        self.data: dict[str, object] = {}
        self.forward_result = forward_result
        self.unload_result = unload_result
        self.on_forward = on_forward
        self.config_entries = SimpleNamespace(
            async_forward_entry_setups=self.async_forward_entry_setups,
            async_unload_platforms=self.async_unload_platforms,
            forwarded=[],
            unloaded=[],
        )

    async def async_forward_entry_setups(self, entry, platforms):
        self.config_entries.forwarded.append((entry.entry_id, tuple(platforms)))
        if self.on_forward is not None:
            self.on_forward(entry, platforms)
        return self.forward_result

    async def async_unload_platforms(self, entry, platforms):
        self.config_entries.unloaded.append((entry.entry_id, tuple(platforms)))
        return self.unload_result


class FakeDataUpdateCoordinator:
    """Minimal DataUpdateCoordinator stand-in."""

    def __init__(self, hass, logger, name, update_interval) -> None:
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = None
        self._listeners = []

    async def async_config_entry_first_refresh(self):
        self.data = await self._async_update_data()
        return self.data

    def async_add_listener(self, listener):
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)


class FakeCoordinatorEntity:
    """Minimal CoordinatorEntity stand-in."""

    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator


class FakeUpdateFailed(Exception):
    """Raised when the fake coordinator fails."""


def _install_stubs() -> None:
    """Install minimum module stubs needed to import the Windmill package."""

    for module_name in (WINDMILL_MODULE, COORDINATOR_MODULE):
        sys.modules.pop(module_name, None)

    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    update_coordinator_module = ModuleType("homeassistant.helpers.update_coordinator")

    update_coordinator_module.DataUpdateCoordinator = FakeDataUpdateCoordinator
    update_coordinator_module.CoordinatorEntity = FakeCoordinatorEntity
    update_coordinator_module.UpdateFailed = FakeUpdateFailed

    sys.modules["homeassistant"] = homeassistant_module
    sys.modules["homeassistant.helpers"] = helpers_module
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator_module


def setUpModule() -> None:
    """Prepare stubs and import the package once for this module."""

    global windmill_module
    global WindmillApi
    global WindmillDevice
    global WindmillDeviceState
    global WindmillDataUpdateCoordinator
    global WindmillRuntimeData
    global async_setup_entry
    global async_unload_entry

    _install_stubs()

    import custom_components.windmill as imported_module
    from custom_components.windmill.api import (
        WindmillApi as ImportedWindmillApi,
        WindmillDevice as ImportedWindmillDevice,
        WindmillDeviceState as ImportedWindmillDeviceState,
    )
    from custom_components.windmill.coordinator import (
        WindmillDataUpdateCoordinator as ImportedWindmillDataUpdateCoordinator,
    )

    windmill_module = imported_module
    WindmillApi = ImportedWindmillApi
    WindmillDevice = ImportedWindmillDevice
    WindmillDeviceState = ImportedWindmillDeviceState
    WindmillDataUpdateCoordinator = ImportedWindmillDataUpdateCoordinator
    WindmillRuntimeData = imported_module.WindmillRuntimeData
    async_setup_entry = imported_module.async_setup_entry
    async_unload_entry = imported_module.async_unload_entry


def tearDownModule() -> None:
    """Clean up the import stubs after the tests finish."""

    for name in (
        WINDMILL_MODULE,
        API_MODULE,
        COORDINATOR_MODULE,
        "homeassistant.helpers.update_coordinator",
        "homeassistant.helpers",
        "homeassistant",
    ):
        sys.modules.pop(name, None)


class WindmillSetupTest(unittest.IsolatedAsyncioTestCase):
    """Verify the integration stores and clears runtime data."""

    async def test_setup_creates_runtime_bucket_and_unload_removes_it(self) -> None:
        hass = FakeHass()
        entry_data = {
            "email": "user@example.com",
            "password_hash": "hashed-password",
            "org_id": 1234,
        }
        entry = SimpleNamespace(entry_id="entry-1", data=entry_data)
        session = object()
        device = WindmillDevice(
            unique_id="device-abc123",
            name="Living Room AC",
            can_set_temperature=True,
        )
        device_state = WindmillDeviceState(
            unique_id=device.unique_id,
            power=True,
            current_temperature=69.0,
            target_temperature=72.0,
            mode="cool",
            fan_speed="low",
        )

        original_get_session = windmill_module._async_get_session
        original_refresh = WindmillDataUpdateCoordinator.async_config_entry_first_refresh

        async def fake_refresh(self):
            self.devices = [device]
            self.device_states = {device.unique_id: device_state}
            self.data = dict(self.device_states)
            return self.data

        windmill_module._async_get_session = lambda _hass: session
        WindmillDataUpdateCoordinator.async_config_entry_first_refresh = fake_refresh
        try:
            setup_result = await async_setup_entry(hass, entry)
            self.assertTrue(setup_result)

            self.assertIn(DOMAIN, hass.data)
            self.assertIn(entry.entry_id, hass.data[DOMAIN])

            runtime = hass.data[DOMAIN][entry.entry_id]
            self.assertTrue(is_dataclass(runtime))
            self.assertIsInstance(runtime, WindmillRuntimeData)
            self.assertIsInstance(runtime.api, WindmillApi)
            self.assertIsInstance(runtime.coordinator, WindmillDataUpdateCoordinator)
            self.assertIsNone(runtime.token)
            self.assertEqual(runtime.email, "user@example.com")
            self.assertEqual(runtime.password_hash, "hashed-password")
            self.assertEqual(runtime.org_id, 1234)
            self.assertEqual(runtime.entry_data, entry_data)
            self.assertIs(runtime.api._session, session)
            self.assertEqual(runtime.api._email, "user@example.com")
            self.assertEqual(runtime.api._password_hash, "hashed-password")
            self.assertEqual(runtime.api._org_id, 1234)
            self.assertEqual(runtime.devices, [device])
            self.assertEqual(runtime.coordinator.devices, [device])
            self.assertEqual(
                runtime.coordinator.device_states,
                {device.unique_id: device_state},
            )
            self.assertEqual(hass.config_entries.forwarded, [("entry-1", ("climate",))])

            unsubscribe = runtime.coordinator.async_add_listener(lambda: None)
            runtime.discovery_listener = unsubscribe
            self.assertEqual(len(runtime.coordinator._listeners), 1)
            unload_result = await async_unload_entry(hass, entry)
            self.assertTrue(unload_result)
            self.assertNotIn(DOMAIN, hass.data)
            self.assertEqual(len(runtime.coordinator._listeners), 0)
            self.assertIsNone(runtime.discovery_listener)
            self.assertEqual(hass.config_entries.unloaded, [("entry-1", ("climate",))])
        finally:
            windmill_module._async_get_session = original_get_session
            WindmillDataUpdateCoordinator.async_config_entry_first_refresh = original_refresh

    async def test_setup_cleans_up_when_platform_forward_fails(self) -> None:
        listener_calls = []
        coordinator_box = {}

        def on_forward(entry, platforms):
            runtime = hass.data[DOMAIN][entry.entry_id]
            unsubscribe = runtime.coordinator.async_add_listener(lambda: None)
            runtime.discovery_listener = unsubscribe
            coordinator_box["coordinator"] = runtime.coordinator
            listener_calls.append("registered")

        hass = FakeHass(forward_result=False, on_forward=on_forward)
        entry = SimpleNamespace(
            entry_id="entry-2",
            data={
                "email": "user@example.com",
                "password_hash": "hashed-password",
                "org_id": 1234,
            },
        )
        session = object()
        device = WindmillDevice(
            unique_id="device-abc123",
            name="Living Room AC",
            can_set_temperature=True,
        )
        device_state = WindmillDeviceState(
            unique_id=device.unique_id,
            power=True,
            current_temperature=69.0,
            target_temperature=72.0,
            mode="cool",
            fan_speed="low",
        )

        original_get_session = windmill_module._async_get_session
        original_refresh = WindmillDataUpdateCoordinator.async_config_entry_first_refresh

        async def fake_refresh(self):
            self.devices = [device]
            self.device_states = {device.unique_id: device_state}
            self.data = dict(self.device_states)
            return self.data

        windmill_module._async_get_session = lambda _hass: session
        WindmillDataUpdateCoordinator.async_config_entry_first_refresh = fake_refresh
        try:
            setup_result = await async_setup_entry(hass, entry)
            self.assertFalse(setup_result)
            self.assertNotIn(DOMAIN, hass.data)
            self.assertEqual(listener_calls, ["registered"])
            self.assertEqual(coordinator_box["coordinator"]._listeners, [])
            self.assertEqual(hass.config_entries.forwarded, [("entry-2", ("climate",))])
        finally:
            windmill_module._async_get_session = original_get_session
            WindmillDataUpdateCoordinator.async_config_entry_first_refresh = original_refresh

    async def test_setup_cleans_up_when_first_refresh_fails(self) -> None:
        hass = FakeHass()
        entry = SimpleNamespace(
            entry_id="entry-3",
            data={
                "email": "user@example.com",
                "password_hash": "hashed-password",
                "org_id": 1234,
            },
        )
        session = object()

        original_get_session = windmill_module._async_get_session
        original_refresh = WindmillDataUpdateCoordinator.async_config_entry_first_refresh

        async def fake_refresh(self):
            raise RuntimeError("refresh failed")

        windmill_module._async_get_session = lambda _hass: session
        WindmillDataUpdateCoordinator.async_config_entry_first_refresh = fake_refresh
        try:
            with self.assertRaises(RuntimeError):
                await async_setup_entry(hass, entry)

            self.assertNotIn(DOMAIN, hass.data)
        finally:
            windmill_module._async_get_session = original_get_session
            WindmillDataUpdateCoordinator.async_config_entry_first_refresh = original_refresh


if __name__ == "__main__":
    unittest.main()
