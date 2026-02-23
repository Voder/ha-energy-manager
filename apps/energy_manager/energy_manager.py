"""
Energy Manager - AppDaemon App für Home Assistant
==================================================
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

import appdaemon.plugins.hass.hassapi as hass
from datetime import datetime, timedelta
import statistics
import os
import shutil


# ─────────────────────────────────────────────
# KONFIGURATION – Passe diese Werte an dein Setup an
# ─────────────────────────────────────────────
CONFIG = {
    # Hausakku
    "battery_capacity_kwh": 10.0,       # Kapazität in kWh
    "battery_min_soc": 10,              # Minimaler SOC in % (Puffer)
    "battery_max_soc": 95,              # Maximaler SOC in %
    "battery_reserve_evening": 30,      # Reserve für den Abend (%)

    # Elektroauto
    "car_battery_capacity_kwh": 77.0,   # z.B. Tesla Model 3 Long Range
    "car_max_charge_power_kw": 11.0,    # Max. Ladeleistung in kW
    "car_min_soc_target": 20,           # Mindest-SOC, unter dem immer geladen wird
    "car_default_target_soc": 80,       # Standard-Ziel-SOC

    # PV-Anlage
    "pv_peak_power_kw": 10.0,           # Peak-Leistung der Anlage

    # Strompreise (Schwellenwerte in Cent/kWh)
    "price_cheap_threshold": 15.0,      # Unter diesem Preis: Netz günstig zum Laden
    "price_very_cheap_threshold": 8.0,  # Sehr günstig – aggressiv laden
    "price_expensive_threshold": 30.0,  # Teuer – Speicher entladen statt Netzbezug

    # PV-Schwellenwerte (kW)
    "pv_surplus_for_car_charging": 3.0, # Min. PV-Überschuss zum Auto-Laden
    "pv_surplus_for_battery": 1.0,      # Min. PV-Überschuss zum Akku-Laden

    # Home Assistant Entity IDs – ANPASSEN!
    "entities": {
        # PV
        "pv_power": "sensor.pv_power",                          # Aktuelle PV-Leistung (W)
        "pv_forecast_today": "sensor.solcast_pv_forecast_today", # kWh heute gesamt
        "pv_forecast_remaining": "sensor.solcast_forecast_remaining", # kWh verbleibend heute

        # Hausakku
        "battery_soc": "sensor.battery_soc",                    # SOC in %
        "battery_power": "sensor.battery_power",                # Lade-/Entladeleistung (W)
        "battery_charging_switch": "switch.battery_force_charge",
        "battery_mode": "select.battery_operating_mode",

        # Elektroauto
        "car_soc": "sensor.car_battery_level",                  # SOC in %
        "car_charging_switch": "switch.car_charger",
        "car_charging_power": "sensor.car_charging_power",      # W
        "car_connected": "binary_sensor.car_connected",

        # Stromzähler / Netz
        "grid_power": "sensor.grid_power",                      # + = Bezug, - = Einspeisung (W)
        "house_consumption": "sensor.house_consumption",        # W

        # Tibber / Strompreise
        "current_price": "sensor.tibber_current_price",         # Cent/kWh
        "price_level": "sensor.tibber_price_level",             # LOW/NORMAL/HIGH/VERY_HIGH
    },

    # Benachrichtigungen
    "notify_service": "notify.mobile_app_dein_smartphone",     # ANPASSEN!
    "check_interval_minutes": 15,       # Wie oft der Algorithmus läuft
}


class EnergyManager(hass.Hass):
    """Zentraler Energiemanager als AppDaemon-App."""

    def initialize(self):
        """AppDaemon-Initialisierung."""
        self.log("🔋 Energy Manager gestartet", level="INFO")

        # Dashboard-Dateien nach /config/www/ bereitstellen
        self._deploy_dashboard()

        # Zustandsspeicher für Hysterese (verhindert zu häufiges Schalten)
        self.state = {
            "car_charging_pv": False,       # Auto lädt gerade via PV
            "car_charging_cheap": False,    # Auto lädt gerade wegen günstigem Strom
            "battery_force_charging": False, # Akku wird aus Netz geladen
            "last_notification": {},        # Vermeidet doppelte Nachrichten
            "last_decision": None,
        }

        # Alle 15 Minuten ausführen
        interval = CONFIG["check_interval_minutes"] * 60
        self.run_every(self.run_energy_manager, "now", interval)

        # Zusätzlich bei Preisänderungen reagieren
        self.listen_state(
            self.on_price_change,
            CONFIG["entities"]["current_price"]
        )

        self.log("⏰ Energiemanager läuft alle {} Minuten".format(
            CONFIG["check_interval_minutes"]))

    # ─────────────────────────────────────────────
    # HAUPTLOGIK
    # ─────────────────────────────────────────────

    def run_energy_manager(self, kwargs):
        """Hauptfunktion – wird regelmäßig aufgerufen."""
        self.log("🔄 Energiemanager-Durchlauf startet...", level="INFO")

        # 1. Systemzustand erfassen
        system = self.get_system_state()
        if system is None:
            self.log("⚠️ Konnte Systemzustand nicht lesen", level="WARNING")
            return

        self.log_system_state(system)

        # 2. Entscheidungslogik (nach Priorität)
        decisions = self.make_decisions(system)

        # 3. Aktionen ausführen (Benachrichtigungen)
        self.execute_decisions(decisions, system)

    def get_system_state(self) -> dict | None:
        """Liest alle relevanten Sensordaten aus Home Assistant."""
        try:
            e = CONFIG["entities"]

            # Hilfsfunktion: sicher float lesen
            def safe_float(entity_id, default=0.0):
                val = self.get_state(entity_id)
                if val in (None, "unavailable", "unknown"):
                    return default
                try:
                    return float(val)
                except (ValueError, TypeError):
                    return default

            def safe_bool(entity_id):
                val = self.get_state(entity_id)
                return val in ("on", "true", "True", "1", "home")

            pv_power_w = safe_float(e["pv_power"])
            house_consumption_w = safe_float(e["house_consumption"])
            grid_power_w = safe_float(e["grid_power"])

            # PV-Überschuss berechnen (positiv = Überschuss verfügbar)
            pv_surplus_w = pv_power_w - house_consumption_w

            return {
                # PV
                "pv_power_kw": pv_power_w / 1000,
                "pv_surplus_kw": pv_surplus_w / 1000,
                "pv_forecast_today_kwh": safe_float(e["pv_forecast_today"]),
                "pv_forecast_remaining_kwh": safe_float(e["pv_forecast_remaining"]),

                # Hausakku
                "battery_soc": safe_float(e["battery_soc"]),
                "battery_power_kw": safe_float(e["battery_power"]) / 1000,

                # Elektroauto
                "car_soc": safe_float(e["car_soc"]),
                "car_connected": safe_bool(e["car_connected"]),
                "car_charging_power_kw": safe_float(e["car_charging_power"]) / 1000,

                # Netz & Verbrauch
                "grid_power_kw": grid_power_w / 1000,
                "house_consumption_kw": house_consumption_w / 1000,

                # Preise
                "current_price_ct": safe_float(e["current_price"]),
                "price_level": self.get_state(e["price_level"]) or "NORMAL",

                # Zeit
                "hour": datetime.now().hour,
                "is_night": datetime.now().hour < 6 or datetime.now().hour >= 22,
                "is_morning": 6 <= datetime.now().hour < 10,
            }
        except Exception as ex:
            self.log(f"❌ Fehler beim Lesen des Systemzustands: {ex}", level="ERROR")
            return None

    # ─────────────────────────────────────────────
    # ENTSCHEIDUNGSALGORITHMUS
    # ─────────────────────────────────────────────

    def make_decisions(self, s: dict) -> list[dict]:
        """
        Kernalgorithmus: Trifft Entscheidungen nach Priorität.
        Gibt eine Liste von Entscheidungen zurück.
        """
        decisions = []
        price = s["current_price_ct"]
        cheap = CONFIG["price_cheap_threshold"]
        very_cheap = CONFIG["price_very_cheap_threshold"]
        expensive = CONFIG["price_expensive_threshold"]

        # ──────────────────────────────
        # PRIORITÄT 1: AUTARKIE / PV-Nutzung
        # ──────────────────────────────

        # Auto laden mit PV-Überschuss?
        if (s["car_connected"]
                and s["car_soc"] < CONFIG["car_default_target_soc"]
                and s["pv_surplus_kw"] >= CONFIG["pv_surplus_for_car_charging"]):

            decisions.append({
                "action": "car_charge_pv",
                "priority": 1,
                "reason": "PV-Überschuss",
                "details": (
                    f"☀️ PV-Überschuss: {s['pv_surplus_kw']:.1f} kW verfügbar.\n"
                    f"Auto-Akku: {s['car_soc']:.0f}% → Laden empfohlen!"
                ),
                "notify": True,
            })

        # Akku laden mit PV-Überschuss (wenn noch nicht voll)?
        if (s["pv_surplus_kw"] >= CONFIG["pv_surplus_for_battery"]
                and s["battery_soc"] < CONFIG["battery_max_soc"]
                and not s["car_connected"]):  # Auto hat Vorrang
            decisions.append({
                "action": "battery_charge_pv",
                "priority": 1,
                "reason": "PV-Überschuss für Speicher",
                "details": None,  # Stille Aktion, kein Notify nötig
                "notify": False,
            })

        # ──────────────────────────────
        # PRIORITÄT 2: KOSTENMINIMIERUNG
        # ──────────────────────────────

        # Speicher aus Netz laden wenn Strom sehr günstig?
        if (price <= very_cheap
                and s["battery_soc"] < CONFIG["battery_max_soc"]
                and not self._is_pv_producing_well(s)):
            decisions.append({
                "action": "battery_charge_grid",
                "priority": 2,
                "reason": "Sehr günstiger Netzstrom",
                "details": (
                    f"💰 Strompreis sehr günstig: {price:.1f} Ct/kWh\n"
                    f"Speicher ({s['battery_soc']:.0f}%) aus dem Netz laden empfohlen!"
                ),
                "notify": True,
            })

        # Auto laden weil Strom günstig (auch ohne PV)?
        if (s["car_connected"]
                and s["car_soc"] < CONFIG["car_default_target_soc"]
                and price <= cheap
                and s["pv_surplus_kw"] < CONFIG["pv_surplus_for_car_charging"]):
            decisions.append({
                "action": "car_charge_cheap",
                "priority": 2,
                "reason": "Günstiger Netzstrom",
                "details": (
                    f"💡 Günstiger Strom: {price:.1f} Ct/kWh\n"
                    f"Auto-Akku: {s['car_soc']:.0f}% → Jetzt laden empfohlen!"
                ),
                "notify": True,
            })

        # Notfall: Auto-SOC kritisch niedrig
        if s["car_connected"] and s["car_soc"] < CONFIG["car_min_soc_target"]:
            decisions.append({
                "action": "car_charge_emergency",
                "priority": 0,  # Höchste Priorität
                "reason": "Kritischer Auto-SOC",
                "details": (
                    f"⚠️ Auto-Akku kritisch niedrig: {s['car_soc']:.0f}%!\n"
                    f"Sofortiges Laden empfohlen (Mindest-SOC: {CONFIG['car_min_soc_target']}%)"
                ),
                "notify": True,
            })

        # ──────────────────────────────
        # STOP-Empfehlungen (Kosten sparen)
        # ──────────────────────────────

        # Laden stoppen wenn Strom teuer?
        if (price >= expensive
                and s["battery_soc"] > CONFIG["battery_reserve_evening"]):
            decisions.append({
                "action": "stop_grid_consumption",
                "priority": 2,
                "reason": "Hoher Strompreis",
                "details": (
                    f"🔴 Strom teuer: {price:.1f} Ct/kWh\n"
                    f"Speicher ({s['battery_soc']:.0f}%) statt Netzbezug nutzen empfohlen."
                ),
                "notify": True,
            })

        # Nach Priorität sortieren
        decisions.sort(key=lambda d: d["priority"])
        return decisions

    # ─────────────────────────────────────────────
    # AKTIONEN AUSFÜHREN
    # ─────────────────────────────────────────────

    def execute_decisions(self, decisions: list[dict], system: dict):
        """Führt Entscheidungen aus – vorerst nur Benachrichtigungen."""
        if not decisions:
            self.log("✅ Keine besonderen Maßnahmen nötig.", level="INFO")
            return

        for decision in decisions:
            action = decision["action"]
            self.log(f"📋 Entscheidung: {action} – {decision['reason']}", level="INFO")

            # Benachrichtigung senden (mit Duplikat-Schutz)
            if decision.get("notify") and decision.get("details"):
                self.send_smart_notification(action, decision["details"])

        # Zusammenfassung loggen
        self.state["last_decision"] = {
            "time": datetime.now().isoformat(),
            "decisions": [d["action"] for d in decisions],
            "system_snapshot": {
                "pv_kw": system["pv_power_kw"],
                "battery_soc": system["battery_soc"],
                "car_soc": system["car_soc"],
                "price_ct": system["current_price_ct"],
            }
        }

    # ─────────────────────────────────────────────
    # HILFSFUNKTIONEN
    # ─────────────────────────────────────────────

    def _is_pv_producing_well(self, s: dict) -> bool:
        """Prüft ob PV gerade gut produziert."""
        return s["pv_power_kw"] > (CONFIG["pv_peak_power_kw"] * 0.2)

    def send_smart_notification(self, action_key: str, message: str):
        """
        Sendet Benachrichtigungen mit Cooldown-Schutz.
        Gleiche Nachricht wird max. alle 2 Stunden gesendet.
        """
        now = datetime.now()
        last = self.state["last_notification"].get(action_key)

        if last and (now - last) < timedelta(hours=2):
            self.log(f"🔕 Benachrichtigung '{action_key}' gedrosselt (Cooldown)", level="DEBUG")
            return

        try:
            self.call_service(
                CONFIG["notify_service"].replace(".", "/", 1),
                message=message,
                title="⚡ Energiemanager"
            )
            self.state["last_notification"][action_key] = now
            self.log(f"📱 Benachrichtigung gesendet: {action_key}", level="INFO")
        except Exception as ex:
            self.log(f"❌ Benachrichtigungsfehler: {ex}", level="ERROR")

    def log_system_state(self, s: dict):
        """Gibt aktuellen Systemzustand ins Log aus."""
        self.log(
            f"📊 System | "
            f"PV: {s['pv_power_kw']:.1f}kW (Überschuss: {s['pv_surplus_kw']:.1f}kW) | "
            f"Akku: {s['battery_soc']:.0f}% | "
            f"Auto: {s['car_soc']:.0f}% ({'verbunden' if s['car_connected'] else 'getrennt'}) | "
            f"Preis: {s['current_price_ct']:.1f}Ct/kWh ({s['price_level']})",
            level="INFO"
        )

    def _deploy_dashboard(self):
        """Kopiert Dashboard-Dateien nach /config/www/energy_manager/ für HA-Zugriff."""
        app_dir = os.path.dirname(os.path.abspath(__file__))
        src_dir = os.path.join(app_dir, "dashboard")
        dest_dir = "/config/www/energy_manager"

        if not os.path.isdir(src_dir):
            self.log("Dashboard-Quelldateien nicht gefunden, überspringe Deploy", level="DEBUG")
            return

        os.makedirs(dest_dir, exist_ok=True)

        for filename in os.listdir(src_dir):
            src_file = os.path.join(src_dir, filename)
            dest_file = os.path.join(dest_dir, filename)

            if not os.path.isfile(src_file):
                continue

            # Nur kopieren wenn Ziel nicht existiert oder Quelle neuer ist
            if (not os.path.exists(dest_file)
                    or os.path.getmtime(src_file) > os.path.getmtime(dest_file)):
                shutil.copy2(src_file, dest_file)
                self.log(f"Dashboard-Datei kopiert: {filename}", level="INFO")

        self.log(f"Dashboard verfügbar unter /local/energy_manager/energy_manager_dashboard.html", level="INFO")

    def on_price_change(self, entity, attribute, old, new, kwargs):
        """Reagiert auf Preisänderungen (z.B. stündlich bei Tibber)."""
        if old == new:
            return
        try:
            new_price = float(new)
            old_price = float(old) if old not in (None, "unavailable") else None

            # Nur reagieren wenn sich Preis signifikant ändert
            if old_price and abs(new_price - old_price) > 2.0:
                self.log(f"💶 Preisänderung: {old_price:.1f} → {new_price:.1f} Ct/kWh", level="INFO")
                self.run_energy_manager({})  # Sofortiger Durchlauf
        except (ValueError, TypeError):
            pass
