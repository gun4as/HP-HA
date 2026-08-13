"""Config flow."""

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
    CONF_PROTOCOL,
    CONF_VERSION,
    CONF_VLANS,
    DEFAULT_METRICS,
    DEFAULT_PORT,
    DEFAULT_PROTOCOL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MODEL_AUTO,
    PRIV_PROTOCOL_OPTIONS,
    PROTOCOL_OPTIONS,
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


async def _probe(data: dict[str, Any]) -> dict[str, str | None]:
    client = SnmpClient(_credentials(data))
    try:
        return await client.probe()
    finally:
        client.close()


def _v3_schema() -> vol.Schema:
    return vol.Schema(
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


class NetvizConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._models: dict[str, str] | None = None

    async def _available_models(self) -> dict[str, str]:
        """The list of models on disk.

        Goes through the executor: `available_models` opens files, and HA detects
        blocking I/O in the event loop and logs a warning with a stack trace.
        """
        if self._models is None:
            self._models = await self.hass.async_add_executor_job(available_models)
        return self._models

    def _user_schema(self, models: dict[str, str]) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_HOST): TextSelector(),
                # A model file only adds faceplate geometry. Ports themselves
                # come from the device, so requiring one would mean nobody
                # could add hardware until someone had drawn it.
                vol.Required(CONF_MODEL, default=MODEL_AUTO): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            {
                                "value": MODEL_AUTO,
                                "label": "Detect ports automatically",
                            },
                            *(
                                {"value": slug, "label": label}
                                for slug, label in models.items()
                            ),
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
                vol.Optional(CONF_PROTOCOL, default=DEFAULT_PROTOCOL): SelectSelector(
                    SelectSelectorConfig(
                        options=PROTOCOL_OPTIONS, mode=SelectSelectorMode.DROPDOWN
                    )
                ),
            }
        )

    async def _show(
        self, step_id: str, schema: vol.Schema, errors: dict[str, str]
    ) -> ConfigFlowResult:
        """Show the form, keeping whatever the user already typed.

        Without `data_schema` HA renders a form with no fields at all, and the
        next submit arrives as an empty dict - the user is stuck.
        """
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, self._data),
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data = dict(user_input)
            if user_input.get(CONF_VERSION) == "3":
                return await self.async_step_v3()
            info, errors = await self._validate()
            if not errors:
                return await self._create(info)
        models = await self._available_models()
        return await self._show("user", self._user_schema(models), errors)

    async def async_step_v3(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data.update(user_input)
            self._data.pop(CONF_COMMUNITY, None)
            info, errors = await self._validate()
            if not errors:
                return await self._create(info)
        return await self._show("v3", _v3_schema(), errors)

    async def _validate(self) -> tuple[dict[str, str | None], dict[str, str]]:
        self._data[CONF_PORT] = int(self._data.get(CONF_PORT, DEFAULT_PORT))
        try:
            return await _probe(self._data), {}
        except SnmpConnectionError as err:
            _LOGGER.debug("validation failed: %s", err)
            return {}, {"base": "cannot_connect"}
        except Exception:  # noqa: BLE001
            _LOGGER.exception("unexpected error during validation")
            return {}, {"base": "unknown"}

    async def _create(self, info: dict[str, str | None]) -> ConfigFlowResult:
        # The serial number is stable; the address is not. Falling back to
        # host:port is reserved for devices that do not answer
        # entPhysicalSerialNum at all.
        serial = info.get("serial")
        unique = serial or f"{self._data[CONF_HOST]}:{self._data[CONF_PORT]}"
        if not serial:
            _LOGGER.warning(
                "%s: no serial number could be read, unique_id will be the address - "
                "if the switch address changes, HA will treat it as a new device",
                self._data[CONF_HOST],
            )
        await self.async_set_unique_id(unique)
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._data[CONF_HOST]})

        self._data["serial"] = serial
        self._data["profile"] = info.get("profile")
        return self.async_create_entry(
            title=info.get("name") or self._data[CONF_HOST],
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
                vol.Required(
                    CONF_PROTOCOL,
                    default=options.get(
                        CONF_PROTOCOL,
                        self.config_entry.data.get(CONF_PROTOCOL, DEFAULT_PROTOCOL),
                    ),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=PROTOCOL_OPTIONS, mode=SelectSelectorMode.DROPDOWN
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
