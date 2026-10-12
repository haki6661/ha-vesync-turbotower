"""Support for VeSync Services."""

from pyvesync.base_devices.vesyncbasedevice import VeSyncBaseDevice
import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send

from . import VesyncConfigEntry
from .const import (
    AIR_FRYER_MODE_LIMITS,
    DOMAIN,
    SERVICE_PREPARE_AIR_FRYER,
    SERVICE_PREPARE_AIR_FRYER_BOTH,
    SERVICE_UPDATE_DEVS,
    VS_DEVICES,
    VS_DISCOVERY,
)

ATTR_DEVICE_ID = "device_id"
ATTR_CHAMBER = "chamber"
ATTR_TEMPERATURE = "temperature"
ATTR_MINUTES = "minutes"
ATTR_MODE = "mode"
ATTR_SYNC = "sync"

SYNC_TYPES = {"finish": 2, "match": 1}
"""syncType values read from the appliance: Sync key = 2, Match key = 1."""

PREPARE_AIR_FRYER_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_CHAMBER): vol.All(vol.Coerce(int), vol.In([1, 2])),
        vol.Required(ATTR_TEMPERATURE): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Required(ATTR_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(ATTR_MODE, default="AirFry"): cv.string,
    }
)

PREPARE_AIR_FRYER_BOTH_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Optional(ATTR_SYNC, default="finish"): vol.In(list(SYNC_TYPES)),
        vol.Required("chamber_1_temperature"): vol.All(
            vol.Coerce(int), vol.Range(min=1)
        ),
        vol.Required("chamber_1_minutes"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional("chamber_1_mode", default="AirFry"): cv.string,
        vol.Optional("chamber_2_temperature"): vol.All(
            vol.Coerce(int), vol.Range(min=1)
        ),
        vol.Optional("chamber_2_minutes"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional("chamber_2_mode", default="AirFry"): cv.string,
    }
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Handle for services."""

    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE_DEVS, async_new_device_discovery
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PREPARE_AIR_FRYER,
        async_prepare_air_fryer_program,
        schema=PREPARE_AIR_FRYER_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PREPARE_AIR_FRYER_BOTH,
        async_prepare_air_fryer_both_chambers,
        schema=PREPARE_AIR_FRYER_BOTH_SCHEMA,
    )


async def async_new_device_discovery(call: ServiceCall) -> None:
    """Discover and add new devices."""

    entries = call.hass.config_entries.async_entries(DOMAIN)
    config_entry: VesyncConfigEntry | None = entries[0] if entries else None

    if not config_entry:
        raise ServiceValidationError("Entry not found")
    if config_entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError("Entry not loaded")
    manager = config_entry.runtime_data.manager
    known_devices = list(manager.devices)
    await manager.get_devices()
    new_devices = [device for device in manager.devices if device not in known_devices]

    if new_devices:
        async_dispatcher_send(call.hass, VS_DISCOVERY.format(VS_DEVICES), new_devices)


def _find_device(call: ServiceCall) -> tuple:
    """Return (coordinator, device) for the device_id of a service call."""

    device_entry = dr.async_get(call.hass).async_get(call.data[ATTR_DEVICE_ID])
    if device_entry is None:
        raise ServiceValidationError("Device not found")
    unique_ids = {value for domain, value in device_entry.identifiers if domain == DOMAIN}

    for config_entry in call.hass.config_entries.async_loaded_entries(DOMAIN):
        coordinator = config_entry.runtime_data
        for device in coordinator.manager.devices:
            base_unique_id = device.cid
            if isinstance(device.sub_device_no, int):
                base_unique_id = f"{device.cid}{device.sub_device_no!s}"
            if base_unique_id in unique_ids:
                break
        else:
            continue
        break
    else:
        raise ServiceValidationError("Device is not a loaded VeSync device")
    return coordinator, device


async def async_prepare_air_fryer_program(call: ServiceCall) -> None:
    """Prepare a cooking program; the appliance still needs its Start button."""

    coordinator, device = _find_device(call)
    if not hasattr(device, "prepare_program"):
        raise ServiceValidationError(
            f"{device.device_name} does not support preparing programs"
        )

    _validate_program(device, call.data)

    try:
        success = await device.prepare_program(
            call.data[ATTR_CHAMBER],
            call.data[ATTR_TEMPERATURE],
            call.data[ATTR_MINUTES],
            call.data[ATTR_MODE],
        )
    except ValueError as err:
        raise ServiceValidationError(str(err)) from err

    if not success:
        raise HomeAssistantError(
            f"{device.device_name} rejected the program. Check that the drawer "
            "is closed and the chamber is idle"
        )

    await device.update()
    coordinator.async_update_listeners()


async def async_prepare_air_fryer_both_chambers(call: ServiceCall) -> None:
    """Prepare both chambers linked by Sync or Match; Start is still needed.

    Sync (``finish``): each chamber gets its own program and both end together,
    the shorter one waits. Match: chamber 2 runs the program of chamber 1.
    """

    coordinator, device = _find_device(call)
    if not hasattr(device, "prepare_both_chambers"):
        raise ServiceValidationError(
            f"{device.device_name} does not support preparing both chambers"
        )

    data = call.data
    chamber_1 = {
        ATTR_TEMPERATURE: data["chamber_1_temperature"],
        ATTR_MINUTES: data["chamber_1_minutes"],
        ATTR_MODE: data["chamber_1_mode"],
    }
    if data[ATTR_SYNC] == "match":
        chamber_2 = dict(chamber_1)
    else:
        if "chamber_2_temperature" not in data or "chamber_2_minutes" not in data:
            raise ServiceValidationError(
                "Sync needs temperature and minutes for chamber 2"
            )
        chamber_2 = {
            ATTR_TEMPERATURE: data["chamber_2_temperature"],
            ATTR_MINUTES: data["chamber_2_minutes"],
            ATTR_MODE: data["chamber_2_mode"],
        }
    for chamber in (chamber_1, chamber_2):
        _validate_program(device, chamber)

    try:
        success = await device.prepare_both_chambers(
            chamber_1, chamber_2, SYNC_TYPES[data[ATTR_SYNC]]
        )
    except ValueError as err:
        raise ServiceValidationError(str(err)) from err

    if not success:
        raise HomeAssistantError(
            f"{device.device_name} rejected the programs. Check that both drawers "
            "are closed and both chambers are idle"
        )

    await device.update()
    coordinator.async_update_listeners()


def _validate_program(device: VeSyncBaseDevice, data: dict) -> None:
    """Check temperature and time against the limits measured for the mode."""
    limits = AIR_FRYER_MODE_LIMITS.get(data[ATTR_MODE])
    if limits is None or getattr(device, "temp_unit", "celsius") != "celsius":
        return
    min_temp, max_temp, min_minutes, max_minutes = limits
    if not min_temp <= data[ATTR_TEMPERATURE] <= max_temp:
        raise ServiceValidationError(
            f"{data[ATTR_MODE]} takes {min_temp} to {max_temp} degrees, "
            f"got {data[ATTR_TEMPERATURE]}"
        )
    if not min_minutes <= data[ATTR_MINUTES] <= max_minutes:
        raise ServiceValidationError(
            f"{data[ATTR_MODE]} takes {min_minutes} to {max_minutes} minutes, "
            f"got {data[ATTR_MINUTES]}"
        )
