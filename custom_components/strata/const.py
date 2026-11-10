"""Constants for the Strata integration."""

from __future__ import annotations

import logging

DOMAIN = "strata"
LOGGER = logging.getLogger(__package__)

CONF_VERIFY_SSL = "verify_ssl"
DEFAULT_SCAN_INTERVAL = 5  # seconds
MIN_SCAN_INTERVAL = 2
MAX_SCAN_INTERVAL = 300

# The Lovelace card is served from the integration folder and loaded automatically.
STATIC_URL = "/strata_static"
CARD_URL = f"{STATIC_URL}/strata-card.js"

# Fields of a request record the card needs (the server keeps ~30 per record).
REQUEST_FIELDS = (
    "time", "finish", "prompt_tokens", "reused", "output_tokens", "prompt_ms",
    "decode_tok_s", "hit_rate", "pcie_share", "duration_s",
)
