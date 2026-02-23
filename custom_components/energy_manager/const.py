"""Konstanten für den Energy Manager."""

DOMAIN = "energy_manager"

DEFAULT_CONFIG = {
    # Hausakku
    "battery_capacity_kwh": 10.0,
    "battery_min_soc": 10,
    "battery_max_soc": 95,
    "battery_reserve_evening": 30,

    # Elektroauto
    "car_battery_capacity_kwh": 77.0,
    "car_max_charge_power_kw": 11.0,
    "car_min_soc_target": 20,
    "car_default_target_soc": 80,

    # PV-Anlage
    "pv_peak_power_kw": 10.0,

    # Strompreise (Schwellenwerte in Cent/kWh)
    "price_cheap_threshold": 15.0,
    "price_very_cheap_threshold": 8.0,
    "price_expensive_threshold": 30.0,

    # PV-Schwellenwerte (kW)
    "pv_surplus_for_car_charging": 3.0,
    "pv_surplus_for_battery": 1.0,

    # Home Assistant Entity IDs – ANPASSEN!
    "entities": {
        # PV
        "pv_power": "sensor.pv_power",
        "pv_forecast_today": "sensor.solcast_pv_forecast_today",
        "pv_forecast_remaining": "sensor.solcast_forecast_remaining",

        # Hausakku
        "battery_soc": "sensor.battery_soc",
        "battery_power": "sensor.battery_power",
        "battery_charging_switch": "switch.battery_force_charge",
        "battery_mode": "select.battery_operating_mode",

        # Elektroauto
        "car_soc": "sensor.car_battery_level",
        "car_charging_switch": "switch.car_charger",
        "car_charging_power": "sensor.car_charging_power",
        "car_connected": "binary_sensor.car_connected",

        # Stromzähler / Netz
        "grid_power": "sensor.grid_power",
        "house_consumption": "sensor.house_consumption",

        # Tibber / Strompreise
        "current_price": "sensor.tibber_current_price",
        "price_level": "sensor.tibber_price_level",
    },

    # Benachrichtigungen
    "notify_service": "notify.mobile_app_dein_smartphone",
    "check_interval_minutes": 15,
}
