# VeSync with Cosori Turbo Tower Pro support

[![Tests](https://github.com/haki6661/ha-vesync-turbotower/actions/workflows/tests.yml/badge.svg)](https://github.com/haki6661/ha-vesync-turbotower/actions/workflows/tests.yml)

A drop-in replacement for the built-in Home Assistant `vesync` integration that adds the
**Cosori Turbo Tower Pro Smart** dual-chamber air fryer (`CAF-DC111S-AEU`). All other
VeSync devices keep working as in core.

This is a stopgap until support lands upstream in
[pyvesync#552](https://github.com/webdjoe/pyvesync/pull/552) and in Home Assistant itself.

## What you get

For each chamber:

| Entity | |
|---|---|
| `sensor.<device>_chamber_N_status` | Raw status from the API: `standby`, `ready`, `cooking`, … |
| `sensor.<device>_chamber_N_set_temperature` | Set temperature of the running program |
| `sensor.<device>_chamber_N_remaining_time` | Remaining time in minutes |
| `button.<device>_stop_chamber_N` | Ends the program of that chamber |

Plus the usual air fryer sensors of the core integration for the active chamber
(`cooking_status`, `cooking_set_temperature`, `cooking_set_time`).

And an action to set up a program from Home Assistant:

```yaml
action: vesync.prepare_air_fryer_program
data:
  device_id: <your air fryer>
  chamber: 1
  temperature: 200   # in the unit the appliance uses
  minutes: 15
  mode: AirFry       # AirFry, Bake, Roast, Reheat, Grill, Dry or Proof
```

The chamber then shows `ready` and starts when you press Start on the appliance.

The stop buttons make automations like "stop chamber 1 when the meat probe reaches 62 °C"
possible.

## Limitations

- **Programs cannot be started remotely.** They can be prepared, but the appliance requires
  pressing Start on the device, a safety lock in the firmware. Stopping works.
- All seven modes are supported. The limits were measured on one appliance (in °C; every
  whole degree and minute inside the range is accepted, everything else is rejected):

  | Mode | Temperature | Time |
  |---|---|---|
  | `AirFry` | 120–230 °C | 1–60 min |
  | `Bake` | 80–205 °C | 1–60 min |
  | `Roast` | 175–230 °C | 1–60 min |
  | `Reheat` | 40–205 °C | 1–60 min |
  | `Grill` | 160–230 °C | 1–60 min |
  | `Dry` | 35–95 °C | 30–1440 min |
  | `Proof` | 30–45 °C | 15–720 min |

  The lower time limit of `Proof` was only probed down to 15 minutes. Limits are only
  checked when the appliance is set to Celsius.
- Cloud polling every 60 seconds, like core. While a chamber is cooking or preheating,
  the air fryer alone is polled every 15 seconds, so a finished program shows up within
  about 15 seconds. Other VeSync devices stay at 60 seconds to protect the daily API quota
  (3200 + 1500 per device).
- Tested with one EU device (`CAF-DC111S-AEU`, firmware as of October 2026, °C).
  Statuses during preheat, at program end and with the drawer pulled out are not
  verified yet. Unknown statuses show as `unknown` on the enum sensor instead of failing;
  the per-chamber status sensors always show the raw value.
- The code is a copy of the core integration from Home Assistant **2026.9.3**. It does not
  follow core updates. If the integration breaks after a Home Assistant update, this fork
  is the first suspect.

## Installation

1. HACS → three dots → **Custom repositories** → add
   `https://github.com/haki6661/ha-vesync-turbotower`, category **Integration**.
2. Install **VeSync (Turbo Tower Pro fork)** and restart Home Assistant.
3. If you did not use VeSync before: Settings → Devices & services → Add integration →
   **VeSync**, log in with your VeSync app account. An existing VeSync config entry is
   picked up as is.

Home Assistant logs a warning that a custom integration overrides `vesync`. That is
expected.

## Going back to the built-in integration

Remove the repository in HACS and restart Home Assistant. Your config entry stays. The
stop buttons and per-chamber sensors disappear and the air fryer is no longer recognized
until core supports it.

## Development

Tests run on Linux (Home Assistant does not run on Windows):

```bash
pip install pytest-homeassistant-custom-component==0.13.367 \
  "pyvesync @ https://github.com/haki6661/pyvesync/archive/20a1080e5f340f8188af160ffae7f5185e6c3879.zip"
pytest
```

## Credits and license

- Integration code: [Home Assistant core](https://github.com/home-assistant/core)
  `homeassistant/components/vesync`, Apache License 2.0 (see [LICENSE.md](LICENSE.md)).
- Turbo Tower Pro support in pyvesync and the first version of this fork:
  [gnisch](https://github.com/gnisch/ha-vesync-turbotower). pyvesync is installed from the
  mirror [haki6661/pyvesync](https://github.com/haki6661/pyvesync), branch
  `feat/turbo-tower-pro-dc123`: gnisch's work plus the recipe IDs of all seven modes and
  the corrected Sync/Match values, read from a real appliance.
- `tests/call_json_fryers.py` is taken from [pyvesync](https://github.com/webdjoe/pyvesync)
  (MIT License).
- This fork adds the stop buttons, faster polling while cooking, hides sensors the Turbo
  Tower Pro never fills, and makes the status sensor robust against unknown values.

Not affiliated with Cosori, VeSync or Home Assistant.
