# Nairobi Traffic Monitoring System

A lightweight, Python-based traffic data collection pipeline for East African urban monitoring. Collects traffic data from TomTom API for 51 strategic monitoring points in Nairobi, Kenya every 30 minutes.

> **Note on Project Scope**: This project was originally designed for Dar es Salaam, Tanzania. However, TomTom's Traffic Flow API does not provide coverage in Tanzania or Uganda. The monitoring points were pivoted to Nairobi, Kenya, which has full TomTom traffic coverage. For more information on coverage limitations and alternative data sources for Dar es Salaam and Uganda, see [Future Directions](#future-directions) below.

## Architecture

**Phase 1 (Current Implementation)**
- **Collection**: TomTom Traffic Flow API queries
- **Storage**: Supabase PostgreSQL (free tier)
- **Scheduling**: GitHub Actions (runs every 30 minutes)
- **Dependencies**: Minimal (`requests`, `psycopg2`, `pandas`)

**Data Pipeline**
```
GitHub Actions (scheduler)
    ↓
main.py collect()
    ↓
TomTomCollector (API calls)
    ↓
DatabaseManager (batch insert)
    ↓
Supabase PostgreSQL (storage)
```

## Setup

### Prerequisites

- GitHub account (public or private repository)
- Supabase account (free tier)
- TomTom API key (free tier)
- Python 3.11+ (for local testing)

### Step 1: Create Supabase Project

