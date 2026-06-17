"""Tests for Windmill climate entities and coordinator refresh."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntFlag
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

DOMAIN = "windmill"
API_MODULE = "custom_components.windmill.api"
COORDINATOR_MODULE = "custom_components.windmill.coordinator"
CLIMATE_MODULE = "custom_components.windmill.climate"
INIT_MODULE = "custom_components.windmill"

windmill_api = None
windmill_coordinator = None
windmill_climate = None
windmill_init = None


class HVACMode(str, Enum):
    """Minimal HVAC mode stand-in."""

    OFF = "off"
    COOL = "cool"
    FAN_ONLY = "fan_only"
    AUTO = "auto"


class ClimateEntityFeature(IntFlag):
    """Minimal climate feature stand-in."""

    TARGET_TEMPERATURE = 1
    FAN_MODE = 2


class FakeClimateEntity:
    """Base climate entity stub."""

    @property
    def name(self):
        return getattr(self, "_attr_name", None)

    @property
    def unique_id(self):
        return getattr(self, "_attr_unique_id", None)


class FakeCoordinatorEntity:
    """Coordinator entity stub."""

    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator


class FakeDataUpdateCoordinator:
    """DataUpdateCoordinator stub used by the component under test."""

    def __init__(self, hass, logger, name, update_interval) -> None:
        self.hass = hass
        self.logger = logger
        self.name = name
        self.update_interval = update_interval
        self.data = None
        self._listeners = []

    async def async_config_entry_first_refresh(self):
        self.data = await self._async_update_data()
        for listener in list(self._listeners):
            listener()
        return self.data

    async def async_request_refresh(self):
        return await self.async_config_entry_first_refresh()

    def async_add_listener(self, listener):
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)


class FakeUpdateFailed(Exception):
    """Raised when a coordinator refresh fails."""


class FakeHAHass:
    """Minimal Home Assistant stand-in."""

    def __init__(self) -> None:
        self.data = {}


class FakeApi:
    """Record Windmill API calls for assertions."""

    def __init__(self, devices, states) -> None:
        self._devices = devices
        self._states = states
        self.calls = []

    async def async_list_devices(self):
        self.calls.append(("list_devices",))
        return list(self._devices)

    async def async_get_device_state(self, device_id):
        self.calls.append(("get_device_state", device_id))
        return self._states[device_id]

    async def async_set_power(self, device_id, power):
        self.calls.append(("set_power", device_id, power))
        self._states[device_id].power = power

    async def async_set_temperature(self, device_id, temperature):
        self.calls.append(("set_temperature", device_id, temperature))
        self._states[device_id].target_temperature = temperature

    async def async_set_mode(self, device_id, mode):
        self.calls.append(("set_mode", device_id, mode))
        self._states[device_id].mode = mode

    async def async_set_fan_speed(self, device_id, fan_speed):
        self.calls.append(("set_fan_speed", device_id, fan_speed))
        self._states[device_id].fan_speed = fan_speed


@dataclass
class FakeEntry:
    """Minimal config entry stub."""

    entry_id: str


def _install_stubs() -> None:
    """Install minimum module stubs needed to import the component."""

    for module_name in (CLIMATE_MODULE, COORDINATOR_MODULE, INIT_MODULE, API_MODULE):
        sys.modules.pop(module_name, None)

    homeassistant_module = ModuleType("homeassistant")
    climate_module = ModuleType("homeassistant.components.climate")
    climate_const_module = ModuleType("homeassistant.components.climate.const")
    const_module = ModuleType("homeassistant.const")
    helpers_module = ModuleType("homeassistant.helpers")
    update_coordinator_module = ModuleType("homeassistant.helpers.update_coordinator")

    climate_module.ClimateEntity = FakeClimateEntity
    climate_module.ClimateEntityFeature = ClimateEntityFeature
    climate_const_module.HVACMode = HVACMode
    const_module.TEMP_FAHRENHEIT = "fahrenheit"
    update_coordinator_module.CoordinatorEntity = FakeCoordinatorEntity
    update_coordinator_module.DataUpdateCoordinator = FakeDataUpdateCoordinator
    update_coordinator_module.UpdateFailed = FakeUpdateFailed

    sys.modules["homeassistant"] = homeassistant_module
    sys.modules["homeassistant.components"] = ModuleType("homeassistant.components")
    sys.modules["homeassistant.components.climate"] = climate_module
    sys.modules["homeassistant.components.climate.const"] = climate_const_module
    sys.modules["homeassistant.const"] = const_module
    sys.modules["homeassistant.helpers"] = helpers_module
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator_module


def setUpModule() -> None:
    """Prepare stubs and import the component once for this module."""

    global windmill_api, windmill_coordinator, windmill_climate, windmill_init

    _install_stubs()

    import custom_components.windmill.api as imported_api
    import custom_components.windmill.coordinator as imported_coordinator
    import custom_components.windmill.climate as imported_climate
    import custom_components.windmill as imported_init

    windmill_api = imported_api
    windmill_coordinator = imported_coordinator
    windmill_climate = imported_climate
    windmill_init = imported_init


def tearDownModule() -> None:
    """Clean up import stubs after the tests finish."""

    for name in (
        CLIMATE_MODULE,
        COORDINATOR_MODULE,
        INIT_MODULE,
        API_MODULE,
        "homeassistant.components.climate",
        "homeassistant.components.climate.const",
        "homeassistant.components",
        "homeassistant.const",
        "homeassistant.helpers.update_coordinator",
        "homeassistant.helpers",
        "homeassistant",
    ):
        sys.modules.pop(name, None)


class WindmillClimateTest(unittest.IsolatedAsyncioTestCase):
    """Validate climate setup and control behavior without Home Assistant."""

    def setUp(self) -> None:
        self.device = windmill_api.WindmillDevice(
            unique_id="device-abc123",
            name="Living Room AC",
            can_set_temperature=True,
        )
        self.state = windmill_api.WindmillDeviceState(
            unique_id=self.device.unique_id,
            power=True,
            current_temperature=69.0,
            target_temperature=72.0,
            mode="cool",
            fan_speed="low",
        )
        self.api = FakeApi([self.device], {self.device.unique_id: self.state})
        self.hass = FakeHAHass()
        self.coordinator = windmill_coordinator.WindmillDataUpdateCoordinator(
            self.hass, self.api, "entry-1"
        )
        self.coordinator.devices = [self.device]
        self.coordinator.data = {self.device.unique_id: self.state}
        self.runtime = windmill_init.WindmillRuntimeData(
            api=self.api,
            token="wm_token",
            entry_data={"token": "wm_token"},
            coordinator=self.coordinator,
            devices=[self.device],
        )
        self.entry = FakeEntry(entry_id="entry-1")
        self.hass.data[DOMAIN] = {self.entry.entry_id: self.runtime}

    async def test_coordinator_refresh_populates_device_keyed_mapping(self) -> None:
        api = FakeApi(
            [
                self.device,
                windmill_api.WindmillDevice(
                    unique_id="secondary-device",
                    name="Bedroom AC",
                    can_set_temperature=True,
                ),
            ],
            {
                self.device.unique_id: self.state,
                "secondary-device": windmill_api.WindmillDeviceState(
                    unique_id="secondary-device",
                    power=False,
                    current_temperature=71.0,
                    target_temperature=73.0,
                    mode="fan",
                    fan_speed="high",
                ),
            },
        )
        coordinator = windmill_coordinator.WindmillDataUpdateCoordinator(
            self.hass, api, "entry-2"
        )

        data = await coordinator.async_config_entry_first_refresh()

        self.assertEqual(
            list(data.keys()),
            ["device-abc123", "secondary-device"],
        )
        self.assertEqual(coordinator.devices[0].name, "Living Room AC")
        self.assertEqual(coordinator.devices[1].name, "Bedroom AC")
        self.assertEqual(
            api.calls,
            [
                ("list_devices",),
                ("get_device_state", "device-abc123"),
                ("get_device_state", "secondary-device"),
            ],
        )

    async def test_setup_creates_one_climate_entity_for_device(self) -> None:
        added_entities = []

        def async_add_entities(entities):
            added_entities.extend(entities)

        await windmill_climate.async_setup_entry(
            self.hass, self.entry, async_add_entities
        )

        self.assertEqual(len(added_entities), 1)
        entity = added_entities[0]
        self.assertEqual(entity.unique_id, self.device.unique_id)
        self.assertEqual(entity.name, "Living Room AC")
        self.assertEqual(entity.current_temperature, 69.0)
        self.assertEqual(entity.target_temperature, 72.0)
        self.assertEqual(entity.hvac_mode, HVACMode.COOL)
        self.assertEqual(entity.fan_mode, "low")
        self.assertEqual(
            entity.supported_features,
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE,
        )

    async def test_setup_adds_new_entities_when_devices_are_discovered_later(self) -> None:
        added_entities = []

        def async_add_entities(entities):
            added_entities.extend(entities)

        await windmill_climate.async_setup_entry(
            self.hass, self.entry, async_add_entities
        )

        self.assertEqual(len(added_entities), 1)

        new_device = windmill_api.WindmillDevice(
            unique_id="secondary-device",
            name="Bedroom AC",
            can_set_temperature=True,
        )
        self.api._devices.append(new_device)
        self.api._states[new_device.unique_id] = windmill_api.WindmillDeviceState(
            unique_id=new_device.unique_id,
            power=False,
            current_temperature=71.0,
            target_temperature=73.0,
            mode="fan",
            fan_speed="high",
        )

        await self.coordinator.async_request_refresh()

        self.assertEqual(len(added_entities), 2)
        self.assertEqual(
            {entity.unique_id for entity in added_entities},
            {
                self.device.unique_id,
                "secondary-device",
            },
        )
        self.assertEqual(added_entities[1].name, "Bedroom AC")

    async def test_setup_adds_new_entities_even_if_one_refresh_fails(self) -> None:
        added_entities = []

        def async_add_entities(entities):
            added_entities.extend(entities)

        await windmill_climate.async_setup_entry(
            self.hass, self.entry, async_add_entities
        )

        failing_device_id = self.device.unique_id
        new_device = windmill_api.WindmillDevice(
            unique_id="secondary-device",
            name="Bedroom AC",
            can_set_temperature=True,
        )
        self.api._devices.append(new_device)
        self.api._states[new_device.unique_id] = windmill_api.WindmillDeviceState(
            unique_id=new_device.unique_id,
            power=False,
            current_temperature=71.0,
            target_temperature=73.0,
            mode="fan",
            fan_speed="high",
        )

        original_get_device_state = self.api.async_get_device_state

        async def flaky_get_device_state(device_id):
            if device_id == failing_device_id:
                self.api.calls.append(("get_device_state", device_id))
                raise windmill_api.WindmillResponseError("temporary device error")
            return await original_get_device_state(device_id)

        self.api.async_get_device_state = flaky_get_device_state

        await self.coordinator.async_request_refresh()

        self.assertEqual(len(added_entities), 2)
        self.assertEqual(
            {entity.unique_id for entity in added_entities},
            {
                self.device.unique_id,
                "secondary-device",
            },
        )
        self.assertEqual(self.coordinator.devices[-1].unique_id, "secondary-device")
        self.assertIn("temporary device error", self.coordinator.last_error)
        self.assertEqual(self.coordinator.device_failures[self.device.unique_id], 1)

    async def test_entity_availability_handles_missing_data_and_failures(self) -> None:
        entity = windmill_climate.WindmillClimateEntity(self.coordinator, self.device)

        self.coordinator.data = None
        self.coordinator.device_states = {}
        self.coordinator.consecutive_failures = 0
        self.assertFalse(entity.available)

        self.coordinator.data = {self.device.unique_id: self.state}
        self.coordinator.consecutive_failures = 1
        self.assertTrue(entity.available)

        self.coordinator.consecutive_failures = 2
        self.assertFalse(entity.available)

        self.coordinator.consecutive_failures = 0
        self.coordinator.device_failures = {self.device.unique_id: 1}
        self.assertTrue(entity.available)

        self.coordinator.device_failures = {self.device.unique_id: 2}
        self.assertFalse(entity.available)

    async def test_supported_features_reflect_temperature_capability(self) -> None:
        temperatureless_device = windmill_api.WindmillDevice(
            unique_id="no-temp-device",
            name="Living Room AC",
            can_set_temperature=False,
        )
        entity = windmill_climate.WindmillClimateEntity(
            self.coordinator, temperatureless_device
        )

        self.assertEqual(entity.supported_features, ClimateEntityFeature.FAN_MODE)

    async def test_entity_control_methods_use_normalized_values(self) -> None:
        entity = windmill_climate.WindmillClimateEntity(self.coordinator, self.device)

        self.api.calls = []
        await entity.async_turn_on()
        self.assertEqual(
            self.api.calls,
            [
                ("set_power", self.device.unique_id, True),
                ("list_devices",),
                ("get_device_state", self.device.unique_id),
            ],
        )
        self.assertTrue(self.coordinator.data[self.device.unique_id].power)

        self.api.calls = []
        await entity.async_turn_off()
        self.assertEqual(
            self.api.calls,
            [
                ("set_power", self.device.unique_id, False),
                ("list_devices",),
                ("get_device_state", self.device.unique_id),
            ],
        )
        self.assertFalse(self.coordinator.data[self.device.unique_id].power)

        self.api.calls = []
        await entity.async_set_temperature(temperature=74)
        self.assertEqual(
            self.api.calls,
            [
                ("set_temperature", self.device.unique_id, 74.0),
                ("list_devices",),
                ("get_device_state", self.device.unique_id),
            ],
        )
        self.assertEqual(
            self.coordinator.data[self.device.unique_id].target_temperature, 74.0
        )

        self.api.calls = []
        await entity.async_set_hvac_mode(HVACMode.COOL)
        self.assertEqual(
            self.api.calls,
            [
                ("set_power", self.device.unique_id, True),
                ("set_mode", self.device.unique_id, "cool"),
                ("list_devices",),
                ("get_device_state", self.device.unique_id),
            ],
        )
        self.assertEqual(self.coordinator.data[self.device.unique_id].mode, "cool")

        self.api.calls = []
        await entity.async_set_hvac_mode(HVACMode.OFF)
        self.assertEqual(
            self.api.calls,
            [
                ("set_mode", self.device.unique_id, "off"),
                ("set_power", self.device.unique_id, False),
                ("list_devices",),
                ("get_device_state", self.device.unique_id),
            ],
        )
        self.assertFalse(self.coordinator.data[self.device.unique_id].power)
        self.assertEqual(self.coordinator.data[self.device.unique_id].mode, "off")

        self.api.calls = []
        await entity.async_set_fan_mode("high")
        self.assertEqual(
            self.api.calls,
            [
                ("set_fan_speed", self.device.unique_id, "high"),
                ("list_devices",),
                ("get_device_state", self.device.unique_id),
            ],
        )
        self.assertEqual(self.coordinator.data[self.device.unique_id].fan_speed, "high")

    async def test_entity_rejects_unsupported_hvac_mode_before_writing(self) -> None:
        entity = windmill_climate.WindmillClimateEntity(self.coordinator, self.device)

        class UnsupportedMode:
            def __str__(self) -> str:
                return "unsupported"

        self.api.calls = []
        with self.assertRaises(ValueError):
            await entity.async_set_hvac_mode(UnsupportedMode())

        self.assertEqual(self.api.calls, [])


if __name__ == "__main__":
    unittest.main()
