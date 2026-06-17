"""Data update coordinator for Windmill devices."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import WindmillApi, WindmillApiError, WindmillDevice, WindmillDeviceState

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=5)


class WindmillDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinate Windmill device discovery and state refreshes."""

    def __init__(self, hass, api: WindmillApi, entry_id: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"windmill_{entry_id}",
            update_interval=SCAN_INTERVAL,
        )
        self.api = api
        self.entry_id = entry_id
        self.devices: list[WindmillDevice] = []
        self.device_states: dict[str, WindmillDeviceState] = {}
        self.device_failures: dict[str, int] = {}
        self.consecutive_failures = 0
        self.last_error: str | None = None

    async def _async_update_data(self) -> dict[str, WindmillDeviceState]:
        """Refresh the device list and all known device states."""

        try:
            devices = await self.api.async_list_devices()
            self.devices = list(devices)
            device_states: dict[str, WindmillDeviceState] = dict(self.device_states)
            state_errors: list[str] = []
            current_ids = {device.unique_id for device in devices}
            for device in devices:
                try:
                    device_states[device.unique_id] = await self.api.async_get_device_state(
                        device.unique_id
                    )
                    self.device_failures[device.unique_id] = 0
                except WindmillApiError as err:
                    self.device_failures[device.unique_id] = (
                        self.device_failures.get(device.unique_id, 0) + 1
                    )
                    state_errors.append(f"{device.unique_id}: {err}")
            device_states = {
                device_id: state
                for device_id, state in device_states.items()
                if device_id in current_ids
            }
            self.device_failures = {
                device_id: count
                for device_id, count in self.device_failures.items()
                if device_id in current_ids
            }
        except WindmillApiError as err:
            self.consecutive_failures += 1
            self.last_error = str(err)
            raise UpdateFailed(str(err)) from err

        self.device_states = device_states
        self.consecutive_failures = 0
        self.last_error = "; ".join(state_errors) if state_errors else None
        return device_states
