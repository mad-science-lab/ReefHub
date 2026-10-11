# Changelog

## 0.1.0
- Reads every Apex outlet, probe and the feed state and publishes them to MQTT.
- Controls outlets (Off / Auto / On) and feed modes A-D plus cancel.
- Home Assistant MQTT discovery with one device per Apex module, one for the
  base unit and one for feed.
- Outlet power level, raw state and MXM pump mode sensors.
- Installable from GitHub as a Home Assistant add-on repository, or run with Docker.
