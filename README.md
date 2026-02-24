# ⚡ Energy Manager für Home Assistant

Automatisiertes Energiemanagement als native HA Custom Integration – optimiert PV-Nutzung, Akkusteuerung und Elektroauto-Laden anhand von Echtzeit-Daten und dynamischen Strompreisen.

## Features

- ☀️ **PV-Überschuss-Erkennung** – Auto und Akku laden wenn genug Solarstrom da ist
- 💰 **Dynamischer Stromtarif** (Tibber) – Laden wenn Strom günstig, Netz meiden wenn teuer
- 🔋 **Speichermanagement** – Nachtreserve, Ladezyklen schonen
- 🚗 **Elektroauto** – PV-Laden, günstige Netzladefenster, Notfall-SOC-Schutz
- 📱 **Benachrichtigungen** – Push-Nachrichten bei relevanten Ereignissen (mit Cooldown)
- 📊 **Live-Dashboard** – WebSocket-Anbindung, Sparklines, Entscheidungsanzeige

## Projektstruktur

```
ha-energy-manager/
├── custom_components/
│   └── energy_manager/
│       ├── __init__.py                    # Coordinator + Kernlogik
│       ├── const.py                       # DOMAIN + DEFAULT_CONFIG
│       ├── manifest.json                  # HA Integration Metadaten
│       └── dashboard/
│           ├── energy_manager_dashboard.html  # Live-Dashboard
│           └── ha_websocket.js               # HA WebSocket API Client
├── hacs.json
├── CLAUDE.md
└── README.md
```

## Schnellstart

### 1. HACS-Installation
1. HACS → Integrationen → Repository hinzufügen → `https://github.com/Voder/ha-energy-manager`
2. Energy Manager installieren
3. Home Assistant neu starten

Nach der Installation liegt die Integration automatisch unter `/config/custom_components/energy_manager/`.

### 2. `configuration.yaml` anpassen

Füge den folgenden Block in deine `configuration.yaml` ein. Alle Parameter sind optional – Standardwerte sind in der Integration hinterlegt.

```yaml
energy_manager:
  notify_service: notify.mobile_app_mein_smartphone  # ANPASSEN!

  # Optional: Entity IDs anpassen (falls abweichend von den Standardwerten)
  entities:
    pv_power: sensor.pv_power
    pv_forecast_today: sensor.solcast_pv_forecast_today
    pv_forecast_remaining: sensor.solcast_forecast_remaining
    battery_soc: sensor.battery_soc
    battery_power: sensor.battery_power
    battery_charging_switch: switch.battery_force_charge
    battery_mode: select.battery_operating_mode
    car_soc: sensor.car_battery_level
    car_charging_switch: switch.car_charger
    car_charging_power: sensor.car_charging_power
    car_connected: binary_sensor.car_connected
    grid_power: sensor.grid_power
    house_consumption: sensor.house_consumption
    current_price: sensor.tibber_current_price

  # Optional: Schwellenwerte anpassen
  battery_capacity_kwh: 10.0
  battery_min_soc: 10
  battery_max_soc: 95
  battery_reserve_evening: 30
  car_battery_capacity_kwh: 77.0
  car_min_soc_target: 20
  car_default_target_soc: 80
  pv_peak_power_kw: 10.0
  price_cheap_threshold: 15.0
  price_very_cheap_threshold: 8.0
  price_expensive_threshold: 30.0
  pv_surplus_for_car_charging: 3.0
  pv_surplus_for_battery: 1.0
  check_interval_minutes: 15
```

### 3. Home Assistant neu starten

### 4. Dashboard öffnen

Das Dashboard wird beim Start automatisch nach `/config/www/energy_manager/` kopiert und ist dann erreichbar:

```
http://DEINE_HA_IP:8123/local/energy_manager/energy_manager_dashboard.html?token=DEIN_TOKEN
```

**Token erstellen (Langlebiges Zugriffstoken):**
1. HA-Profil öffnen: unten links auf deinen Benutzernamen und dann auf 'Security' klicken
2. Ganz nach unten scrollen zum Abschnitt **„Langlebige Zugriffstoken"**
3. **„Token erstellen"** klicken, einen Namen vergeben (z.B. „Dashboard")
4. Den angezeigten Token kopieren – er wird nur einmal angezeigt!
5. Token in die URL einfügen oder beim ersten Öffnen des Dashboards eingeben

> Das Token authentifiziert den WebSocket-Zugriff des Dashboards auf Home Assistant. Es wird nie an externe Server übertragen.

## Benötigte Integrationen

| Integration | Zweck |
|-------------|-------|
| [Solcast](https://github.com/BJReplay/ha-solcast-solar) | PV-Vorhersage |
| [Tibber](https://www.home-assistant.io/integrations/tibber/) | Dynamische Strompreise |
| Wechselrichter-Integration | PV + Akku-Daten |
| Wallbox / OCPP | Auto-Ladesteuerung |

## Roadmap

- [x] Algorithmus-Grundlogik
- [x] Push-Benachrichtigungen
- [x] Live-Dashboard mit Sparklines
- [x] WebSocket HA-Anbindung
- [x] HACS-kompatible Repo-Struktur
- [x] Native HA Custom Integration (kein AppDaemon)
- [ ] Direkte Steuerung (Wallbox, Wechselrichter)
- [ ] Tibber 24h-Preisoptimierung
- [ ] Lineare Optimierung (PuLP)

## Lizenz
MIT
