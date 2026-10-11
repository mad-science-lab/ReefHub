#!/usr/bin/with-contenv bashio
# Map the add-on options and the Supervisor's MQTT service onto ReefHub's
# environment variables, then start it.
set -e

if ! bashio::services.available "mqtt"; then
    bashio::exit.nok "No MQTT service available - install and start the Mosquitto broker add-on first."
fi

export APEX_HOST="$(bashio::config 'apex_host')"
export APEX_USERNAME="$(bashio::config 'apex_username')"
export APEX_PASSWORD="$(bashio::config 'apex_password')"
export POLL_SECONDS="$(bashio::config 'poll_seconds')"
export LOG_LEVEL="$(bashio::config 'log_level')"

export MQTT_HOST="$(bashio::services 'mqtt' 'host')"
export MQTT_PORT="$(bashio::services 'mqtt' 'port')"
export MQTT_USERNAME="$(bashio::services 'mqtt' 'username')"
export MQTT_PASSWORD="$(bashio::services 'mqtt' 'password')"


bashio::log.info "Using MQTT broker at ${MQTT_HOST}:${MQTT_PORT}"
bashio::log.info "Starting ReefHub (Apex at ${APEX_HOST})"
exec python3 -m reefhub
