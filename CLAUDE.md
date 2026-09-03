# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a personal activity statistics visualization project. It combines manually curated records, a one-time Strava website export, and incremental Garmin Connect activities. Cycling is excluded; all other activity types are included. GitHub Actions updates it daily.

## Commands

```bash
# Import the one-time Strava website export
python import_strava_export.py /path/to/strava-export

# Sync incremental Garmin data (requires GARMIN_TOKEN_KEY)
GARMIN_TOKEN_KEY="..." python sync.py

# Generate the running statistics SVG visualization
python render.py
```

## Architecture

### Data Flow
1. `import_strava_export.py` - Imports non-cycling activities from the Strava export into:
   - `data/running_records_strava_export.json` - immutable Strava history and cutoff

2. `sync.py` - Fetches Garmin activities after the Strava cutoff and merges all sources:
   - `data/running_records_garmin_sync.json` - incremental Garmin activities
   - `data/running_records_manual_add.json` - Manual records
   - `data/running_records_combined.json` - Merged dataset
   - `data/running.csv` - CSV format for rendering

3. `render.py` - Reads `data/running.csv` and generates `running.svg` with:
   - Cumulative distance chart
   - Pace violin plot
   - Monthly attendance radar chart
   - Last 12 months distance bar chart
   - Map showing run starting locations (using Natural Earth shapefiles)

### Key Dependencies
- `garminconnect` - Garmin Connect client
- `cryptography` - encrypted Garmin token persistence
- `fitdecode` - Strava FIT activity import
- `matplotlib` - Plotting (uses xkcd style)
- `cartopy` - Map rendering with shapefiles

### Data Format
CSV columns: `DT`, `distance(Km)`, `heart`, `pace`, `start_lat`, `start_lng`

### Map Data
Natural Earth 50m shapefiles are stored in `data/ne_50m/` for land, ocean, and coastline features.

## GitHub Actions

The workflow `.github/workflows/sync_render.yml` runs daily at 00:00 UTC, on pushes to main, and on manual dispatch. It requires one repository secret:

- `GARMIN_TOKEN_KEY` - Fernet key used to decrypt and re-encrypt `data/garmin_tokens.enc`

The encrypted token file is committed after every run so rotated access and refresh tokens are preserved. The built-in `GITHUB_TOKEN` has only `contents: write`; no personal access token is needed.
