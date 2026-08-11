"""Shared entity base."""

from __future__ import annotations

import re

from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_PROTOCOL, DEFAULT_PROTOCOL, DOMAIN
from .coordinator import NetvizCoordinator

# AOS-S sysDescr:
#   Aruba JL357A 2540-48G-PoE+-4SFP+ Switch, revision YC.16.11.0029, ROM ... (...)
# The `revision` field is the one we want. `split(",")[-1]` would pick up the ROM
# version together with the build path, truncated mid-word.
_RE_REVISION = re.compile(r"revision\s+([A-Za-z0-9._-]+)", re.IGNORECASE)
_RE_VERSIONISH = re.compile(r"\b([A-Za-z]{0,3}\.?\d+\.\d+[.\d]*)\b")


def sw_version_from_descr(descr: str | None) -> str | None:
    """Firmware version from sysDescr, or None if the format is unrecognised."""
    if not descr:
        return None
    if match := _RE_REVISION.search(descr):
        return match.group(1).rstrip(".,")
    # Different vendor or different format: take the first thing that looks like
    # a version. None beats putting a model name or a file path on the device page.
    if match := _RE_VERSIONISH.search(descr):
        return match.group(1)
    return None


class NetvizEntity(CoordinatorEntity[NetvizCoordinator]):
    """Base for every netviz entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NetvizCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        model = coordinator.model
        system = coordinator.system
        # The scheme is a choice, not an assumption: the AOS-S web UI is often
        # plain http with no certificate, and the wrong scheme turns the
        # "Visit device" link into a dead end.
        protocol = entry.options.get(
            CONF_PROTOCOL, entry.data.get(CONF_PROTOCOL, DEFAULT_PROTOCOL)
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=model.get("vendor"),
            model=model.get("display", model.get("model")),
            sw_version=sw_version_from_descr(system.get("descr")),
            configuration_url=f"{protocol}://{entry.data[CONF_HOST]}",
            serial_number=entry.data.get("serial"),
        )


class NetvizPortEntity(NetvizEntity):
    """An entity bound to one specific port.

    The `port` and `metric` attributes are how the faceplate card collects
    entities together, so it does not depend on any entity_id naming scheme.
    """

    def __init__(
        self,
        coordinator: NetvizCoordinator,
        port_def: dict,
        metric: str,
    ) -> None:
        self._port_id = str(port_def["id"])
        self._port_def = port_def
        self._metric = metric
        super().__init__(coordinator, f"p{self._port_id}_{metric}")

    @property
    def port(self) -> dict:
        return self.coordinator.port_data(self._port_id)

    @property
    def available(self) -> bool:
        return super().available and bool(self.port)

    @property
    def extra_state_attributes(self) -> dict:
        attrs = {
            "port": self._port_id,
            "metric": self._metric,
            "kind": self._port_def.get("kind", "rj45"),
        }
        if self._metric == "link":
            port = self.port
            attrs["ifindex"] = port.get("ifindex")
            attrs["description"] = port.get("alias")
            attrs["admin_up"] = port.get("admin_up")
            if port.get("vlans"):
                attrs["vlans"] = port["vlans"]
                attrs["mode"] = port.get("mode")
        return attrs
