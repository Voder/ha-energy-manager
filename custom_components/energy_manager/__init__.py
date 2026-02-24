"""
Energy Manager – Native HA Custom Integration
=============================================
Automatisiertes Energiemanagement mit:
- PV-Anlage + Solcast-Vorhersage
- Hausakku (Stromspeicher)
- Elektroauto
- Dynamischer Stromtarif (Tibber)

Prioritäten:
1. Maximale Eigenversorgung (Autarkie)
2. Minimale Stromkosten
3. Akku-Schonung
4. CO₂-Minimierung
"""

import json
import logging
import os
import re
import shutil
from datetime import datetime, timedelta

import voluptuous as vol
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_CONFIG, DOMAIN

_LOGGER = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONFIG SCHEMA (voluptuous)
# ─────────────────────────────────────────────

_ENTITIES_SCHEMA = vol.Schema(
    {
        vol.Optional("pv_power"): cv.entity_id,
        vol.Optional("pv_forecast_today"): cv.entity_id,
        vol.Optional("pv_forecast_remaining"): cv.entity_id,
        vol.Optional("pv_forecast_tomorrow"): cv.entity_id,
        vol.Optional("pv_forecast_next_hour"): cv.entity_id,
        vol.Optional("pv_forecast_d3"): cv.entity_id,
        vol.Optional("pv_forecast_d4"): cv.entity_id,
        vol.Optional("pv_forecast_d5"): cv.entity_id,
        vol.Optional("pv_forecast_d6"): cv.entity_id,
        vol.Optional("pv_forecast_d7"): cv.entity_id,
        vol.Optional("battery_soc"): cv.entity_id,
        vol.Optional("battery_power"): cv.entity_id,
        vol.Optional("battery_charging_switch"): cv.entity_id,
        vol.Optional("battery_mode"): cv.entity_id,
        vol.Optional("car_soc"): cv.entity_id,
        vol.Optional("car_charging_switch"): cv.entity_id,
        vol.Optional("car_charging_power"): cv.entity_id,
        vol.Optional("car_connected"): cv.entity_id,
        vol.Optional("grid_power"): cv.entity_id,
        vol.Optional("house_consumption"): cv.entity_id,
        vol.Optional("current_price"): cv.entity_id,
        vol.Optional("tibber_prices"): cv.entity_id,
    },
    extra=vol.ALLOW_EXTRA,
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional("battery_capacity_kwh"): vol.Coerce(float),
                vol.Optional("battery_min_soc"): vol.Coerce(int),
                vol.Optional("battery_max_soc"): vol.Coerce(int),
                vol.Optional("battery_reserve_evening"): vol.Coerce(int),
                vol.Optional("car_battery_capacity_kwh"): vol.Coerce(float),
                vol.Optional("car_max_charge_power_kw"): vol.Coerce(float),
                vol.Optional("car_min_soc_target"): vol.Coerce(int),
                vol.Optional("car_default_target_soc"): vol.Coerce(int),
                vol.Optional("pv_peak_power_kw"): vol.Coerce(float),
                vol.Optional("price_cheap_threshold"): vol.Coerce(float),       # €/kWh
                vol.Optional("price_very_cheap_threshold"): vol.Coerce(float),  # €/kWh
                vol.Optional("price_expensive_threshold"): vol.Coerce(float),   # €/kWh
                vol.Optional("pv_surplus_for_car_charging"): vol.Coerce(float),
                vol.Optional("pv_surplus_for_battery"): vol.Coerce(float),
                vol.Optional("notify_service"): cv.string,
                vol.Optional("check_interval_minutes"): vol.Coerce(int),
                vol.Optional("entities"): _ENTITIES_SCHEMA,
            },
            extra=vol.ALLOW_EXTRA,
        )
    },
    extra=vol.ALLOW_EXTRA,
)


# ─────────────────────────────────────────────
# EINSTIEGSPUNKT
# ─────────────────────────────────────────────


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """HA-Einstiegspunkt: Integration initialisieren."""
    _LOGGER.info("Setting up energy_manager")

    user_cfg = config.get(DOMAIN, {})

    # Entity-Defaults mit User-Konfiguration zusammenführen
    entities = {**DEFAULT_CONFIG["entities"], **user_cfg.get("entities", {})}
    cfg = {**DEFAULT_CONFIG, **user_cfg, "entities": entities}

    coordinator = EnergyManagerCoordinator(hass, cfg)
    await coordinator.async_setup()
    await coordinator.async_refresh()

    hass.data[DOMAIN] = coordinator
    return True


