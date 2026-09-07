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

## Alternatives: not pursued, because neither is free without a card (2026-09-07)

The project runs on services that cost nothing and cannot bill you: TomTom's
free tier allows ~2,500 requests/day with no payment method on file. Both
candidate replacements fail that test.

| Provider | Free allowance | Card required? | Verdict |
|---|---|---|---|
| **HERE Traffic API v7** | 30,000 transactions/month (Base plan) | **Yes.** The no-card "Limited" plan was discontinued on 2025-08-31. | Not pursued |
| **Google Routes API** | 5,000 events/month on the Pro SKU | **Yes.** A billing account with a valid payment method is required to issue an API key at all, even to stay inside the free tier. | Not pursued |

Both bill automatically on overage, so a runaway loop or a raised cadence turns
into a real invoice. That is a different risk profile from the current setup and
was declined.

Detail worth keeping, should the decision be revisited:

- **Google**: traffic-aware routing (`TRAFFIC_AWARE`, `TRAFFIC_AWARE_OPTIMAL`)
  bills as the **Pro** SKU - $10/1,000 beyond 5,000/month - not the
  10,000-event Essentials tier. The universal $200 monthly credit was retired
  in March 2025 and replaced by per-SKU allowances that do not pool.
- **HERE**: 30,000/month is genuinely workable. The current shape - 52 points
  every 30 minutes - is ~75,000/month and would not fit, but 52 points sampled
  hourly over an 18-hour day is ~28,000/month and would. Its flow-segment
  response also maps almost directly onto the existing schema.
- Neither provider's Tanzania coverage has been tested. HERE's marketing claims
  70+ countries without naming them. **If either is ever adopted, probe
  coverage before building anything** - the `check-coverage` command exists for
  exactly this, and skipping that step is what cost this project four months.
- **Mapbox** was not investigated.

### Genuinely free routes to Dar es Salaam data, if the goal is pursued

None of these give live traffic, and all are more work:

- **OSM/Overpass road network + historical speed assumptions** - no live signal,
  but free and locally independent.
- **Crowdsourced GPS traces** from daladala fleets - builds a local speed
  profile with no external provider at all.
- **Academic and institutional datasets** - UDSM, World Bank and UN-Habitat
  have published Dar es Salaam traffic counts.

### Budget shape if a routing-based provider is ever adopted

Point-sampling every 30 minutes does not survive contact with these free tiers.
52 points x 48 cycles = 2,496 requests/day, roughly 75,000/month, against a
5,000/month Google Pro allowance.

A workable free design measures **corridors** rather than points, less often:

- 8 corridors x 18 samples/day (05:00-22:00 hourly) = 144/day, ~4,300/month.

That fits inside the free tier and still resolves both rush hours. It is a
different measurement - journey time along a corridor, not spot speed at a
point - so the schema and the analysis would both need revisiting.