1. Go to [supabase.com](https://supabase.com)
2. Create a new project (free tier is fine)
3. Wait for project to be provisioned
4. Get your credentials:
   - **Project URL**: `https://[project-id].supabase.co`
   - **API Key**: Go to Settings → API → Service role key

### Step 2: Get TomTom API Key

1. Go to [developer.tomtom.com](https://developer.tomtom.com)
2. Create an account and sign in
3. Get your API key from the dashboard (free tier allows ~2,500 requests/day)

### Step 3: Clone Repository

```bash
git clone https://github.com/YOUR_USERNAME/dar-traffic-monitoring
cd dar-traffic-monitoring
```

### Step 4: Set GitHub Secrets

In your GitHub repository:

1. Go to **Settings** → **Secrets and variables** → **Actions**
2. Create three secrets:
   - `TOMTOM_API_KEY`: Your TomTom API key
   - `SUPABASE_URL`: Your Supabase project URL
   - `SUPABASE_KEY`: Your Supabase API key

### Step 5: Initialize Database

Run once before first collection:

```bash
# Local setup (optional, for testing)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Set environment variables
export TOMTOM_API_KEY="your_key"
export SUPABASE_URL="your_url"
export SUPABASE_KEY="your_key"

# Initialize database schema
python main.py init
```

### Step 6: Test Locally (Optional)

```bash
# Run a single collection cycle
python main.py collect

# Check Supabase: Go to SQL Editor and run:
# SELECT COUNT(*) FROM traffic_snapshots;
```

### Step 7: Push to GitHub & Enable Actions

```bash
git add .
git commit -m "Initial traffic monitoring setup"
git push origin main
```

Collection will start automatically every 30 minutes. Monitor runs in:
**Actions** tab → **Collect Traffic Data** workflow

## Monitoring Points

**51 strategic locations covering Nairobi:**
- CBD corridors (Tom Mboya St, Dedan Kimathi Ave, Kenyatta Ave)
- Major highways (Southern Bypass, Eastern Bypass, Northern Bypass, Thika Road)
- Airport corridor (JKIA approaches)
- Commercial zones (Westlands, Gigiri, Upper Hill)
- Residential areas (Karen, Langata, Parklands, Muthaiga, Kilimani)
- Industrial zones (Industrial Area, Dandora, Embakasi)
- Key institutions (University of Nairobi, Kenyatta National Hospital)
- Outer ring road segments

**Categories:**
- `cbd_corridor`: City center routes
- `major_intersection`: Peak traffic areas
- `highway`: Bypass and major roads
- `main_road`: Secondary arterial roads
- `commercial`: Business/commercial zones
- `residential`: Residential areas
- `industrial`: Industrial zones
- `airport`: Airport access points
- `university`: University routes
- `healthcare`: Hospital access roads

Configured in `config/monitored_points.json`

## Database Schema

### traffic_snapshots

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL | Primary key |
| `timestamp` | TEXT | ISO 8601 timestamp (UTC) |
| `point_name` | TEXT | Monitoring point name |
| `latitude` | REAL | Latitude coordinate |
| `longitude` | REAL | Longitude coordinate |
| `current_speed` | REAL | Current traffic speed (km/h) |
| `free_flow_speed` | REAL | Free flow speed (km/h) |
| `congestion_ratio` | REAL | 0-1 (0=no congestion, 1=severe) |
| `road_closure` | INTEGER | 0=open, 1=closed |
| `confidence` | REAL | Data confidence (0-1) |
| `created_at` | TIMESTAMP | Database insertion time |

**Indexes:**
- `timestamp` (for time-range queries)
- `point_name` (for location-based queries)

## Querying Data

### Get Latest Data for All Points

```sql
SELECT DISTINCT ON (point_name) *
FROM traffic_snapshots
ORDER BY point_name, timestamp DESC;
```

### Get Data for Specific Time Range

```sql
SELECT * FROM traffic_snapshots
WHERE timestamp >= '2026-05-08T08:00:00Z'
  AND timestamp <= '2026-05-08T09:00:00Z'
ORDER BY timestamp DESC;
```

### Get Average Speed by Point

```sql
SELECT point_name, AVG(current_speed) as avg_speed, COUNT(*) as samples
FROM traffic_snapshots
WHERE timestamp >= NOW() - INTERVAL '7 days'
GROUP BY point_name
ORDER BY avg_speed ASC;
```

## Performance

**Data Volume (30-minute intervals)**
- Points: 50
- Collection cycles/day: 48
- Rows/day: 2,400
- Rows/month: ~72,000
- Storage/month: ~3-4 MB

**Supabase Free Tier Capacity**
- Storage: 500 MB
- Estimated lifespan: ~11 years at current rate

**API Costs**
- TomTom free tier: ~2,500 requests/day
- Current usage: ~2,400 requests/day (within free tier)
- Supabase: Free tier (adequate)

## Coverage & Limitations

### Why Nairobi, Not Dar es Salaam?

TomTom's Traffic Flow API does **not** cover Tanzania or Uganda. This is due to insufficient probe vehicle data (GPS from navigation app users) in these countries. The following coverage applies in East Africa:

| Country | TomTom Coverage | HERE Maps Coverage |
|---------|-----------------|-------------------|
| **Kenya** | ✅ (Nairobi) | ✅ (Limited) |
| **Tanzania** | ❌ | ❌ |
| **Uganda** | ❌ | ❌ |

**Other Free/Paid Options Evaluated:**
- HERE Maps Traffic API: No Tanzania/Uganda coverage
- Mapbox: No East Africa traffic data
- Google Maps: No free tier for traffic flow
- Uber Movement: Archived (no longer updated for Dar es Salaam)

## Future Directions

### Option 1: Pilot Alternative Data Sources for Dar es Salaam & Uganda

**OpenStreetMap-based collection:**
- Use Overpass API to extract road network and historical speeds
- Combine with manual traffic surveys or academic datasets
- No real-time data, but cheaper and locally independent

**Crowdsourced GPS data:**
- Collect anonymized GPS traces from dala-dala (matatu) fleets
- Build local speed profiles without relying on external APIs
- Fits the East African research context better

### Option 2: Academic Partnerships

UDSM and international urban mobility research teams (World Bank, UN-Habitat) have published Dar es Salaam traffic datasets:
- Manual traffic counts at strategic intersections
- Could seed a local database
- Combine with progressive real-time collection infrastructure

### Option 3: Expand to Other East African Cities

Once the Nairobi pipeline is stable (2-4 weeks of data):
- Add Kigali, Rwanda (TomTom + HERE coverage unclear, needs verification)
- Add other Kenyan cities (Mombasa, Kisumu)
- Establish regional comparison baseline

## Future Enhancements

**Phase 2**: Weather data integration
- Add rainfall collection
- Merge with traffic data

**Phase 3**: Traffic analysis
- Congestion trends
- Rush-hour patterns
- Anomaly detection

**Phase 4**: Graph-based routing
- OSMnx integration
- Network analysis

**Phase 5**: AI/Forecasting
- Traffic predictions
- Event disruption modeling

## Troubleshooting

### No data appearing in database

1. Check GitHub Actions logs: **Actions** → **Collect Traffic Data** → Latest run
2. Verify secrets are set correctly
3. Test locally: `python main.py collect`
4. Check Supabase connection: Run `python main.py init` again

### GitHub Actions fails with "Rate limit"

TomTom rate limit exceeded. Happens if:
- Multiple collection runs triggered simultaneously
- API quota exhausted
- Solution: Check TomTom dashboard; reduce collection frequency if needed

### Supabase connection timeout

1. Verify project is running (Supabase dashboard)
2. Check firewall/VPN isn't blocking access
3. Verify credentials are correct

## Project Structure

```
dar-traffic-monitoring/
├── config/
│   ├── settings.py              # Configuration (API keys, paths)
│   └── monitored_points.json    # 50 monitoring locations
├── collectors/
│   └── tomtom_collector.py      # TomTom API integration
├── database/
│   ├── init_db.py               # Schema initialization
│   └── database_manager.py      # CRUD operations
├── utils/
│   ├── api_helpers.py           # Request/retry logic
│   ├── logger.py                # Logging configuration
│   └── time_helpers.py          # Timestamp utilities
├── notebooks/                   # Jupyter notebooks for analysis
├── .github/workflows/
│   └── collect-traffic.yml      # GitHub Actions scheduler
├── main.py                      # Entry point (collect/init)
├── requirements.txt             # Python dependencies
└── README.md                    # This file
```

## Security

- **API Keys**: Stored as GitHub repository secrets, never in code
- **Database**: Supabase enforces column-level security
- **Public Repository**: Safe (no credentials exposed)
- **Best Practice**: Rotate keys periodically via Supabase/TomTom dashboards

## License

MIT

## Support

For issues or questions:
1. Check GitHub Actions logs for detailed errors
2. Review Supabase dashboard for database status
3. Verify TomTom API key is active and has quota remaining
