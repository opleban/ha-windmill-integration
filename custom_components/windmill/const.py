"""Constants for the Windmill integration."""

DOMAIN = "windmill"
DEFAULT_BASE_URL = "https://dashboard.windmillair.com"

GET_ENDPOINT = "external/api/get"
UPDATE_ENDPOINT = "external/api/update"

TOKEN_PARAM = "token"

PIN_POWER = "V0"
PIN_CURRENT_TEMPERATURE = "V1"
PIN_TARGET_TEMPERATURE = "V2"
PIN_MODE = "V3"
PIN_FAN_SPEED = "V4"

MODE_PIN_BY_NORMALIZED = {
    "fan": 0,
    "cool": 1,
    "auto": 2,
    "off": 3,
}

MODE_NORMALIZED_BY_PIN = {
    0: "fan",
    1: "cool",
    2: "auto",
    3: "off",
}

FAN_PIN_BY_NORMALIZED = {
    "auto": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}

FAN_NORMALIZED_BY_PIN = {
    0: "auto",
    1: "low",
    2: "medium",
    3: "high",
}

