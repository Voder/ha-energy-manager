# ⚡ Energy Manager für Home Assistant

Automatisiertes Energiemanagement mit AppDaemon – optimiert PV-Nutzung, Akkusteuerung und Elektroauto-Laden anhand von Echtzeit-Daten und dynamischen Strompreisen.

## Features

- ☀️ **PV-Überschuss-Erkennung** – Auto und Akku laden wenn genug Solarstrom da ist
- 💰 **Dynamischer Stromtarif** (Tibber) – Laden wenn Strom günstig, Netz meiden wenn teuer
- 🔋 **Speichermanagement** – Nachtreserve, Ladezyklen schonen
- 🚗 **Elektroauto** – PV-Laden, günstige Netzladefenster, Notfall-SOC-Schutz
- 📱 **Benachrichtigungen** – Push-Nachrichten bei relevanten Ereignissen (mit Cooldown)
- 📊 **Live-Dashboard** – WebSocket-Anbindung, Sparklines, Entscheidungsanzeige

## Projektstruktur

```
energy-manager/
├── appdaemon/
│   ├── energy_manager.py   # AppDaemon-App (Kernlogik)
│   └── apps.yaml           # AppDaemon-Konfiguration
├── dashboard/
│   ├── energy_manager_dashboard.html  # Live-Dashboard
│   └── ha_websocket.js     # HA WebSocket API Client
├── .gitignore
└── README.md
```

## Schnellstart

### 1. AppDaemon installieren
HA → Einstellungen → Add-ons → AppDaemon

### 2. Dateien kopieren
```bash
cp appdaemon/energy_manager.py /config/appdaemon/apps/
cp appdaemon/apps.yaml /config/appdaemon/apps/
```

### 3. Entity IDs anpassen
In `energy_manager.py` den `CONFIG["entities"]`-Block an eigene HA-Entities anpassen.

### 4. Dashboard öffnen
```
energy_manager_dashboard.html?host=192.168.1.X&token=DEIN_TOKEN
```
Token erstellen: **HA → Profil → Langlebige Zugriffstoken**

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
- [ ] Direkte Steuerung (Wallbox, Wechselrichter)
- [ ] Tibber 24h-Preisoptimierung
- [ ] Lineare Optimierung (PuLP)

## Lizenz
MIT
