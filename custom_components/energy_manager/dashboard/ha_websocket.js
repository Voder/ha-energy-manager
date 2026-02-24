/**
 * ha_websocket.js
 * ───────────────────────────────────────────────────────────────────
 * Home Assistant WebSocket API – Live-Datenanbindung für das
 * Energy Manager Dashboard.
 *
 * Verwendung:
 *   const ha = new HAWebSocket({ host: 'homeassistant.local', token: '...' });
 *   ha.onUpdate = (liveData) => render(liveData);
 *   ha.connect();
 *
 * Dokumentation: https://developers.home-assistant.io/docs/api/websocket
 * ───────────────────────────────────────────────────────────────────
 */

class HAWebSocket {
  /**
   * @param {Object} config
   * @param {string} config.host        - HA-Hostname oder IP, z.B. "homeassistant.local" oder "192.168.1.10"
   * @param {number} [config.port=8123] - HA-Port (Standard: 8123)
   * @param {boolean} [config.ssl=false] - true für https/wss (z.B. Nabu Casa Cloud)
   * @param {string} config.token       - Long-Lived Access Token aus HA
   * @param {Object} config.entities    - Mapping von logischen Namen zu Entity-IDs
   */
  constructor(config) {
    this.host    = config.host;
    this.port    = config.port ?? 8123;
    this.ssl     = config.ssl ?? false;
    this.token   = config.token;
    this.entities = config.entities ?? DEFAULT_ENTITIES;

    this.ws              = null;
    this.msgId           = 1;        // Jede WS-Nachricht braucht eine eindeutige ID
    this.connected       = false;
    this.reconnectMs     = 5000;     // Wiederverbindungsintervall
    this.refreshIntervalMs = config.refreshIntervalMs ?? 30000; // Polling-Fallback für stille Entities
    this._stateCache     = {};       // Lokaler Cache aller Entity-States
    this._subId          = null;     // ID des state_changed-Subscriptions
    this._refreshTimer   = null;     // Periodischer get_states-Poll

    /** Wird aufgerufen wenn sich Daten ändern – überschreiben! */
    this.onUpdate = (_liveData) => {};
    /** Wird aufgerufen bei Verbindungsstatusänderungen */
    this.onConnectionChange = (_connected) => {};
  }

  // ─────────────────────────────────────────────
  // VERBINDUNG
  // ─────────────────────────────────────────────

  connect() {
    const proto = this.ssl ? 'wss' : 'ws';
    const url   = `${proto}://${this.host}:${this.port}/api/websocket`;

    console.log(`[HA] Verbinde mit ${url} ...`);
    this.ws = new WebSocket(url);

    this.ws.onopen    = () => this._onOpen();
    this.ws.onmessage = (e) => this._onMessage(JSON.parse(e.data));
    this.ws.onerror   = (e) => console.error('[HA] WebSocket Fehler:', e);
    this.ws.onclose   = () => this._onClose();
  }

  disconnect() {
    this._stopRefreshTimer();
    if (this.ws) {
      this.ws.onclose = null; // Kein Auto-Reconnect
      this.ws.close();
      this.ws = null;
    }
    this.connected = false;
  }

  // ─────────────────────────────────────────────
  // INTERNE HANDLER
  // ─────────────────────────────────────────────

  _onOpen() {
    console.log('[HA] WebSocket verbunden – warte auf auth_required...');
  }

  _onMessage(msg) {
    switch (msg.type) {

      // 1. HA fordert Authentifizierung an
      case 'auth_required':
        this._send({ type: 'auth', access_token: this.token });
        break;

      // 2. Authentifizierung erfolgreich
      case 'auth_ok':
        console.log(`[HA] Authentifiziert (HA Version: ${msg.ha_version})`);
        this.connected = true;
        this.onConnectionChange(true);
        this._fetchInitialStates();
        this._startRefreshTimer();
        break;

      // 3. Authentifizierung fehlgeschlagen
      case 'auth_invalid':
        console.error('[HA] Authentifizierung fehlgeschlagen! Token prüfen.');
        this.onConnectionChange(false);
        break;

      // 4. Antwort auf eine Anfrage (result)
      case 'result':
        if (msg.success && Array.isArray(msg.result)) {
          // Antwort auf get_states: alle States einlesen
          this._processInitialStates(msg.result);
        }
        break;

      // 5. Echtzeit-Ereignis (state_changed)
      case 'event':
        if (msg.event?.event_type === 'state_changed') {
          this._processStateChange(msg.event.data);
        }
        break;
    }
  }

  _onClose() {
    console.warn(`[HA] Verbindung getrennt – Wiederverbindung in ${this.reconnectMs / 1000}s`);
    this._stopRefreshTimer();
    this.connected = false;
    this.onConnectionChange(false);
    setTimeout(() => this.connect(), this.reconnectMs);
  }

  // ─────────────────────────────────────────────
  // DATEN LADEN & VERARBEITEN
  // ─────────────────────────────────────────────

  /** Schritt 1: Alle aktuellen States auf einmal abrufen */
  _fetchInitialStates() {
    this._send({ type: 'get_states' });
    this._subscribeStateChanges();
  }

  /** Schritt 2: Auf künftige Änderungen subscriben */
  _subscribeStateChanges() {
    this._subId = this.msgId;
    this._send({
      type: 'subscribe_events',
      event_type: 'state_changed',
    });
    console.log('[HA] Subscribiert auf state_changed Events');
  }

  /** Verarbeitet get_states Antworten (initial und periodisch) */
  _processInitialStates(states) {
    for (const state of states) {
      this._stateCache[state.entity_id] = state;
    }
    this._emitUpdate();
  }

