"""Konfigurācijas plūsma."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    ALL_METRICS,
    AUTH_PROTOCOL_OPTIONS,
    CONF_AUTH_KEY,
    CONF_AUTH_PROTOCOL,
    CONF_COMMUNITY,
    CONF_ENTITIES,
    CONF_MODEL,
    CONF_PRIV_KEY,
    CONF_PRIV_PROTOCOL,
    CONF_VERSION,
    CONF_VLANS,
    DEFAULT_METRICS,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PRIV_PROTOCOL_OPTIONS,
    SNMP_VERSIONS,
)
from .model import available_models
from .snmp import SnmpClient, SnmpConnectionError, SnmpCredentials

_LOGGER = logging.getLogger(__name__)


def _credentials(data: dict[str, Any]) -> SnmpCredentials:
    return SnmpCredentials(
        host=data[CONF_HOST],
        port=data.get(CONF_PORT, DEFAULT_PORT),
        version=data.get(CONF_VERSION, "2c"),
        community=data.get(CONF_COMMUNITY, "public"),
        username=data.get(CONF_USERNAME),
        auth_protocol=data.get(CONF_AUTH_PROTOCOL, "sha"),
        auth_key=data.get(CONF_AUTH_KEY),
        priv_protocol=data.get(CONF_PRIV_PROTOCOL, "aes"),
        priv_key=data.get(CONF_PRIV_KEY),
    )


async def _validate(data: dict[str, Any]) -> dict[str, str | None]:
    client = SnmpClient(_credentials(data))
    try:
        return await client.probe()
    finally:
        client.close()


class NetvizConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        models = available_models()

        if user_input is not None:
            self._data = dict(user_input)
            if user_input.get(CONF_VERSION) == "3":
                return await self.async_step_v3()
            return await self._finish(errors)

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): TextSelector(),
                vol.Required(CONF_MODEL): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            {"value": slug, "label": label}
                            for slug, label in models.items()
                        ],
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_VERSION, default="2c"): SelectSelector(
                    SelectSelectorConfig(
                        options=SNMP_VERSIONS, mode=SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Optional(CONF_COMMUNITY, default="public"): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): NumberSelector(
                    NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_v3(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data.update(user_input)
            self._data.pop(CONF_COMMUNITY, None)
            return await self._finish(errors)

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): TextSelector(),
                vol.Required(CONF_AUTH_PROTOCOL, default="sha"): SelectSelector(
                    SelectSelectorConfig(
                        options=AUTH_PROTOCOL_OPTIONS, mode=SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Required(CONF_AUTH_KEY): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
                vol.Required(CONF_PRIV_PROTOCOL, default="aes"): SelectSelector(
                    SelectSelectorConfig(
                        options=PRIV_PROTOCOL_OPTIONS, mode=SelectSelectorMode.DROPDOWN
                    )
                ),
                vol.Required(CONF_PRIV_KEY): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(step_id="v3", data_schema=schema, errors=errors)

    async def _finish(self, errors: dict[str, str]) -> ConfigFlowResult:
        self._data[CONF_PORT] = int(self._data.get(CONF_PORT, DEFAULT_PORT))
        try:
            info = await _validate(self._data)
        except SnmpConnectionError as err:
            _LOGGER.debug("validācija neizdevās: %s", err)
            errors["base"] = "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("negaidīta kļūda validācijā")
            errors["base"] = "unknown"

        if errors:
            step = "v3" if self._data.get(CONF_VERSION) == "3" else "user"
            return self.async_show_form(step_id=step, errors=errors)

        unique = info.get("serial") or f"{self._data[CONF_HOST]}:{self._data[CONF_PORT]}"
        await self.async_set_unique_id(unique)
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._data[CONF_HOST]})

        title = info.get("name") or self._data[CONF_HOST]
        self._data["serial"] = info.get("serial")
        return self.async_create_entry(
            title=title,
            data=self._data,
            options={
                CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                CONF_ENTITIES: DEFAULT_METRICS,
                CONF_VLANS: True,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return NetvizOptionsFlow()


class NetvizOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            user_input[CONF_SCAN_INTERVAL] = int(user_input[CONF_SCAN_INTERVAL])
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(min=10, max=600, mode=NumberSelectorMode.BOX)
                ),
                vol.Required(
                    CONF_ENTITIES,
                    default=options.get(CONF_ENTITIES, DEFAULT_METRICS),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=ALL_METRICS,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Required(
                    CONF_VLANS, default=options.get(CONF_VLANS, True)
                ): bool,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
