# Immich Simple Slideshow

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/benjR/immich-simple-slideshow)](https://github.com/benjR/immich-simple-slideshow/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Home Assistant custom integration for displaying photos from your [Immich](https://immich.app/) library as a slideshow.

Forked from [outadoc/immich-home-assistant](https://github.com/outadoc/immich-home-assistant).

## Features

- **Multiple sources** - Recent photos, "On This Day" memories, albums, persons - each with configurable weight
- **Pool system** - Pre-fetches 100 photos, serves them without repetition, auto-refills in background
- **Prefetch** - Next image is downloaded and resized while the current one is displayed
- **Dual portrait** - Two portrait photos side by side on landscape displays
- **Album & person filters** - Include/exclude specific albums or people from the config flow
- **View Assist support** - Writes images to disk for use as VA backgrounds
- **3 sensors** - Pool size, current source, prefetch status

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu → Custom repositories
3. Add `https://github.com/benjR/immich-simple-slideshow` with category "Integration"
4. Search for "Immich Simple Slideshow" and install
5. Restart Home Assistant
6. Go to Settings → Devices & Services → Add Integration → "Immich Simple Slideshow"
7. Enter your Immich server URL and API key

### Manual

1. Copy the `custom_components/immich_slideshow` folder to your Home Assistant `custom_components` directory
2. Restart Home Assistant
3. Go to Settings → Devices & Services → Add Integration → "Immich Simple Slideshow"
4. Enter your Immich server URL and API key

## Configuration Options

### Source weights

Each source has a weight (0-100). Set to 0 to disable. Weights are relative to each other - if recent=50 and memories=50, you get ~50/50. If recent=80 and albums=20, you get ~80/20.

| Source | Default | Description |
|--------|---------|-------------|
| Recent | 50 | Photos from the last N days |
| Memories | 50 | "On This Day" photos from previous years |
| Albums | 0 | Photos from selected albums |
| Persons | 0 | Photos containing selected people |

### Other options

| Option | Default | Description |
|--------|---------|-------------|
| Recent days | 90 | How far back for recent photos (0 = all time) |
| Favorites filter | All | All photos, favorites only, or exclude favorites |
| Memory years | 0 | Max years back for memories (0 = unlimited) |
| Albums include | - | Select specific albums (empty = all) |
| Persons include | - | Select specific people |
| Exclude albums | - | Albums to exclude from all sources |
| Exclude persons | - | People to exclude from all sources |
| Dual portrait | Yes | Combine two portraits side by side |
| Resolution | 1920x1080 | Output resolution (supports multiple, comma-separated) |
| Refresh interval | 30s | Time between photo changes |
| Write files | No | Save images to disk (for View Assist) |

## Usage

### As a fullscreen background

#### Wallpanel (recommended)

[Wallpanel](https://github.com/j-a-n/lovelace-wallpanel) provides fullscreen backgrounds for any Lovelace view:

```yaml
wallpanel:
  enabled: true
  image_url: /api/image_proxy/image.immich_slideshow
```

#### card-mod

Requires [card-mod](https://github.com/thomasloven/lovelace-card-mod):

```yaml
type: picture-entity
entity: image.immich_slideshow
show_state: false
show_name: false
card_mod:
  style: |
    ha-card {
      position: fixed !important;
      top: 0 !important;
      left: 0 !important;
      width: 100vw !important;
      height: 100vh !important;
      z-index: 0 !important;
      border: none !important;
      box-shadow: none !important;
      border-radius: 0 !important;
      pointer-events: none !important;
    }
    img {
      object-fit: cover !important;
      width: 100% !important;
      height: 100% !important;
    }
```

### With View Assist

1. Enable "Write files to disk" in the integration options
2. In View Assist settings:
   - **Background image source**: `Random image from local file path`
   - **Image path or url**: `backgrounds`

Images are saved to `/config/view_assist/images/backgrounds/` by default.

### Entity attributes

The image entity exposes these attributes (suffixed `_1`, and `_2` when dual portrait):

| Attribute | Description |
|-----------|-------------|
| `is_dual_portrait` | Whether showing two photos |
| `asset_id` | Immich asset ID |
| `immich_url` | Direct link to photo in Immich |
| `original_filename` | Original file name |
| `date_taken` | When the photo was taken |
| `source` | `recent`, `memory`, `album`, or `person` |
| `album_name` | Album name (if from album source) |
| `owner_name` | Photo owner (for shared libraries) |
| `memory_year` | Year of the memory |
| `years_ago` | How many years ago |
| `city` / `country` | Location info |
| `people` | Recognized people in the photo |
| `is_favorite` | Favorite status in Immich |
| `has_live_photo` | Whether the photo has a Live Photo video |

### Sensors

| Entity | Description |
|--------|-------------|
| `sensor.immich_slideshow_pool_size` | Number of photos ready in the pool |
| `sensor.immich_slideshow_current_source` | Source of the currently displayed photo |
| `sensor.immich_slideshow_prefetch_status` | Prefetch state (idle, fetching, ready) |

## Known limitations

- **Shared album assets**: Immich's `search/random` API filters by asset owner even when `albumIds` is specified. Photos uploaded by other users in a shared album won't appear. Workaround: set up [Partners](https://immich.app/docs/features/partner-sharing) in Immich. [Reported upstream](https://github.com/immich-app/immich/issues/28662).
- **HEIC not supported**: Photos in HEIC/HEIF format are skipped.

## Requirements

- Home Assistant 2024.1+
- Immich server with API access

## License

MIT

## Credits

- Original integration: [outadoc/immich-home-assistant](https://github.com/outadoc/immich-home-assistant)
- Immich: [immich-app/immich](https://github.com/immich-app/immich)
