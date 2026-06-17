# Windmill for Home Assistant

Windmill is a Home Assistant custom integration for Windmill AC devices.

This first release focuses on basic cloud-connected control through the Windmill dashboard API. It creates a climate entity for each discovered AC device.

## Installation

### HACS

1. In HACS, add this repository as a custom repository.
2. Install the integration from HACS.
3. Restart Home Assistant.

### Manual install

1. Copy the `custom_components/windmill/` folder into your Home Assistant `custom_components/` directory.
2. Restart Home Assistant.

## Validate credentials before installing

Before installing into Home Assistant, validate that the reverse-engineered Windmill dashboard API still accepts your dashboard credentials. Use the organization id from the dashboard URL, for example `1234` in `/dashboard/1234/global/devices/1`:

```bash
WINDMILL_EMAIL=... WINDMILL_PASSWORD=... WINDMILL_ORG_ID=1234 ./scripts/probe_windmill_api.py
```

The probe performs read-only device list/state calls and does not print the password.

## Setup

1. In Home Assistant, go to `Settings` > `Devices & services`.
2. Add the Windmill integration.
3. Enter your Windmill email, password, and organization id from the dashboard URL.

The password is hashed before it is stored in Home Assistant config entry storage. The raw password is not stored or logged by the integration.

## What it supports

- Climate entities for each discovered Windmill AC device.
- Basic control through the Windmill cloud/dashboard API.

## Current limitations

- This integration depends on Windmill cloud/dashboard API behavior.
- Local LAN control is not part of v1.

## Troubleshooting

- `invalid_auth`: check that the Windmill credentials are correct.
- `cannot_connect`: check your network connection and confirm Windmill is reachable from Home Assistant.
- If no devices are discovered, verify that the dashboard organization id is correct and the account has access to at least one AC device in Windmill.
