"""Tests for the Turbo Tower Pro additions of this fork."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er

from pyvesync.device_map import get_device_config
from pyvesync.devices.vesynckitchen import VeSyncAirFryerDC111
from pyvesync.models.vesync_models import ResponseDeviceDetailsModel

sys.path.insert(0, str(Path(__file__).parent))
from call_json_fryers import (  # noqa: E402
    DEVICE_DETAILS,
    STATUS_READY,
    bypass_response,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/vesync instead of the built-in integration."""
    return


class _Devices(list):
    outlets: list = []


@pytest.fixture
async def fryer(hass: HomeAssistant) -> VeSyncAirFryerDC111:
    """Set up the integration with one Turbo Tower Pro, chamber 1 ready."""
    manager = MagicMock()
    manager.account_id = "test-account"
    manager.login = AsyncMock()
    manager.update = AsyncMock()
    manager.check_firmware = AsyncMock()
    manager.update_all_devices = AsyncMock()

    details = ResponseDeviceDetailsModel.from_dict(DEVICE_DETAILS)
    device = VeSyncAirFryerDC111(details, manager, get_device_config("CAF-DC111S-AEU"))
    with patch.object(
        VeSyncAirFryerDC111,
        "call_bypassv2_api",
        new=AsyncMock(return_value=bypass_response(STATUS_READY)[0]),
    ):
        await device.get_details()
    manager.devices = _Devices([device])

    entry = MockConfigEntry(
        domain="vesync",
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        unique_id="test-account",
        minor_version=3,
    )
    entry.add_to_hass(hass)
    with patch("custom_components.vesync.VeSync", return_value=manager):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return device


def _entity_id(hass: HomeAssistant, domain: str, key: str) -> str | None:
    registry = er.async_get(hass)
    for entry in registry.entities.values():
        if entry.domain == domain and entry.unique_id.endswith(f"-{key}"):
            return entry.entity_id
    return None


async def test_entities(hass: HomeAssistant, fryer: VeSyncAirFryerDC111) -> None:
    """Stop buttons exist, sensors this model never fills do not."""
    assert _entity_id(hass, "button", "chamber_1_stop")
    assert _entity_id(hass, "button", "chamber_2_stop")
    assert _entity_id(hass, "sensor", "chamber_1_status")
    assert _entity_id(hass, "sensor", "cook_status")
    assert _entity_id(hass, "sensor", "current_temp") is None
    assert _entity_id(hass, "sensor", "preheat_set_time") is None

    state = hass.states.get(_entity_id(hass, "sensor", "cook_status"))
    assert state.state == "ready"


async def test_stop_chamber(hass: HomeAssistant, fryer: VeSyncAirFryerDC111) -> None:
    """Pressing the button ends the program of that chamber."""
    mocked = AsyncMock(return_value=bypass_response()[0])
    with patch.object(VeSyncAirFryerDC111, "call_bypassv2_api", new=mocked):
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": _entity_id(hass, "button", "chamber_1_stop")},
            blocking=True,
        )
    mocked.assert_awaited_once_with("endCook", data={"chamber": 1})


async def test_stop_empty_chamber(
    hass: HomeAssistant, fryer: VeSyncAirFryerDC111
) -> None:
    """Stopping a chamber without a program raises a readable error."""
    response = bypass_response()[0]
    response["result"]["code"] = 11923000
    mocked = AsyncMock(return_value=response)
    with (
        patch.object(VeSyncAirFryerDC111, "call_bypassv2_api", new=mocked),
        pytest.raises(ServiceValidationError, match="Chamber 2 has no program"),
    ):
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": _entity_id(hass, "button", "chamber_2_stop")},
            blocking=True,
        )


async def test_unknown_cook_status(
    hass: HomeAssistant, fryer: VeSyncAirFryerDC111
) -> None:
    """An unknown API status leaves the enum sensor unknown instead of failing."""
    fryer.state.chambers[1].cook_status = "somethingNew"
    coordinator = hass.config_entries.async_entries("vesync")[0].runtime_data
    coordinator.async_set_updated_data(None)
    await hass.async_block_till_done()

    assert hass.states.get(_entity_id(hass, "sensor", "cook_status")).state == "unknown"
    assert (
        hass.states.get(_entity_id(hass, "sensor", "chamber_1_status")).state
        == "somethingNew"
    )
