# Immich Simple Slideshow

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/benjR/immich-simple-slideshow)](https://github.com/benjR/immich-simple-slideshow/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Home Assistant custom integration for displaying photos from your [Immich](https://immich.app/) library as a slideshow.

Forked from [outadoc/immich-home-assistant](https://github.com/outadoc/immich-home-assistant).

## Features

- **Weighted sources**: recent photos, "On This Day" memories, albums and people, each with its own weight.
- **Recent boost**: photos taken or uploaded in the last few days come up more often and can repeat sooner.
- **No same-day repeats**: a photo that was shown stays out for 24 hours (a few hours for boosted photos).
- **Dual portrait**: two portraits side by side on a landscape display.
- **Filters**: include or exclude albums and people, favorites only, archived photos off by default.
- **Smooth changes**: the next photo is downloaded and resized while the current one is on screen.
- **View Assist**: can write the images to disk for use as backgrounds.

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

### Recent source

| Option | Default | Description |
|--------|---------|-------------|
| Recent days | 90 | How far back to look (0 = all time) |
| Favorites filter | All | All photos, favorites only, or no favorites |
| Boost window | 7 days | Photos taken **or uploaded** within this window are boosted (0 = off) |
| Boost share | 40 % | Share of the recent draws taken from the boost window |
| Boost reshow delay | 4 h | Hours before a boosted photo can come back (1 to 24) |

### Other options

| Option | Default | Description |
|--------|---------|-------------|
| Memory years | 0 | Max years back for memories (0 = no limit) |
| Albums include | - | Albums for the Albums source |
| Persons include | - | People for the Persons source |
| Exclude albums | - | Albums never shown, whatever the source |
| Exclude persons | - | People never shown, whatever the source |
| Include archived | No | Also draw photos archived in Immich. Roughly 40 % of some libraries is archived, so turning this on changes what you see a lot |
| Dual portrait | Yes | Pair two portraits on a landscape display |
| Resolution | 1920x1080 | Output size; several can be given, comma-separated |
| Refresh interval | 30 s | Time between photos |
| Write files | No | Save images to disk (for View Assist) |

## How photos are picked

The integration keeps a pool of up to 200 photos and refills it with 100 more when
fewer than 20 are left. Each refill draws from the enabled sources in proportion to
their weights.

- **No repeats within 24 hours.** Every photo shown is remembered, and the history
  survives restarts. Photos in the boost window use the shorter *boost reshow delay*
  instead, so the newest photos can cycle several times a day.
- **Small libraries still work.** If every candidate was shown recently, the least
  recently shown ones are used instead of leaving the screen stuck.
- **Boost.** With a 7-day window and a 40 % share, four in ten recent draws come from
  photos taken or uploaded in the last week. An old scan uploaded yesterday counts.
- **Broken photos are skipped.** See [Undisplayable photos](#undisplayable-photos).

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

## API key permissions

Create the API key in Immich under **User Settings → API Keys**. The integration
checks the key's permissions at setup and after every reload (Immich v3+ enforces
granular permissions); anything missing is shown in the config flow and as a
Repair issue in Home Assistant.

| Permission | When it's needed |
|------------|------------------|
| `asset.read` | Always (random search, metadata) |
| `asset.download` | Always (fetch the photo to display) |
| `memory.read` | Only if the **Memories** source is enabled |
| `album.read` | Only if the **Albums** source is enabled |
| `person.read` | Only if the **Persons** source is enabled |
| `user.read` | Recommended. Shows the photo owner's name |
| `asset.view` | Recommended. Lets the integration fetch Immich's JPEG rendition, so HEIC and other formats Pillow can't read still display. Without it, originals are downloaded |

> On Immich v3+, partner-shared photos appear in the random search and do **not**
> need `partner.read`.

## Immich versions

On Immich 3.2 and newer, exclusions, archived and trashed photos are filtered by the
server. On older servers the integration uses the legacy search fields: album
exclusion then only applies to photos drawn from the Albums source, because Immich
does not tell which albums an asset belongs to. Person exclusion works everywhere.

Album ids that no longer exist are ignored with a warning; Immich 3.2 would
otherwise reject the whole query.

## Undisplayable photos

A photo that can't be decoded (e.g. HEIC saved with a `.jpg` extension, PSD,
panoramas above Pillow's pixel limit) or whose original is missing on the Immich
server (repeated download failure) is skipped for 7 days, logged once with its
asset id and file name, and the next photo is shown instead of losing the slot.
Before giving up on an undecodable file, the integration retries once with
Immich's preview rendition (a server-generated, downscaled JPEG).

## Known limitations

- **Shared album assets (Immich < v3)**: `search/random` only returned photos owned
  by the user, so photos other people added to a shared album did not appear
  ([reported upstream](https://github.com/immich-app/immich/issues/28662)). Fixed in
  Immich v3+. On older servers, set up [Partners](https://immich.app/docs/features/partner-sharing) as a
  workaround.
- **HEIC**: Pillow can't decode HEIC/HEIF originals. Grant `asset.view` so the
  integration uses Immich's converted rendition; otherwise such photos are skipped.

## Requirements

- Home Assistant 2024.1+
- **Immich v1.106.0 or newer** (the integration uses Immich's plural REST API;
  older servers are detected and flagged with a Repair issue). Tested against
  Immich 3.3.1.
- An Immich API key with the [permissions above](#api-key-permissions)

## License

MIT

## Credits

- Original integration: [outadoc/immich-home-assistant](https://github.com/outadoc/immich-home-assistant)
- Immich: [immich-app/immich](https://github.com/immich-app/immich)
