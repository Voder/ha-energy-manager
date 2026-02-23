# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**HA Energy Manager** is a Home Assistant add-on that automates energy optimization for solar PV, home batteries, EV charging, and dynamic electricity pricing (Tibber). It runs as an **AppDaemon** Python app and includes a live web dashboard.

This is a HACS-compatible custom integration. No build step is needed — files are deployed directly into Home Assistant.

## Deployment

```bash
# Copy app files to Home Assistant AppDaemon directory
cp appdaemon/energy_manager.py /config/appdaemon/apps/
cp appdaemon/apps.yaml /config/appdaemon/apps/
```

There are no automated tests. Logic is validated manually in a running Home Assistant instance.

## Architecture

### Core Components

**`appdaemon/energy_manager.py`** — The main AppDaemon app. Three key phases:
1. `get_system_state()` — Reads 15+ HA sensor entities; computes derived metrics (PV surplus, etc.)
2. `make_decisions()` — Priority-based decision engine (see below)
3. `execute_decisions()` — Sends push notifications with a 2-hour cooldown per decision type

**`dashboard/energy_manager_dashboard.html`** — Single-file self-contained dashboard
**`dashboard/ha_websocket.js`** — WebSocket client that caches entity states and subscribes to changes from HA

### Decision Priority Order

The decision engine in `make_decisions()` evaluates in strict priority:
1. **Emergency**: Car SOC < 20% → force charge
2. **PV-first**: PV surplus ≥ 3 kW → charge car; PV surplus ≥ 1 kW → charge battery
3. **Cost optimization**: Very cheap price (≤ 8 Ct) → charge battery from grid; Cheap price (≤ 15 Ct) → charge car; Expensive price (≥ 30 Ct) → stop charging

### Configuration

App parameters live in two places:
- **`appdaemon/apps.yaml`** — Overridable runtime config (thresholds, entity IDs, capacities)
- **`appdaemon/energy_manager.py`** lines 25–81 — `CONFIG` dict with hardcoded defaults

Dashboard entity mappings:
- **`dashboard/ha_websocket.js`** `DEFAULT_ENTITIES` dict (around line 235–254)
- **`dashboard/energy_manager_dashboard.html`** `CFG` object (around line 532–542)

### Entity Naming Conventions

The app expects these HA entity ID patterns (customizable in `apps.yaml`):

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
- **AppDaemon** — Provides `hassapi.Hass` base class; handles HA WebSocket under the hood

## Code Conventions

- Code and comments are primarily in **German**
- Safe value parsing helpers (`safe_float`, `safe_bool`) handle missing/unavailable HA sensor states
- All decisions use a `last_decision_time` dict for 2-hour cooldown enforcement
- The dashboard uses vanilla JS/HTML with no build tooling; dark theme, Google Fonts (DM Mono, Syne)
