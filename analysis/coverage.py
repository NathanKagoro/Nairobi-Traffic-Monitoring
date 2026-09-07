"""
Provider coverage checker.

Answers the question this project has never actually tested: does the traffic
provider return real data for these coordinates?

The README asserts TomTom has no Traffic Flow coverage in Tanzania, and the
project was pivoted to Nairobi on that basis. That claim was never verified
point by point, and it is the reason the project stopped monitoring the city
it was built for. This probes it directly.

It also separates failure modes that look identical in the collector's logs,
because `make_request` returns None for all of them:

  OK           - a real reading came back
  NO_COVERAGE  - the provider has no road segment near this coordinate
  AUTH         - the API key was rejected (expired, revoked, wrong)
  QUOTA        - the daily request allowance is exhausted
  ERROR        - anything else, with the status and body kept for inspection

Run with:  python main.py check-coverage [--city NAME] [--limit N]
"""
import logging
from collections import Counter
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

TOMTOM_TRAFFIC_FLOW_URL = (
    "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
)


def probe_point(point: Dict, api_key: str, timeout: int = 15) -> Dict:
    """Make one Traffic Flow request and classify what came back."""
    result = {
        "name": point.get("name"),
        "lat": point.get("lat"),
        "lon": point.get("lon"),
        "verdict": "ERROR",
        "status": None,
        "current_speed": None,
        "free_flow_speed": None,
        "confidence": None,
        "detail": "",
    }

    try:
        response = requests.get(
            TOMTOM_TRAFFIC_FLOW_URL,
            params={"point": f"{point['lat']},{point['lon']}", "key": api_key},
            timeout=timeout,
        )
    except Exception as e:
        result["detail"] = f"request failed: {type(e).__name__}: {e}"
        return result

    result["status"] = response.status_code
    body = response.text[:300]

    if response.status_code == 200:
        try:
            segment = response.json().get("flowSegmentData")
        except ValueError:
            result["detail"] = f"200 but body is not JSON: {body}"
            return result

        if not segment:
            result["verdict"] = "NO_COVERAGE"
            result["detail"] = "200 but no flowSegmentData in response"
            return result

        result["current_speed"] = segment.get("currentSpeed")
        result["free_flow_speed"] = segment.get("freeFlowSpeed")
        result["confidence"] = segment.get("confidence")
        result["verdict"] = "OK"
        result["detail"] = (
            f"current {result['current_speed']} / free-flow "
            f"{result['free_flow_speed']} km/h, confidence {result['confidence']}"
        )
        return result

    lowered = body.lower()

    # TomTom answers a coordinate with no nearby mapped segment with a 400.
    if response.status_code == 400 and (
        "too far" in lowered or "no route" in lowered or "segment" in lowered
    ):
        result["verdict"] = "NO_COVERAGE"
    elif response.status_code in (401, 403) and (
        "quota" in lowered or "limit" in lowered or "exceeded" in lowered
    ):
        result["verdict"] = "QUOTA"
    elif response.status_code in (401, 403):
        result["verdict"] = "AUTH"

    result["detail"] = f"HTTP {response.status_code}: {body}"
    return result


def check_coverage(points: List[Dict], api_key: str,
                   limit: Optional[int] = None) -> List[Dict]:
    """
    Probe points and return one result each.

    Probing costs one request per point against a 2,500/day free-tier
    allowance that a 30-minute collection cadence already nearly exhausts, so
    callers should sample rather than probe everything.
    """
    sample = points[:limit] if limit else points
    logger.info(f"Probing {len(sample)} of {len(points)} points "
                f"({len(sample)} API requests)")

    results = []
    for index, point in enumerate(sample, start=1):
        outcome = probe_point(point, api_key)
        logger.info(f"[{index}/{len(sample)}] {outcome['verdict']:12s} "
                    f"{outcome['name']}")
        results.append(outcome)
    return results


def render_coverage(results: List[Dict], city: str = "") -> str:
    """Render probe results as Markdown, with a plain-language conclusion."""
    counts = Counter(r["verdict"] for r in results)
    total = len(results)

    lines = [f"# Provider coverage check{f' - {city}' if city else ''}", ""]
    lines.append(f"Probed **{total}** monitoring points against the TomTom "
                 "Traffic Flow API.")
    lines.append("")
    for verdict in ("OK", "NO_COVERAGE", "AUTH", "QUOTA", "ERROR"):
        if counts.get(verdict):
            lines.append(f"- **{verdict}**: {counts[verdict]}")
    lines.append("")

    lines.append("| Verdict | Point | Status | Detail |")
    lines.append("|---|---|---:|---|")
    order = {"OK": 0, "NO_COVERAGE": 1, "QUOTA": 2, "AUTH": 3, "ERROR": 4}
    for r in sorted(results, key=lambda r: (order.get(r["verdict"], 9), r["name"] or "")):
        lines.append(f"| {r['verdict']} | {r['name']} | {r['status'] or '-'} "
                     f"| {r['detail']} |")

    lines.append("")
    lines.append("## Conclusion")
    lines.append("")
    for line in coverage_verdict(counts, total):
        lines.append(f"- {line}")

    return "\n".join(lines)


def coverage_verdict(counts: Counter, total: int) -> List[str]:
    """Plain-language reading of the counts."""
    if not total:
        return ["No points were probed."]

    ok = counts.get("OK", 0)
    out: List[str] = []

    if counts.get("AUTH"):
        out.append(f"{counts['AUTH']} of {total} points were rejected as "
                   "unauthorised. That is an API key problem, not a coverage "
                   "problem - the key is expired, revoked or wrong. Nothing can "
                   "be concluded about coverage until it is replaced.")
        return out

    if counts.get("QUOTA"):
        out.append(f"{counts['QUOTA']} of {total} points hit the request quota. "
                   "Re-run tomorrow, or on an account with headroom - coverage "
                   "cannot be judged from a quota-limited run.")
        return out

    if ok == total:
        out.append(f"Full coverage: all {total} probed points returned live "
                   "readings. This city is usable with TomTom.")
    elif ok:
        out.append(f"Partial coverage: {ok} of {total} points returned live "
                   f"readings ({100.0 * ok / total:.0f}%). The covered points are "
                   "usable; drop or relocate the rest.")
    else:
        out.append(f"No coverage: none of the {total} probed points returned a "
                   "reading. TomTom has no traffic data for this area, and a "
                   "different provider is needed.")

    if ok:
        out.append("A reading returning does not by itself prove the data is "
                   "live - run a collection cycle and then `python main.py audit` "
                   "to check whether speeds actually vary with time of day.")
    return out
