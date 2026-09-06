"""
Data quality audit for collected traffic snapshots.

Pulls the traffic_snapshots table out of Supabase via the REST API and answers
one question: is the data that was collected actually usable?

Three things are checked separately, because they fail in different ways:

  1. Coverage   - did the scheduler run when it was supposed to, and did every
                  monitoring point report in each cycle?
  2. Integrity  - are the stored values internally consistent (no nulls where
                  values are required, congestion in range, no duplicate rows)?
  3. Signal     - does the data actually vary with real-world traffic? A feed
                  can be 100% complete and still be worthless if the provider
                  returns the same free-flow speed around the clock.

Run with:  python main.py audit [--days N] [--out report.md]
"""
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# Columns the audit needs. Kept narrow so paging a large table stays cheap.
SELECT_COLUMNS = (
    "id,timestamp,point_name,latitude,longitude,"
    "current_speed,free_flow_speed,congestion_ratio,road_closure,confidence"
)

PAGE_SIZE = 1000  # PostgREST caps a single response at 1000 rows by default.


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def _headers(key: str) -> Dict[str, str]:
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def count_rows(base_url: str, key: str) -> Optional[int]:
    """Ask PostgREST for an exact row count without transferring any rows."""
    headers = dict(_headers(key))
    headers["Prefer"] = "count=exact"
    headers["Range"] = "0-0"
    try:
        response = requests.get(
            f"{base_url}/rest/v1/traffic_snapshots?select=id",
            headers=headers,
            timeout=30,
        )
    except Exception as e:
        logger.error(f"Count request failed: {e}")
        return None

    if response.status_code not in (200, 206):
        logger.error(f"Count failed [{response.status_code}]: {response.text[:300]}")
        return None

    # Content-Range looks like "0-0/144231"; the part after the slash is the total.
    content_range = response.headers.get("Content-Range", "")
    if "/" in content_range:
        total = content_range.rsplit("/", 1)[1]
        if total.isdigit():
            return int(total)
    return None


def latest_timestamp(base_url: str, key: str) -> Optional[datetime]:
    """
    Fetch the single newest snapshot timestamp.

    Used by the health check, which needs to know whether collection is still
    alive without pulling the whole table.
    """
    url = (
        f"{base_url}/rest/v1/traffic_snapshots"
        "?select=timestamp&order=timestamp.desc&limit=1"
    )
    try:
        response = requests.get(url, headers=_headers(key), timeout=30)
    except Exception as e:
        logger.error(f"Latest-timestamp request failed: {e}")
        return None

    if response.status_code != 200:
        logger.error(f"Latest-timestamp failed [{response.status_code}]: "
                     f"{response.text[:300]}")
        return None

    payload = response.json()
    if not payload:
        return None
    return _parse_ts(payload[0].get("timestamp"))


