"""wa-permit-engine v5.0.0 — WA State backcountry permit chain finder."""
import logging

__version__ = "5.0.0"

# Attach a NullHandler so library callers don't get "No handlers found" warnings.
# The CLI configures a real handler on --verbose; everything else stays silent.
logging.getLogger(__name__).addHandler(logging.NullHandler())
