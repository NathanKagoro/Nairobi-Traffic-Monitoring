# Provider coverage findings

Evidence for which traffic providers can and cannot serve this project, so the
question does not have to be re-litigated from memory. Add a dated section when
a provider is tested.

---

## TomTom Traffic Flow - Dar es Salaam: NO COVERAGE (verified 2026-09-07)

**Result: 52 of 52 points returned `NO_COVERAGE`. Zero readings.**

Every point returned the same HTTP 400:

```json
{"error": "Point too far from nearest existing segment.",
 "httpStatusCode": 400,
 "detailedError": {"code": "INVALID_REQUEST",
                   "message": "Point too far from nearest existing segment."}}
```

Method: `python main.py check-coverage --city dar_es_salaam --limit 52`, run
from the Diagnostics workflow against the live `TOMTOM_API_KEY`.

### Why this result is trustworthy

The same conclusion was reached in May 2026 and acted on, but the evidence then
was weak: it came from a session that was simultaneously fixing a zoom-level
bug, changing the database transport and debugging response parsing, and the
collector returned `None` for every kind of failure. A coverage gap, a bad key
and a malformed request were indistinguishable.

This run rules out each competing explanation:

| Alternative explanation | Ruled out by |
|---|---|
| API key expired or invalid | The same key returned 52/52 successful readings for Nairobi minutes earlier. A rejected key gives 403, not 400. |
| Quota exhausted | Quota errors are 403 with a quota message; these are 400s with a geometry message. |
| Bad coordinates | All 52 points were generated from OpenStreetMap way geometry and verified against Nominatim: 48 confirmed on the road they name, 4 unverifiable, 0 mismatched. |
| Points in obscure locations | The set spans the CBD (Samora Avenue, Sokoine Drive, Azikiwe Road) and every major arterial (Morogoro, Bagamoyo, Kilwa, Nyerere, Ali Hassan Mwinyi, Nelson Mandela). |
| A transient provider fault | A uniform, specific geometry error across 52 distinct coordinates is a data-coverage answer, not an outage. |

"Point too far from nearest existing segment" is TomTom reporting that its
*traffic-enabled* segment database has nothing near the coordinate. TomTom map
coverage and TomTom traffic coverage are different products; Tanzania has the
former and not the latter.

**Conclusion: TomTom cannot serve Dar es Salaam. A different provider is
required.** The May 2026 pivot to Nairobi was the right call, for a reason that
had not actually been established at the time.

---

## TomTom Traffic Flow - Nairobi: COVERED (verified 2026-09-07)

`Collection complete: 52 successful, 0 failed` in run 34083003107. Nairobi is
served normally by the same key.

Note this only establishes that readings are *returned*. Whether they carry
real signal - speeds that move with time of day rather than a static free-flow
figure - is a separate question, answered by `python main.py audit` and its
rush-hour lift measure.

---

## Untested alternatives

Do not act on the table below without probing first. That is the mistake this
document exists to prevent.

| Provider | Free tier | Notes |
|---|---|---|
| Google Routes API | 5,000 events/month | Traffic-aware routing (`TRAFFIC_AWARE`, `TRAFFIC_AWARE_OPTIMAL`) is billed as the **Pro** SKU at $10/1,000 beyond the free tier - not the 10,000-event Essentials tier. Congestion would be derived from duration versus static duration rather than read as a speed. |
| HERE Traffic API v7 | Freemium tier | Covers 70+ countries; whether Tanzania is among them is not established. Returns flow segments closest in shape to the current schema. |
| Mapbox | Free tier | Traffic-aware directions; Tanzania coverage unclear. |

### Budget shape if switching to a routing-based provider

Point-sampling every 30 minutes does not survive contact with these free tiers.
52 points x 48 cycles = 2,496 requests/day, roughly 75,000/month, against a
5,000/month Google Pro allowance.

A workable free design measures **corridors** rather than points, less often:

- 8 corridors x 18 samples/day (05:00-22:00 hourly) = 144/day, ~4,300/month.

That fits inside the free tier and still resolves both rush hours. It is a
different measurement - journey time along a corridor, not spot speed at a
point - so the schema and the analysis would both need revisiting.
