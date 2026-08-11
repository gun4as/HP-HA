"""Shared entity base."""

from __future__ import annotations

from homeassistant.const import CONF_HOST
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_PROTOCOL, DEFAULT_PROTOCOL, DOMAIN
from .coordinator import NetvizCoordinator

# The sysDescr parser lives in snmp.py: it is a pure function over SNMP data, and
# that module is the one that can be imported and tested without Home Assistant.
from .snmp import sw_version_from_descr


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