def fetch_rows(base_url: str, key: str, since: Optional[datetime] = None) -> List[Dict]:
    """
    Page through traffic_snapshots in id order.

    Ordering by id rather than timestamp gives stable paging even though many
    rows share a timestamp - every point in a cycle is written within the same
    few seconds.
    """
    rows: List[Dict] = []
    offset = 0

    query = f"select={SELECT_COLUMNS}&order=id.asc"
    if since is not None:
        query += f"&timestamp=gte.{since.isoformat()}"

    while True:
        url = f"{base_url}/rest/v1/traffic_snapshots?{query}&limit={PAGE_SIZE}&offset={offset}"
        try:
            response = requests.get(url, headers=_headers(key), timeout=60)
        except Exception as e:
            logger.error(f"Fetch failed at offset {offset}: {e}")
            break

        if response.status_code != 200:
            logger.error(f"Fetch failed [{response.status_code}]: {response.text[:300]}")
            break

        page = response.json()
        if not page:
            break

        rows.extend(page)
        logger.info(f"Fetched {len(rows)} rows...")

        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return rows


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_ts(value) -> Optional[datetime]:
    """Parse the ISO-8601 text timestamp written by the collector."""
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bucket(ts: datetime, minutes: int) -> datetime:
    """
    Snap a timestamp to its collection cycle.

    Rows in one run are written seconds apart, and GitHub's cron fires late by
    anything from seconds to tens of minutes, so raw timestamps cannot be
    compared directly. Flooring to the cadence groups a run together.
    """
    epoch_minutes = int(ts.timestamp() // 60)
    floored = (epoch_minutes // minutes) * minutes
    return datetime.fromtimestamp(floored * 60, tz=timezone.utc)


def _pct(part: int, whole: int) -> float:
    return (100.0 * part / whole) if whole else 0.0


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def audit_rows(
    rows: List[Dict],
    expected_points: Optional[List[str]] = None,
    interval_minutes: int = 30,
    local_offset_hours: int = 3,
) -> Dict:
    """
    Analyse fetched snapshots and return a structured findings dictionary.

    Pure function over the row list - no network access - so it is easy to test
    against a fixture.
    """
    report: Dict = {"row_count": len(rows)}
    if not rows:
        return report

    # --- normalise ---------------------------------------------------------
    parsed = []
    unparseable = 0
    for row in rows:
        ts = _parse_ts(row.get("timestamp"))
        if ts is None:
            unparseable += 1
            continue
        parsed.append((ts, row))
    parsed.sort(key=lambda pair: pair[0])

    report["unparseable_timestamps"] = unparseable
    if not parsed:
        return report

    first_ts = parsed[0][0]
    last_ts = parsed[-1][0]
    span = last_ts - first_ts
    report["first_timestamp"] = first_ts
    report["last_timestamp"] = last_ts
    report["span_days"] = span.total_seconds() / 86400.0
    report["age_of_latest_days"] = (
        datetime.now(timezone.utc) - last_ts
    ).total_seconds() / 86400.0

    # --- coverage: cycles --------------------------------------------------
    cycles: Dict[datetime, List[Dict]] = defaultdict(list)
    for ts, row in parsed:
        cycles[_bucket(ts, interval_minutes)].append(row)

    cycle_keys = sorted(cycles)
    expected_cycles = int(span.total_seconds() // (interval_minutes * 60)) + 1
    report["cycles_observed"] = len(cycle_keys)
    report["cycles_expected"] = expected_cycles
    report["cycle_completeness_pct"] = _pct(len(cycle_keys), expected_cycles)

    # Gaps: consecutive observed cycles more than one interval apart.
    gaps = []
    for previous, current in zip(cycle_keys, cycle_keys[1:]):
        missing = int(
            (current - previous).total_seconds() // (interval_minutes * 60)
        ) - 1
        if missing > 0:
            gaps.append(
                {
                    "after": previous,
                    "before": current,
                    "missed_cycles": missing,
                    "hours": (current - previous).total_seconds() / 3600.0,
                }
            )
    gaps.sort(key=lambda g: g["missed_cycles"], reverse=True)
    report["gap_count"] = len(gaps)
    report["total_missed_cycles"] = sum(g["missed_cycles"] for g in gaps)
    report["largest_gaps"] = gaps[:10]

    # --- coverage: points per cycle ---------------------------------------
    observed_points = sorted({row.get("point_name") for _, row in parsed})
    report["distinct_points"] = len(observed_points)
    report["observed_points"] = observed_points

    if expected_points:
        expected_set = set(expected_points)
        observed_set = set(observed_points)
        report["points_configured"] = len(expected_set)
        report["points_never_collected"] = sorted(expected_set - observed_set)
        report["points_not_in_config"] = sorted(observed_set - expected_set)
        points_per_cycle_target = len(expected_set)
    else:
        points_per_cycle_target = len(observed_points)

    report["points_per_cycle_target"] = points_per_cycle_target
    sizes = [len(v) for v in cycles.values()]
    report["points_per_cycle_mean"] = mean(sizes)
    report["points_per_cycle_min"] = min(sizes)
    report["points_per_cycle_max"] = max(sizes)
    report["full_cycles"] = sum(1 for s in sizes if s >= points_per_cycle_target)
    report["partial_cycles"] = sum(1 for s in sizes if s < points_per_cycle_target)

    # --- integrity ---------------------------------------------------------
    nulls = Counter()
    numeric_fields = [
        "current_speed",
        "free_flow_speed",
        "congestion_ratio",
        "confidence",
    ]
    for _, row in parsed:
        for field in numeric_fields:
            if row.get(field) is None:
                nulls[field] += 1
    report["null_counts"] = dict(nulls)

    anomalies = Counter()
    closures = 0
    low_confidence = 0
    confidences = []
    for _, row in parsed:
        current = row.get("current_speed")
        free_flow = row.get("free_flow_speed")
        ratio = row.get("congestion_ratio")
        confidence = row.get("confidence")

        if current is not None and current <= 0:
            anomalies["non_positive_current_speed"] += 1
        if free_flow is not None and free_flow <= 0:
            anomalies["non_positive_free_flow_speed"] += 1
        if current is not None and free_flow is not None and current > free_flow:
            anomalies["current_above_free_flow"] += 1
        if ratio is not None and not (0.0 <= ratio <= 1.0):
            anomalies["congestion_ratio_out_of_range"] += 1
        if row.get("road_closure"):
            closures += 1
        if confidence is not None:
            confidences.append(confidence)
            if confidence < 0.5:
                low_confidence += 1
    report["anomalies"] = dict(anomalies)
    report["road_closure_rows"] = closures
    report["low_confidence_rows"] = low_confidence
    report["confidence_mean"] = mean(confidences) if confidences else None

    # Duplicates: the same point recorded twice inside one cycle. Would mean a
    # cycle ran twice (overlapping runs) and the series is double counted.
    pair_counts = Counter()
    for ts, row in parsed:
        pair_counts[(_bucket(ts, interval_minutes), row.get("point_name"))] += 1
    duplicate_rows = sum(count - 1 for count in pair_counts.values() if count > 1)
    report["duplicate_rows"] = duplicate_rows
    report["duplicate_pct"] = _pct(duplicate_rows, len(parsed))

    # A point should always be reported at the same coordinates. Drift means the
    # config was edited mid-history and the series is not comparable over time.
    coords_per_point = defaultdict(set)
    for _, row in parsed:
        coords_per_point[row.get("point_name")].add(
            (row.get("latitude"), row.get("longitude"))
        )
    report["points_with_moving_coords"] = sorted(
        name for name, coords in coords_per_point.items() if len(coords) > 1
    )

    # --- signal ------------------------------------------------------------
    # The important test. If current_speed never moves away from free_flow_speed,
    # the provider has no live probe data for that road and the series is a
    # constant dressed up as a measurement.
    per_point: Dict[str, Dict] = {}
    for ts, row in parsed:
        name = row.get("point_name")
        entry = per_point.setdefault(
            name,
            {
                "samples": 0,
                "speeds": [],
                "ratios": [],
                "confidences": [],
                "at_free_flow": 0,
                "series": [],
            },
        )
        entry["samples"] += 1
        current = row.get("current_speed")
        free_flow = row.get("free_flow_speed")
        ratio = row.get("congestion_ratio")
        confidence = row.get("confidence")

        if current is not None:
            entry["speeds"].append(current)
            entry["series"].append((ts, current))
        if ratio is not None:
            entry["ratios"].append(ratio)
        if confidence is not None:
            entry["confidences"].append(confidence)
        if current is not None and free_flow is not None and current >= free_flow:
            entry["at_free_flow"] += 1

    point_stats = []
    for name, entry in per_point.items():
        speeds = entry["speeds"]
        ratios = entry["ratios"]
        series = sorted(entry["series"])
        # How often a reading is identical to the previous cycle. High values
        # mean a stale or cached feed rather than a live measurement.
        repeats = sum(1 for a, b in zip(series, series[1:]) if a[1] == b[1])
        point_stats.append(
            {
                "point_name": name,
                "samples": entry["samples"],
                "coverage_pct": _pct(entry["samples"], len(cycle_keys)),
                "distinct_speeds": len(set(speeds)),
                "speed_mean": mean(speeds) if speeds else None,
                "speed_stdev": pstdev(speeds) if len(speeds) > 1 else 0.0,
                "congestion_mean": mean(ratios) if ratios else None,
                "congestion_max": max(ratios) if ratios else None,
                "at_free_flow_pct": _pct(entry["at_free_flow"], entry["samples"]),
                "repeat_pct": _pct(repeats, max(len(series) - 1, 1)),
                "confidence_mean": (
                    mean(entry["confidences"]) if entry["confidences"] else None
                ),
            }
        )
    point_stats.sort(key=lambda s: s["coverage_pct"])
    report["point_stats"] = point_stats

    # A point whose speed never changes carries no information at all.
    report["static_points"] = [
        s["point_name"] for s in point_stats if s["distinct_speeds"] <= 1
    ]
    # Near static: fewer than 5 distinct readings across the whole history.
    report["near_static_points"] = [
        s["point_name"] for s in point_stats if 1 < s["distinct_speeds"] < 5
    ]
    report["always_free_flow_points"] = [
        s["point_name"] for s in point_stats if s["at_free_flow_pct"] >= 99.0
    ]

    # --- signal: does congestion follow the working day? -------------------
    # Real urban traffic has a morning and an evening peak. If the hourly
    # profile is flat, the feed is not tracking anything real.
    by_hour: Dict[int, List[float]] = defaultdict(list)
    for ts, row in parsed:
        ratio = row.get("congestion_ratio")
        if ratio is None:
            continue
        local_hour = (ts + timedelta(hours=local_offset_hours)).hour
        by_hour[local_hour].append(ratio)
    hourly = {
        hour: {"mean_congestion": mean(vals), "samples": len(vals)}
        for hour, vals in sorted(by_hour.items())
    }
    report["hourly_congestion"] = hourly

    if hourly:
        hour_means = [v["mean_congestion"] for v in hourly.values()]
        peak_hours = [h for h in (7, 8, 17, 18) if h in hourly]
        night_hours = [h for h in (0, 1, 2, 3, 4) if h in hourly]
        report["congestion_overall_mean"] = mean(hour_means)
        report["congestion_hourly_spread"] = max(hour_means) - min(hour_means)
        if peak_hours and night_hours:
            peak = mean(hourly[h]["mean_congestion"] for h in peak_hours)
            night = mean(hourly[h]["mean_congestion"] for h in night_hours)
            report["congestion_peak_mean"] = peak
            report["congestion_night_mean"] = night
            report["rush_hour_lift"] = peak - night

    return report


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _fmt(value, spec: str = ".2f", dash: str = "-") -> str:
    if value is None:
        return dash
    if isinstance(value, float):
        return format(value, spec)
    return str(value)


def render_report(report: Dict, worst_points: int = 15) -> str:
    """Render the findings dictionary as a readable Markdown report."""
    lines: List[str] = []
    add = lines.append

    add("# Traffic data quality audit")
    add("")
    add(f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
    add("")

    if not report.get("row_count"):
        add("**No rows found in `traffic_snapshots`.** Either nothing was ever "
            "stored, or the credentials point at a different project.")
        return "\n".join(lines)

    add("## 1. Coverage")
    add("")
    add(f"- Rows: **{report['row_count']:,}**")
    add(f"- Window: **{report['first_timestamp']:%Y-%m-%d %H:%M} UTC** "
        f"to **{report['last_timestamp']:%Y-%m-%d %H:%M} UTC** "
        f"({report['span_days']:.1f} days)")
    add(f"- Most recent snapshot is **{report['age_of_latest_days']:.1f} days old**")
    add(f"- Collection cycles: **{report['cycles_observed']:,} of "
        f"{report['cycles_expected']:,} expected** "
        f"({report['cycle_completeness_pct']:.1f}%)")
    add(f"- Missed cycles: **{report['total_missed_cycles']:,}** "
        f"across {report['gap_count']:,} gaps")
    add(f"- Points per cycle: mean **{report['points_per_cycle_mean']:.1f}**, "
        f"min {report['points_per_cycle_min']}, max {report['points_per_cycle_max']} "
        f"(target {report['points_per_cycle_target']})")
    add(f"- Complete cycles: **{report['full_cycles']:,}**, "
        f"partial: **{report['partial_cycles']:,}**")

    if report.get("points_never_collected"):
        add(f"- Configured points that never returned data "
            f"(**{len(report['points_never_collected'])}**): "
            + ", ".join(report["points_never_collected"]))
    if report.get("points_not_in_config"):
        add("- Points in the database but no longer in config: "
            + ", ".join(report["points_not_in_config"]))

    if report.get("largest_gaps"):
        add("")
        add("Largest gaps:")
        add("")
        add("| From (UTC) | To (UTC) | Missed cycles | Hours |")
        add("|---|---|---:|---:|")
        for gap in report["largest_gaps"]:
            add(f"| {gap['after']:%Y-%m-%d %H:%M} | {gap['before']:%Y-%m-%d %H:%M} "
                f"| {gap['missed_cycles']:,} | {gap['hours']:.1f} |")

    add("")
    add("## 2. Integrity")
    add("")
    nulls = report.get("null_counts") or {}
    if nulls:
        for field, count in sorted(nulls.items(), key=lambda kv: -kv[1]):
            add(f"- Null `{field}`: **{count:,}** "
                f"({_pct(count, report['row_count']):.1f}%)")
    else:
        add("- No null values in the numeric columns")

    anomalies = report.get("anomalies") or {}
    if anomalies:
        for name, count in sorted(anomalies.items(), key=lambda kv: -kv[1]):
            add(f"- `{name}`: **{count:,}** rows")
    else:
        add("- No out-of-range or contradictory values")

    add(f"- Duplicate rows (same point twice in one cycle): "
        f"**{report['duplicate_rows']:,}** ({report['duplicate_pct']:.2f}%)")
    add(f"- Rows flagged as road closure: **{report['road_closure_rows']:,}**")
    add(f"- Rows with confidence below 0.5: **{report['low_confidence_rows']:,}** "
        f"(mean confidence {_fmt(report.get('confidence_mean'))})")
    if report.get("points_with_moving_coords"):
        add("- Points whose coordinates changed mid-history: "
            + ", ".join(report["points_with_moving_coords"]))

    add("")
    add("## 3. Signal")
    add("")
    add("Does the data track real traffic, or is it a constant?")
    add("")
    static = report.get("static_points") or []
    near_static = report.get("near_static_points") or []
    always_ff = report.get("always_free_flow_points") or []
    add(f"- Points whose speed **never changed**: **{len(static)}**"
        + (" - " + ", ".join(static) if static else ""))
    add(f"- Points with fewer than 5 distinct speeds: **{len(near_static)}**"
        + (" - " + ", ".join(near_static) if near_static else ""))
    add(f"- Points at or above free-flow 99%+ of the time: **{len(always_ff)}**"
        + (" - " + ", ".join(always_ff) if always_ff else ""))

    if "rush_hour_lift" in report:
        add(f"- Mean congestion at rush hour (07, 08, 17, 18 local): "
            f"**{report['congestion_peak_mean']:.3f}**")
        add(f"- Mean congestion overnight (00-04 local): "
            f"**{report['congestion_night_mean']:.3f}**")
        add(f"- Rush-hour lift: **{report['rush_hour_lift']:+.3f}** "
            "(a clearly positive value is what a working feed looks like)")

    hourly = report.get("hourly_congestion") or {}
    if hourly:
        add("")
        add("Mean congestion by local hour (UTC+3):")
        add("")
        add("| Hour | Mean congestion | Samples |")
        add("|---:|---|---:|")
        for hour, stats in hourly.items():
            bar = "#" * int(round(stats["mean_congestion"] * 40))
            add(f"| {hour:02d} | {stats['mean_congestion']:.3f} {bar} "
                f"| {stats['samples']:,} |")

    stats = report.get("point_stats") or []
    if stats:
        add("")
        add(f"## 4. Per-point detail (worst {min(worst_points, len(stats))} by coverage)")
        add("")
        add("| Point | Samples | Coverage % | Distinct speeds | Mean speed | "
            "Speed stdev | Mean congestion | At free-flow % | Confidence |")
        add("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for s in stats[:worst_points]:
            add(
                f"| {s['point_name']} | {s['samples']:,} | {s['coverage_pct']:.1f} "
                f"| {s['distinct_speeds']} | {_fmt(s['speed_mean'], '.1f')} "
                f"| {_fmt(s['speed_stdev'], '.2f')} "
                f"| {_fmt(s['congestion_mean'], '.3f')} "
                f"| {s['at_free_flow_pct']:.1f} "
                f"| {_fmt(s['confidence_mean'])} |"
            )

    add("")
    add("## Verdict")
    add("")
    for line in verdict_lines(report):
        add(f"- {line}")

    return "\n".join(lines)


def verdict_lines(report: Dict) -> List[str]:
    """Plain-language conclusions, worst first."""
    out: List[str] = []

    if not report.get("row_count"):
        return ["No data at all - the pipeline never successfully stored a row."]

    completeness = report.get("cycle_completeness_pct", 0.0)
    if completeness >= 95:
        out.append(f"Scheduling was reliable: {completeness:.1f}% of expected cycles ran.")
    elif completeness >= 75:
        out.append(f"Scheduling was patchy: only {completeness:.1f}% of expected cycles "
                   "ran. GitHub's cron is best-effort and drops runs under load.")
    else:
        out.append(f"Scheduling was unreliable: only {completeness:.1f}% of expected "
                   "cycles ran.")

    target = report.get("points_per_cycle_target", 0)
    mean_points = report.get("points_per_cycle_mean", 0)
    if target and mean_points < target * 0.95:
        out.append(f"Cycles were usually incomplete: {mean_points:.1f} of {target} points "
                   "reported on average - points are failing or being rate limited.")

    if report.get("duplicate_rows"):
        out.append(f"{report['duplicate_rows']:,} duplicate rows - any average over the "
                   "raw table is skewed towards the duplicated cycles.")

    static_total = len(report.get("static_points") or []) + len(
        report.get("near_static_points") or []
    )
    if static_total:
        noun = "point carries" if static_total == 1 else "points carry"
        out.append(f"{static_total} {noun} little or no variation - the provider has no "
                   "live probe data there and those series are not measurements.")

    lift = report.get("rush_hour_lift")
    if lift is not None:
        if lift >= 0.05:
            out.append(f"The data has real signal: congestion is {lift:+.3f} higher at "
                       "rush hour than overnight, which is what a working feed looks like.")
        elif lift >= 0.01:
            out.append(f"Weak signal: rush hour is only {lift:+.3f} above overnight. "
                       "Usable for coarse trend work, marginal for anything finer.")
        else:
            out.append(f"No diurnal signal ({lift:+.3f} rush-hour lift). The feed is not "
                       "tracking real congestion, whatever the row count says.")

    age = report.get("age_of_latest_days")
    if age is not None and age > 2:
        out.append(f"Collection is currently dead: the newest row is {age:.0f} days old.")

    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_audit(
    supabase_url: str,
    supabase_key: str,
    expected_points: Optional[List[str]] = None,
    days: Optional[int] = None,
    interval_minutes: int = 30,
    local_offset_hours: int = 3,
) -> Optional[Dict]:
    """Fetch snapshots and audit them. Returns the findings dict, or None on failure."""
    base_url = supabase_url.rstrip("/")

    total = count_rows(base_url, supabase_key)
    if total is None:
        logger.error("Could not read traffic_snapshots. Check the credentials, and "
                     "check the Supabase project is not paused.")
        return None

    logger.info(f"Table holds {total:,} rows")
    if total == 0:
        return {"row_count": 0}

    since = None
    if days:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        logger.info(f"Restricting audit to snapshots since {since:%Y-%m-%d}")

    rows = fetch_rows(base_url, supabase_key, since=since)
    if not rows:
        logger.error("Fetched no rows")
        return {"row_count": 0}

    logger.info(f"Auditing {len(rows):,} rows")
    return audit_rows(
        rows,
        expected_points=expected_points,
        interval_minutes=interval_minutes,
        local_offset_hours=local_offset_hours,
    )
