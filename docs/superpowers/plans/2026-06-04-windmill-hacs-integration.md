# Windmill AC HACS Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a HACS-ready Home Assistant custom integration that authenticates with a Windmill token, discovers every AC visible to the account, polls state, and sends control commands for power, temperature, mode, and fan speed.

**Architecture:** Keep all reverse-engineered Windmill HTTP details inside one API client module and drive the Home Assistant-facing code from a small normalized state model. Use a config flow for setup, a coordinator for polling, and one climate entity per AC so the UI stays simple and the integration remains easy to maintain when Windmill changes its dashboard internals.

**Tech Stack:** Home Assistant custom integration, Python async I/O, `aiohttp`/Home Assistant HTTP helpers, `pytest`, `pytest-homeassistant-custom-component`, and captured JSON fixtures from the Windmill dashboard session.

---

## File Map

- `custom_components/windmill/__init__.py` - config entry setup and unload wiring.
- `custom_components/windmill/manifest.json` - Home Assistant integration metadata.
- `custom_components/windmill/const.py` - domain constants, config keys, and polling defaults.
- `custom_components/windmill/api.py` - Windmill HTTP client, request/response models, and API exceptions.
- `custom_components/windmill/config_flow.py` - token entry flow and device discovery.
- `custom_components/windmill/coordinator.py` - polling, caching, and refresh error handling.
- `custom_components/windmill/climate.py` - climate entity implementation and service mapping.
- `custom_components/windmill/strings.json` and `translations/en.json` - setup UI strings.
- `hacs.json` - HACS metadata.
- `README.md` - install and setup instructions.
- `tests/components/windmill/` - config flow, API, coordinator, and entity tests.
- `tests/fixtures/windmill/` - captured Windmill JSON responses used by the tests.

## Task 1: Capture the Windmill API Contract and Lock the Normalized Model

**Files:**
- Create: `tests/fixtures/windmill/device_list.json`
- Create: `tests/fixtures/windmill/device_state.json`
- Create: `tests/fixtures/windmill/device_control_success.json`
- Create: `tests/fixtures/windmill/auth_failure.json`
- Create: `tests/components/windmill/test_api_client.py`
- Create: `custom_components/windmill/api.py`

- [ ] **Step 1: Write the failing tests**

Create tests that load the captured Windmill dashboard JSON fixtures and assert the normalized client contract. Use the current device UID from the dashboard session in the assertions so the model is anchored to real data.

```python
async def test_list_devices_parses_real_fixture(api: WindmillApi) -> None:
    devices = await api.async_list_devices()

    assert devices[0].unique_id == "device-abc123"
    assert devices[0].name == "Living Room AC"
    assert devices[0].can_set_temperature is True


async def test_get_device_state_parses_real_fixture(api: WindmillApi) -> None:
    state = await api.async_get_device_state("device-abc123")

    assert state.power is not None
    assert state.target_temperature is not None
    assert state.mode is not None
    assert state.fan_speed is not None
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run:

```bash
pytest tests/components/windmill/test_api_client.py -v
```

Expected: fail because `custom_components/windmill/api.py` does not exist yet and the model methods are not implemented.

- [ ] **Step 3: Implement the minimal Windmill API client**

Create `custom_components/windmill/api.py` with:

```python
@dataclass(slots=True)
class WindmillDevice:
    unique_id: str
    name: str
    can_set_temperature: bool


@dataclass(slots=True)
class WindmillDeviceState:
    unique_id: str
    power: bool | None
    current_temperature: float | None
    target_temperature: float | None
    mode: str | None
    fan_speed: str | None


class WindmillApiError(Exception):
    pass


class WindmillApi:
    async def async_list_devices(self) -> list[WindmillDevice]:
        raise NotImplementedError

    async def async_get_device_state(self, device_id: str) -> WindmillDeviceState:
        raise NotImplementedError

    async def async_set_power(self, device_id: str, power: bool) -> None:
        raise NotImplementedError

    async def async_set_temperature(self, device_id: str, temperature: float) -> None:
        raise NotImplementedError

    async def async_set_mode(self, device_id: str, mode: str) -> None:
        raise NotImplementedError

    async def async_set_fan_speed(self, device_id: str, fan_speed: str) -> None:
        raise NotImplementedError
