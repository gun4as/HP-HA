"""Binārie sensori - porta link stāvoklis."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_ENTITIES, DEFAULT_METRICS, METRIC_LINK
from .coordinator import NetvizConfigEntry, NetvizCoordinator
from .entity import NetvizPortEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NetvizConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    enabled = entry.options.get(CONF_ENTITIES, DEFAULT_METRICS)
    if METRIC_LINK not in enabled:
        return
    async_add_entities(
        NetvizPortLink(coordinator, port_def) for port_def in coordinator.ports
    )


class NetvizPortLink(NetvizPortEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "port_link"

    def __init__(self, coordinator: NetvizCoordinator, port_def: dict) -> None:
        super().__init__(coordinator, port_def, METRIC_LINK)
        self._attr_translation_placeholders = {
            "port": str(port_def.get("label", port_def["id"]))
        }

    @property
    def is_on(self) -> bool | None:
        port = self.port
        if not port:
            return None
        return bool(port.get("link"))
