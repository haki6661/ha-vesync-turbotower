"""Tests for the Turbo Tower Pro additions of this fork."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er

from pyvesync.device_map import get_device_config
from pyvesync.devices.vesynckitchen import VeSyncAirFryerDC111
from pyvesync.models.vesync_models import ResponseDeviceDetailsModel

sys.path.insert(0, str(Path(__file__).parent))
import custom_components.vesync  # noqa: E402, F401  (patch target below)
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
    humidifiers: list = []
    air_purifiers: list = []
    fans: list = []
    bulbs: list = []
    switches: list = []


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
    with (
        patch.object(VeSyncAirFryerDC111, "call_bypassv2_api", new=mocked),
        patch.object(VeSyncAirFryerDC111, "update", new=AsyncMock()) as update,
    ):
        await hass.services.async_call(
            "button",
            "press",
            {"entity_id": _entity_id(hass, "button", "chamber_1_stop")},
            blocking=True,
        )
    mocked.assert_awaited_once_with("endCook", data={"chamber": 1})
    update.assert_awaited_once()


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


async def test_fast_polling_while_cooking(
    hass: HomeAssistant, fryer: VeSyncAirFryerDC111
) -> None:
    """While a chamber cooks, only the fryer is polled, every 15 seconds."""
    coordinator = hass.config_entries.async_entries("vesync")[0].runtime_data
    manager = coordinator.manager

    # chamber 1 is only "ready" (waiting for Start): normal interval
    coordinator.full_update_time = None
    await coordinator.async_refresh()
    assert coordinator.update_interval.total_seconds() == 60
    full_updates = manager.update_all_devices.await_count

    fryer.state.chambers[1].cook_status = "cooking"
    with patch.object(VeSyncAirFryerDC111, "update", new=AsyncMock()) as update:
        await coordinator.async_refresh()
        update.assert_awaited_once()
    # fast tick: the other devices were not polled again
    assert manager.update_all_devices.await_count == full_updates
    assert coordinator.update_interval.total_seconds() == 15

    fryer.state.chambers[1].cook_status = "standby"
    with patch.object(VeSyncAirFryerDC111, "update", new=AsyncMock()):
        await coordinator.async_refresh()
    assert coordinator.update_interval.total_seconds() == 60


async def test_full_update_still_runs_while_cooking(
    hass: HomeAssistant, fryer: VeSyncAirFryerDC111
) -> None:
    """All devices are still refreshed once a minute during a long program."""
    coordinator = hass.config_entries.async_entries("vesync")[0].runtime_data
    fryer.state.chambers[1].cook_status = "cooking"
    await coordinator.async_refresh()
    calls = coordinator.manager.update_all_devices.await_count

    coordinator.full_update_time -= 60
    await coordinator.async_refresh()
    assert coordinator.manager.update_all_devices.await_count == calls + 1


def _device_id(hass: HomeAssistant) -> str:
    registry = dr.async_get(hass)
    return next(
        device.id
        for device in registry.devices
        if any(domain == "vesync" for domain, _ in device.identifiers)
    )


async def test_prepare_program(
    hass: HomeAssistant, fryer: VeSyncAirFryerDC111
) -> None:
    """The service prepares a program, which then waits for Start on the device."""
    mocked = AsyncMock(return_value=bypass_response()[0])
    with (
        patch.object(VeSyncAirFryerDC111, "call_bypassv2_api", new=mocked),
        patch.object(VeSyncAirFryerDC111, "update", new=AsyncMock()) as update,
    ):
        await hass.services.async_call(
            "vesync",
            "prepare_air_fryer_program",
            {
                "device_id": _device_id(hass),
                "chamber": 2,
                "temperature": 200,
                "minutes": 15,
            },
            blocking=True,
        )
    method, kwargs = mocked.await_args.args[0], mocked.await_args.kwargs
    assert method == "startMultiCook"
    config = kwargs["data"]["cookConfigs"][0]
    assert config["chamber"] == 2
    assert config["cookTemp"] == 200
    assert config["cookSetTime"] == 900
    assert config["mode"] == "AirFry"
    assert kwargs["data"]["readyStart"] is True
    update.assert_awaited_once()


async def test_prepare_program_out_of_range(
    hass: HomeAssistant, fryer: VeSyncAirFryerDC111
) -> None:
    """Values the appliance does not accept are rejected before any API call."""
    mocked = AsyncMock(return_value=bypass_response()[0])
    with (
        patch.object(VeSyncAirFryerDC111, "call_bypassv2_api", new=mocked),
        pytest.raises(ServiceValidationError, match="takes 120 to 230 degrees"),
    ):
        await hass.services.async_call(
            "vesync",
            "prepare_air_fryer_program",
            {
                "device_id": _device_id(hass),
                "chamber": 1,
                "temperature": 300,
                "minutes": 15,
            },
            blocking=True,
        )
    mocked.assert_not_awaited()


@pytest.mark.parametrize(
    ("temperature", "minutes", "message"),
    [(100, 15, "takes 120 to 230 degrees"), (231, 15, "takes 120 to 230 degrees"), (180, 61, "takes 1 to 60 minutes")],
)
async def test_prepare_program_airfry_limits(
    hass: HomeAssistant,
    fryer: VeSyncAirFryerDC111,
    temperature: int,
    minutes: int,
    message: str,
) -> None:
    """AirFry limits measured on the real appliance are enforced up front."""
    mocked = AsyncMock(return_value=bypass_response()[0])
    with (
        patch.object(VeSyncAirFryerDC111, "call_bypassv2_api", new=mocked),
        pytest.raises(ServiceValidationError, match=message),
    ):
        await hass.services.async_call(
            "vesync",
            "prepare_air_fryer_program",
            {
                "device_id": _device_id(hass),
                "chamber": 1,
                "temperature": temperature,
                "minutes": minutes,
            },
            blocking=True,
        )
    mocked.assert_not_awaited()


async def test_prepare_program_rejected(
    hass: HomeAssistant, fryer: VeSyncAirFryerDC111
) -> None:
    """A program the appliance refuses gives a readable error."""
    response = bypass_response()[0]
    response["result"]["code"] = 11011000
    mocked = AsyncMock(return_value=response)
    with (
        patch.object(VeSyncAirFryerDC111, "call_bypassv2_api", new=mocked),
        pytest.raises(HomeAssistantError, match="rejected the program"),
    ):
        await hass.services.async_call(
            "vesync",
            "prepare_air_fryer_program",
            {
                "device_id": _device_id(hass),
                "chamber": 1,
                "temperature": 180,
                "minutes": 15,
            },
            blocking=True,
        )


async def test_mode_and_link_sensors(
    hass: HomeAssistant, fryer: VeSyncAirFryerDC111
) -> None:
    """Mode shows only for a chamber with a program; link maps the sync type."""
    assert hass.states.get(_entity_id(hass, "sensor", "chamber_1_mode")).state == "AirFry"
    assert hass.states.get(_entity_id(hass, "sensor", "chamber_2_mode")).state == "unknown"
    assert hass.states.get(_entity_id(hass, "sensor", "chamber_link")).state == "none"

    fryer.state.sync_type = 2
    coordinator = hass.config_entries.async_entries("vesync")[0].runtime_data
    coordinator.async_set_updated_data(None)
    await hass.async_block_till_done()
    assert hass.states.get(_entity_id(hass, "sensor", "chamber_link")).state == "sync"


async def test_manual_refresh_polls_idle_fryer(
    hass: HomeAssistant, fryer: VeSyncAirFryerDC111
) -> None:
    """A refresh between full updates still reads an idle fryer."""
    coordinator = hass.config_entries.async_entries("vesync")[0].runtime_data
    coordinator.full_update_time = None
    await coordinator.async_refresh()
    fryer.state.chambers[1].cook_status = "standby"

    with patch.object(VeSyncAirFryerDC111, "update", new=AsyncMock()) as update:
        await coordinator.async_refresh()
        update.assert_awaited_once()


async def test_prepare_bake(hass: HomeAssistant, fryer: VeSyncAirFryerDC111) -> None:
    """Modes read from the appliance can be prepared with their recipe ID."""
    mocked = AsyncMock(return_value=bypass_response()[0])
    with (
        patch.object(VeSyncAirFryerDC111, "call_bypassv2_api", new=mocked),
        patch.object(VeSyncAirFryerDC111, "update", new=AsyncMock()),
    ):
        await hass.services.async_call(
            "vesync",
            "prepare_air_fryer_program",
            {
                "device_id": _device_id(hass),
                "chamber": 1,
                "temperature": 165,
                "minutes": 20,
                "mode": "Bake",
            },
            blocking=True,
        )
    config = mocked.await_args.kwargs["data"]["cookConfigs"][0]
    assert (config["mode"], config["recipeId"]) == ("Bake", 9)


async def test_prepare_program_whole_degrees_and_other_modes(
    hass: HomeAssistant, fryer: VeSyncAirFryerDC111
) -> None:
    """Every whole degree inside the limits goes through; limits differ per mode."""
    mocked = AsyncMock(return_value=bypass_response()[0])
    with (
        patch.object(VeSyncAirFryerDC111, "call_bypassv2_api", new=mocked),
        patch.object(VeSyncAirFryerDC111, "update", new=AsyncMock()),
    ):
        await hass.services.async_call(
            "vesync",
            "prepare_air_fryer_program",
            {
                "device_id": _device_id(hass),
                "chamber": 1,
                "temperature": 183,
                "minutes": 7,
                "mode": "AirFry",
            },
            blocking=True,
        )
        await hass.services.async_call(
            "vesync",
            "prepare_air_fryer_program",
            {
                "device_id": _device_id(hass),
                "chamber": 2,
                "temperature": 33,
                "minutes": 720,
                "mode": "Proof",
            },
            blocking=True,
        )
    temps = [c.kwargs["data"]["cookConfigs"][0]["cookTemp"] for c in mocked.await_args_list]
    assert temps == [183, 33]


@pytest.mark.parametrize(
    ("mode", "temperature", "minutes", "message"),
    [
        ("Bake", 79, 20, "Bake takes 80 to 205"),
        ("Bake", 206, 20, "Bake takes 80 to 205"),
        ("Roast", 174, 20, "Roast takes 175 to 230"),
        ("Reheat", 39, 5, "Reheat takes 40 to 205"),
        ("Grill", 159, 10, "Grill takes 160 to 230"),
        ("Dry", 96, 360, "Dry takes 35 to 95"),
        ("Dry", 55, 29, "Dry takes 30 to 1440 minutes"),
        ("Dry", 55, 1441, "Dry takes 30 to 1440 minutes"),
        ("Proof", 46, 60, "Proof takes 30 to 45"),
        ("Proof", 35, 721, "Proof takes 15 to 720 minutes"),
    ],
)
async def test_prepare_program_mode_limits(
    hass: HomeAssistant,
    fryer: VeSyncAirFryerDC111,
    mode: str,
    temperature: int,
    minutes: int,
    message: str,
) -> None:
    """Limits measured on the appliance are checked per mode."""
    mocked = AsyncMock(return_value=bypass_response()[0])
    with (
        patch.object(VeSyncAirFryerDC111, "call_bypassv2_api", new=mocked),
        pytest.raises(ServiceValidationError, match=message),
    ):
        await hass.services.async_call(
            "vesync",
            "prepare_air_fryer_program",
            {
                "device_id": _device_id(hass),
                "chamber": 1,
                "temperature": temperature,
                "minutes": minutes,
                "mode": mode,
            },
            blocking=True,
        )
    mocked.assert_not_awaited()
