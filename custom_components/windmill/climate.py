"""Climate platform for Windmill devices."""

from __future__ import annotations

from typing import Any, Optional

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate.const import HVACMode
from homeassistant.const import TEMP_FAHRENHEIT
from homeassistant.helpers.update_coordinator import CoordinatorEntity, UpdateFailed

from .api import WindmillDevice, WindmillDeviceState
from .const import DOMAIN
from .coordinator import WindmillDataUpdateCoordinator


async def async_setup_entry(hass: Any, entry: Any, async_add_entities: Any) -> None:
    """Set up Windmill climate entities from a config entry."""

    runtime = hass.data[DOMAIN][entry.entry_id]
    coordinator = runtime.coordinator
    devices = list(runtime.devices or coordinator.devices)
    entities = [WindmillClimateEntity(coordinator, device) for device in devices]
    async_add_entities(entities)

    known_unique_ids = {device.unique_id for device in devices}

    def _async_handle_coordinator_update() -> None:
        if runtime.tearing_down:
            return

        new_devices = [
            device
            for device in coordinator.devices
            if device.unique_id not in known_unique_ids
        ]
        if not new_devices:
            return

        known_unique_ids.update(device.unique_id for device in new_devices)
        async_add_entities(
            [WindmillClimateEntity(coordinator, device) for device in new_devices]
        )

    runtime.discovery_listener = coordinator.async_add_listener(
        _async_handle_coordinator_update
    )


class WindmillClimateEntity(CoordinatorEntity, ClimateEntity):
    """Representation of a Windmill AC."""

    _attr_has_entity_name = True
    _attr_min_temp = 60.0
    _attr_max_temp = 90.0
    _attr_target_temperature_step = 1.0

    def __init__(
        self, coordinator: WindmillDataUpdateCoordinator, device: WindmillDevice
    ) -> None:
        super().__init__(coordinator)
        self._device = device
        self._attr_unique_id = device.unique_id

    def _current_device(self) -> WindmillDevice:
        """Return the latest device metadata for this entity."""

        for device in getattr(self.coordinator, "devices", []):
            if device.unique_id == self._device.unique_id:
                return device
        return self._device

    def _is_known_device(self) -> bool:
        """Return whether the device is still discovered."""

        return any(
            device.unique_id == self._device.unique_id
            for device in getattr(self.coordinator, "devices", [])
        )

    @property
    def name(self) -> str:
        """Return the current display name."""

        return self._current_device().name

    @property
    def available(self) -> bool:
        """Return whether the entity has state."""

        if not self._is_known_device():
            return False

        device_failures = getattr(self.coordinator, "device_failures", {})
        if isinstance(device_failures, dict) and device_failures.get(self._device.unique_id, 0) >= 2:
            return False

        if getattr(self.coordinator, "consecutive_failures", 0) >= 2:
            return False

        unique_id = self._device.unique_id
        device_states = getattr(self.coordinator, "data", None)
        if not isinstance(device_states, dict):
            device_states = {}

        if unique_id in device_states:
            return True

        device_states = getattr(self.coordinator, "device_states", None)
        if not isinstance(device_states, dict):
            device_states = {}

        return unique_id in device_states

    @property
    def temperature_unit(self) -> str:
        """Return the temperature unit."""

        return TEMP_FAHRENHEIT

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Supported HVAC modes."""

        return [HVACMode.OFF, HVACMode.COOL, HVACMode.FAN_ONLY, HVACMode.AUTO]

    @property
    def fan_modes(self) -> list[str]:
        """Supported fan modes."""

        return ["auto", "low", "medium", "high"]

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return supported features."""

        features = ClimateEntityFeature.FAN_MODE
        if self._current_device().can_set_temperature:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        return features

    def _state(self) -> Optional[WindmillDeviceState]:
        """Return the current normalized state for this device."""

        if not self._is_known_device():
            return None

        device_states = getattr(self.coordinator, "data", None)
        if isinstance(device_states, dict) and self._device.unique_id in device_states:
            state = device_states[self._device.unique_id]
            if isinstance(state, WindmillDeviceState):
                return state

        device_states = getattr(self.coordinator, "device_states", None)
        if isinstance(device_states, dict):
            state = device_states.get(self._device.unique_id)
            if isinstance(state, WindmillDeviceState):
                return state

        return None

    @property
    def current_temperature(self) -> Optional[float]:
        """Return the current temperature."""

        state = self._state()
        return None if state is None else state.current_temperature

    @property
    def target_temperature(self) -> Optional[float]:
        """Return the target temperature."""

        state = self._state()
        return None if state is None else state.target_temperature

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current HVAC mode."""

        state = self._state()
        if state is None or state.power is False or state.mode == "off":
            return HVACMode.OFF
        if state.mode == "cool":
            return HVACMode.COOL
        if state.mode == "fan":
            return HVACMode.FAN_ONLY
        if state.mode == "auto":
            return HVACMode.AUTO
        return HVACMode.OFF

    @property
    def fan_mode(self) -> Optional[str]:
        """Return the current fan mode."""

        state = self._state()
        return None if state is None else state.fan_speed

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the AC on."""

        hvac_mode = kwargs.get("hvac_mode")
        if hvac_mode is not None:
            await self.async_set_hvac_mode(hvac_mode)
            return

        await self.coordinator.api.async_set_power(self._device.unique_id, True)
        await self._async_refresh_after_write()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the AC off."""

        await self.coordinator.api.async_set_power(self._device.unique_id, False)
        await self._async_refresh_after_write()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature."""

        if not self._current_device().can_set_temperature:
            return

        temperature = kwargs.get("temperature")
        if temperature is None:
            return
        await self.coordinator.api.async_set_temperature(
            self._device.unique_id, float(temperature)
        )
        await self._async_refresh_after_write()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode."""

        refresh_needed = False
        if hvac_mode == HVACMode.OFF:
            try:
                await self.coordinator.api.async_set_mode(self._device.unique_id, "off")
                refresh_needed = True
                await self.coordinator.api.async_set_power(self._device.unique_id, False)
                refresh_needed = True
                return
            finally:
                if refresh_needed:
                    await self._async_refresh_after_write()

        normalized = self._normalize_hvac_mode(hvac_mode)
        if normalized not in {"cool", "fan", "auto"}:
            raise ValueError(f"Unsupported HVAC mode: {hvac_mode!r}")

        try:
            await self.coordinator.api.async_set_power(self._device.unique_id, True)
            refresh_needed = True
            await self.coordinator.api.async_set_mode(self._device.unique_id, normalized)
            refresh_needed = True
        finally:
            if refresh_needed:
                await self._async_refresh_after_write()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the fan mode."""

        await self.coordinator.api.async_set_fan_speed(
            self._device.unique_id, fan_mode
        )
        await self._async_refresh_after_write()

    async def _async_refresh_after_write(self) -> None:
        """Refresh state after a successful write."""

        try:
            await self.coordinator.async_request_refresh()
        except UpdateFailed:
            return

    def _normalize_hvac_mode(self, hvac_mode: HVACMode) -> str:
        """Normalize Home Assistant HVAC mode values."""

        if hvac_mode == HVACMode.COOL:
            return "cool"
        if hvac_mode == HVACMode.FAN_ONLY:
            return "fan"
        if hvac_mode == HVACMode.AUTO:
            return "auto"
        if hvac_mode == HVACMode.OFF:
            return "off"
        return str(hvac_mode)
