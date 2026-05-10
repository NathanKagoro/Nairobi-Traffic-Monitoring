# Contributions Guide

Thank you for helping improve this project.

This repository is designed so contributors can replicate the pipeline for other cities when traffic coverage is available from the selected provider.

## What You Can Contribute

1. Add monitoring points for your city.
2. Add support for a different traffic API (if TomTom does not support your location).
3. Add weather tracking for each collection time.
4. Add roadworks and accidents tracking for monitored corridors.
5. Improve data quality checks, tests, and dashboards.

## 1) Add Monitoring Points For Your Location

Update the points file:

- config/monitored_points.json

Use the same object format for each point:

```json
{
  "name": "Your Point Name",
  "lat": -6.7924,
  "lon": 39.2083,
  "category": "main_road"
}
```

Rules:

- name: clear and unique location label.
- lat: decimal latitude.
- lon: decimal longitude.
- category: use an existing category when possible.

Recommended categories:

- cbd_corridor
- major_intersection
- highway
- main_road
- commercial
- residential
- industrial
- airport
- university
- healthcare

Quality checks before opening a pull request:

- Confirm coordinates map to real roads.
- Confirm points are distributed across the city, not clustered in one area.
- Run one local collection cycle to verify parse and insert success.

## 2) Replicate The Project In Your City

You can create this stack quickly with free accounts:

- TomTom API key from developer.tomtom.com
- Supabase project URL and service role key from supabase.com

Set environment variables:

- TOMTOM_API_KEY
- SUPABASE_URL
- SUPABASE_KEY

Important:

- Your city must be supported by TomTom Traffic Flow coverage for live traffic collection.
- If unsupported, use the alternative API path described below.

## 3) Add A Different Traffic API Provider

If TomTom does not support your area, contributions are welcome for providers with similar traffic outputs.

Target behavior:

- Keep the internal snapshot format stable so database inserts continue to work.
- Map provider fields into these core snapshot fields:

- timestamp
- point_name
- latitude
- longitude
- current_speed
- free_flow_speed
- congestion_ratio
- road_closure
- confidence

Implementation suggestion:

1. Add a new collector module under collectors/.
2. Add parser logic that normalizes provider response into the snapshot schema above.
3. Keep retries, logging, and failure handling consistent with existing helpers.
4. Add provider setup instructions to README.

## 4) Add Weather Tracking

Weather context is highly valuable for congestion analysis.

Useful variables per timestamp and point:

- rainfall_mm
- temperature_c
- humidity_percent
- wind_speed_kph
- weather_code or condition

Recommended implementation:

1. Create a weather collector module.
2. Store weather in a separate table keyed by timestamp and point_name (or nearest coordinates).
3. Join traffic and weather during analysis queries/notebooks.

## 5) Add Roadworks And Accidents Tracking

Roadworks and incidents can explain sudden congestion spikes.

Possible approaches:

- Add incident endpoints from the traffic provider when available.
- Add structured manual event logs from reliable local sources.
- Track event type, start time, end time, location, and severity.

Suggested event fields:

- event_type (roadwork, crash, closure, hazard)
- point_name or geometry reference
- start_timestamp
- end_timestamp
- severity
- source

## Pull Request Checklist

Before submitting:

1. Keep changes focused and documented.
2. Run local validation and include evidence in PR description.
3. Include sample output (logs or query result) showing successful collection.
4. Update docs if setup or schema behavior changed.
5. Avoid committing secrets or private keys.

## Good Next Contributions

If you want more ideas, these are high-impact:

1. City template generator for monitored_points.json.
2. Provider coverage checker script before collection starts.
3. Data completeness report (expected vs inserted snapshots per cycle).
4. Simple dashboard notebook for daily congestion trends.
5. Automated anomaly flags for sudden speed drops.

Open an issue first for larger feature work so we can align on approach before implementation.
