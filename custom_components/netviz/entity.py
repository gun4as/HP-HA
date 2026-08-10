"""Kopīgā entītiju bāze."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NetvizCoordinator


class NetvizEntity(CoordinatorEntity[NetvizCoordinator]):
    """Bāze visām netviz entītijām."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NetvizCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        model = coordinator.model
        system = coordinator.system
        sw_version = None
        if descr := system.get("descr"):
            sw_version = descr.split(",")[-1].strip()[:64]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=model.get("vendor"),
            model=model.get("display", model.get("model")),
            sw_version=sw_version,
            configuration_url=f"https://{entry.data['host']}",
            serial_number=entry.data.get("serial"),
        )


class NetvizPortEntity(NetvizEntity):
    """Entītija, kas piesaistīta konkrētam portam.

    `port` un `metric` atribūti ir tas, pēc kā faceplate karte savāc entītijas
    kopā - tā nav atkarīga no entity_id nosaukumu shēmas.
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
