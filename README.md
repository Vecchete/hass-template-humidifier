# Humidifier Template

A Home Assistant custom integration that creates a template-based humidifier
entity. It is based on [jcwillox/hass-template-climate](https://github.com/jcwillox/hass-template-climate), but
for the `humidifier` domain.

## Changes in this fork

This is a fork of [kei81131/hass-template-humidifier](https://github.com/kei81131/hass-template-humidifier).
Everything below is what this copy adds; the rest of the behaviour is unchanged.

The Home Assistant internals these changes rely on — which names move between releases, how
attribute values are translated, how generated dashboards choose a tile's control, and the traps in
each — are written up in [docs/home-assistant-internals.md](docs/home-assistant-internals.md).

### Loads on Home Assistant 2026.9 and later

Upstream cannot start on 2026.9: it imports two names the release removed from the `template`
integration's internals, so the platform raises `ImportError` during setup and every entity comes up
`unavailable` as a registry stub.

| Name | What happened | Fix here |
| --- | --- | --- |
| `make_template_entity_base_schema` | Renamed to `make_template_entity_common_schema` by core PR #178762 | Import the new name, fall back to the old one, so both work |
| `validate_template_scripts` | Removed from `homeassistant.components.template.helpers` | Imported defensively; the pre-setup script validation is skipped when it is absent |

`check_config` does **not** catch this. It reports `valid` with only a warning that the integration
was not found, because Home Assistant scans `custom_components/` at startup. Verify with a real
import instead:

```bash
python3 -c "import sys; sys.path.insert(0, '/config'); import importlib; importlib.import_module('custom_components.humidifier_template.humidifier')"
```

### An `error` action

`HumidifierAction` has no member for a machine that is switched on but cannot run. A dehumidifier
with a full water tank or a reported fault is neither `drying` nor `idle`, so `action_template` had
to report something untrue.

`action_template` may now also return **`error`**. The value is passed through to the `action` state
attribute and shown in place of Drying or Idle. Anything outside the enum plus this extension is
still rejected, and the log line lists every accepted value.

```yaml
action_template: >
  {{ 'error' if is_state('binary_sensor.dehumidifier_tank', 'on')
     else ('drying' if is_state('humidifier.real_unit', 'on') else 'idle') }}
```

Home Assistant only publishes `action` while the entity is on; when it is off, core forces `off`.
So `error` is visible exactly when the unit is switched on and unable to work, which is the case
worth showing.

### Translated action values

The entity now sets a `translation_key` and the integration ships `translations/en.json`. The
frontend resolves an attribute value from
`component.<platform>.entity.<domain>.<translation_key>.state_attributes.action.state.<value>`
before it tries core's `humidifier` namespace, so `error` renders as **Error** rather than as a raw
lowercase fallback. The enum values are translated in the same file so the whole set comes from one
place.

The key is assigned on the instance rather than the class, because `Entity`'s metaclass turns every
`_attr_` name into a property and a class-level assignment never reaches the entity. Note that the
entity registry records `translation_key` when an entry is **created**: entities that already exist
keep whatever they were registered with, so delete the registry entries once after upgrading if the
translated values do not appear.

### `icon_template`, `entity_picture_template` and `availability_template` actually work

Upstream's schema accepts all three, but the modern template entity base reads `icon`, `picture` and
`availability`, and the platform never wired the long spellings. They were accepted and then silently
dropped, so an `icon_template` never rendered and nothing said why.

This fork maps the legacy names onto the modern ones before the entity is built, so either spelling
works.

### Minus/plus humidity buttons on generated dashboards

Home Assistant's built-in **Climate**, **Home** and **Areas** pages are produced by view
strategies, and every tile's control is chosen by `computeAreaTileCardConfig` from a fixed chain:

```
light-brightness -> cover-open-close -> target-temperature -> fan-speed -> alarm-modes -> lock-commands
```

There is no humidity entry, so a humidifier tile on those pages shows a name and a state and
nothing to press, while a climate tile beside it gets a `- 20,0 °C +` widget. `target-humidity`
would not help either: it renders a slider, and the buttons widget
(`ha-control-number-buttons`) is only wired to the `numeric-input` feature, which accepts
`number` and `input_number` entities only. None of this is reachable from an integration.

This fork ships a small frontend module that closes the gap:

- it registers a custom card feature, **`custom:humidity-number-buttons`**, rendering the *same*
  `ha-control-number-buttons` the temperature feature uses, with the unit set to `%`, the bounds
  taken from `min_humidity` / `max_humidity` / `target_humidity_step`, and changes sent with
  `humidifier.set_humidity`;
- it wraps the built-in view strategies so that humidifier tiles they generate carry that feature.
  `getLovelaceStrategy` resolves a built-in strategy with `customElements.get(tag)` on every
  regeneration and then calls its static `generate()`, so wrapping that method is a stable seam.

The module is **served and registered by the integration itself** through `add_extra_js_url`, so
there is nothing to add to `configuration.yaml`, no copy in `www/`, and it returns by itself after
a restart. The URL carries the integration version as a query string so a new release is not served
from the browser's cache.

It only ever adds a feature to a tile that has none, and every hook is wrapped: if anything fails,
the tile degrades to stock Home Assistant rather than breaking the dashboard. You can also place
the feature by hand on any tile card:

```yaml
type: tile
entity: humidifier.humidity_control_bathroom
features:
  - type: custom:humidity-number-buttons
```

Strategies patched: `climate-view-strategy`, `home-area-view-strategy`, `area-view-strategy`,
`home-overview-view-strategy`, `areas-overview-view-strategy`.

⚠ This is the one part of the fork that reaches into frontend internals, so it is the part most
likely to need attention after a Home Assistant release. If a generated page loses the buttons,
check that the strategy tag names above still exist and that `ha-control-number-buttons` still
takes `value` / `min` / `max` / `step` / `unit`.

## Installation With HACS

1. Open HACS in Home Assistant.
2. Open the top right three-dot menu and choose **Custom repositories**.
3. Add this repository URL.
4. Choose **Integration** as the category.
5. Install **Humidifier Template**.
6. Restart Home Assistant.

## Example Configuration

Add this to configuration.yaml

```yaml
humidifier:
  - platform: humidifier_template
    name: Bedroom dehumidifier
    unique_id: bedroom_dehumidifier
    min_humidity: 30
    max_humidity: 70
    target_humidity_step: 1
    modes:
      - "Smart"
      - "Sleep"
      - "Clothes Drying"
    state_template: "{{ states('humidifier.<your_humidifier>') }}"
    current_humidity_template: "{{ states('sensor.<your_humidity_sensor>') }}"
    target_humidity_template: >
      {{ state_attr('humidifier.<your_humidifier>', 'humidity') }}
    mode_template: >
      {{ state_attr('humidifier.<your_humidifier>', 'mode') }}
    action_template: >
      {{ state_attr('humidifier.<your_humidifier>', 'action') }}
    turn_on:
      - action: humidifier.turn_on
        target:
          entity_id: humidifier.<your_humidifier>
    turn_off:
      - action: humidifier.turn_off
        target:
          entity_id: humidifier.<your_humidifier>
    set_humidity:
      - action: humidifier.set_humidity
        target:
          entity_id: humidifier.<your_humidifier>
        data:
          humidity: "{{ humidity }}"
    set_mode:
      - action: humidifier.set_mode
        target:
          entity_id: humidifier.<your_humidifier>
        data:
          mode: "{{ mode }}"
```

## Options

| Option | Description |
| --- | --- |
| `state_template` | Template returning `on` or `off`. |
| `current_humidity_template` | Template for current humidity. |
| `target_humidity_template` | Template for target humidity. |
| `min_humidity` / `max_humidity` | Static humidity range. |
| `min_humidity_template` / `max_humidity_template` | Dynamic humidity range templates. |
| `target_humidity_step` | Humidity step size. |
| `modes` | Available modes shown by Home Assistant. |
| `mode_template` | Template for current mode. |
| `action_template` | Template for `humidifying`, `drying`, `idle`, `off`, or `error` (this fork). |
| `turn_on` / `turn_off` | Scripts to call when the entity is toggled. |
| `set_humidity` | Script to call when target humidity changes. |
| `set_mode` | Script to call when mode changes. |

## Notes