  _startRefreshTimer() {
    if (this._refreshTimer) return; // läuft bereits
    this._refreshTimer = setInterval(() => {
      if (this.connected) this._send({ type: 'get_states' });
    }, this.refreshIntervalMs);
  }

  _stopRefreshTimer() {
    if (this._refreshTimer) {
      clearInterval(this._refreshTimer);
      this._refreshTimer = null;
    }
  }

  /** Verarbeitet ein einzelnes state_changed Event */
  _processStateChange({ entity_id, new_state }) {
    if (!new_state) return;
    this._stateCache[entity_id] = new_state;

    // Nur updaten wenn eine relevante Entity sich geändert hat
    const relevantIds = Object.values(this.entities);
    if (relevantIds.includes(entity_id)) {
      this._emitUpdate();
    }
  }

  /** Liest Entity-Werte aus dem Cache und baut das liveData-Objekt */
  _emitUpdate() {
    const get = (key, fallback = 0) => {
      const entityId = this.entities[key];
      if (!entityId) return fallback;
      const state = this._stateCache[entityId];
      if (!state || state.state === 'unavailable' || state.state === 'unknown') return fallback;
      const num = parseFloat(state.state);
      return isNaN(num) ? state.state : num;
    };

    const getBool = (key) => {
      const entityId = this.entities[key];
      if (!entityId) return false;
      const state = this._stateCache[entityId];
      return state?.state === 'on' || state?.state === 'home' || state?.state === 'connected';
    };

    const getAttr = (key, attr, fallback = null) => {
      const entityId = this.entities[key];
      if (!entityId) return fallback;
      const state = this._stateCache[entityId];
      return state?.attributes?.[attr] ?? fallback;
    };

    const liveData = {
      // PV
      pv_kw:              get('pv_power') / 1000,
      house_kw:           get('house_consumption') / 1000,
      pv_forecast_kwh:    get('pv_forecast_today', 0),
      pv_forecast_remaining_kwh: get('pv_forecast_remaining', 0),
      pv_forecast_tomorrow_kwh:  get('pv_forecast_tomorrow', 0),

      // Hausakku
      battery_soc:        get('battery_soc', 0),
      battery_kw:         get('battery_power') / 1000,

      // Auto
      car_soc:            get('car_soc', 0),
      car_connected:      getBool('car_connected'),
      car_kw:             get('car_charging_power') / 1000,

      // Preis
      price_eur:          get('current_price', 0),
      price_records:      (() => {
        const records = getAttr('tibber_prices', 'records');
        if (!Array.isArray(records)) return [];
        return records.map(r => ({ time: r.Time, price: r.Price }));
      })(),

      // Grid
      grid_kw:            get('grid_power') / 1000,
    };

    this.onUpdate(liveData);
  }

  // ─────────────────────────────────────────────
  // HILFSFUNKTIONEN
  // ─────────────────────────────────────────────

  _send(payload) {
    if (!payload.id && payload.type !== 'auth') {
      payload.id = this.msgId++;
    }
    this.ws.send(JSON.stringify(payload));
  }

  /** Gibt den aktuellen State einer beliebigen Entity zurück */
  getState(entityId) {
    return this._stateCache[entityId] ?? null;
  }

  /** Gibt alle gecachten States zurück (z.B. für Debugging) */
  getAllStates() {
    return this._stateCache;
  }
}

// ─────────────────────────────────────────────
// DEFAULT ENTITY-MAPPING – an eigenes Setup anpassen
// ─────────────────────────────────────────────
const DEFAULT_ENTITIES = {
  // PV
  pv_power:             'sensor.pv_power',
  house_consumption:    'sensor.house_consumption',
  pv_forecast_today:    'sensor.solcast_pv_forecast_today',
  pv_forecast_remaining: 'sensor.solcast_forecast_remaining',
  pv_forecast_tomorrow: 'sensor.solcast_pv_forecast_tomorrow',

  // Hausakku
  battery_soc:          'sensor.battery_soc',
  battery_power:        'sensor.battery_power',

  // Elektroauto
  car_soc:              'sensor.car_battery_level',
  car_connected:        'binary_sensor.car_connected',
  car_charging_power:   'sensor.car_charging_power',

  // Netz & Preis
  grid_power:           'sensor.grid_power',
  current_price:        'sensor.tibber_current_price',
  tibber_prices:        'sensor.tibber_prices',
};


// ─────────────────────────────────────────────
// KONFIGURATIONS-HELPER für das Dashboard
// ─────────────────────────────────────────────

/**
 * Liest die HA-Verbindungskonfiguration.
 * Priorität: URL-Parameter > localStorage > Defaults
 *
 * Beispiel-URL: dashboard.html?host=192.168.1.10&ssl=true
 */
function loadHAConfig() {
  const params = new URLSearchParams(window.location.search);
  return {
    host:  params.get('host')  ?? localStorage.getItem('ha_host')  ?? 'homeassistant.local',
    port:  parseInt(params.get('port')  ?? localStorage.getItem('ha_port')  ?? '8123'),
    ssl:   (params.get('ssl')   ?? localStorage.getItem('ha_ssl')   ?? 'false') === 'true',
    token: params.get('token') ?? localStorage.getItem('ha_token') ?? '',
  };
}

/**
 * Speichert die Konfiguration in localStorage.
 */
function saveHAConfig(config) {
  localStorage.setItem('ha_host',  config.host);
  localStorage.setItem('ha_port',  config.port);
  localStorage.setItem('ha_ssl',   config.ssl);
  localStorage.setItem('ha_token', config.token);
}
