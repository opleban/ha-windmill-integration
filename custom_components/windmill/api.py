"""Async Windmill API client."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import hashlib
import json
import struct
from typing import Any, Optional
from urllib.parse import quote_plus

from .const import (
    DEFAULT_BASE_URL,
    FAN_NORMALIZED_BY_PIN,
    FAN_PIN_BY_NORMALIZED,
    GET_ENDPOINT,
    MODE_NORMALIZED_BY_PIN,
    MODE_PIN_BY_NORMALIZED,
    PIN_CURRENT_TEMPERATURE,
    PIN_FAN_SPEED,
    PIN_MODE,
    PIN_POWER,
    PIN_TARGET_TEMPERATURE,
    TOKEN_PARAM,
    UPDATE_ENDPOINT,
)

try:
    import async_timeout
except ImportError:  # pragma: no cover - Home Assistant normally provides this.
    async_timeout = None  # type: ignore[assignment]


@dataclass
class WindmillDevice:
    """Normalized Windmill device metadata."""

    unique_id: str
    name: str
    can_set_temperature: bool = True


@dataclass
class WindmillDeviceState:
    """Normalized Windmill device state."""

    unique_id: str
    power: Optional[bool]
    current_temperature: Optional[float]
    target_temperature: Optional[float]
    mode: Optional[str]
    fan_speed: Optional[str]


class WindmillApiError(Exception):
    """Base error for Windmill API failures."""


class WindmillAuthError(WindmillApiError):
    """Raised when the token is invalid or expired."""


class WindmillResponseError(WindmillApiError):
    """Raised when Windmill returns an unexpected response."""


WS_COMMAND_RESPONSE = 0
WS_COMMAND_LOGIN = 2
WS_COMMAND_HARDWARE = 20
WS_COMMAND_WEB_CONNECT_REDIRECT = 41
WS_COMMAND_WEB_GET_DEVICES = 104
WS_COMMAND_WEB_GET_DEVICE_NEW = 260
WS_RESPONSE_OK_MIN = 200
WS_RESPONSE_OK_MAX = 299

DASHBOARD_CLIENT_VERSION = "0.104.5"
DASHBOARD_LOCALE = "en_US"
WS_VALUE_SEPARATOR = "\0"


class _WindmillRedirect(Exception):
    """Raised internally when Windmill redirects to a regional socket."""

    def __init__(self, ws_url: str) -> None:
        super().__init__(ws_url)
        self.ws_url = ws_url


def _hash_password(email: str, password: str) -> str:
    """Return the password hash used by the Windmill dashboard login flow."""

    email_digest = hashlib.sha256(email.strip().lower().encode()).digest()
    password_bytes = password.encode()
    password_digest = hashlib.sha256(password_bytes + email_digest).digest()
    return base64.b64encode(password_digest).decode()


def _encode_ws_frame(command: int, msg_id: int, payload: str | bytes = "") -> bytes:
    """Encode a Windmill/Blynk WebSocket command frame."""

    body = payload if isinstance(payload, bytes) else payload.encode()
    return struct.pack(">HH", command, msg_id) + body


def _decode_ws_frame(
    data: bytes | bytearray | memoryview,
) -> tuple[int, int, int | None, bytes]:
    """Decode a Windmill/Blynk WebSocket command frame."""

    raw = bytes(data)
    if len(raw) < 4:
        raise WindmillResponseError("Windmill returned a truncated WebSocket frame")
    command, msg_id = struct.unpack(">HH", raw[:4])
    if command == WS_COMMAND_RESPONSE:
        if len(raw) < 8:
            raise WindmillResponseError("Windmill returned a truncated response frame")
        return command, msg_id, struct.unpack(">I", raw[4:8])[0], raw[8:]
    return command, msg_id, None, raw[4:]


class WindmillApi:
    """Windmill dashboard API wrapper."""

    def __init__(
        self,
        session: Any,
        token: str | None = None,
        email: str | None = None,
        password: str | None = None,
        password_hash: str | None = None,
        org_id: int | str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        request_timeout: float = 10.0,
    ) -> None:
        self._token = token
        self._email = email.strip().lower() if email else None
        self._password_hash = (
            password_hash
            or (
                _hash_password(self._email, password)
                if self._email and password
                else None
            )
        )
        self._org_id = self._coerce_int(org_id)
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._request_timeout = request_timeout
        self._msg_id = 0

    async def async_list_devices(self) -> list[WindmillDevice]:
        """Return the accessible Windmill devices."""

        if self._uses_dashboard_ws:
            payload = await self._async_dashboard_request(
                WS_COMMAND_WEB_GET_DEVICES,
                lambda: {"orgId": self._require_org_id()},
                expect_command=WS_COMMAND_WEB_GET_DEVICES,
            )
            device_dicts = self._extract_devices(payload)
            return [self._parse_device(device_dict) for device_dict in device_dicts]

        payload = await self._async_get_json(
            self._build_url(GET_ENDPOINT, {"devices": "1"}),
        )

        device_dicts = self._extract_devices(payload)
        return [self._parse_device(device_dict) for device_dict in device_dicts]

    async def async_get_device_state(self, device_id: str) -> WindmillDeviceState:
        """Fetch and normalize the current state for one device."""

        if self._uses_dashboard_ws:
            payload = await self._async_dashboard_request(
                WS_COMMAND_WEB_GET_DEVICE_NEW,
                lambda: {
                    "pageId": self._require_org_id(),
                    "deviceId": self._coerce_device_id(device_id),
                    "dashboardPageId": None,
                },
                expect_command=WS_COMMAND_WEB_GET_DEVICE_NEW,
            )
            return self._parse_state(device_id, payload)

        payload = await self._async_get_json(
            self._build_url(
                GET_ENDPOINT,
                {
                    PIN_POWER: None,
                    PIN_CURRENT_TEMPERATURE: None,
                    PIN_TARGET_TEMPERATURE: None,
                    PIN_MODE: None,
                    PIN_FAN_SPEED: None,
                    "device": device_id,
                },
            )
        )
        return self._parse_state(device_id, payload)

    async def async_set_power(self, device_id: str, power: bool) -> None:
        """Set device power."""

        await self._async_update_pin(device_id, PIN_POWER, 1 if power else 0)

    async def async_set_temperature(self, device_id: str, temperature: float) -> None:
        """Set the target temperature."""

        await self._async_update_pin(device_id, PIN_TARGET_TEMPERATURE, temperature)

    async def async_set_target_temperature(
        self, device_id: str, temperature: float
    ) -> None:
        """Backward-compatible alias for set_temperature."""

        await self.async_set_temperature(device_id, temperature)

    async def async_set_mode(self, device_id: str, mode: str) -> None:
        """Set the HVAC mode."""

        normalized = self._normalize_mode(mode)
        if normalized is None:
            raise WindmillResponseError(f"Unsupported mode value: {mode!r}")
        await self._async_update_pin(
            device_id, PIN_MODE, MODE_PIN_BY_NORMALIZED[normalized]
        )

    async def async_set_fan_speed(self, device_id: str, fan_speed: str) -> None:
        """Set the fan speed."""

        normalized = self._normalize_fan_speed(fan_speed)
        if normalized is None:
            raise WindmillResponseError(f"Unsupported fan speed value: {fan_speed!r}")
        await self._async_update_pin(
            device_id, PIN_FAN_SPEED, FAN_PIN_BY_NORMALIZED[normalized]
        )

    async def _async_update_pin(self, device_id: str, pin: str, value: Any) -> None:
        if self._uses_dashboard_ws:
            await self._async_dashboard_hardware_write(device_id, pin, value)
            return

        payload = await self._async_get_json(
            self._build_url(UPDATE_ENDPOINT, {pin: value, "device": device_id}),
        )
        self._ensure_success(payload)

    @property
    def _uses_dashboard_ws(self) -> bool:
        return bool(self._email and self._password_hash)

    async def _async_dashboard_hardware_write(
        self, device_id: str, pin: str, value: Any
    ) -> None:
        pin_type, dashboard_pin = self._dashboard_pin(pin)
        await self._async_dashboard_request(
            WS_COMMAND_HARDWARE,
            lambda: (
                f"{self._coerce_device_id(device_id)}{WS_VALUE_SEPARATOR}"
                f"{pin_type}{WS_VALUE_SEPARATOR}{dashboard_pin}"
                f"{WS_VALUE_SEPARATOR}{value}"
            ),
            expect_command=None,
        )

    def _dashboard_pin(self, pin: str) -> tuple[str, str]:
        """Return the dashboard hardware pin type and numeric pin value."""

        pin_text = str(pin)
        if len(pin_text) > 1 and pin_text[1:].isdigit():
            pin_prefix = pin_text[0].upper()
            if pin_prefix == "A":
                return "aw", pin_text[1:]
            if pin_prefix == "D":
                return "dw", pin_text[1:]
            if pin_prefix == "V":
                return "vw", pin_text[1:]
        return "vw", pin_text

    async def _async_dashboard_request(
        self,
        command: int,
        payload_factory,
        *,
        expect_command: int | None,
    ) -> Any:
        self._ensure_dashboard_credentials()
        socket_base_url = self._base_url.replace("https://", "wss://").replace(
            "http://", "ws://"
        )
        ws_url = f"{socket_base_url}/dashws"
        redirect_attempts = 0

        while True:
            try:
                async with self._timeout():
                    ws_cm = self._session.ws_connect(
                        ws_url,
                        heartbeat=30,
                        timeout=self._request_timeout,
                    )
                    async with ws_cm as ws:
                        login_payload = await self._async_ws_login(ws)
                        self._update_org_from_payload(login_payload)
                        payload = payload_factory()
                        return await self._async_ws_request(
                            ws,
                            command,
                            payload,
                            expect_command=expect_command,
                        )
            except _WindmillRedirect as err:
                redirect_attempts += 1
                if redirect_attempts > 2:
                    raise WindmillResponseError(
                        "Windmill redirected too many times"
                    ) from err
                ws_url = err.ws_url
            except asyncio.TimeoutError as err:
                raise WindmillResponseError("Windmill WebSocket request timed out") from err

    async def _async_ws_login(self, ws: Any) -> Any:
        assert self._email is not None
        assert self._password_hash is not None
        return await self._async_ws_request(
            ws,
            WS_COMMAND_LOGIN,
            {
                "email": self._email,
                "hash": self._password_hash,
                "clientType": "web",
                "version": DASHBOARD_CLIENT_VERSION,
                "locale": DASHBOARD_LOCALE,
            },
            expect_command=WS_COMMAND_LOGIN,
        )

    async def _async_ws_request(
        self,
        ws: Any,
        command: int,
        payload: dict[str, Any] | str,
        *,
        expect_command: int | None,
    ) -> Any:
        msg_id = self._next_msg_id()
        payload_text = (
            json.dumps(payload, separators=(",", ":"))
            if isinstance(payload, dict)
            else payload
        )
        frame = _encode_ws_frame(command, msg_id, payload_text)
        send_bytes = getattr(ws, "send_bytes", None)
        if send_bytes is None:
            await ws.send(frame)
        else:
            await send_bytes(frame)

        if expect_command is None:
            return None

        while True:
            message = await self._async_receive_ws_message(ws)
            message_data = getattr(message, "data", message)
            if isinstance(message_data, str):
                message_data = message_data.encode()
            frame_command, frame_msg_id, response_code, body = _decode_ws_frame(
                message_data
            )

            if frame_command == WS_COMMAND_WEB_CONNECT_REDIRECT:
                host = body.decode().strip()
                if not host:
                    raise WindmillResponseError("Windmill returned an empty redirect")
                raise _WindmillRedirect(f"wss://{host}/dashws")

            if frame_msg_id != msg_id:
                continue

            if frame_command == WS_COMMAND_RESPONSE:
                assert response_code is not None
                if response_code in (401, 403):
                    raise WindmillAuthError(
                        "Windmill rejected the supplied credentials"
                    )
                if not (WS_RESPONSE_OK_MIN <= response_code <= WS_RESPONSE_OK_MAX):
                    raise WindmillResponseError(
                        f"Windmill returned response code {response_code}"
                    )
                continue

            if expect_command is not None and frame_command == expect_command:
                return self._parse_ws_body(body)

    async def _async_receive_ws_message(self, ws: Any) -> Any:
        receive = ws.receive()
        try:
            async with self._timeout():
                return await receive
        except WindmillApiError:
            raise
        except Exception as err:
            raise WindmillResponseError(
                f"Windmill WebSocket request failed: {err}"
            ) from err

    def _next_msg_id(self) -> int:
        self._msg_id = 1 if self._msg_id >= 65535 else self._msg_id + 1
        return self._msg_id

    def _ensure_dashboard_credentials(self) -> None:
        if not self._uses_dashboard_ws:
            raise WindmillAuthError("Windmill dashboard credentials are required")

    def _require_org_id(self) -> int:
        if self._org_id is None:
            raise WindmillResponseError(
                "Windmill did not provide an organization id; configure org_id"
            )
        return self._org_id

    def _update_org_from_payload(self, payload: Any) -> None:
        if self._org_id is not None:
            return
        org_id = self._find_first_key(payload, {"orgId", "org_id", "currentOrgId"})
        self._org_id = self._coerce_int(org_id)

    def _parse_ws_body(self, body: bytes) -> Any:
        text = body.decode().strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    async def _async_get_json(self, url: str) -> Any:
        status, body = await self._request_text("get", url)
        if status in (401, 403):
            raise WindmillAuthError("Windmill rejected the supplied token")
        if status >= 400:
            raise WindmillResponseError(
                f"Windmill returned HTTP {status}: {body[:200]}"
            )
        try:
            return json.loads(body)
        except json.JSONDecodeError as err:
            raise WindmillResponseError("Windmill returned invalid JSON") from err

    async def _request_text(self, method: str, url: str) -> tuple[int, str]:
        request = getattr(self._session, method)
        try:
            async with self._timeout():
                response_cm = request(url)
                async with response_cm as resp:
                    return resp.status, await resp.text()
        except WindmillApiError:
            raise
        except Exception as err:
            raise WindmillResponseError(f"Windmill request failed: {err}") from err

    def _timeout(self):
        if async_timeout is not None:
            return async_timeout.timeout(self._request_timeout)
        return asyncio.timeout(self._request_timeout)

    def _build_url(self, endpoint: str, params: dict[str, Any]) -> str:
        if self._token is None:
            raise WindmillAuthError("Windmill token is required for legacy API calls")
        query: list[tuple[str, Any]] = [(TOKEN_PARAM, self._token)]
        for key, value in params.items():
            query.append((key, value))
        encoded = "&".join(
            f"{key}"
            if value is None
            else f"{key}={quote_plus(str(value))}"
            for key, value in query
        )
        return f"{self._base_url}/{endpoint}?{encoded}"

    def _extract_devices(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            if "devices" in payload and isinstance(payload["devices"], list):
                if not payload["devices"]:
                    raise WindmillResponseError("Windmill returned no devices")
                devices = [device for device in payload["devices"] if isinstance(device, dict)]
                if devices:
                    return devices
            if "device" in payload and isinstance(payload["device"], dict):
                return [payload["device"]]
            for key in ("items", "data", "rows"):
                if key in payload and isinstance(payload[key], list):
                    devices = [
                        device for device in payload[key] if isinstance(device, dict)
                    ]
                    if devices:
                        return devices
                if key in payload and isinstance(payload[key], dict):
                    return self._extract_devices(payload[key])
            return [payload]
        if isinstance(payload, list):
            if not payload:
                raise WindmillResponseError("Windmill returned no devices")
            devices = [device for device in payload if isinstance(device, dict)]
            if devices:
                return devices
        raise WindmillResponseError("Windmill returned an unexpected device payload")

    def _parse_device(self, payload: dict[str, Any]) -> WindmillDevice:
        unique_id = self._coerce_string(
            payload.get("unique_id")
            or payload.get("id")
            or payload.get("device_id")
            or payload.get("uid")
        )
        name = self._coerce_string(payload.get("name") or payload.get("label"))
        can_set_temperature = self._coerce_bool(
            payload.get("can_set_temperature"), default=True
        )
        if unique_id is None or name is None:
            raise WindmillResponseError("Windmill returned incomplete device metadata")
        return WindmillDevice(
            unique_id=unique_id,
            name=name,
            can_set_temperature=can_set_temperature,
        )

    def _parse_state(self, device_id: str, payload: Any) -> WindmillDeviceState:
        if not isinstance(payload, dict):
            raise WindmillResponseError("Windmill returned an unexpected state payload")
        pin_values = self._extract_pin_values(payload)
        unique_id = self._coerce_string(
            payload.get("unique_id")
            or payload.get("id")
            or payload.get("device_id")
            or payload.get("uid")
            or device_id
        )
        if unique_id is None:
            raise WindmillResponseError("Windmill returned an incomplete state payload")
        return WindmillDeviceState(
            unique_id=unique_id,
            power=self._normalize_bool(
                self._value_for_pin(payload, pin_values, PIN_POWER, "power")
            ),
            current_temperature=self._normalize_number(
                self._value_for_pin(
                    payload,
                    pin_values,
                    PIN_CURRENT_TEMPERATURE,
                    "current_temperature",
                )
            ),
            target_temperature=self._normalize_number(
                self._value_for_pin(
                    payload,
                    pin_values,
                    PIN_TARGET_TEMPERATURE,
                    "target_temperature",
                )
            ),
            mode=self._normalize_mode(
                self._value_for_pin(payload, pin_values, PIN_MODE, "mode")
            ),
            fan_speed=self._normalize_fan_speed(
                self._value_for_pin(payload, pin_values, PIN_FAN_SPEED, "fan_speed")
            ),
        )

    def _value_for_pin(
        self,
        payload: dict[str, Any],
        pin_values: dict[str, Any],
        pin: str,
        friendly_name: str,
    ) -> Any:
        if pin in pin_values:
            return pin_values[pin]
        if pin in payload:
            return payload[pin]
        return payload.get(friendly_name)

    def _extract_pin_values(self, payload: Any) -> dict[str, Any]:
        values: dict[str, Any] = {}

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                for pin in (
                    PIN_POWER,
                    PIN_CURRENT_TEMPERATURE,
                    PIN_TARGET_TEMPERATURE,
                    PIN_MODE,
                    PIN_FAN_SPEED,
                ):
                    if pin in value:
                        values.setdefault(pin, value[pin])
                pin = self._coerce_string(
                    self._first_present(
                        value,
                        (
                            "pin",
                            "virtualPin",
                            "dataStreamPin",
                            "datastreamPin",
                        ),
                    )
                )
                if pin:
                    pin = pin.upper()
                    if not pin.startswith("V") and pin.isdigit():
                        pin = f"V{pin}"
                    if pin in {
                        PIN_POWER,
                        PIN_CURRENT_TEMPERATURE,
                        PIN_TARGET_TEMPERATURE,
                        PIN_MODE,
                        PIN_FAN_SPEED,
                    }:
                        pin_value = self._find_first_key(
                            value,
                            {
                                "value",
                                "currentValue",
                                "latestValue",
                                "defaultValue",
                                "valueFormatted",
                            },
                        )
                        if pin_value is not None:
                            values[pin] = pin_value
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(payload)
        return values

    def _ensure_success(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return

        error = payload.get("error")
        status = str(payload.get("status", "")).strip().lower()
        error_text = str(error).strip().lower() if error is not None else ""
        if error_text in {"unauthorized", "invalid_token"} or status in {
            "unauthorized",
            "invalid_token",
        }:
            raise WindmillAuthError("Windmill rejected the supplied token")
        if error or status in {"error", "failed", "failure"}:
            raise WindmillResponseError(
                f"Windmill returned an error payload: {payload!r}"
            )

    def _normalize_bool(self, value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(int(value))
        text = str(value).strip().lower()
        if text in {"1", "true", "on", "yes"}:
            return True
        if text in {"0", "false", "off", "no"}:
            return False
        return None

    def _normalize_number(self, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value).strip())
        except ValueError:
            return None

    def _normalize_mode(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return MODE_NORMALIZED_BY_PIN.get(int(value))
        text = str(value).strip().lower()
        if text.isdigit():
            return MODE_NORMALIZED_BY_PIN.get(int(text))
        aliases = {
            "auto": "auto",
            "automatic": "auto",
            "cool": "cool",
            "cooling": "cool",
            "eco": "auto",
            "fan": "fan",
            "fan_only": "fan",
            "fan only": "fan",
            "off": "off",
        }
        return aliases.get(text)

    def _normalize_fan_speed(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return FAN_NORMALIZED_BY_PIN.get(int(value))
        text = str(value).strip().lower()
        if text.isdigit():
            return FAN_NORMALIZED_BY_PIN.get(int(text))
        aliases = {
            "auto": "auto",
            "low": "low",
            "medium": "medium",
            "med": "medium",
            "high": "high",
        }
        return aliases.get(text)

    def _coerce_string(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _coerce_bool(self, value: Any, *, default: bool) -> bool:
        normalized = self._normalize_bool(value)
        return default if normalized is None else normalized

    def _coerce_int(self, value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    def _coerce_device_id(self, value: Any) -> int | str:
        text = self._coerce_string(value)
        if text is None:
            raise WindmillResponseError("Windmill device id is required")
        integer = self._coerce_int(text)
        return integer if integer is not None else text

    def _find_first_key(self, payload: Any, keys: set[str]) -> Any:
        if isinstance(payload, dict):
            for key in keys:
                if key in payload:
                    return payload[key]
            for value in payload.values():
                found = self._find_first_key(value, keys)
                if found is not None:
                    return found
        elif isinstance(payload, list):
            for value in payload:
                found = self._find_first_key(value, keys)
                if found is not None:
                    return found
        return None

    def _first_present(self, payload: dict[str, Any], keys: tuple[str, ...]) -> Any:
        for key in keys:
            if key in payload:
                return payload[key]
        return None
