"""netviz - managed network switch visualisation for Home Assistant."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .config_flow import _credentials
from .const import (
    CARD_FILENAME,
    CARD_URL,
    CONF_MODEL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MODEL_AUTO,
)
from .coordinator import NetvizConfigEntry, NetvizCoordinator
from .model import ModelNotFound, load_model
from .snmp import SnmpClient, SnmpConnectionError

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


def _card_mtime(path: Path) -> int | None:
    """mtime of the card file, or None if absent. Blocking - for the executor."""
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


async def _register_card(hass: HomeAssistant) -> None:
    """Serve the faceplate card straight out of the integration directory.

    That way the card does not need its own HACS entry, and the user does not
    have to add a Lovelace resource by hand - the step half of all custom cards
    trip over.
    """
    if hass.data.get(f"{DOMAIN}_card_registered"):
        return
    path = Path(__file__).parent / "www" / CARD_FILENAME
    # stat() and is_file() both block - do it in one trip to the executor
    mtime = await hass.async_add_executor_job(_card_mtime, path)
    if mtime is None:
        _LOGGER.warning(
            "card file not found: %s - the faceplate card will be unavailable", path
        )
        return
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(path), cache_headers=False)]
    )
    # `frontend` is a manifest.json dependency, so it is already loaded here.
    # It used to be an after_dependency guarded by `if "frontend" in components`
    # - when that condition did not hold, the file was reachable but the script
    # was never injected into the dashboard, with nothing in the log. The card
    # then failed with "Custom element doesn't exist".
    try:
        from homeassistant.components.frontend import add_extra_js_url

        add_extra_js_url(hass, f"{CARD_URL}?v={mtime}")
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "could not hand the card JS to the frontend; it can be added by hand "
            "as a Lovelace resource pointing at %s",
            CARD_URL,
        )
        return
    _LOGGER.info("faceplate card registered: %s?v=%s", CARD_URL, mtime)
    hass.data[f"{DOMAIN}_card_registered"] = True


async def _reconcile_identity(
    hass: HomeAssistant, entry: NetvizConfigEntry, client: SnmpClient
) -> None:
    """Move unique_id off the address and onto the serial number, if not done yet.

    Up to 0.2.0 the serial was requested as `entPhysicalSerialNum.1`, but on
    AOS-S the chassis sits at index 1001, so the answer was NoSuchInstance and
    unique_id fell back to host:port. For entries created by that older code we
    can fix this quietly, which beats asking the user to delete and re-add the
    integration and lose their entity IDs and history.
    """
    if entry.data.get("serial"):
        return
    try:
        info = await client.probe()
    except SnmpConnectionError:
        return
    if not (serial := info.get("serial")) or entry.unique_id == serial:
        return
    # If someone has already added the same switch twice, two entries cannot
    # share one unique_id - leave it alone and say so.
    if any(
        other.unique_id == serial
        for other in hass.config_entries.async_entries(DOMAIN)
        if other.entry_id != entry.entry_id
    ):
        _LOGGER.warning(
            "serial number %s already belongs to another entry, unique_id left as %s",
            serial,
            entry.unique_id,
        )
        return
    _LOGGER.info(
        "unique_id moved from %s to serial number %s", entry.unique_id, serial
    )
    hass.config_entries.async_update_entry(
        entry, unique_id=serial, data={**entry.data, "serial": serial}
    )


async def async_setup_entry(hass: HomeAssistant, entry: NetvizConfigEntry) -> bool:
    slug = entry.data.get(CONF_MODEL)
    model = None
    if slug and slug != MODEL_AUTO:
        try:
            # load_model opens a file - to the executor, otherwise HA complains
            # about blocking I/O in the event loop
            model = await hass.async_add_executor_job(load_model, slug)
        except ModelNotFound as err:
            _LOGGER.error("model not found: %s", err)
            return False

    client = SnmpClient(_credentials(dict(entry.data)))
    scan_interval = int(entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    coordinator = NetvizCoordinator(hass, entry, client, model, scan_interval)

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        client.close()
        raise
    except SnmpConnectionError as err:
        client.close()
        raise ConfigEntryNotReady(f"{entry.data[CONF_HOST]}: {err}") from err

    # Before the platforms load, so entities pick up the right serial_number
    # straight away. And before the update listener is registered, so that
    # async_update_entry does not trigger a reload in the middle of setup.
    await _reconcile_identity(hass, entry, client)

    entry.runtime_data = coordinator
    await _register_card(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NetvizConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and (coordinator := getattr(entry, "runtime_data", None)):
        coordinator.client.close()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: NetvizConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
