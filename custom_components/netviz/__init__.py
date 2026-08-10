"""netviz - pārvaldāmu switch'u vizualizācija Home Assistant."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.const import CONF_HOST, CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .config_flow import _credentials
from .const import CARD_FILENAME, CARD_URL, CONF_MODEL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import NetvizConfigEntry, NetvizCoordinator
from .model import ModelNotFound, load_model
from .snmp import SnmpClient, SnmpConnectionError

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


def _card_mtime(path: Path) -> int | None:
    """Kartes faila mtime, vai None, ja faila nav. Blokējošs - izpildītājam."""
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


async def _register_card(hass: HomeAssistant) -> None:
    """Pasniedz faceplate karti no integrācijas mapes.

    Tā kartei nav jāiet caur HACS atsevišķi un lietotājam nav jāpievieno
    resurss ar roku - kļūda, uz kuras uzkāpj puse custom karšu.
    """
    if hass.data.get(f"{DOMAIN}_card_registered"):
        return
    path = Path(__file__).parent / "www" / CARD_FILENAME
    # stat() un is_file() ir blokējoši izsaukumi - vienā gājumā izpildītājā
    mtime = await hass.async_add_executor_job(_card_mtime, path)
    if mtime is None:
        _LOGGER.warning("kartes fails nav atrasts: %s", path)
        return
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(path), cache_headers=False)]
    )
    if "frontend" in hass.config.components:
        from homeassistant.components.frontend import add_extra_js_url

        add_extra_js_url(hass, f"{CARD_URL}?v={mtime}")
    hass.data[f"{DOMAIN}_card_registered"] = True


async def _reconcile_identity(
    hass: HomeAssistant, entry: NetvizConfigEntry, client: SnmpClient
) -> None:
    """Pārliek unique_id no adreses uz seriālnumuru, ja tas vēl nav noticis.

    Līdz 0.2.0 seriālnumurs tika prasīts kā `entPhysicalSerialNum.1`, bet AOS-S
    šasija ir indeksā 1001, tāpēc atbilde bija NoSuchInstance un unique_id
    atkāpās uz host:port. Ierakstiem, kas izveidoti ar veco kodu, to var
    izlabot klusi - tas ir daudz labāk, nekā likt dzēst integrāciju un
    pievienot no jauna, zaudējot entītiju ID un vēsturi.
    """
    if entry.data.get("serial"):
        return
    try:
        info = await client.probe()
    except SnmpConnectionError:
        return
    if not (serial := info.get("serial")) or entry.unique_id == serial:
        return
    # Ja kāds jau ir pievienojis to pašu switch'u otrreiz, divi ieraksti ar
    # vienu unique_id nav pieļaujami - labāk atstājam kā ir un pasakām.
    if any(
        other.unique_id == serial
        for other in hass.config_entries.async_entries(DOMAIN)
        if other.entry_id != entry.entry_id
    ):
        _LOGGER.warning(
            "seriālnumurs %s jau pieder citam ierakstam, unique_id atstāts kā %s",
            serial,
            entry.unique_id,
        )
        return
    _LOGGER.info(
        "unique_id pārlikts no %s uz seriālnumuru %s", entry.unique_id, serial
    )
    hass.config_entries.async_update_entry(
        entry, unique_id=serial, data={**entry.data, "serial": serial}
    )


async def async_setup_entry(hass: HomeAssistant, entry: NetvizConfigEntry) -> bool:
    try:
        # load_model atver failu - izpildītājā, citādi HA met brīdinājumu par
        # blokējošu I/O event loop'ā
        model = await hass.async_add_executor_job(load_model, entry.data[CONF_MODEL])
    except ModelNotFound as err:
        _LOGGER.error("modelis nav atrasts: %s", err)
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

    # Pirms platformu ielādes, lai entītijas uzreiz dabū pareizo serial_number.
    # Un pirms update listener reģistrācijas, lai async_update_entry neizraisītu
    # pārlādi tieši setup vidū.
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