```

Keep all Windmill-specific request formatting inside this file. Use the reverse-engineered dashboard endpoint shape only here, not in Home Assistant entities.

- [ ] **Step 4: Re-run the API client tests**

Run:

```bash
pytest tests/components/windmill/test_api_client.py -v
```

Expected: pass with the fixture-backed parser and command methods mapped correctly.

- [ ] **Step 5: Commit the fixture-backed API contract**

Use a commit message like:

```bash
git add tests/fixtures/windmill tests/components/windmill/test_api_client.py custom_components/windmill/api.py
git commit -m "feat: add Windmill API client contract"
```

## Task 2: Scaffold the Home Assistant Integration Package

**Files:**
- Create: `custom_components/windmill/__init__.py`
- Create: `custom_components/windmill/const.py`
- Create: `custom_components/windmill/manifest.json`
- Create: `custom_components/windmill/strings.json`
- Create: `custom_components/windmill/translations/en.json`
- Create: `hacs.json`
- Create: `tests/components/windmill/test_setup.py`

- [ ] **Step 1: Write the failing setup test**

Add a setup test that proves the integration can store an API client on the config entry runtime data and unload cleanly.

```python
async def test_setup_and_unload_entry(hass, mock_config_entry) -> None:
    assert await async_setup_entry(hass, mock_config_entry)
    assert mock_config_entry.entry_id in hass.data[DOMAIN]
    assert await async_unload_entry(hass, mock_config_entry)
```

- [ ] **Step 2: Run the setup test and confirm it fails**

Run:

```bash
pytest tests/components/windmill/test_setup.py -v
```

Expected: fail because the package skeleton and `async_setup_entry` wiring do not exist yet.

- [ ] **Step 3: Create the integration skeleton**

Implement `custom_components/windmill/__init__.py` to:

```python
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {}
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True
```

Add `manifest.json` with the integration domain, integration name, version, `config_flow: true`, and no external dependencies unless the API client truly needs one.

- [ ] **Step 4: Re-run the setup test**

Run:

```bash
pytest tests/components/windmill/test_setup.py -v
```

Expected: pass.

- [ ] **Step 5: Commit the package scaffold**

Use a commit message like:

```bash
git add custom_components/windmill hacs.json tests/components/windmill/test_setup.py
git commit -m "feat: scaffold Windmill integration package"
```

## Task 3: Build the Config Flow and Token Validation

**Files:**
- Create: `custom_components/windmill/config_flow.py`
- Modify: `custom_components/windmill/__init__.py`
- Create: `tests/components/windmill/test_config_flow.py`

- [ ] **Step 1: Write the failing config flow tests**

Cover these cases:

```python
async def test_user_flow_creates_entry(hass) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"token": "wm_valid_token"},
    )
    assert result["type"] == "create_entry"


async def test_user_flow_rejects_invalid_token(hass) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"token": "wm_bad_token"},
    )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "invalid_auth"
```

- [ ] **Step 2: Run the config flow tests and confirm failure**

Run:

```bash
pytest tests/components/windmill/test_config_flow.py -v
```

Expected: fail because the flow handler is missing and token validation has not been wired to `WindmillApi`.

- [ ] **Step 3: Implement the config flow**

Create a `ConfigFlow` that:

```python
class WindmillConfigFlow(ConfigFlow, domain=DOMAIN):
    async def async_step_user(self, user_input=None):
        # Ask for token, validate it with WindmillApi.async_list_devices(),
        # and create one config entry that stores the token securely.
        raise NotImplementedError
```

Validation rules:

- reject bad or expired tokens with `invalid_auth`
- reject duplicate entries with `already_configured`
- discover all devices during setup so the user sees immediately whether the token is usable

- [ ] **Step 4: Re-run the config flow tests**

Run:

```bash
pytest tests/components/windmill/test_config_flow.py -v
```

Expected: pass.

- [ ] **Step 5: Commit the flow and token validation**

Use a commit message like:

```bash
git add custom_components/windmill/config_flow.py custom_components/windmill/__init__.py tests/components/windmill/test_config_flow.py
git commit -m "feat: add Windmill config flow"
```

## Task 4: Add the Coordinator and Climate Entity

**Files:**
- Create: `custom_components/windmill/coordinator.py`
- Create: `custom_components/windmill/climate.py`
- Create: `tests/components/windmill/test_climate.py`
- Modify: `custom_components/windmill/__init__.py`

- [ ] **Step 1: Write the failing climate tests**

Verify that a device becomes a climate entity, that current state maps correctly, and that each control writes through the API client.

```python
async def test_climate_entity_maps_state(hass) -> None:
    entity = await add_test_entity(hass)
    assert entity.hvac_mode == HVACMode.COOL
    assert entity.target_temperature == 72
    assert entity.fan_mode == "low"


