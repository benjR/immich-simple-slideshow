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
# Boost sub-option: reserve a share of "recent" draws for the very latest
# photos (taken OR uploaded within the last N days).
CONF_RECENT_BOOST_DAYS = "recent_boost_days"
CONF_RECENT_BOOST_SHARE = "recent_boost_share"
CONF_RECENT_BOOST_RESHOW_HOURS = "recent_boost_reshow_hours"

# Configuration keys - Memories source
CONF_MEMORIES_MAX_YEARS = "memories_max_years"

# Configuration keys - Albums source
CONF_ALBUMS_INCLUDE = "albums_include"

# Configuration keys - Persons source
CONF_PERSONS_INCLUDE = "persons_include"

# Configuration keys - Global exclusions
CONF_EXCLUDE_ALBUMS = "exclude_albums"
CONF_EXCLUDE_PERSONS = "exclude_persons"
# Include photos archived in Immich (hidden from its timeline). Legacy search
# returned them implicitly; with the v3.2 search API it is an explicit choice.
CONF_INCLUDE_ARCHIVED = "include_archived"

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
DEFAULT_RECENT_BOOST_DAYS = 7  # 0 = boost disabled
DEFAULT_RECENT_BOOST_SHARE = 40  # % of "recent" draws reserved for the boost window
# Hours before a boosted (very recent) photo may be shown again; the regular
# exclusion window is SHOWN_MEMORY_HOURS. Configurable in the recent source options.
DEFAULT_RECENT_BOOST_RESHOW_HOURS = 4

# Default values - Global filters
DEFAULT_INCLUDE_ARCHIVED = False

# Default values - Memories source
DEFAULT_MEMORIES_MAX_YEARS = 0  # 0 = unlimited

# Default values - Legacy (for migration)
DEFAULT_DAYS = 90
DEFAULT_MEMORY_YEARS = 0
DEFAULT_MIX_RATIO = 0
DEFAULT_FAVORITES_FILTER = "all"

# Timing (used as fallback)
SCAN_INTERVAL = timedelta(seconds=DEFAULT_REFRESH_INTERVAL)

# =============================================================================
# Anti-repetition — "recently shown" memory
# =============================================================================
# Assets displayed less than SHOWN_MEMORY_HOURS ago are excluded when the pool
# is refilled and when assets are popped for display. The history is persisted
# via homeassistant.helpers.storage.Store (one file per config entry:
# .storage/immich_slideshow_shown_<entry_id>) so it survives HA restarts.
# Writes are rate-limited to at most one every SHOWN_SAVE_DELAY_SECONDS.
SHOWN_MEMORY_HOURS = 24  # exclusion window (hours)
# Shorter window for assets inside the "recent boost" window (taken OR uploaded
# less than recent_boost_days ago): they may reappear after only a few hours so
# the very latest photos actually cycle through the slideshow during the day.
SHOWN_MEMORY_HOURS_BOOSTED = DEFAULT_RECENT_BOOST_RESHOW_HOURS  # option default
SHOWN_SAVE_DELAY_SECONDS = 300  # min seconds between .storage writes
SHOWN_STORAGE_VERSION = 1
SHOWN_STORAGE_KEY = f"{DOMAIN}_shown"  # final key: f"{SHOWN_STORAGE_KEY}_{entry_id}"

# =============================================================================
# Undisplayable assets ("bad assets")
# =============================================================================
# Assets whose download fails (e.g. original missing on disk → 404) or whose
# bytes Pillow cannot decode (HEIC saved as .jpg, PSD, AppleDouble "._" files,
# decompression-bomb panoramas) are remembered for BAD_ASSET_TTL_HOURS and
# skipped at refill and pop time, so the same broken file is not re-drawn at
# every refill. Persisted in the shown-history Store under this reserved key
# (asset ids are UUIDs, so it cannot collide with a shown entry).
BAD_ASSET_TTL_HOURS = 7 * 24
BAD_ASSETS_STORE_KEY = "_bad_assets"
# Max pool assets tried per display slot before giving up on this cycle.
MAX_DISPLAY_ATTEMPTS = 3

