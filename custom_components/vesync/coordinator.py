"""Class to manage VeSync data updates."""

from datetime import timedelta
import logging
import time
from typing import override

from pyvesync import VeSync
from pyvesync.base_devices.vesyncbasedevice import VeSyncBaseDevice
from pyvesync.utils.errors import VeSyncError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .common import is_air_fryer
from .const import (
    AIR_FRYER_ACTIVE_STATUSES,
    UPDATE_INTERVAL,
    UPDATE_INTERVAL_ENERGY,
    UPDATE_INTERVAL_FRYER_ACTIVE,
)

_LOGGER = logging.getLogger(__name__)

type VesyncConfigEntry = ConfigEntry[VeSyncDataCoordinator]


class VeSyncDataCoordinator(DataUpdateCoordinator[None]):
    """Class representing data coordinator for VeSync devices."""

    config_entry: VesyncConfigEntry
    update_time: float | None = None
    full_update_time: float | None = None

    def __init__(
        self, hass: HomeAssistant, config_entry: VesyncConfigEntry, manager: VeSync
    ) -> None:
        """Initialize."""
        self.manager = manager

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="VeSyncDataCoordinator",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

    def should_update_energy(self) -> bool:
        """Test if specified update interval has been exceeded."""
        if self.update_time is None:
            return True

        return time.time() - self.update_time >= UPDATE_INTERVAL_ENERGY

    @override
    async def _async_update_data(self) -> None:
        """Fetch data from API endpoint."""
        try:
            if self.should_update_all():
                self.full_update_time = time.monotonic()
                await self.manager.update_all_devices()
            else:
                # Between full updates only air fryers are polled. All of them, not
                # only the cooking ones, so a manual refresh also picks up a start.
                for fryer in self.air_fryers():
                    await fryer.update()

            if self.should_update_energy():
                self.update_time = time.time()
                for outlet in self.manager.devices.outlets:
                    await outlet.update_energy()
        except VeSyncError as err:
            raise UpdateFailed(f"The service is unavailable: {err}") from err
        finally:
            self.update_interval = timedelta(
                seconds=UPDATE_INTERVAL_FRYER_ACTIVE
                if self.active_air_fryers()
                else UPDATE_INTERVAL
            )

    def should_update_all(self) -> bool:
        """Test if all devices are due, not only the active air fryers."""
        if self.full_update_time is None:
            return True

        # A little slack so the 15 second ticks do not push the full update to 75 s.
        return (
            time.monotonic() - self.full_update_time
            >= UPDATE_INTERVAL - UPDATE_INTERVAL_FRYER_ACTIVE / 2
        )

    def air_fryers(self) -> list[VeSyncBaseDevice]:
        """Return all air fryers."""
        return [device for device in self.manager.devices if is_air_fryer(device)]

    def active_air_fryers(self) -> list[VeSyncBaseDevice]:
        """Return air fryers with a running program."""
        return [
            device
            for device in self.manager.devices
            if is_air_fryer(device) and _is_cooking(device)
        ]


def _is_cooking(device: VeSyncBaseDevice) -> bool:
    """Check if any chamber of the air fryer is preheating or cooking."""
    chambers = getattr(device.state, "chambers", None)
    if chambers:
        statuses = [chamber.cook_status for chamber in chambers.values()]
    else:
        statuses = [device.state.cook_status]
    return any(str(status).lower() in AIR_FRYER_ACTIVE_STATUSES for status in statuses)
