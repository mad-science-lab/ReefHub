ARG BUILD_FROM
FROM $BUILD_FROM

# HA base images are Alpine with bashio preinstalled
RUN apk add --no-cache python3 py3-pip

# ReefHub package, installed from the matching tag on GitHub.
# Keep REEFHUB_REF in step with `version` in config.yaml (tag = v<version>).
ARG REEFHUB_REF=v0.1.0
RUN pip3 install --no-cache-dir --break-system-packages \
    "https://github.com/mad-science-lab/ReefHub/archive/refs/tags/${REEFHUB_REF}.tar.gz"

COPY run.sh /
RUN chmod a+x /run.sh
CMD [ "/run.sh" ]
