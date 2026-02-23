# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**HA Energy Manager** is a native Home Assistant Custom Integration that automates energy optimization for solar PV, home batteries, EV charging, and dynamic electricity pricing (Tibber). It runs directly inside Home Assistant without any additional add-ons and is installable via HACS.

## Deployment

HACS handles deployment automatically. After HACS installation:
- Integration files land in `/config/custom_components/energy_manager/`
- Dashboard files are auto-copied to `/config/www/energy_manager/` on HA startup
- Configuration is done via `configuration.yaml` (see `README.md`)

There are no automated tests. Logic is validated manually in a running Home Assistant instance.

## Architecture

### Core Components

**`custom_components/energy_manager/__init__.py`** — Main integration file. Key parts:
1. `async_setup(hass, config)` — HA entry point; merges config, creates coordinator, triggers initial refresh
2. `EnergyManagerCoordinator` — `DataUpdateCoordinator` subclass; manages the polling loop and price-change listener
3. `async_setup()` — Deploys dashboard (via executor), registers state-change listener for price entity
4. `_async_update_data()` — Called every N minutes; reads state → makes decisions → executes decisions
5. `_get_system_state()` — Reads 15+ HA sensor entities; computes derived metrics (PV surplus, etc.)
6. `_make_decisions(s)` — Priority-based decision engine (see below)
7. `_execute_decisions(decisions, system)` — Sends push notifications with a 2-hour cooldown per decision type
8. `_deploy_dashboard()` — Sync method (runs in executor); copies dashboard files to `/config/www/energy_manager/`
9. `_on_price_change(event)` — `@callback` (sync); triggers `async_refresh()` on significant price changes

**`custom_components/energy_manager/const.py`** — `DOMAIN` constant + `DEFAULT_CONFIG` dict with all defaults

**`custom_components/energy_manager/manifest.json`** — HA integration metadata

**`custom_components/energy_manager/dashboard/energy_manager_dashboard.html`** — Single-file self-contained dashboard

**`custom_components/energy_manager/dashboard/ha_websocket.js`** — WebSocket client that caches entity states and subscribes to changes from HA

### Decision Priority Order

The decision engine in `_make_decisions()` evaluates in strict priority:
1. **Emergency**: Car SOC < 20% → force charge
2. **PV-first**: PV surplus ≥ 3 kW → charge car; PV surplus ≥ 1 kW → charge battery
3. **Cost optimization**: Very cheap price (≤ 8 Ct) → charge battery from grid; Cheap price (≤ 15 Ct) → charge car; Expensive price (≥ 30 Ct) → stop charging

### Configuration

Configuration lives in two places:
- **`configuration.yaml`** — User config (`energy_manager:` block); all fields optional
- **`custom_components/energy_manager/const.py`** — `DEFAULT_CONFIG` dict with all hardcoded defaults

Dashboard entity mappings:
- **`custom_components/energy_manager/dashboard/ha_websocket.js`** `DEFAULT_ENTITIES` dict
- **`custom_components/energy_manager/dashboard/energy_manager_dashboard.html`** `CFG` object

### API Mapping (AppDaemon → Native HA)

| AppDaemon | Native HA Custom Component |
|-----------|---------------------------|
| `class EnergyManager(hass.Hass)` | `class EnergyManagerCoordinator(DataUpdateCoordinator)` |
| `def initialize(self)` | `async_setup(hass, config)` + `coordinator.async_setup()` |
| `self.get_state(entity_id)` | `hass.states.get(entity_id).state` |
| `self.log(msg, level=...)` | `_LOGGER.info/warning/error(msg)` |
| `self.run_every(cb, "now", interval)` | `DataUpdateCoordinator(update_interval=...)` |
| `self.listen_state(cb, entity)` | `async_track_state_change_event(hass, [entity], cb)` |
| `self.call_service("notify/svc", ...)` | `await hass.services.async_call("notify", "svc", {...})` |

### Entity Naming Conventions

The integration expects these HA entity ID patterns (customizable in `configuration.yaml`):

| Sensor | Entity ID |
|--------|-----------|
| PV power | `sensor.pv_power` |
| PV forecast today | `sensor.solcast_pv_forecast_today` |
| Battery SOC | `sensor.battery_soc` |
| Battery power | `sensor.battery_power` |
| Car battery level | `sensor.car_battery_level` |
| Car connected | `binary_sensor.car_connected` |
| Grid power | `sensor.grid_power` |
| Current price | `sensor.tibber_current_price` |
| Price level | `sensor.tibber_price_level` |

### External Integrations

- **Solcast** — PV production forecasting
- **Tibber** — Dynamic electricity pricing (price change events trigger re-evaluation)
- **Home Assistant** — Provides native async infrastructure; no additional add-ons required

## Code Conventions

- Code and comments are primarily in **German**
- Safe value parsing helpers (`_safe_float`, `_safe_bool`) handle missing/unavailable HA sensor states
- All decisions use a `_last_notification` dict for 2-hour cooldown enforcement
- `_deploy_dashboard()` is blocking I/O → must always be called via `hass.async_add_executor_job()`
- `_on_price_change()` is a `@callback` (sync) → use `hass.async_create_task()`, never `await`
- `notify_service` is split on `.` to get domain + service name for `hass.services.async_call()`
- The dashboard uses vanilla JS/HTML with no build tooling; dark theme, Google Fonts (DM Mono, Syne)
