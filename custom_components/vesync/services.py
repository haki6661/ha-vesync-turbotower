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
    SERVICE_UPDATE_DEVS,
    VS_DEVICES,
    VS_DISCOVERY,
)

ATTR_DEVICE_ID = "device_id"
ATTR_CHAMBER = "chamber"
ATTR_TEMPERATURE = "temperature"
ATTR_MINUTES = "minutes"
ATTR_MODE = "mode"

PREPARE_AIR_FRYER_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): cv.string,
        vol.Required(ATTR_CHAMBER): vol.All(vol.Coerce(int), vol.In([1, 2])),
        vol.Required(ATTR_TEMPERATURE): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Required(ATTR_MINUTES): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(ATTR_MODE, default="AirFry"): cv.string,
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


async def async_prepare_air_fryer_program(call: ServiceCall) -> None:
    """Prepare a cooking program; the appliance still needs its Start button."""

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


def _validate_program(device: VeSyncBaseDevice, data: dict) -> None:
    """Check temperature and time against the limits known for the mode."""
    limits = AIR_FRYER_MODE_LIMITS.get(data[ATTR_MODE])
    if limits is None:
        return
    unit = getattr(device, "temp_unit", "celsius")
    min_temp, max_temp = limits.get(unit, limits["celsius"])
    temperature = data[ATTR_TEMPERATURE]
    if not min_temp <= temperature <= max_temp or temperature % 5:
        raise ServiceValidationError(
            f"{data[ATTR_MODE]} takes {min_temp} to {max_temp} degrees "
            f"in steps of 5, got {temperature}"
        )
    min_minutes, max_minutes = limits["minutes"]
    if not min_minutes <= data[ATTR_MINUTES] <= max_minutes:
        raise ServiceValidationError(
            f"{data[ATTR_MODE]} takes {min_minutes} to {max_minutes} minutes, "
            f"got {data[ATTR_MINUTES]}"
        )
