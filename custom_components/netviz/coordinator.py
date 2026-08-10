"""Aptaujas koordinators."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_VLANS, DEFAULT_SCAN_INTERVAL, DOMAIN
from .snmp import SnmpClient, SnmpConnectionError

_LOGGER = logging.getLogger(__name__)

type NetvizConfigEntry = ConfigEntry[NetvizCoordinator]


class NetvizCoordinator(DataUpdateCoordinator[dict]):
    """Aptaujā vienu switch'u un tur pēdējo momentuzņēmumu."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: SnmpClient,
        model: dict,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.data.get('host')}",
            update_interval=timedelta(seconds=scan_interval),
            config_entry=entry,
        )
        self.client = client
        self.model = model
        self.ports = model["ports"]
        self._with_vlans = entry.options.get(CONF_VLANS, True)

    async def _async_update_data(self) -> dict:
        try:
            return await self.client.poll(self.ports, with_vlans=self._with_vlans)
        except SnmpConnectionError as err:
            raise UpdateFailed(f"SNMP: {err}") from err
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"negaidīta kļūda: {err}") from err

    def port_data(self, port_id: str) -> dict:
        if not self.data:
            return {}
        return self.data.get("ports", {}).get(port_id, {})

    @property
    def system(self) -> dict:
        if not self.data:
            return {}
        return self.data.get("system", {})
