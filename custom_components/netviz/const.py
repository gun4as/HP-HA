"""Konstantes."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "netviz"

CONF_MODEL: Final = "model"
CONF_VERSION: Final = "snmp_version"
CONF_COMMUNITY: Final = "community"
CONF_AUTH_PROTOCOL: Final = "auth_protocol"
CONF_AUTH_KEY: Final = "auth_key"
CONF_PRIV_PROTOCOL: Final = "priv_protocol"
CONF_PRIV_KEY: Final = "priv_key"
CONF_ENTITIES: Final = "entities"
CONF_VLANS: Final = "vlans"

DEFAULT_PORT: Final = 161
DEFAULT_SCAN_INTERVAL: Final = 30
DEFAULT_TIMEOUT: Final = 4
DEFAULT_RETRIES: Final = 2

# Metrikas, ko var ieslēgt uz portu. Noklusējums apzināti nav "viss".
METRIC_LINK: Final = "link"
METRIC_SPEED: Final = "speed"
METRIC_RX_RATE: Final = "rx_rate"
METRIC_TX_RATE: Final = "tx_rate"
METRIC_RX_TOTAL: Final = "rx_total"
METRIC_TX_TOTAL: Final = "tx_total"
METRIC_POE_POWER: Final = "poe_power"
METRIC_POE_STATUS: Final = "poe_status"
METRIC_PVID: Final = "pvid"
METRIC_ALIAS: Final = "alias"

ALL_METRICS: Final = [
    METRIC_LINK,
    METRIC_SPEED,
    METRIC_RX_RATE,
    METRIC_TX_RATE,
    METRIC_RX_TOTAL,
    METRIC_TX_TOTAL,
    METRIC_POE_POWER,
    METRIC_POE_STATUS,
    METRIC_PVID,
    METRIC_ALIAS,
]

DEFAULT_METRICS: Final = [
    METRIC_LINK,
    METRIC_SPEED,
    METRIC_RX_RATE,
    METRIC_TX_RATE,
    METRIC_POE_POWER,
    METRIC_POE_STATUS,
]

# Metrikas, kas ir jēdzīgas tikai PoE portiem
POE_METRICS: Final = {METRIC_POE_POWER, METRIC_POE_STATUS}

SNMP_VERSIONS: Final = ["1", "2c", "3"]
AUTH_PROTOCOL_OPTIONS: Final = ["sha", "md5"]
PRIV_PROTOCOL_OPTIONS: Final = ["aes", "aes192", "aes256", "des"]

CARD_URL: Final = "/netviz/netviz-faceplate-card.js"
CARD_FILENAME: Final = "netviz-faceplate-card.js"
