"""Support for VeSync buttons."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
from typing import override

from pyvesync.base_devices.vesyncbasedevice import VeSyncBaseDevice
from pyvesync.device_container import DeviceContainer

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .common import is_air_fryer, rgetattr
from .const import VS_DEVICES, VS_DISCOVERY
from .coordinator import VesyncConfigEntry, VeSyncDataCoordinator
from .entity import VeSyncBaseEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1


def _has_chambers(device: VeSyncBaseDevice) -> bool:
    """Check if the device is a multi-chamber air fryer."""
    return is_air_fryer(device) and rgetattr(device, "state.chambers") is not None


@dataclass(frozen=True, kw_only=True)
class VeSyncButtonEntityDescription(ButtonEntityDescription):
    """Describe VeSync button entity."""

    press_fn: Callable[[VeSyncBaseDevice], Awaitable[bool]]
    exists_fn: Callable[[VeSyncBaseDevice], bool]
    chamber: int


BUTTONS: tuple[VeSyncButtonEntityDescription, ...] = (
    VeSyncButtonEntityDescription(
        key="chamber_1_stop",
        translation_key="chamber_1_stop",
        chamber=1,
        press_fn=lambda device: device.stop_chamber(1),
        exists_fn=_has_chambers,
    ),
    VeSyncButtonEntityDescription(
        key="chamber_2_stop",
        translation_key="chamber_2_stop",
        chamber=2,
        press_fn=lambda device: device.stop_chamber(2),
        exists_fn=_has_chambers,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: VesyncConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up buttons."""

    coordinator = config_entry.runtime_data

    @callback
    def discover(devices: list[VeSyncBaseDevice]) -> None:
        """Add new devices to platform."""
        _setup_entities(devices, async_add_entities, coordinator)

    config_entry.async_on_unload(
        async_dispatcher_connect(hass, VS_DISCOVERY.format(VS_DEVICES), discover)
    )

    _setup_entities(
        config_entry.runtime_data.manager.devices, async_add_entities, coordinator
    )


@callback
def _setup_entities(
    devices: DeviceContainer | list[VeSyncBaseDevice],
    async_add_entities: AddConfigEntryEntitiesCallback,
    coordinator: VeSyncDataCoordinator,
) -> None:
    """Add button entities for supported devices."""

    async_add_entities(
        VeSyncButtonEntity(dev, description, coordinator)
        for dev in devices
        for description in BUTTONS
        if description.exists_fn(dev)
    )


class VeSyncButtonEntity(VeSyncBaseEntity, ButtonEntity):
    """Representation of a button on a VeSync device."""

    entity_description: VeSyncButtonEntityDescription

    def __init__(
        self,
        device: VeSyncBaseDevice,
        description: VeSyncButtonEntityDescription,
        coordinator: VeSyncDataCoordinator,
    ) -> None:
        """Initialize the VeSync button."""
        super().__init__(device, coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{super().unique_id}-{description.key}"

    @override
    async def async_press(self) -> None:
        """Stop the program of the chamber."""
        chamber = self.entity_description.chamber
        if not await self.entity_description.press_fn(self.device):
            if self.device.state.chambers[chamber].cook_status == "standby":
                raise ServiceValidationError(
                    f"Chamber {chamber} has no program to stop."
                )
            if self.device.last_response:
                raise HomeAssistantError(self.device.last_response.message)
            raise HomeAssistantError(f"Unknown error stopping chamber {chamber}.")

        await self.device.update()
        self.coordinator.async_update_listeners()
