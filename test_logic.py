#!/usr/bin/env python3
"""
Lokaler Test der Entscheidungslogik ohne Home Assistant.

Führe aus mit:  python3 test_logic.py

Simulates _get_system_state() + _make_decisions() with fake sensor values
so you can iterate on the logic without deploying to HA.
"""

import sys
import os

# const.py direkt importieren (kein HA nötig)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "custom_components/energy_manager"))
from const import DEFAULT_CONFIG

# ─────────────────────────────────────────────
# Mock-Sensordaten (Werte wie sie aus HA kommen)
# Passe die Einheiten hier an deine realen Sensoren an!
# ─────────────────────────────────────────────

MOCK_SENSORS = {
    # Watt oder kW? → prüfe mit: hass.states.get("sensor.pv_power").attributes["unit_of_measurement"]
    "sensor.pv_power":          3500,   # TODO: W oder kW?
    "sensor.house_consumption":  800,   # TODO: W oder kW?
    "sensor.grid_power":         200,   # TODO: W oder kW? (positiv = Einspeisung)
    "sensor.battery_power":      500,   # TODO: W oder kW?
    "sensor.battery_soc":         72,   # % (keine Umrechnung)
    "sensor.car_battery_level":   45,   # % (keine Umrechnung)
    "sensor.car_charging_power":    0,  # TODO: W oder kW?
    "binary_sensor.car_connected": "on",
    "sensor.tibber_current_price": 0.125,  # €/kWh (price_level wird automatisch berechnet)
    "sensor.solcast_pv_forecast_today":    18.0,  # kWh
    "sensor.solcast_forecast_remaining":    8.0,  # kWh
}

# ─────────────────────────────────────────────
# Einheitenkonfiguration – hier anpassen!
# ─────────────────────────────────────────────

# Wenn dein Sensor Watt liefert → /1000
# Wenn dein Sensor kW liefert   → /1
UNIT_DIVISORS = {
    "pv_power":           1000,  # ← ändere auf 1 wenn Sensor kW liefert
    "house_consumption":  1000,  # ← ändere auf 1 wenn Sensor kW liefert
    "grid_power":         1000,  # ← ändere auf 1 wenn Sensor kW liefert
    "battery_power":      1000,  # ← ändere auf 1 wenn Sensor kW liefert
    "car_charging_power": 1000,  # ← ändere auf 1 wenn Sensor kW liefert
}


# ─────────────────────────────────────────────
# Hilfsfunktionen (aus __init__.py extrahiert)
# ─────────────────────────────────────────────

def compute_price_level(price: float, cfg: dict) -> str:
    """Berechnet Preisniveau anhand der konfigurierten Schwellenwerte (€/kWh)."""
    very_cheap = cfg.get("price_very_cheap_threshold", DEFAULT_CONFIG["price_very_cheap_threshold"])
    cheap      = cfg.get("price_cheap_threshold",      DEFAULT_CONFIG["price_cheap_threshold"])
    expensive  = cfg.get("price_expensive_threshold",  DEFAULT_CONFIG["price_expensive_threshold"])
    if price <= very_cheap:
        return "VERY_CHEAP"
    if price <= cheap:
        return "CHEAP"
    if price >= expensive:
        return "EXPENSIVE"
    return "NORMAL"


def safe_float(entity_id: str, default: float = 0.0) -> float:
    val = MOCK_SENSORS.get(entity_id, default)
    if val in ("unavailable", "unknown", None):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_bool(entity_id: str) -> bool:
    val = MOCK_SENSORS.get(entity_id, "off")
    return str(val) in ("on", "true", "True", "1", "home")


# ─────────────────────────────────────────────
# Systemzustand berechnen (analog _get_system_state)
# ─────────────────────────────────────────────

def get_system_state(cfg: dict) -> dict:
    e = cfg["entities"]

    pv_power_raw        = safe_float(e["pv_power"])
    house_consumption_raw = safe_float(e["house_consumption"])
    grid_power_raw      = safe_float(e["grid_power"])
    battery_power_raw   = safe_float(e["battery_power"])
    car_charging_raw    = safe_float(e["car_charging_power"])

    # Einheitenumrechnung
    pv_power_kw         = pv_power_raw        / UNIT_DIVISORS["pv_power"]
    house_consumption_kw = house_consumption_raw / UNIT_DIVISORS["house_consumption"]
    grid_power_kw       = grid_power_raw       / UNIT_DIVISORS["grid_power"]
    battery_power_kw    = battery_power_raw    / UNIT_DIVISORS["battery_power"]
    car_charging_kw     = car_charging_raw     / UNIT_DIVISORS["car_charging_power"]
    pv_surplus_kw       = pv_power_kw - house_consumption_kw

    current_price_eur = safe_float(e["current_price"])
    price_level = compute_price_level(current_price_eur, cfg)

    return {
        "pv_power_kw":              pv_power_kw,
        "pv_surplus_kw":            pv_surplus_kw,
        "pv_forecast_today_kwh":    safe_float(e["pv_forecast_today"]),
        "pv_forecast_remaining_kwh": safe_float(e["pv_forecast_remaining"]),
        "battery_soc":              safe_float(e["battery_soc"]),
        "battery_power_kw":         battery_power_kw,
        "car_soc":                  safe_float(e["car_soc"]),
        "car_connected":            safe_bool(e["car_connected"]),
        "car_charging_power_kw":    car_charging_kw,
        "grid_power_kw":            grid_power_kw,
        "house_consumption_kw":     house_consumption_kw,
        "current_price_eur":        current_price_eur,
        "price_level":              price_level,
        "hour":                     8,
        "is_night":                 False,
        "is_morning":               True,
    }


