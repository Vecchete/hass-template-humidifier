"""Support for Template humidifiers."""

import logging

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.humidifier import (
    DEVICE_CLASSES_SCHEMA,
    DOMAIN as HUMIDIFIER_DOMAIN,
    ENTITY_ID_FORMAT,
    HumidifierAction,
    HumidifierEntity,
    HumidifierEntityFeature,
)
from homeassistant.components.humidifier.const import (
    ATTR_ACTION,
    ATTR_CURRENT_HUMIDITY,
    ATTR_HUMIDITY,
    ATTR_MAX_HUMIDITY,
    ATTR_MIN_HUMIDITY,
    DEFAULT_MAX_HUMIDITY,
    DEFAULT_MIN_HUMIDITY,
)
from homeassistant.components.template.const import CONF_AVAILABILITY_TEMPLATE
from homeassistant.components.template.helpers import (
    async_create_template_tracking_entities,
)

try:
    from homeassistant.components.template.helpers import validate_template_scripts
except ImportError:
    validate_template_scripts = None

try:
    from homeassistant.components.template.schemas import (
        make_template_entity_common_schema,
    )
except ImportError:
    from homeassistant.components.template.schemas import (
        make_template_entity_base_schema as make_template_entity_common_schema,
    )
from homeassistant.components.template.template_entity import TemplateEntity
from homeassistant.const import (
    ATTR_MODE,
    CONF_DEVICE_CLASS,
    CONF_ENTITY_PICTURE_TEMPLATE,
    CONF_ICON_TEMPLATE,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.reload import async_setup_reload_service
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.script import Script
from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

CONF_ACTION_TEMPLATE = "action_template"
CONF_CURRENT_HUMIDITY_TEMPLATE = "current_humidity_template"
CONF_MAX_HUMIDITY = "max_humidity"
CONF_MAX_HUMIDITY_TEMPLATE = "max_humidity_template"
CONF_MIN_HUMIDITY = "min_humidity"
CONF_MIN_HUMIDITY_TEMPLATE = "min_humidity_template"
CONF_MODE_LIST = "modes"
CONF_MODE_TEMPLATE = "mode_template"
CONF_SET_HUMIDITY_ACTION = "set_humidity"
CONF_SET_MODE_ACTION = "set_mode"
CONF_STATE_TEMPLATE = "state_template"
CONF_TARGET_HUMIDITY_STEP = "target_humidity_step"
CONF_TARGET_HUMIDITY_TEMPLATE = "target_humidity_template"
CONF_TURN_OFF_ACTION = "turn_off"
CONF_TURN_ON_ACTION = "turn_on"
SCRIPT_OPTIONS = (
    CONF_TURN_ON_ACTION,
    CONF_TURN_OFF_ACTION,
    CONF_SET_HUMIDITY_ACTION,
    CONF_SET_MODE_ACTION,
)

DEFAULT_NAME = "Template Humidifier"
DEFAULT_TARGET_HUMIDITY = 50
DEFAULT_TARGET_HUMIDITY_STEP = 1.0
DOMAIN = "humidifier_template"
PLATFORMS = [HUMIDIFIER_DOMAIN]

# Actions this platform accepts beyond HumidifierAction. A physical dehumidifier can be neither
# drying nor idle: a full tank or a reported fault stops it while it is still switched on, and the
# core enum has no member for that. Values here are passed through to the state attribute and
# translated from this integration's own translations/en.json, which the frontend consults first
# (component.<platform>.entity.<domain>.<translation_key>.state_attributes.action.state.<value>).
EXTENDED_ACTIONS = frozenset({"error"})

# Set so the frontend looks up action values in this integration's translations. Without it the
# lookup falls through to core's humidifier namespace, which knows nothing of the values above and
# renders them raw and lowercase.
TRANSLATION_KEY = "template_humidifier"


def _humidity(value):
    """Validate a humidity value."""
    return vol.All(vol.Coerce(float), vol.Range(min=0, max=100))(value)


def _integration_version() -> str:
    """Read this integration's version, used to cache-bust the frontend module."""
    try:
        import json
        import os

        manifest = os.path.join(os.path.dirname(__file__), "manifest.json")
        with open(manifest, encoding="utf-8") as file:
            return str(json.load(file).get("version", "0"))
    except Exception:  # noqa: BLE001 - a missing version only costs cache-busting
        return "0"


PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA.extend(
    make_template_entity_common_schema(HUMIDIFIER_DOMAIN, DEFAULT_NAME).schema
).extend(
    {
        vol.Optional(CONF_AVAILABILITY_TEMPLATE): cv.template,
        vol.Optional(CONF_ICON_TEMPLATE): cv.template,
        vol.Optional(CONF_ENTITY_PICTURE_TEMPLATE): cv.template,
        vol.Optional(CONF_DEVICE_CLASS): DEVICE_CLASSES_SCHEMA,
        vol.Optional(CONF_STATE_TEMPLATE): cv.template,
        vol.Optional(CONF_CURRENT_HUMIDITY_TEMPLATE): cv.template,
        vol.Optional(CONF_MIN_HUMIDITY_TEMPLATE): cv.template,
        vol.Optional(CONF_MAX_HUMIDITY_TEMPLATE): cv.template,
        vol.Optional(CONF_TARGET_HUMIDITY_TEMPLATE): cv.template,
        vol.Optional(CONF_MODE_TEMPLATE): cv.template,
        vol.Optional(CONF_ACTION_TEMPLATE): cv.template,
        vol.Optional(CONF_TURN_ON_ACTION): cv.SCRIPT_SCHEMA,
        vol.Optional(CONF_TURN_OFF_ACTION): cv.SCRIPT_SCHEMA,
        vol.Optional(CONF_SET_HUMIDITY_ACTION): cv.SCRIPT_SCHEMA,
        vol.Optional(CONF_SET_MODE_ACTION): cv.SCRIPT_SCHEMA,
        vol.Optional(CONF_MODE_LIST): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(
            CONF_MIN_HUMIDITY, default=DEFAULT_MIN_HUMIDITY
        ): _humidity,
        vol.Optional(
            CONF_MAX_HUMIDITY, default=DEFAULT_MAX_HUMIDITY
        ): _humidity,
        vol.Optional(
            CONF_TARGET_HUMIDITY_STEP, default=DEFAULT_TARGET_HUMIDITY_STEP
        ): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
    }
)


async def async_setup_platform(
    hass: HomeAssistant, config: ConfigType, async_add_entities, discovery_info=None
):
    """Set up the Template Humidifier."""
    # Done here rather than in async_setup, because a platform-only integration has no
    # configuration.yaml key of its own and async_setup is not guaranteed to run.
    from . import async_register_frontend

    await async_register_frontend(hass, _integration_version())

    await async_setup_reload_service(hass, DOMAIN, PLATFORMS)
    if validate_template_scripts is not None:
        await validate_template_scripts(hass, config, SCRIPT_OPTIONS)
    async_create_template_tracking_entities(
        TemplateHumidifier,
        async_add_entities,
        hass,
        [config],
        None,
    )


class TemplateHumidifier(TemplateEntity, HumidifierEntity, RestoreEntity):
    """A template humidifier component."""

    _attr_should_poll = False
    _entity_id_format = ENTITY_ID_FORMAT

    def __init__(self, hass: HomeAssistant, config: ConfigType, unique_id: str | None):
        """Initialize the humidifier device."""
        super().__init__(hass, config, unique_id)

        # On the instance, not the class: Entity's metaclass turns every _attr_ name into a
        # property, so a class-level assignment does not reach the entity, and the entity registry
        # records translation_key when the entry is first created.
        self._attr_translation_key = TRANSLATION_KEY

        self._attr_available_modes = config.get(CONF_MODE_LIST)
        self._attr_is_on = False
        self._attr_min_humidity = config[CONF_MIN_HUMIDITY]
        self._attr_max_humidity = config[CONF_MAX_HUMIDITY]
        self._attr_mode = None
        self._attr_target_humidity = DEFAULT_TARGET_HUMIDITY
        self._attr_target_humidity_step = config[CONF_TARGET_HUMIDITY_STEP]

        if device_class := config.get(CONF_DEVICE_CLASS):
            self._attr_device_class = device_class

        self._action_template = config.get(CONF_ACTION_TEMPLATE)
        self._current_humidity_template = config.get(CONF_CURRENT_HUMIDITY_TEMPLATE)
        self._min_humidity_template = config.get(CONF_MIN_HUMIDITY_TEMPLATE)
        self._max_humidity_template = config.get(CONF_MAX_HUMIDITY_TEMPLATE)
        self._mode_template = config.get(CONF_MODE_TEMPLATE)
        self._state_template = config.get(CONF_STATE_TEMPLATE)
        self._target_humidity_template = config.get(CONF_TARGET_HUMIDITY_TEMPLATE)

        self._turn_on_script = None
        if turn_on_action := config.get(CONF_TURN_ON_ACTION):
            self._turn_on_script = Script(
                hass, turn_on_action, self._attr_name, DOMAIN
            )

        self._turn_off_script = None
        if turn_off_action := config.get(CONF_TURN_OFF_ACTION):
            self._turn_off_script = Script(
                hass, turn_off_action, self._attr_name, DOMAIN
            )

        self._set_humidity_script = None
        if set_humidity_action := config.get(CONF_SET_HUMIDITY_ACTION):
            self._set_humidity_script = Script(
                hass, set_humidity_action, self._attr_name, DOMAIN
            )

        self._set_mode_script = None
        if set_mode_action := config.get(CONF_SET_MODE_ACTION):
            self._set_mode_script = Script(
                hass, set_mode_action, self._attr_name, DOMAIN
            )
            if self._attr_available_modes:
                self._attr_supported_features |= HumidifierEntityFeature.MODES

    async def async_added_to_hass(self):
        """Run when entity about to be added."""
        await super().async_added_to_hass()

        previous_state = await self.async_get_last_state()
        if previous_state is None:
            return

        if previous_state.state == STATE_ON:
            self._attr_is_on = True
        elif previous_state.state == STATE_OFF:
            self._attr_is_on = False

        if humidity := previous_state.attributes.get(ATTR_CURRENT_HUMIDITY):
            self._attr_current_humidity = float(humidity)

        if humidity := previous_state.attributes.get(ATTR_HUMIDITY):
            self._attr_target_humidity = float(humidity)

        if humidity := previous_state.attributes.get(ATTR_MIN_HUMIDITY):
            self._attr_min_humidity = float(humidity)

        if humidity := previous_state.attributes.get(ATTR_MAX_HUMIDITY):
            self._attr_max_humidity = float(humidity)

        self._attr_mode = previous_state.attributes.get(ATTR_MODE)

        if action := previous_state.attributes.get(ATTR_ACTION):
            self._attr_action = self._coerce_action(action)

    @callback
    def _async_setup_templates(self) -> None:
        """Set up templates."""
        if self._state_template:
            self.add_template_attribute(
                "_attr_is_on",
                self._state_template,
                None,
                self._update_state,
                none_on_template_error=True,
            )

        if self._current_humidity_template:
            self.add_template_attribute(
                "_attr_current_humidity",
                self._current_humidity_template,
                None,
                self._update_current_humidity,
                none_on_template_error=True,
            )

        if self._min_humidity_template:
            self.add_template_attribute(
                "_attr_min_humidity",
                self._min_humidity_template,
                None,
                self._update_min_humidity,
                none_on_template_error=True,
            )

        if self._max_humidity_template:
            self.add_template_attribute(
                "_attr_max_humidity",
                self._max_humidity_template,
                None,
                self._update_max_humidity,
                none_on_template_error=True,
            )

        if self._target_humidity_template:
            self.add_template_attribute(
                "_attr_target_humidity",
                self._target_humidity_template,
                None,
                self._update_target_humidity,
                none_on_template_error=True,
            )

        if self._mode_template:
            self.add_template_attribute(
                "_attr_mode",
                self._mode_template,
                None,
                self._update_mode,
                none_on_template_error=True,
            )

        if self._action_template:
            self.add_template_attribute(
                "_attr_action",
                self._action_template,
                None,
                self._update_action,
                none_on_template_error=True,
            )

        super()._async_setup_templates()

    @callback
    def _update_state(self, state):
        if state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return

        try:
            is_on = cv.boolean(state)
        except vol.Invalid:
            _LOGGER.error("Could not parse humidifier state from %s", state)
            return

        if self._attr_is_on != is_on:
            self._attr_is_on = is_on
            self.async_write_ha_state()

    @callback
    def _update_current_humidity(self, humidity):
        if humidity not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            try:
                self._attr_current_humidity = float(humidity)
            except ValueError:
                _LOGGER.error("Could not parse current humidity from %s", humidity)

    @callback
    def _update_min_humidity(self, humidity):
        if humidity not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            try:
                self._attr_min_humidity = float(humidity)
            except ValueError:
                _LOGGER.error("Could not parse min humidity from %s", humidity)

    @callback
    def _update_max_humidity(self, humidity):
        if humidity not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            try:
                self._attr_max_humidity = float(humidity)
            except ValueError:
                _LOGGER.error("Could not parse max humidity from %s", humidity)

    @callback
    def _update_target_humidity(self, humidity):
        if humidity not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            try:
                new_humidity = float(humidity)
                if new_humidity != self._attr_target_humidity:
                    self._attr_target_humidity = new_humidity
                    self.async_write_ha_state()
            except ValueError:
                _LOGGER.error("Could not parse target humidity from %s", humidity)

    @callback
    def _update_mode(self, mode):
        if mode in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return

        mode_str = str(mode)
        if self._attr_available_modes and mode_str not in self._attr_available_modes:
            _LOGGER.error(
                "Received invalid mode: %s. Expected: %s.",
                mode_str,
                self._attr_available_modes,
            )
            return

        if self._attr_mode != mode_str:
            self._attr_mode = mode_str
            self.async_write_ha_state()

    def _coerce_action(self, action) -> HumidifierAction | str | None:
        """Convert an action value to a HumidifierAction or an accepted extension."""
        if action in (None, STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None

        try:
            return HumidifierAction(action)
        except ValueError:
            pass

        if action in EXTENDED_ACTIONS:
            return action

        _LOGGER.error(
            "Received invalid action: %s. Expected: %s.",
            action,
            [member.value for member in HumidifierAction] + sorted(EXTENDED_ACTIONS),
        )
        return None

    @callback
    def _update_action(self, action):
        new_action = self._coerce_action(action)
        if self._attr_action != new_action:
            self._attr_action = new_action
            self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on the humidifier."""
        if self._state_template is None:
            self._attr_is_on = True
            self.async_write_ha_state()

        if self._turn_on_script:
            await self.async_run_script(
                self._turn_on_script,
                context=self._context,
            )

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off the humidifier."""
        if self._state_template is None:
            self._attr_is_on = False
            self.async_write_ha_state()

        if self._turn_off_script:
            await self.async_run_script(
                self._turn_off_script,
                context=self._context,
            )

    async def async_set_humidity(self, humidity: int) -> None:
        """Set new target humidity."""
        if self._target_humidity_template is None:
            self._attr_target_humidity = humidity
            self.async_write_ha_state()

        if self._set_humidity_script:
            await self.async_run_script(
                self._set_humidity_script,
                run_variables={ATTR_HUMIDITY: humidity},
                context=self._context,
            )

    async def async_set_mode(self, mode: str) -> None:
        """Set new mode."""
        if self._mode_template is None:
            self._attr_mode = mode
            self.async_write_ha_state()

        if self._set_mode_script:
            await self.async_run_script(
                self._set_mode_script,
                run_variables={ATTR_MODE: mode},
                context=self._context,
            )
