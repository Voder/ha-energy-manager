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
ha-energy-manager/
├── apps/
│   └── energy_manager/
│       ├── energy_manager.py          # AppDaemon-App (Kernlogik)
│       ├── apps.yaml                  # Minimal-Konfiguration (module + class)
│       ├── apps.yaml.template         # Vorlage mit allen Parametern
│       └── dashboard/
│           ├── energy_manager_dashboard.html  # Live-Dashboard
│           └── ha_websocket.js               # HA WebSocket API Client
├── hacs.json
├── CLAUDE.md
└── README.md
```

## Schnellstart

### 1. AppDaemon installieren
HA → Einstellungen → Add-ons → AppDaemon

### 2. HACS-Installation
1. HACS → AppDaemon Apps → Repository hinzufügen → `https://github.com/DEIN_USER/ha-energy-manager`
2. Energy Manager installieren
3. AppDaemon neu starten

Nach der Installation liegt die App automatisch unter `/config/appdaemon/apps/energy_manager/` und ist sofort lauffähig.

### 3. Entity IDs anpassen (optional)
Kopiere `apps.yaml.template` als `apps.yaml` und passe die Werte an dein Setup an:
```bash
cd /config/appdaemon/apps/energy_manager/
cp apps.yaml.template apps.yaml
# apps.yaml bearbeiten – Entity IDs und Schwellenwerte anpassen
```

Alternativ: Die Standardwerte in `energy_manager.py` (CONFIG-Block) direkt anpassen.

### 4. Dashboard öffnen
Das Dashboard wird beim App-Start automatisch nach `/config/www/energy_manager/` kopiert und ist dann unter folgender URL erreichbar:
```
http://DEINE_HA_IP:8123/local/energy_manager/energy_manager_dashboard.html?token=DEIN_TOKEN
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
- [x] HACS-kompatible Repo-Struktur
- [ ] Direkte Steuerung (Wallbox, Wechselrichter)
- [ ] Tibber 24h-Preisoptimierung
- [ ] Lineare Optimierung (PuLP)

## Lizenz
MIT
