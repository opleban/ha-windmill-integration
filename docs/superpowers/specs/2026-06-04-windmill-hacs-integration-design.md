# Windmill AC HACS Integration Design

## Summary

Build a Home Assistant custom integration for Windmill AC units that works with Windmill's cloud dashboard API and exposes both status and control for each accessible AC device under one Windmill account. The first release should be HACS-friendly, intentionally narrow, and structured so that any reverse-engineered API details are isolated in one client module.

## Goals

- Discover Windmill AC devices from a user-provided Windmill auth token.
- Expose current device state to Home Assistant.
- Support control of the primary AC functions:
  - power on/off
  - target temperature
  - mode
  - fan speed
- Refresh state on a polling interval so Home Assistant stays in sync with the Windmill cloud.
- Keep the implementation maintainable and easy to update if Windmill changes its dashboard internals.

## Non-Goals

- No local-LAN control path in v1.
- No mobile-app reverse engineering in v1.
- No support for every Windmill dashboard feature unless it is directly useful for AC control.
- No attempt to build a generalized Windmill platform integration for unrelated products.

## Assumptions

1. Windmill still accepts authenticated cloud requests that can read and control AC state.
2. The user can obtain a token through Windmill's account/settings flow or an equivalent valid session-derived token.
3. The dashboard/API surface used for device control is stable enough to support a first HACS release.
4. One integration instance can manage one Windmill account and all ACs visible to that account.

## Proposed Architecture

### 1. Config Flow

The integration will use a standard Home Assistant config flow.

- User enters:
  - Windmill auth token
  - optional friendly name for the account or location
- The config flow validates the token by calling the Windmill API.
- On success, the flow discovers all accessible AC devices and creates one coordinator-backed entry.

### 2. API Client

Create a dedicated `windmill_api` module responsible for all Windmill HTTP traffic.

Responsibilities:

- Authenticate requests
- List accessible devices
- Fetch current device state
- Send control commands
- Normalize API responses into small typed models for the rest of the integration

This module is the only place that should know about Windmill-specific endpoint shapes, parameter names, or token placement.

### 3. Data Update Coordinator

Use a Home Assistant data update coordinator to poll state.

- Poll interval should be conservative, around 30 to 60 seconds.
- Failed refreshes should not immediately break the entities.
- The coordinator should cache the last known good state and expose errors separately.

### 4. Entities

Use Home Assistant entities that match the AC control surface.

Primary entity:

- `climate` entity for the AC itself

Secondary entities, only if they map cleanly to Windmill state:

- `switch` for power if the climate entity does not fully cover it
- `select` for mode
- `select` for fan speed

Preferred behavior is to keep the UI centered on a single climate entity if Windmill's state model supports it. Additional entities should only be added if they improve usability and do not duplicate controls unnecessarily.

### 5. State Model

The integration should normalize Windmill's response into a small internal model with fields like:

- device id
- display name
- power state
- current temperature
- target temperature
- mode
- fan speed
- availability / last refresh status

That internal model should be the contract between the API client and the Home Assistant entities.

## Data Flow

1. User installs the HACS integration and opens the config flow.
2. User enters a Windmill token.
3. The integration validates the token and fetches the device list.
4. Home Assistant creates entities for each AC device.
5. The coordinator polls Windmill on a schedule.
6. Entity state updates from the normalized internal model.
7. User changes a control in Home Assistant.
8. The entity sends the matching Windmill command through the API client.
9. The coordinator refreshes and reconciles the new state.

## Error Handling

- Invalid token:
  - show a config-flow error
  - do not create the entry
- Partial device API failure:
  - keep the last known good entity state
  - mark the integration unavailable only when the refresh failure is persistent
- Command failure:
  - raise a Home Assistant service error
  - preserve the previous state until the next successful refresh
- Schema drift / unexpected API shape:
  - fail closed in the API client
  - log enough detail to diagnose the mismatch without exposing secrets

## Security And Privacy

- Store the Windmill token in Home Assistant's config entry storage, not in plain text files.
- Never log the token.
- Keep all Windmill endpoint logic in one module to minimize the blast radius of any API changes.
- Avoid any design that requires scraping browser session data at runtime.

## Testing Strategy

### Unit Tests

- token validation success/failure
- device discovery parsing
- state normalization
- command payload generation
- error mapping from API failures to Home Assistant errors

### Integration Tests

- config flow creates and validates a config entry
- coordinator refresh updates entity state
- climate entity accepts control commands and schedules refreshes

### Regression Coverage

- one test fixture for a typical AC device
- one fixture for an unavailable device
- one fixture for a malformed API response

## Release Shape

The first HACS release should be small:

- one custom integration folder
- one dependency-free HTTP client if possible
- one climate entity per device
- one clear README with setup steps and known limitations

## Open Questions

- Does Windmill expose enough information to model all of the climate features cleanly, or do we need a power-only fallback for some devices?
- Is there a single token format that works for both dashboard reads and device commands?
- Are multiple ACs under one account likely enough that entity naming and unique IDs need special handling from day one?
