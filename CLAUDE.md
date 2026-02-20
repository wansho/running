# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a personal running statistics visualization project that syncs running data from Strava and generates an SVG visualization. The project automatically updates daily via GitHub Actions.

## Commands

```bash
# Sync running data from Strava (requires STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, STRAVA_REFRESH_TOKEN env vars)
python sync.py

# Generate the running statistics SVG visualization
python render.py
```

## Architecture

### Data Flow
1. `sync.py` - Fetches running activities from Strava API, merges with manually added records, outputs:
   - `data/running_records_strava_sync.json` - Strava activities
   - `data/running_records_manual_add.json` - Manual records
   - `data/running_records_combined.json` - Merged dataset
   - `data/running.csv` - CSV format for rendering

2. `render.py` - Reads `data/running.csv` and generates `running.svg` with:
   - Cumulative distance chart
   - Pace violin plot
   - Monthly attendance radar chart
   - Last 12 months distance bar chart
   - Map showing run starting locations (using Natural Earth shapefiles)

### Key Dependencies
- `stravalib` - Strava API client
- `matplotlib` - Plotting (uses xkcd style)
- `cartopy` - Map rendering with shapefiles

### Data Format
CSV columns: `DT`, `distance(Km)`, `heart`, `pace`, `start_lat`, `start_lng`

### Map Data
Natural Earth 50m shapefiles are stored in `data/ne_50m/` for land, ocean, and coastline features.

## GitHub Actions

The workflow `.github/workflows/sync_render.yml` runs daily at 00:00 UTC and on pushes to main. It requires these repository secrets:
- `STRAVA_CLIENT_ID`
- `STRAVA_CLIENT_SECRET`
- `STRAVA_REFRESH_TOKEN`
- `PAT_TOKEN`