# ─────────────────────────────────────────────
# KOORDINATOR
# ─────────────────────────────────────────────


class EnergyManagerCoordinator(DataUpdateCoordinator):
    """Koordinator: verwaltet regelmäßige Updates und Preisänderungs-Listener."""

    def __init__(self, hass: HomeAssistant, cfg: dict):
        interval_minutes = cfg.get("check_interval_minutes", DEFAULT_CONFIG["check_interval_minutes"])
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=interval_minutes),
        )
        self._cfg = cfg
        self._entities = cfg["entities"]
        self._last_notification: dict[str, datetime] = {}
        self._unsub_listeners: list = []

    async def async_setup(self):
        """Dashboard deployen und Preislistener registrieren."""
        _LOGGER.info("Energy Manager wird initialisiert")

        # Dashboard-Deploy in Thread-Pool (blocking I/O)
        await self.hass.async_add_executor_job(self._deploy_dashboard)

        # Preisänderungs-Listener registrieren
        price_entity = self._entities["current_price"]
        unsub = async_track_state_change_event(
            self.hass,
            [price_entity],
            self._on_price_change,
        )
        self._unsub_listeners.append(unsub)

        _LOGGER.info(
            "Energy Manager initialisiert – Intervall: %d Minuten",
            self._cfg.get("check_interval_minutes", DEFAULT_CONFIG["check_interval_minutes"]),
        )

    async def async_teardown(self):
        """Listener aufräumen."""
        for unsub in self._unsub_listeners:
            unsub()
        self._unsub_listeners.clear()

    async def _async_update_data(self):
        """Pflichtmethode: Systemzustand lesen → Entscheidungen → ausführen."""
        _LOGGER.info("Energiemanager-Durchlauf startet...")

        system = self._get_system_state()
        if system is None:
            raise UpdateFailed("Konnte Systemzustand nicht lesen")

        self._log_system_state(system)
        decisions = self._make_decisions(system)
        await self._execute_decisions(decisions, system)

        return system

    # ─────────────────────────────────────────────
    # SYSTEMZUSTAND LESEN
    # ─────────────────────────────────────────────

    def _get_system_state(self) -> dict | None:
        """Liest alle relevanten Sensordaten aus Home Assistant."""
        try:
            e = self._entities

            pv_power_w = self._safe_float(e["pv_power"])
            house_consumption_w = self._safe_float(e["house_consumption"])
            grid_power_w = self._safe_float(e["grid_power"])

            # PV-Überschuss berechnen (positiv = Überschuss verfügbar)
            pv_surplus_w = pv_power_w - house_consumption_w

            current_price_eur = self._safe_float(e["current_price"])
            price_level = self._compute_price_level(current_price_eur)

            return {
                # PV
                "pv_power_kw": pv_power_w / 1000,
                "pv_surplus_kw": pv_surplus_w / 1000,
                "pv_forecast_today_kwh": self._safe_float(e["pv_forecast_today"]),
                "pv_forecast_remaining_kwh": self._safe_float(e["pv_forecast_remaining"]),
                "pv_forecast_tomorrow_kwh": self._safe_float(e["pv_forecast_tomorrow"]),
                "pv_forecast_next_hour_kwh": self._safe_float(e["pv_forecast_next_hour"]),
                "pv_forecast_d3_kwh": self._safe_float(e["pv_forecast_d3"]),
                "pv_forecast_d4_kwh": self._safe_float(e["pv_forecast_d4"]),
                "pv_forecast_d5_kwh": self._safe_float(e["pv_forecast_d5"]),
                "pv_forecast_d6_kwh": self._safe_float(e["pv_forecast_d6"]),
                "pv_forecast_d7_kwh": self._safe_float(e["pv_forecast_d7"]),
                # Hausakku
                "battery_soc": self._safe_float(e["battery_soc"]),
                "battery_power_kw": self._safe_float(e["battery_power"]) / 1000,
                # Elektroauto
                "car_soc": self._safe_float(e["car_soc"]),
                "car_connected": self._safe_bool(e["car_connected"]),
                "car_charging_power_kw": self._safe_float(e["car_charging_power"]) / 1000,
                # Netz & Verbrauch
                "grid_power_kw": grid_power_w / 1000,
                "house_consumption_kw": house_consumption_w / 1000,
                # Preise
                "current_price_eur": current_price_eur,
                "price_level": price_level,
                # Zeit
                "hour": datetime.now().hour,
                "is_night": datetime.now().hour < 6 or datetime.now().hour >= 22,
                "is_morning": 6 <= datetime.now().hour < 10,
            }
        except Exception as ex:
            _LOGGER.error("Fehler beim Lesen des Systemzustands: %s", ex)
            return None

    # ─────────────────────────────────────────────
    # ENTSCHEIDUNGSALGORITHMUS
    # ─────────────────────────────────────────────

    def _make_decisions(self, s: dict) -> list[dict]:
        """
        Kernalgorithmus: Trifft Entscheidungen nach Priorität.
        Gibt eine Liste von Entscheidungen zurück.
        """
        decisions = []
        cfg = self._cfg
        price = s["current_price_eur"]
        cheap = cfg.get("price_cheap_threshold", DEFAULT_CONFIG["price_cheap_threshold"])
        very_cheap = cfg.get("price_very_cheap_threshold", DEFAULT_CONFIG["price_very_cheap_threshold"])
        expensive = cfg.get("price_expensive_threshold", DEFAULT_CONFIG["price_expensive_threshold"])

        # ──────────────────────────────
        # PRIORITÄT 1: AUTARKIE / PV-Nutzung
        # ──────────────────────────────

        # Auto laden mit PV-Überschuss?
        if (
            s["car_connected"]
            and s["car_soc"] < cfg.get("car_default_target_soc", DEFAULT_CONFIG["car_default_target_soc"])
            and s["pv_surplus_kw"] >= cfg.get("pv_surplus_for_car_charging", DEFAULT_CONFIG["pv_surplus_for_car_charging"])
        ):
            decisions.append(
                {
                    "action": "car_charge_pv",
                    "priority": 1,
                    "reason": "PV-Überschuss",
                    "details": (
                        f"PV-Überschuss: {s['pv_surplus_kw']:.1f} kW verfügbar.\n"
                        f"Auto-Akku: {s['car_soc']:.0f}% → Laden empfohlen!"
                    ),
                    "notify": True,
                }
            )

        # Akku laden mit PV-Überschuss (wenn noch nicht voll)?
        if (
            s["pv_surplus_kw"] >= cfg.get("pv_surplus_for_battery", DEFAULT_CONFIG["pv_surplus_for_battery"])
            and s["battery_soc"] < cfg.get("battery_max_soc", DEFAULT_CONFIG["battery_max_soc"])
            and not s["car_connected"]  # Auto hat Vorrang
        ):
            decisions.append(
                {
                    "action": "battery_charge_pv",
                    "priority": 1,
                    "reason": "PV-Überschuss für Speicher",
                    "details": None,  # Stille Aktion, kein Notify nötig
                    "notify": False,
                }
            )

        # ──────────────────────────────
        # PRIORITÄT 2: KOSTENMINIMIERUNG
        # ──────────────────────────────

        # Speicher aus Netz laden wenn Strom sehr günstig?
        if (
            price <= very_cheap
            and s["battery_soc"] < cfg.get("battery_max_soc", DEFAULT_CONFIG["battery_max_soc"])
            and not self._is_pv_producing_well(s)
        ):
            decisions.append(
                {
                    "action": "battery_charge_grid",
                    "priority": 2,
                    "reason": "Sehr günstiger Netzstrom",
                    "details": (
                        f"Strompreis sehr günstig: {price:.3f} €/kWh\n"
                        f"Speicher ({s['battery_soc']:.0f}%) aus dem Netz laden empfohlen!"
                    ),
                    "notify": True,
                }
            )

        # Auto laden weil Strom günstig (auch ohne PV)?
        if (
            s["car_connected"]
            and s["car_soc"] < cfg.get("car_default_target_soc", DEFAULT_CONFIG["car_default_target_soc"])
            and price <= cheap
            and s["pv_surplus_kw"] < cfg.get("pv_surplus_for_car_charging", DEFAULT_CONFIG["pv_surplus_for_car_charging"])
        ):
            decisions.append(
                {
                    "action": "car_charge_cheap",
                    "priority": 2,
                    "reason": "Günstiger Netzstrom",
                    "details": (
                        f"Günstiger Strom: {price:.3f} €/kWh\n"
                        f"Auto-Akku: {s['car_soc']:.0f}% → Jetzt laden empfohlen!"
                    ),
                    "notify": True,
                }
            )

        # Notfall: Auto-SOC kritisch niedrig
        if s["car_connected"] and s["car_soc"] < cfg.get("car_min_soc_target", DEFAULT_CONFIG["car_min_soc_target"]):
            decisions.append(
                {
                    "action": "car_charge_emergency",
                    "priority": 0,  # Höchste Priorität
                    "reason": "Kritischer Auto-SOC",
                    "details": (
                        f"Auto-Akku kritisch niedrig: {s['car_soc']:.0f}%!\n"
                        f"Sofortiges Laden empfohlen (Mindest-SOC: {cfg.get('car_min_soc_target', DEFAULT_CONFIG['car_min_soc_target'])}%)"
                    ),
                    "notify": True,
                }
            )

        # ──────────────────────────────
        # STOP-Empfehlungen (Kosten sparen)
        # ──────────────────────────────

        # Laden stoppen wenn Strom teuer?
        if price >= expensive and s["battery_soc"] > cfg.get("battery_reserve_evening", DEFAULT_CONFIG["battery_reserve_evening"]):
            decisions.append(
                {
                    "action": "stop_grid_consumption",
                    "priority": 2,
                    "reason": "Hoher Strompreis",
                    "details": (
                        f"Strom teuer: {price:.3f} €/kWh\n"
                        f"Speicher ({s['battery_soc']:.0f}%) statt Netzbezug nutzen empfohlen."
                    ),
                    "notify": True,
                }
            )

        # Nach Priorität sortieren
        decisions.sort(key=lambda d: d["priority"])
        return decisions

    # ─────────────────────────────────────────────
    # AKTIONEN AUSFÜHREN
    # ─────────────────────────────────────────────

    async def _execute_decisions(self, decisions: list[dict], system: dict):  # pyright: ignore[reportUnusedParameter]
        """Führt Entscheidungen aus – vorerst nur Benachrichtigungen."""
        if not decisions:
            _LOGGER.info("Keine besonderen Maßnahmen nötig.")
            return

        for decision in decisions:
            action = decision["action"]
            _LOGGER.info("Entscheidung: %s – %s", action, decision["reason"])

            if decision.get("notify") and decision.get("details"):
                await self._send_smart_notification(action, decision["details"])

    async def _send_smart_notification(self, action_key: str, message: str):
        """
        Sendet Benachrichtigungen mit Cooldown-Schutz.
        Gleiche Nachricht wird max. alle 2 Stunden gesendet.
        """
        now = datetime.now()
        last = self._last_notification.get(action_key)

        if last and (now - last) < timedelta(hours=2):
            _LOGGER.debug("Benachrichtigung '%s' gedrosselt (Cooldown)", action_key)
            return

        try:
            notify_service = self._cfg.get("notify_service", DEFAULT_CONFIG["notify_service"])
            parts = notify_service.split(".", 1)
            domain = parts[0]
            service = parts[1] if len(parts) > 1 else parts[0]

            await self.hass.services.async_call(
                domain,
                service,
                {"message": message, "title": "Energiemanager"},
            )
            self._last_notification[action_key] = now
            _LOGGER.info("Benachrichtigung gesendet: %s", action_key)
        except Exception as ex:
            _LOGGER.error("Benachrichtigungsfehler: %s", ex)

    # ─────────────────────────────────────────────
    # HILFSFUNKTIONEN
    # ─────────────────────────────────────────────

    def _compute_price_level(self, price: float) -> str:
        """Berechnet Preisniveau anhand der konfigurierten Schwellenwerte (€/kWh)."""
        cfg = self._cfg
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

    def _is_pv_producing_well(self, s: dict) -> bool:
        """Prüft ob PV gerade gut produziert."""
        return s["pv_power_kw"] > (self._cfg.get("pv_peak_power_kw", DEFAULT_CONFIG["pv_peak_power_kw"]) * 0.2)

    def _safe_float(self, entity_id: str, default: float = 0.0) -> float:
        """Liest einen HA-Entitätswert als float (sicher, auch bei unavailable)."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return default
        val = state.state
        if val in ("unavailable", "unknown", None):
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def _safe_bool(self, entity_id: str) -> bool:
        """Liest einen HA-Entitätswert als bool."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return False
        return state.state in ("on", "true", "True", "1", "home")

    def _log_system_state(self, s: dict):
        """Gibt aktuellen Systemzustand ins Log aus."""
        _LOGGER.info(
            "System | PV: %.1fkW (Überschuss: %.1fkW) | Akku: %.0f%% | Auto: %.0f%% (%s) | Preis: %.3f€/kWh (%s)",
            s["pv_power_kw"],
            s["pv_surplus_kw"],
            s["battery_soc"],
            s["car_soc"],
            "verbunden" if s["car_connected"] else "getrennt",
            s["current_price_eur"],
            s["price_level"],
        )

    def _deploy_dashboard(self):
        """Kopiert Dashboard-Dateien nach /config/www/energy_manager/ (sync, im Executor)."""
        src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard")
        dest_dir = "/config/www/energy_manager"

        if not os.path.isdir(src_dir):
            _LOGGER.debug("Dashboard-Quelldateien nicht gefunden, überspringe Deploy")
            return

        os.makedirs(dest_dir, exist_ok=True)

        for filename in os.listdir(src_dir):
            src_file = os.path.join(src_dir, filename)
            dest_file = os.path.join(dest_dir, filename)

            if not os.path.isfile(src_file):
                continue

            if filename.endswith(".html"):
                # HTML immer neu schreiben und Cache-Buster in Script-Tags injizieren,
                # damit der HA Service Worker nie eine veraltete JS-Version ausliefert
                with open(src_file, encoding="utf-8") as f:
                    content = f.read()
                ts = int(datetime.now().timestamp())
                content = re.sub(r'(src="[^"]+\.js)(?:\?v=\d+)?"', rf'\1?v={ts}"', content)
                with open(dest_file, "w", encoding="utf-8") as f:
                    f.write(content)
                _LOGGER.info("Dashboard HTML deployed mit Cache-Buster v=%d", ts)
            elif not os.path.exists(dest_file) or os.path.getmtime(src_file) > os.path.getmtime(dest_file):
                shutil.copy2(src_file, dest_file)
                _LOGGER.info("Dashboard-Datei kopiert: %s", filename)

        # Entitäts-Konfiguration als JS-Datei generieren
        entities_js = (
            "// Automatisch generiert von Energy Manager – nicht manuell bearbeiten\n"
            f"const HA_ENTITIES = {json.dumps(self._entities, indent=2)};\n"
        )
        entities_dest = os.path.join(dest_dir, "ha_entities.js")
        with open(entities_dest, "w") as f:
            f.write(entities_js)
        _LOGGER.info("Entitäts-Konfiguration nach ha_entities.js geschrieben")

        _LOGGER.info("Dashboard verfügbar unter /local/energy_manager/energy_manager_dashboard.html")

    @callback
    def _on_price_change(self, event) -> None:
        """Reagiert auf Preisänderungen (synchroner Callback, kein await)."""
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")

        if new_state is None:
            return

        new_val = new_state.state
        old_val = old_state.state if old_state else None

        if new_val == old_val:
            return

        try:
            new_price = float(new_val)
            old_price = float(old_val) if old_val not in (None, "unavailable", "unknown") else None

            # Nur reagieren wenn sich Preis signifikant ändert (> 2 Ct)
            if old_price is not None and abs(new_price - old_price) > 0.02:
                _LOGGER.info("Preisänderung: %.3f → %.3f €/kWh", old_price, new_price)
                self.hass.async_create_task(self.async_refresh())
        except (ValueError, TypeError):
            pass
