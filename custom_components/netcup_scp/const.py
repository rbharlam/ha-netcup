"""Constants for the netcup SCP integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "netcup_scp"

CONF_REFRESH_TOKEN: Final = "refresh_token"
CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_SCAN_INTERVAL: Final = timedelta(seconds=60)
MIN_SCAN_INTERVAL: Final = 30

SCP_URL: Final = "https://www.servercontrolpanel.de/"
