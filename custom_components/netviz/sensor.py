"""Sensoru platforma."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfDataRate,
    UnitOfInformation,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ENTITIES,
    DEFAULT_METRICS,
    DOMAIN,
    METRIC_ALIAS,
    METRIC_POE_POWER,
    METRIC_POE_STATUS,
    METRIC_PVID,
    METRIC_RX_RATE,
    METRIC_RX_TOTAL,
    METRIC_SPEED,
    METRIC_TX_RATE,
    METRIC_TX_TOTAL,
    POE_METRICS,
)
from .coordinator import NetvizConfigEntry, NetvizCoordinator
from .entity import NetvizEntity, NetvizPortEntity
from .model import faceplate_geometry


@dataclass(frozen=True, kw_only=True)
class NetvizSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict], object]


PORT_SENSORS: dict[str, NetvizSensorDescription] = {
    METRIC_SPEED: NetvizSensorDescription(
        key=METRIC_SPEED,
        translation_key="port_speed",
        native_unit_of_measurement="Mbit/s",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:speedometer",
        value_fn=lambda p: p.get("speed") if p.get("link") else 0,
    ),
    METRIC_RX_RATE: NetvizSensorDescription(
        key=METRIC_RX_RATE,
        translation_key="port_rx_rate",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda p: (
            round(p["rx_bps"] / 1_000_000, 3) if p.get("rx_bps") is not None else None
        ),
    ),
    METRIC_TX_RATE: NetvizSensorDescription(
        key=METRIC_TX_RATE,
        translation_key="port_tx_rate",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda p: (
            round(p["tx_bps"] / 1_000_000, 3) if p.get("tx_bps") is not None else None
        ),
    ),
    METRIC_RX_TOTAL: NetvizSensorDescription(
        key=METRIC_RX_TOTAL,
        translation_key="port_rx_total",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p: p.get("rx_bytes"),
    ),
    METRIC_TX_TOTAL: NetvizSensorDescription(
        key=METRIC_TX_TOTAL,
        translation_key="port_tx_total",
        device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        suggested_unit_of_measurement=UnitOfInformation.GIGABYTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p: p.get("tx_bytes"),
    ),
    METRIC_POE_POWER: NetvizSensorDescription(
        key=METRIC_POE_POWER,
        translation_key="port_poe_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda p: p.get("poe_power"),
    ),
    METRIC_POE_STATUS: NetvizSensorDescription(
        key=METRIC_POE_STATUS,
        translation_key="port_poe_status",
        device_class=SensorDeviceClass.ENUM,
        options=[
            "disabled",
            "searching",
            "delivering",
            "fault",
            "test",
            "other_fault",
            "unknown",
        ],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p: p.get("poe_status", "unknown"),
    ),
    METRIC_PVID: NetvizSensorDescription(
        key=METRIC_PVID,
        translation_key="port_pvid",
        icon="mdi:tag-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p: p.get("pvid"),
    ),
    METRIC_ALIAS: NetvizSensorDescription(
        key=METRIC_ALIAS,
        translation_key="port_alias",
        icon="mdi:tag-text-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p: p.get("alias") or None,
    ),
}

SYSTEM_SENSORS: tuple[NetvizSensorDescription, ...] = (
    NetvizSensorDescription(
        key="cpu",
        translation_key="cpu",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cpu-32-bit",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.get("cpu"),
    ),
    NetvizSensorDescription(
        key="uptime",
        translation_key="uptime",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.DAYS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.get("uptime"),
    ),
    NetvizSensorDescription(
        key="poe_used",
        translation_key="poe_used",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: s.get("poe_used"),
    ),
    NetvizSensorDescription(
        key="poe_budget",
        translation_key="poe_budget",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.get("poe_budget"),
    ),
    NetvizSensorDescription(
        key="ports_up",
        translation_key="ports_up",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:lan-connect",
        value_fn=lambda s: s.get("ports_up"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NetvizConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    enabled = entry.options.get(CONF_ENTITIES, DEFAULT_METRICS)

    entities: list[SensorEntity] = [
        NetvizSystemSensor(coordinator, description) for description in SYSTEM_SENSORS
    ]
    entities.append(NetvizFaceplateSensor(coordinator))

    for port_def in coordinator.ports:
        for metric in enabled:
            description = PORT_SENSORS.get(metric)
            if description is None:
                continue
            if metric in POE_METRICS and not port_def.get("poe"):
                continue
            entities.append(NetvizPortSensor(coordinator, port_def, description))

    async_add_entities(entities)


class NetvizPortSensor(NetvizPortEntity, SensorEntity):
    entity_description: NetvizSensorDescription

    def __init__(
        self,
        coordinator: NetvizCoordinator,
        port_def: dict,
        description: NetvizSensorDescription,
    ) -> None:
        super().__init__(coordinator, port_def, description.key)
        self.entity_description = description
        self._attr_translation_placeholders = {
            "port": str(port_def.get("label", port_def["id"]))
        }

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.port)


class NetvizSystemSensor(NetvizEntity, SensorEntity):
    entity_description: NetvizSensorDescription

    def __init__(
        self, coordinator: NetvizCoordinator, description: NetvizSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.system)


class NetvizFaceplateSensor(NetvizEntity, SensorEntity):
    """Nes faceplate ģeometriju atribūtos, lai kartei nav jāzina par failiem.

    Vērtība ir statiska, tāpēc recorder to saglabā vienreiz, nevis katrā ciklā.
    """

    _attr_translation_key = "faceplate"
    _attr_icon = "mdi:server-network"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator: NetvizCoordinator) -> None:
        super().__init__(coordinator, "faceplate")
        self._geometry = faceplate_geometry(coordinator.model)

    @property
    def native_value(self) -> str:
        return str(self._geometry.get("model") or "unknown")

    @property
    def extra_state_attributes(self) -> dict:
        return self._geometry
