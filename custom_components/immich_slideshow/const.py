"""Constants for Immich Slideshow integration."""
from datetime import timedelta

DOMAIN = "immich_slideshow"

# Configuration keys
CONF_HOST = "host"
CONF_API_KEY = "api_key"
CONF_DAYS = "days"
CONF_DUAL_PORTRAIT = "dual_portrait"
CONF_RESOLUTIONS = "resolutions"
CONF_REFRESH_INTERVAL = "refresh_interval"
CONF_MEMORY_YEARS = "memory_years"
CONF_MIX_RATIO = "mix_ratio"
CONF_BACKGROUND_PATH = "background_path"
CONF_FAVORITES_FILTER = "favorites_filter"
CONF_WRITE_FILES = "write_files"

# Legacy keys (for migration)
CONF_TARGET_WIDTH = "target_width"
CONF_TARGET_HEIGHT = "target_height"

# Default values
DEFAULT_DAYS = 90
DEFAULT_DUAL_PORTRAIT = True
DEFAULT_RESOLUTIONS = "1920x1080"  # Comma-separated, e.g. "1920x1080, 2048x1536"
DEFAULT_REFRESH_INTERVAL = 30  # seconds
DEFAULT_MEMORY_YEARS = 0  # 0 = unlimited
DEFAULT_MIX_RATIO = 0  # 0% = recent only, 100% = memories only
DEFAULT_BACKGROUND_PATH = "view_assist/images/backgrounds"
DEFAULT_FAVORITES_FILTER = "all"  # "all", "only", "exclude"
DEFAULT_WRITE_FILES = False  # Only enable for View Assist users

# Timing (used as fallback)
SCAN_INTERVAL = timedelta(seconds=DEFAULT_REFRESH_INTERVAL)

# View Assist integration - save current image to this path for VA to read
VA_BACKGROUND_PATH = "view_assist/backgrounds"


def parse_resolutions(resolutions_str: str) -> list[tuple[int, int]]:
    """Parse resolution string into list of (width, height) tuples.

    Input: "1920x1080, 2048x1536"
    Output: [(1920, 1080), (2048, 1536)]

    Returns empty list if no valid resolutions found (for validation).
    """
    result = []
    for res in resolutions_str.split(","):
        res = res.strip()
        if "x" in res:
            try:
                w, h = res.split("x")
                result.append((int(w.strip()), int(h.strip())))
            except ValueError:
                continue
    return result