# View Assist integration - save current image to this path for VA to read
VA_BACKGROUND_PATH = "view_assist/backgrounds"


# =============================================================================
# Immich API key permissions (Immich v3+ granular permissions)
# =============================================================================
# The integration talks to Immich with a scoped API key. Immich v3 enforces
# granular permissions and answers 403 with a body of the form
# {"message": "Missing required permission: <perm>"} when one is absent.
# We surface the missing permission(s) at setup and after an Immich upgrade.

PERM_ASSET_READ = "asset.read"          # search/random + asset metadata
PERM_ASSET_DOWNLOAD = "asset.download"  # download original bytes to display
PERM_MEMORY_READ = "memory.read"        # "On this day" memories source
PERM_ALBUM_READ = "album.read"          # albums source + album attribution
PERM_PERSON_READ = "person.read"        # persons source
PERM_USER_READ = "user.read"            # resolve ownerId -> owner display name
PERM_ASSET_VIEW = "asset.view"          # server-converted renditions (HEIC...)

# Capability key -> human-facing Immich permission string.
CAPABILITY_PERMISSION = {
    "asset_read": PERM_ASSET_READ,
    "asset_download": PERM_ASSET_DOWNLOAD,
    "memory_read": PERM_MEMORY_READ,
    "album_read": PERM_ALBUM_READ,
    "person_read": PERM_PERSON_READ,
    "user_read": PERM_USER_READ,
    "asset_view": PERM_ASSET_VIEW,
}

# Required for ANY photo to display, regardless of enabled sources.
CORE_CAPABILITIES = ("asset_read", "asset_download")

# Not required, but the slideshow degrades without them: surfaced as a separate,
# softer repair issue. Without asset.view the integration downloads originals,
# so formats Pillow can't read (HEIC saved as .jpg, PSD...) are skipped instead
# of being displayed from Immich's converted JPEG rendition.
RECOMMENDED_CAPABILITIES = ("asset_view",)

# A weighted source needs its capability only when enabled (weight > 0).
SOURCE_WEIGHT_CAPABILITY = {
    CONF_SOURCE_MEMORIES_WEIGHT: "memory_read",
    CONF_SOURCE_ALBUMS_WEIGHT: "album_read",
    CONF_SOURCE_PERSONS_WEIGHT: "person_read",
}

# Note: partner photos (shared libraries) flow through /api/search/random
# automatically in Immich v3 and do NOT require the `partner.read` permission.
# `user.read` is recommended (owner-name attribution) but not required.


# =============================================================================
# Minimum supported Immich server version
# =============================================================================
# The integration relies on Immich's plural REST API (/api/assets,
# /api/search/random, /api/albums, /api/people, /api/memories). That API shape
# landed with the singular->plural rename in Immich v1.106.0; older servers
# return 404 for these paths, so the slideshow cannot work. We surface this as a
# clear message rather than letting calls fail silently.
MIN_IMMICH_VERSION = (1, 106, 0)


def format_version(version: tuple[int, int, int] | None) -> str:
    """Human-friendly 'major.minor.patch' string, or 'unknown' for None."""
    return ".".join(str(part) for part in version) if version else "unknown"


def required_capabilities(options: dict) -> list[str]:
    """Capabilities the current config actually relies on.

    Always includes the core capabilities; adds a source capability only when
    that source has a non-zero weight. `user.read` is intentionally excluded
    (nice-to-have, not required for the slideshow to work).
    """
    caps = list(CORE_CAPABILITIES)
    for weight_key, cap in SOURCE_WEIGHT_CAPABILITY.items():
        if (options.get(weight_key) or 0) > 0:
            caps.append(cap)
    return caps


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
