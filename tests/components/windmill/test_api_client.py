"""Tests for the Windmill API client."""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType
import struct

import pytest

import sys


def _install_stubs() -> None:
    """Install minimum stubs needed to import the Windmill package."""

    homeassistant_module = ModuleType("homeassistant")
    helpers_module = ModuleType("homeassistant.helpers")
    update_coordinator_module = ModuleType("homeassistant.helpers.update_coordinator")

    class FakeDataUpdateCoordinator:
        """Minimal DataUpdateCoordinator stand-in."""

        def __init__(self, *args, **kwargs) -> None:
            pass

    class FakeCoordinatorEntity:
        """Minimal CoordinatorEntity stand-in."""

        def __init__(self, coordinator) -> None:
            self.coordinator = coordinator

    class FakeUpdateFailed(Exception):
        """Raised when a refresh fails."""

    update_coordinator_module.DataUpdateCoordinator = FakeDataUpdateCoordinator
    update_coordinator_module.CoordinatorEntity = FakeCoordinatorEntity
    update_coordinator_module.UpdateFailed = FakeUpdateFailed

    sys.modules["homeassistant"] = homeassistant_module
    sys.modules["homeassistant.helpers"] = helpers_module
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator_module


_install_stubs()

from custom_components.windmill.api import (
    WindmillApi,
    WindmillAuthError,
    WindmillDeviceState,
    WindmillResponseError,
    _encode_ws_frame,
    _hash_password,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "windmill"


class MockResponse:
    """Minimal async response stub."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body

    async def json(self) -> object:
        return json.loads(self._body)

    async def __aenter__(self) -> "MockResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class MockSession:
    """Capture Windmill requests for assertions."""

    def __init__(self, responses: list[MockResponse]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs: object) -> MockResponse:
        self.calls.append({"method": "GET", "url": url, "kwargs": kwargs})
        return self.responses.pop(0)

    def post(self, url: str, **kwargs: object) -> MockResponse:
        self.calls.append({"method": "POST", "url": url, "kwargs": kwargs})
        return self.responses.pop(0)


class MockWsMessage:
    """Small WebSocket message stand-in."""

    def __init__(self, data: bytes) -> None:
        self.data = data


class MockWebSocket:
    """Capture sent WebSocket frames and return queued messages."""

    def __init__(self, session: "MockWsSession") -> None:
        self._session = session
        self.closed = False

    async def __aenter__(self) -> "MockWebSocket":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def send_bytes(self, data: bytes) -> None:
        self._session.sent_frames.append(data)

    async def receive(self) -> MockWsMessage:
        return MockWsMessage(self._session.messages.pop(0))

    async def close(self) -> None:
        self.closed = True


class MockWsSession:
    """Capture Windmill WebSocket connections for assertions."""

    def __init__(self, messages: list[bytes]) -> None:
        self.messages = messages
        self.sent_frames: list[bytes] = []
        self.ws_urls: list[str] = []

    def ws_connect(self, url: str, **kwargs: object) -> MockWebSocket:
        self.ws_urls.append(url)
        return MockWebSocket(self)


class FailingSession:
    """Raise a transport-level failure when Windmill is queried."""

    def get(self, url: str, **kwargs: object) -> MockResponse:
        raise ConnectionError("windmill offline")


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text())


def _decoded_frame(frame: bytes) -> tuple[int, int, str]:
    command, msg_id = struct.unpack(">HH", frame[:4])
    return command, msg_id, frame[4:].decode()


def _response_frame(msg_id: int, response_code: int) -> bytes:
    return struct.pack(">HHI", 0, msg_id, response_code)


def test_hash_password_matches_dashboard_algorithm() -> None:
    assert (
        _hash_password("User@Example.COM", "correct horse")
        == "xS3O+l/GjIsTNgdUF0vwEAqqwutRpy9ZN1UidK7o0XM="
    )


@pytest.mark.asyncio
async def test_dashboard_list_devices_logs_in_and_fetches_org_devices() -> None:
    session = MockWsSession(
        [
            _encode_ws_frame(2, 1, json.dumps({"orgId": 1234})),
            _encode_ws_frame(
                104,
                2,
                json.dumps(
                    {
                        "devices": [
                            {
                                "id": 1,
                                "name": "Living Room AC",
                                "isActive": True,
                            }
                        ]
                    }
                ),
            ),
        ]
    )
    api = WindmillApi(
        email="user@example.com",
        password_hash="hashed-password",
        org_id=1234,
        session=session,
    )

    devices = await api.async_list_devices()

    assert devices[0].unique_id == "1"
    assert devices[0].name == "Living Room AC"
    assert session.ws_urls == ["wss://dashboard.windmillair.com/dashws"]
    login_command, login_msg_id, login_payload = _decoded_frame(session.sent_frames[0])
    assert login_command == 2
    assert login_msg_id == 1
    assert json.loads(login_payload) == {
        "email": "user@example.com",
        "hash": "hashed-password",
        "clientType": "web",
        "version": "0.104.5",
        "locale": "en_US",
    }
    devices_command, devices_msg_id, devices_payload = _decoded_frame(
        session.sent_frames[1]
    )
    assert devices_command == 104
    assert devices_msg_id == 2
    assert json.loads(devices_payload) == {"orgId": 1234}


@pytest.mark.asyncio
async def test_dashboard_device_state_parses_widget_pin_values() -> None:
    session = MockWsSession(
        [
            _encode_ws_frame(2, 1, json.dumps({"orgId": 1234})),
            _encode_ws_frame(
                260,
                2,
                json.dumps(
                    {
                        "id": 1,
                        "dashboard": {
                            "widgets": [
                                {
                                    "sources": [
                                        {"dataStream": {"pin": 0, "value": "1"}}
                                    ]
                                },
                                {
                                    "sources": [
                                        {"dataStream": {"pin": 1, "value": "69"}}
                                    ]
                                },
                                {
                                    "sources": [
                                        {"dataStream": {"pin": 2, "value": "72"}}
                                    ]
                                },
                                {
                                    "sources": [
                                        {"dataStream": {"pin": 3, "value": "Eco"}}
                                    ]
                                },
                                {
                                    "sources": [
                                        {"dataStream": {"pin": 4, "value": "Low"}}
                                    ]
                                },
                            ]
                        },
                    }
                ),
            ),
        ]
    )
    api = WindmillApi(
        email="user@example.com",
        password_hash="hashed-password",
        org_id=1234,
        session=session,
    )

    state = await api.async_get_device_state("1")

    assert state == WindmillDeviceState(
        unique_id="1",
        power=True,
        current_temperature=69.0,
        target_temperature=72.0,
        mode="auto",
        fan_speed="low",
    )
    command, msg_id, payload = _decoded_frame(session.sent_frames[1])
    assert command == 260
    assert msg_id == 2
    assert json.loads(payload) == {
        "pageId": 1234,
        "deviceId": 1,
        "dashboardPageId": None,
    }


@pytest.mark.asyncio
async def test_dashboard_update_sends_hardware_virtual_write_without_waiting_for_ack() -> None:
    session = MockWsSession(
        [
            _encode_ws_frame(2, 1, json.dumps({"orgId": 1234})),
        ]
    )
    api = WindmillApi(
        email="user@example.com",
        password_hash="hashed-password",
        org_id=1234,
        session=session,
    )

    await api.async_set_power("1", True)

    command, msg_id, payload = _decoded_frame(session.sent_frames[1])
    assert command == 20
    assert msg_id == 2
    assert payload == "1\0vw\0" "0\0" "1"


def test_dashboard_pin_strips_pin_prefix_for_hardware_write() -> None:
    api = WindmillApi(
        email="user@example.com",
        password_hash="hashed-password",
        org_id=1234,
        session=MockWsSession([]),
    )

    assert api._dashboard_pin("V3") == ("vw", "3")
    assert api._dashboard_pin("A1") == ("aw", "1")
    assert api._dashboard_pin("D2") == ("dw", "2")


@pytest.mark.asyncio
async def test_list_devices_parses_real_fixture() -> None:
    session = MockSession(
        [MockResponse(200, json.dumps(load_fixture("device_list.json")))]
    )
    api = WindmillApi(token="wm_token", session=session)

    devices = await api.async_list_devices()

    assert len(devices) == 1
    assert devices[0].unique_id == "device-abc123"
    assert devices[0].name == "Living Room AC"
    assert devices[0].can_set_temperature is True
    assert session.calls[0]["method"] == "GET"
    assert "external/api/get?token=wm_token" in session.calls[0]["url"]


@pytest.mark.asyncio
async def test_get_device_state_parses_real_fixture() -> None:
    session = MockSession(
        [MockResponse(200, json.dumps(load_fixture("device_state.json")))]
    )
    api = WindmillApi(token="wm_token", session=session)

    state = await api.async_get_device_state("device-abc123")

    assert state == WindmillDeviceState(
        unique_id="device-abc123",
        power=True,
        current_temperature=69.0,
        target_temperature=72.0,
        mode="cool",
        fan_speed="low",
    )
    assert "external/api/get?token=wm_token&V0" in session.calls[0]["url"]


@pytest.mark.asyncio
async def test_get_device_state_parses_textual_mode_and_fan_values() -> None:
    payload = {
        "unique_id": "device-abc123",
        "power": "on",
        "current_temperature": "69",
        "target_temperature": "72",
        "mode": "auto",
        "fan_speed": "high",
    }
    session = MockSession([MockResponse(200, json.dumps(payload))])
    api = WindmillApi(token="wm_token", session=session)

    state = await api.async_get_device_state("device-abc123")

    assert state.mode == "auto"
    assert state.fan_speed == "high"
    assert state.power is True
    assert state.current_temperature == 69.0
    assert state.target_temperature == 72.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("setter", "args", "expected_query"),
    [
        ("async_set_power", ("device-abc123", True), "V0=1"),
        ("async_set_temperature", ("device-abc123", 74), "V2=74"),
        ("async_set_mode", ("device-abc123", "auto"), "V3=2"),
        ("async_set_fan_speed", ("device-abc123", "high"), "V4=3"),
    ],
)
async def test_update_requests_use_expected_query(
    setter: str, args: tuple[object, ...], expected_query: str
) -> None:
    session = MockSession(
        [MockResponse(200, json.dumps(load_fixture("device_control_success.json")))]
    )
    api = WindmillApi(token="wm_token", session=session)

    await getattr(api, setter)(*args)

    assert session.calls[0]["method"] == "GET"
    assert expected_query in session.calls[0]["url"]
    assert "external/api/update?token=wm_token" in session.calls[0]["url"]


@pytest.mark.asyncio
async def test_auth_error_raises_for_auth_failure_fixture() -> None:
    session = MockSession(
        [MockResponse(401, json.dumps(load_fixture("auth_failure.json")))]
    )
    api = WindmillApi(token="wm_bad_token", session=session)

    with pytest.raises(WindmillAuthError):
        await api.async_list_devices()


@pytest.mark.asyncio
async def test_update_request_encodes_reserved_characters_in_token() -> None:
    session = MockSession(
        [MockResponse(200, json.dumps(load_fixture("device_control_success.json")))]
    )
    api = WindmillApi(token="wm+token &odd=", session=session)

    await api.async_set_power("device-abc123", True)

    assert "token=wm%2Btoken+%26odd%3D" in session.calls[0]["url"]


@pytest.mark.asyncio
async def test_update_error_payload_raises_response_error() -> None:
    session = MockSession([MockResponse(200, json.dumps(load_fixture("device_control_error.json")))])
    api = WindmillApi(token="wm_token", session=session)

    with pytest.raises(WindmillResponseError):
        await api.async_set_power("device-abc123", False)


@pytest.mark.asyncio
async def test_transport_error_raises_response_error() -> None:
    api = WindmillApi(token="wm_token", session=FailingSession())

    with pytest.raises(WindmillResponseError):
        await api.async_list_devices()
