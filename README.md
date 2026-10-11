<!-- Version: V26.284.1445 -->
# ReefHub

A small bridge from a Neptune Apex controller to MQTT.

- **Reads** every outlet, probe, and the feed state, and publishes them to MQTT.
- **Controls** outlets (Off / Auto / On) and the four feed modes (A, B, C, D) plus cancel.
- **Devices**: in Home Assistant, one device per Apex module (EB832 #2, FMM #1, ...), one for the base unit, and one for feed.

That is the whole feature list. No database, no analytics. Anything that speaks MQTT
(Node-RED, Home Assistant, Grafana pipelines) can use it.

## Related projects

| Name | Link | Description |
|---|---|---|
| **ReefHub** | <https://github.com/mad-science-lab/ReefHub> | Neptune Apex to MQTT bridge: read every outlet and probe, control outlets and feed modes. Home Assistant add-on and Docker. |
| **LunarReef** | <https://github.com/mad-science-lab/LunarReef> | Makes the lunar channel of EcoTech Radion XR15 lights follow the real moon at your location. Home Assistant add-on and local web app. |
| **RADclouds** | <https://github.com/mad-science-lab/RADclouds> | Drifts an EcoTech Radion profile on a Neptune Apex like passing clouds. Home Assistant add-on and local web app. |

## Install

### Home Assistant add-on

1. In Home Assistant: **Settings > Add-ons > Add-on Store > three-dot menu > Repositories**.
2. Add `https://github.com/mad-science-lab/ReefHub` and close the dialog.
3. Find **ReefHub** in the store, **Install**, set the Apex address and password in the
   Configuration tab, then **Start**.

The Mosquitto broker add-on (or any MQTT service known to the Supervisor) is picked up
automatically.

To install from a Samba share instead, run `.\build_addon.ps1` (stages `dist\reefhub`),
copy it to the HA `addons` share and install it from *Local add-ons*.

### Standalone (Docker)

```bash
git clone https://github.com/mad-science-lab/ReefHub && cd ReefHub
# edit docker-compose.yml: APEX_HOST, APEX_PASSWORD, MQTT_HOST
docker compose up -d --build
```

## Configuration

| Variable | Default | |
|---|---|---|
| `APEX_HOST` | required | e.g. `http://192.168.1.50` |
| `APEX_USERNAME` | `admin` | |
| `APEX_PASSWORD` | empty | |
| `MQTT_HOST` | required | your broker |
| `MQTT_PORT` | `1883` | |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | none | |
| `MQTT_BASE_TOPIC` | `reefhub` | |
| `POLL_SECONDS` | `15` | minimum 5 |
| `HA_DISCOVERY` | `true` | publish Home Assistant MQTT discovery |
| `HA_DISCOVERY_PREFIX` | `homeassistant` | |
| `LOG_LEVEL` | `INFO` | |

## How it works

### MQTT topics

`<base>` is `reefhub` unless you changed it. `<did>` is the Apex device id such as `2_1`.

| Topic | Direction | Payload |
|---|---|---|
| `<base>/status` | out | `online` / `offline` (broker last-will) |
| `<base>/controller` | out | `online` / `offline` (is the Apex reachable) |
| `<base>/state` | out | one JSON document with everything |
| `<base>/outlet/<did>/mode` | out | `OFF` / `AUTO` / `ON` |
| `<base>/outlet/<did>/energized` | out | `ON` / `OFF` |
| `<base>/outlet/<did>/state` | out | raw Apex state: `AON` / `AOF` (auto, on/off), `ON` / `OFF` (manual), `TBL` (table-driven) |
| `<base>/outlet/<did>/percent` | out | power level 0-100, only for outlets that report one |
| `<base>/outlet/<did>/pump_mode` | out | MXM pumps only: running mode as the Apex reports it (e.g. `Off`, `Cnst`) |
| `<base>/outlet/<did>/set` | **in** | `OFF` / `AUTO` / `ON` |
| `<base>/probe/<did>` | out | number, or `ON`/`OFF` for digital inputs |
| `<base>/feed/mode` | out | `OFF` / `A` / `B` / `C` / `D` |
| `<base>/feed/remaining` | out | seconds left in the running cycle |
| `<base>/feed/set` | **in** | `A` / `B` / `C` / `D` / `CANCEL` (1-4 also work) |

All outputs are retained. In Node-RED, an `mqtt out` node publishing `AUTO` to
`reefhub/outlet/2_1/set` or `B` to `reefhub/feed/set` is all it takes.

The `state` document is keyed by device id so a function node can pick things
out directly:

```json
{
  "updated": "2026-10-09T18:22:04+00:00",
  "controller": {"serial": "AC6:12345", "hardware": "1.0", "software": "5.15L"},
  "feed": {"mode": "OFF", "seconds_remaining": 0},
  "outlets": {"2_1": {"name": "Heater", "mode": "AUTO", "energized": true, "type": "outlet"}},
  "probes": {"base_Temp": {"name": "Tmp", "type": "Temp", "value": 78.1}}
}
```

### Home Assistant

With `HA_DISCOVERY=true` (the default) and the MQTT integration enabled, ReefHub
creates one device per Apex module (named from the module list, e.g.
`ReefHub EB832 #2`), one for the base unit, and a `ReefHub Feed` device. Each
outlet is a select (Off/Auto/On), an "energized" sensor, and a "state" sensor with the raw Apex value; each probe is a
sensor; the Feed device has buttons for A-D and Cancel plus mode and time
remaining. Names are the Apex's own; rename entities and devices in Home
Assistant if you want something different.

## Safety

- Do not run two ReefHubs against one broker with the same `MQTT_BASE_TOPIC`;
  they share a client id and will disconnect each other.
- Cancelling a feed when none is running is ignored on purpose: AOS 5.15L
  reports garbage feed data for about 17 hours after that.
- Tested against AOS 5.15L. Other 5.x
  firmware should work but is unverified.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

## License and trademarks

Licensed under the [GNU Affero General Public License v3.0](LICENSE). Free for anyone to use; any copy, part or modified version, including one run as a hosted service, must stay open source under the same license.

ReefHub is an independent project, not affiliated with or endorsed by Neptune
Systems. Neptune Apex is a trademark of Neptune Systems. It is named only to
describe the equipment ReefHub works with.
