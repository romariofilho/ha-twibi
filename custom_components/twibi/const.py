"""Constantes da integracao Intelbras Twibi."""
from datetime import timedelta

DOMAIN = "twibi"
DEFAULT_HOST = "10.1.1.1"
DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)
CONF_SCAN_INTERVAL = "scan_interval"

# depois de comandos que reiniciam o Wi-Fi do Twibi, espera antes de reconsultar
WIFI_RESTART_GRACE = 45

PLATFORMS = ["binary_sensor", "device_tracker", "sensor", "switch"]

ATTR_MAC = "mac"
ATTR_IP = "ip"
ATTR_NAME = "name"
ATTR_NAMES = "names"
