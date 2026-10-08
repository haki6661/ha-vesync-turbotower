"""Constants for VeSync Component."""

DOMAIN = "vesync"
VS_DISCOVERY = "vesync_discovery_{}"
SERVICE_UPDATE_DEVS = "update_devices"
SERVICE_PREPARE_AIR_FRYER = "prepare_air_fryer_program"

AIR_FRYER_MODE_LIMITS: dict[str, dict[str, tuple[int, int]]] = {
    "AirFry": {"celsius": (120, 230), "fahrenheit": (250, 450), "minutes": (1, 60)},
}
"""Limits per cooking mode, measured on a CAF-DC111S-AEU on 08.10.2026.

The appliance rejects programs outside them with API code 11011000, so they are
checked before the request. Temperatures go in steps of 5.
"""

UPDATE_INTERVAL = 60
UPDATE_INTERVAL_ENERGY = 60 * 60 * 6
UPDATE_INTERVAL_FRYER_ACTIVE = 15
AIR_FRYER_ACTIVE_STATUSES = {"cooking", "heating", "pullout"}
"""
Update interval for DataCoordinator.

The vesync daily quota formula is 3200 + 1500 * device_count.

An interval of 60 seconds amounts 1440 calls/day which
would be below the 4700 daily quota. For 2 devices, the
total would be 2880.

Using 30 seconds interval gives 8640 for 3 devices which
exceeds the quota of 7700.

While an air fryer is cooking, only that fryer is polled every 15 seconds (240
calls/hour), so a finished program shows up quickly. All other devices stay at
60 seconds. A six-hour program adds about 1080 calls.

Energy history is weekly/monthly/yearly and can be updated a lot more infrequently,
in this case every 6 hours.
"""
VS_DEVICES = "devices"
VS_LISTENERS = "listeners"
VS_NUMBERS = "numbers"

VS_HUMIDIFIER_MODE_AUTO = "auto"
VS_HUMIDIFIER_MODE_HUMIDITY = "humidity"
VS_HUMIDIFIER_MODE_MANUAL = "manual"
VS_HUMIDIFIER_MODE_SLEEP = "sleep"

VS_FAN_MODE_AUTO = "auto"
VS_FAN_MODE_SLEEP = "sleep"
VS_FAN_MODE_TURBO = "turbo"
VS_FAN_MODE_PET = "pet"
VS_FAN_MODE_MANUAL = "manual"
VS_FAN_MODE_NORMAL = "normal"
VS_FAN_MODE_ECO = "eco"

# not a full list as manual is used as speed not present
VS_FAN_MODE_PRESET_LIST_HA = [
    VS_FAN_MODE_AUTO,
    VS_FAN_MODE_SLEEP,
    VS_FAN_MODE_TURBO,
    VS_FAN_MODE_PET,
    VS_FAN_MODE_NORMAL,
    VS_FAN_MODE_ECO,
]
NIGHT_LIGHT_LEVEL_BRIGHT = "bright"
NIGHT_LIGHT_LEVEL_DIM = "dim"
NIGHT_LIGHT_LEVEL_OFF = "off"

HUMIDIFIER_NIGHT_LIGHT_LEVEL_BRIGHT = "bright"
HUMIDIFIER_NIGHT_LIGHT_LEVEL_DIM = "dim"
HUMIDIFIER_NIGHT_LIGHT_LEVEL_OFF = "off"

OUTLET_NIGHT_LIGHT_LEVEL_AUTO = "auto"
OUTLET_NIGHT_LIGHT_LEVEL_OFF = "off"
OUTLET_NIGHT_LIGHT_LEVEL_ON = "on"

PURIFIER_NIGHT_LIGHT_LEVEL_DIM = "dim"
PURIFIER_NIGHT_LIGHT_LEVEL_OFF = "off"
PURIFIER_NIGHT_LIGHT_LEVEL_ON = "on"

AIR_FRYER_MODE_MAP = {
    "cookend": "cooking_end",
    "cooking": "cooking",
    "cookstop": "cooking_stop",
    "heating": "heating",
    "preheatend": "preheat_end",
    "preheatstop": "preheat_stop",
    "pullout": "pull_out",
    "ready": "ready",
    "standby": "standby",
}
