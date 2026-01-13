# Immich Simple Slideshow

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/benjR/immich-simple-slideshow)](https://github.com/benjR/immich-simple-slideshow/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> ⚠️ **Warning:** This project was vibecoded. While it works for my use case, expect rough edges, potential bugs, and code that might make experienced developers cry. Use at your own risk, PRs welcome!

A Home Assistant custom integration for displaying photos from your [Immich](https://immich.app/) library as a slideshow, with support for "On This Day" memories.

Forked from [outadoc/immich-home-assistant](https://github.com/outadoc/immich-home-assistant).

## Features

- **Memories** — "On This Day" photos from previous years
- **Mix ratio** — Blend memories with recent photos (0-100%)
- **Dual portrait** — Combine two portraits side-by-side for landscape displays
- **No repeats** — Pool-based rotation instead of random
- **Configurable** — Resolution, refresh interval, favorites filter

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

| Option | Default | Description |
|--------|---------|-------------|
| Mix Ratio | 0% | Percentage of memories in the photo pool |
| Days | 90 | How far back to look for "recent" photos (0 = unlimited) |
| Memory Years | 0 | Max years back for memories (0 = unlimited) |
| Dual Portrait | Yes | Combine two portraits side-by-side |
| Resolution | 1920x1080 | Output resolution |
| Refresh Interval | 30s | Time between photo changes |

## Usage

### As a Fullscreen Background

#### Option 1: Wallpanel (Recommended)

[Wallpanel](https://github.com/j-a-n/lovelace-wallpanel) is a HACS integration that provides fullscreen backgrounds for any Lovelace view:

```yaml
wallpanel:
  enabled: true
  image_url: /api/image_proxy/image.immich_slideshow
```

#### Option 2: card-mod

Add this card to your view (requires [card-mod](https://github.com/thomasloven/lovelace-card-mod)). Works best with masonry views:

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

### As a Standard Image Entity

The integration creates a standard Home Assistant `image` entity that works with any Lovelace card:

```yaml
type: picture-entity
entity: image.immich_slideshow
show_state: false
show_name: false
```

### With View Assist

To use Immich Simple Slideshow as a background in [View Assist](https://github.com/msp1974/ViewAssist_Companion_App) dashboards:

1. **Enable file writing** in the integration options: check "Write files to disk"
2. **In View Assist settings**, configure the background:
   - **Background image source**: `Random image from local file path`
   - **Image path or url**: `backgrounds`

The integration saves images to `/config/view_assist/images/backgrounds/` by default (customizable in "Background Output Path").

### Entity Attributes

The image entity exposes these attributes for use in cards/automations:

| Attribute | Description |
|-----------|-------------|
| `is_dual_portrait` | Whether showing two photos |
| `asset_id_1` | Immich asset ID |
| `immich_url_1` | Direct link to photo in Immich |
| `original_filename_1` | Original file name |
| `date_taken_1` | When the photo was taken |
| `memory_year_1` | Year of the memory (if memory photo) |
| `years_ago_1` | How many years ago (if memory photo) |
| `city_1` / `country_1` | Location info |
| `people_1` | List of recognized people |
| `source_1` | `memory` or `recent` |
| `is_favorite_1` | Favorite status in Immich |

When `is_dual_portrait` is true, `_2` attributes are also available for the second photo.

Example usage:

```yaml
type: custom:button-card
entity: image.immich_slideshow
custom_fields:
  info: |
    [[[
      const a = entity.attributes;
      if (a.is_dual_portrait) {
        return (a.city_1 || '') + ' / ' + (a.city_2 || '');
      }
      return a.years_ago_1 ? a.years_ago_1 + ' years ago' : a.city_1 || '';
    ]]]
```

## Requirements

- Home Assistant 2024.1+
- Immich server with API access

## Known Limitations

- **HEIC format not supported** — Photos in HEIC/HEIF format are not currently supported and will be skipped. Convert to JPEG in Immich or ensure your photos are stored in a compatible format.

## License

MIT

## Credits

- Original integration: [outadoc/immich-home-assistant](https://github.com/outadoc/immich-home-assistant)
- Immich: [immich-app/immich](https://github.com/immich-app/immich)