async def test_climate_turn_on_off_calls_api(hass) -> None:
    entity = await add_test_entity(hass)
    await entity.async_turn_off()
    await entity.async_turn_on()
```

Add explicit assertions for:

- `async_set_temperature`
- `async_set_hvac_mode`
- `async_set_fan_mode`
- state refresh after each command

- [ ] **Step 2: Run the climate tests and confirm they fail**

Run:

```bash
pytest tests/components/windmill/test_climate.py -v
```

Expected: fail because the coordinator and climate entity do not exist yet.

- [ ] **Step 3: Implement the polling coordinator and climate entity**

Create a `DataUpdateCoordinator` wrapper that refreshes device state on a fixed interval and caches the last known good payload. Then implement one climate entity per Windmill AC device using the normalized model from `api.py`.

```python
class WindmillCoordinator(DataUpdateCoordinator[list[WindmillDeviceState]]):
    async def _async_update_data(self) -> list[WindmillDeviceState]:
        raise NotImplementedError


class WindmillClimateEntity(ClimateEntity):
    async def async_set_temperature(self, **kwargs) -> None:
        raise NotImplementedError

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        raise NotImplementedError

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        raise NotImplementedError
```

Implementation rules:

- use `device_uid` as the entity unique ID
- preserve the last known state if one refresh fails
- mark the entity unavailable only after the coordinator cannot refresh consistently
- keep all Windmill command logic inside `api.py`

If the captured fixture shows that Windmill splits controls in a way that climate entities cannot represent cleanly, add `custom_components/windmill/switch.py` or `custom_components/windmill/select.py` only for those missing controls. Otherwise keep the first release to a single climate entity per device.

- [ ] **Step 4: Re-run the climate tests**

Run:

```bash
pytest tests/components/windmill/test_climate.py -v
```

Expected: pass.

- [ ] **Step 5: Commit the entity layer**

Use a commit message like:

```bash
git add custom_components/windmill/coordinator.py custom_components/windmill/climate.py custom_components/windmill/__init__.py tests/components/windmill/test_climate.py
git commit -m "feat: add Windmill climate entity"
```

## Task 5: Finish HACS Packaging, Documentation, and Release Checks

**Files:**
- Modify: `custom_components/windmill/manifest.json`
- Modify: `hacs.json`
- Modify: `README.md`
- Create or modify: `tests/components/windmill/test_unique_ids.py`

- [ ] **Step 1: Write the release-check tests**

Add a small test that asserts the entity unique IDs and config entry data are stable and derived from the Windmill device UID instead of a display name.

```python
async def test_unique_id_is_device_uid(entity) -> None:
    assert entity.unique_id == "device-abc123"
```

- [ ] **Step 2: Run the full Windmill test suite**

Run:

```bash
pytest tests/components/windmill -v
```

Expected: pass across API, config flow, coordinator, climate, and unique ID tests.

- [ ] **Step 3: Write the HACS and setup documentation**

Update `README.md` with:

- HACS installation steps
- token setup instructions
- what the integration exposes in Home Assistant
- known limitations:
  - cloud-only in v1
  - no mobile-app token scraping
  - no local-LAN control path yet

Update `hacs.json` and `manifest.json` so the repository is HACS-compatible and easy to install.

- [ ] **Step 4: Run a manual Home Assistant smoke check**

In a test Home Assistant instance:

1. Install the integration.
2. Enter a Windmill token.
3. Confirm the AC appears as a climate entity.
4. Change target temperature, fan speed, mode, and power.
5. Confirm the entity state updates after the next coordinator refresh.

Expected: the UI reflects Windmill state changes without requiring a restart.

- [ ] **Step 5: Commit the release-ready package**

Use a commit message like:

```bash
git add README.md hacs.json custom_components/windmill tests/components/windmill
git commit -m "docs: finish Windmill HACS integration"
```