# ─────────────────────────────────────────────
# Entscheidungslogik (1:1 aus __init__.py)
# ─────────────────────────────────────────────

def make_decisions(s: dict, cfg: dict) -> list[dict]:
    decisions = []
    price    = s["current_price_eur"]
    cheap      = cfg.get("price_cheap_threshold",      DEFAULT_CONFIG["price_cheap_threshold"])
    very_cheap = cfg.get("price_very_cheap_threshold", DEFAULT_CONFIG["price_very_cheap_threshold"])
    expensive  = cfg.get("price_expensive_threshold",  DEFAULT_CONFIG["price_expensive_threshold"])

    if (
        s["car_connected"]
        and s["car_soc"] < cfg.get("car_default_target_soc", DEFAULT_CONFIG["car_default_target_soc"])
        and s["pv_surplus_kw"] >= cfg.get("pv_surplus_for_car_charging", DEFAULT_CONFIG["pv_surplus_for_car_charging"])
    ):
        decisions.append({"action": "car_charge_pv", "priority": 1, "reason": "PV-Überschuss"})

    if (
        s["pv_surplus_kw"] >= cfg.get("pv_surplus_for_battery", DEFAULT_CONFIG["pv_surplus_for_battery"])
        and s["battery_soc"] < cfg.get("battery_max_soc", DEFAULT_CONFIG["battery_max_soc"])
        and not s["car_connected"]
    ):
        decisions.append({"action": "battery_charge_pv", "priority": 1, "reason": "PV-Überschuss für Speicher"})

    pv_producing_well = s["pv_power_kw"] > (cfg.get("pv_peak_power_kw", DEFAULT_CONFIG["pv_peak_power_kw"]) * 0.2)

    if (
        price <= very_cheap
        and s["battery_soc"] < cfg.get("battery_max_soc", DEFAULT_CONFIG["battery_max_soc"])
        and not pv_producing_well
    ):
        decisions.append({"action": "battery_charge_grid", "priority": 2, "reason": "Sehr günstiger Netzstrom"})

    if (
        s["car_connected"]
        and s["car_soc"] < cfg.get("car_default_target_soc", DEFAULT_CONFIG["car_default_target_soc"])
        and price <= cheap
        and s["pv_surplus_kw"] < cfg.get("pv_surplus_for_car_charging", DEFAULT_CONFIG["pv_surplus_for_car_charging"])
    ):
        decisions.append({"action": "car_charge_cheap", "priority": 2, "reason": "Günstiger Netzstrom"})

    if s["car_connected"] and s["car_soc"] < cfg.get("car_min_soc_target", DEFAULT_CONFIG["car_min_soc_target"]):
        decisions.append({"action": "car_charge_emergency", "priority": 0, "reason": "Kritischer Auto-SOC"})

    if price >= expensive and s["battery_soc"] > cfg.get("battery_reserve_evening", DEFAULT_CONFIG["battery_reserve_evening"]):
        decisions.append({"action": "stop_grid_consumption", "priority": 2, "reason": "Hoher Strompreis"})

    decisions.sort(key=lambda d: d["priority"])
    return decisions


# ─────────────────────────────────────────────
# Ausgabe
# ─────────────────────────────────────────────

def print_state(s: dict):
    print("\n=== Systemzustand ===")
    print(f"  PV:          {s['pv_power_kw']:.2f} kW  (Überschuss: {s['pv_surplus_kw']:.2f} kW)")
    print(f"  Hauslast:    {s['house_consumption_kw']:.2f} kW")
    print(f"  Netz:        {s['grid_power_kw']:.2f} kW")
    print(f"  Akku:        {s['battery_soc']:.0f}%  ({s['battery_power_kw']:.2f} kW)")
    print(f"  Auto:        {s['car_soc']:.0f}%  ({'verbunden' if s['car_connected'] else 'getrennt'})  Ladeleistung: {s['car_charging_power_kw']:.2f} kW")
    print(f"  Preis:       {s['current_price_eur']:.3f} €/kWh  ({s['price_level']})")


def print_decisions(decisions: list[dict]):
    print("\n=== Entscheidungen ===")
    if not decisions:
        print("  (keine Maßnahmen nötig)")
    for d in decisions:
        print(f"  [{d['priority']}] {d['action']:30s}  ← {d['reason']}")


if __name__ == "__main__":
    cfg = DEFAULT_CONFIG
    s = get_system_state(cfg)
    print_state(s)

    # Plausibilitätsprüfung: Warnung wenn Werte unrealistisch
    if s["pv_power_kw"] > 100:
        print("\n⚠  WARNUNG: PV-Leistung > 100 kW – Sensor liefert vermutlich Watt, nicht kW!")
        print("   → UNIT_DIVISORS['pv_power'] auf 1000 setzen")
    if s["house_consumption_kw"] > 50:
        print("\n⚠  WARNUNG: Hauslast > 50 kW – Sensor liefert vermutlich Watt, nicht kW!")

    decisions = make_decisions(s, cfg)
    print_decisions(decisions)
    print()
