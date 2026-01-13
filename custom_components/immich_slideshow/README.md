# Immich Slideshow for Home Assistant

Display your Immich photos as a slideshow in Home Assistant with "On This Day" memories support.

## Features

- Fetches random photos from your Immich library
- "On This Day" memories (photos from the same date in previous years)
- Configurable mix ratio between recent photos and memories
- Dual portrait mode (combines two portrait photos side-by-side)
- Multiple resolution support
- View Assist integration (optional file writing)

## Usage

### Image Entity

The integration creates an image entity: `image.immich_slideshow`

Access the image via: `/api/image_proxy/image.immich_slideshow`

### Lovelace Background (button-card)

Use a `button-card` to display the slideshow as a full-screen background that updates automatically:

```yaml
type: custom:button-card
entity: image.immich_slideshow
show_name: false
show_icon: false
tap_action:
  action: none
styles:
  card:
    - background: |
        [[[
          return `center / cover no-repeat url("${entity.attributes.entity_picture}")`;
        ]]]
    - height: 100vh
    - border: none
    - box-shadow: none
```

### View Background (wallpanel)

For a view-level background, use the [Wallpanel](https://github.com/j-a-n/lovelace-wallpanel) integration:

```yaml
wallpanel:
  enabled: true
  image_url: /api/image_proxy/image.immich_slideshow
```

### Entity Attributes

The image entity exposes useful metadata (all per-photo attributes use `_1` suffix, `_2` when dual portrait):

| Attribute | Description |
|-----------|-------------|
| `entity_picture` | Current image URL (changes on each refresh) |
| `is_dual_portrait` | Whether showing two photos side-by-side |
| `asset_id_1` | Immich asset ID |
| `immich_url_1` | Direct link to photo in Immich |
| `date_taken_1` | When the photo was taken |
| `city_1`, `country_1` | Location info |
| `people_1` | People detected in the photo |
| `is_favorite_1` | Favorite status |
| `memory_year_1` | Year of the memory (if from memories) |
| `years_ago_1` | How many years ago |
| `source_1` | "recent" or "memory" |

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| Memories mix | 0% | Percentage of memories vs recent photos |
| Recent photos (days) | 90 | Photos from the last N days (0 = unlimited) |
| Memory years limit | 0 | Max years back for memories (0 = unlimited) |
| Dual portrait | true | Combine two portrait photos side-by-side |
| Favorites filter | all | Filter by favorite status |
| Target resolutions | 1920x1080 | Comma-separated list |
| Refresh interval | 30s | How often to change photo |
| Write files | false | Enable for View Assist local_random mode |

## API Permissions

Required Immich API key permissions:
- `asset.read`
- `asset.download`
- `memory.read`
