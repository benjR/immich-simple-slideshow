"""Constants for Immich Slideshow integration."""
from datetime import timedelta

DOMAIN = "immich_slideshow"

# Configuration keys - Core
CONF_HOST = "host"
CONF_API_KEY = "api_key"
CONF_DUAL_PORTRAIT = "dual_portrait"
CONF_RESOLUTIONS = "resolutions"
CONF_REFRESH_INTERVAL = "refresh_interval"
CONF_BACKGROUND_PATH = "background_path"
CONF_WRITE_FILES = "write_files"

# Configuration keys - Source weights (0-100, normalized at runtime)
CONF_SOURCE_RECENT_WEIGHT = "source_recent_weight"
CONF_SOURCE_MEMORIES_WEIGHT = "source_memories_weight"
CONF_SOURCE_ALBUMS_WEIGHT = "source_albums_weight"
CONF_SOURCE_PERSONS_WEIGHT = "source_persons_weight"

# Configuration keys - Recent source
CONF_RECENT_DAYS = "recent_days"
CONF_RECENT_FAVORITES_FILTER = "recent_favorites_filter"

# Configuration keys - Memories source
CONF_MEMORIES_MAX_YEARS = "memories_max_years"

# Configuration keys - Albums source
CONF_ALBUMS_INCLUDE = "albums_include"

# Configuration keys - Persons source
CONF_PERSONS_INCLUDE = "persons_include"

# Configuration keys - Global exclusions
CONF_EXCLUDE_ALBUMS = "exclude_albums"
CONF_EXCLUDE_PERSONS = "exclude_persons"

# Legacy keys (for v1 → v2 migration)
CONF_TARGET_WIDTH = "target_width"
CONF_TARGET_HEIGHT = "target_height"
CONF_DAYS = "days"
CONF_MEMORY_YEARS = "memory_years"
CONF_MIX_RATIO = "mix_ratio"
CONF_FAVORITES_FILTER = "favorites_filter"

# Default values - Core
DEFAULT_DUAL_PORTRAIT = True
DEFAULT_RESOLUTIONS = "1920x1080"  # Comma-separated, e.g. "1920x1080, 2048x1536"
DEFAULT_REFRESH_INTERVAL = 30  # seconds
DEFAULT_BACKGROUND_PATH = "view_assist/images/backgrounds"
DEFAULT_WRITE_FILES = False  # Only enable for View Assist users

# Default values - Source weights
DEFAULT_SOURCE_RECENT_WEIGHT = 50  # 0-100
DEFAULT_SOURCE_MEMORIES_WEIGHT = 50  # 0-100
DEFAULT_SOURCE_ALBUMS_WEIGHT = 0  # Disabled by default
DEFAULT_SOURCE_PERSONS_WEIGHT = 0  # Disabled by default

# Default values - Recent source
DEFAULT_RECENT_DAYS = 90  # 0 = unlimited
DEFAULT_RECENT_FAVORITES_FILTER = "all"  # "all", "only", "exclude"

# Default values - Memories source
DEFAULT_MEMORIES_MAX_YEARS = 0  # 0 = unlimited

# Default values - Legacy (for migration)
DEFAULT_DAYS = 90
DEFAULT_MEMORY_YEARS = 0
DEFAULT_MIX_RATIO = 0
DEFAULT_FAVORITES_FILTER = "all"

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
