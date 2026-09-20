# Dashboard spend guards — verification report

> **Status: findings for review.** Measured against production on 2026-09-19.
> These are a dated snapshot taken to resolve `docs/dashboard-spec.md` §13.4,
> not a live baseline. Re-measure before treating any number here as current.

## 1. Verdict

GCP publishes no per-service-account daily bytes quota, so the isolation §13.4
asked for cannot be bought with a dashboard-scoped limit. It can be bought with
a **per-user-per-day** quota instead, which gives every principal its own
bucket and therefore stops the dashboard from consuming the pipeline's
allowance without a second project.

The exposure being guarded is also much smaller than the spec assumed. The
dashboard's whole BigQuery surface is ~40 MB per cold load. The dominant spend
vector is **Cloud Run**, roughly three orders of magnitude larger, and no
BigQuery quota touches it.

## 2. There is no per-identity BigQuery quota

`bigquery.googleapis.com/quota/query/usage` exposes exactly two limit buckets
on this project, and neither carries a `dimensions` field. No other BigQuery
quota metric exposes a principal dimension.

<!-- prettier-ignore -->
| Unit | Default limit | Effective limit | Meaning |
|---|---|---|---|
| `1/d/{project}` | 209,715,200 | 209,715,200 | 200 TiB/day, project-wide |
| `1/d/{project}/{user}` | 2^63−1 | 2^63−1 | unlimited, per principal |

Two traps worth pinning:

- **The metric's unit is `MiBy`, not bytes.** An override written as a byte
  count is 2^20 too large and silently does nothing.
- **The project default is already a real ceiling** — 200 TiB/day, or roughly
  $1,250/day at on-demand rates. "No quota set" is not "no exposure".

`{user}` is applied uniformly to every principal. One number is set and each
identity gets its own bucket of that size; the bucket is not selectable per
service account.

## 3. Measured BigQuery exposure

Production gold, 2026-09-19:

<!-- prettier-ignore -->
| Relation | Rows | Logical bytes |
|---|---|---|
| `gold_ai_share_by_year` | 154 | 6,237 |
| `gold_citation_age_by_year` | 42 | 3,304 |
| `gold_citation_gini_by_subfield` | 1,001 | 164,528 |
| `gold_citation_gini_by_group` | 273 | 28,028 |
| **Total** | **1,470** | **202,097 (197 KiB)** |

BigQuery's on-demand floor is 10 MB billed per table referenced per query, so
the four fixed queries bill **~40 MB per cold snapshot load regardless of how
small gold actually is**. The spec's `maximum_bytes_billed` of 100 MiB per
query (§4.2) is about ten times above anything these queries can reach; it is
a sanity guard, not a binding constraint.

Even at an implausible 200 cold loads per day that is 8 GB/day — on the order
of $0.05/day, against a 1 TiB/month free tier that the pipeline also draws on.
Most repeats cost nothing anyway: BigQuery's own 24-hour result cache only
invalidates when dbt replaces a table.

## 4. Measured pipeline consumption

From `INFORMATION_SCHEMA.JOBS_BY_PROJECT`, query jobs over 180 days. This sizes
the floor under any per-user ceiling.

<!-- prettier-ignore -->
| Day | Identity | Jobs | GiB billed |
|---|---|---|---|
| 2026-06-24 | `dbt-runner` | 23 | 48.04 |
| 2026-07-29 | `dbt-runner` | 280 | 19.72 |
| 2026-07-30 | `dbt-runner` | 580 | 15.68 |
| 2026-07-30 | developer ADC | 39 | 6.96 |

The worst observed day is a full prod build at 48.04 GiB. Test-heavy days are
cheap: 580 jobs cost less than a quarter of what 23 jobs cost on the build day.

## 5. The dominant exposure is Cloud Run

Streamlit holds a long-lived websocket per open browser tab, and Cloud Run's
request-based billing allocates CPU for the duration of a request. Billed
instance-seconds therefore track **how long a tab stays open**, not how much
computation happens. The 120 s request timeout in §13.1 forces a reconnect, not
a billing pause.

One instance held active for a 30-day month is 2,592,000 instance-seconds. At
the 1 vCPU / 1 GiB shape this is on the order of **$90–100/month gross**,
before the monthly free tier.

> The per-second rate behind that figure could not be verified in the session
> that produced this report (no web access). The arithmetic is exact; confirm
> the europe-west3 rate before relying on the currency amount.

Realistic traffic for a portfolio service — a few dozen visits a month, each a
few minutes — lands inside the free tier at roughly zero. The gap between
realistic and worst case is entirely a function of how long tabs stay open.

## 6. Adopted resolution

1. **No dashboard-scoped BigQuery quota.** It does not exist; §2 is the record
   so it is not re-investigated.
2. **Per-user-per-day override at 256 GiB** (`262144`, unit MiB). This sits
   ~5.3× above the worst measured pipeline day and ~37× above the heaviest
   developer day. Because the bucket is per principal, a runaway dashboard
   cannot consume the pipeline's allowance. Plausible worst case drops from
   200 TiB/day to 256 GiB × 3 identities ≈ 768 GiB/day.
3. **One billing budget, €10/month**, scoped to the project, alerting at 50%,
   90% and 100% of actual plus 100% of forecast, by email to the owner. This is
   the only control that sees the Cloud Run term.
4. **A documented manual kill switch** —
   `gcloud run services update openalex-dashboard --max-instances=0` — as the
   response to an alert.

If a future full-corpus refresh trips the 256 GiB ceiling, dbt fails loudly
with `quotaExceeded` and the value is a one-line change. That is the intended
failure mode, not a regression.

## 7. Rejected alternatives

<!-- prettier-ignore -->
| Alternative | Why rejected |
|---|---|
| Project-level daily quota (`1/d/{project}`) | Puts dashboard and pipeline in one bucket: a runaway dashboard breaks the next dbt build, a heavy build day breaks the dashboard. Creates exactly the coupling §13.4 forbids. |
| A separate GCP project for the dashboard | The only route to a genuinely dashboard-scoped daily cap *and* a hard billing cap. Buys isolation of a $0.05/day risk for a second project, cross-project IAM, a second budget surface and a Terraform restructure — and does not touch the Cloud Run term unless the service moves too. This is the escalation if a real hard ceiling is ever wanted. |
| Budget → Pub/Sub → function disabling billing | The only true hard stop, but it disables billing project-wide, taking down the pipeline, the bronze bucket and BigQuery storage. Disproportionate and destructive. |
| Budget → Pub/Sub → function scaling the service to zero | Scoped and non-destructive, but adds a Cloud Function, a topic and IAM that the spec deliberately excludes, to automate a response a budget alert cannot deliver promptly anyway. The manual command is the right weight. |

## 8. Prerequisites not yet in place

Verified absent on 2026-09-19:

- `terraform-runner` holds `bigquery.admin`, `serviceAccountAdmin`,
  `serviceAccountKeyAdmin`, `projectIamAdmin` and `storage.admin` — it needs
  `roles/serviceusage.quotaAdmin` on the project and
  `roles/billing.costsManager` on the billing account.
- `billingbudgets.googleapis.com` is not enabled.
- `run.googleapis.com` and `artifactregistry.googleapis.com` are not enabled,
  which blocks Waypoint 1 independently of the spend guards.

## 9. Reproducing these measurements

```bash
# Quota surface: buckets, units, effective limits, dimensions
gcloud alpha services quota list \
  --service=bigquery.googleapis.com \
  --consumer=projects/openalex-pipeline

# Gold relation sizes
bq show --format=prettyjson \
  openalex-pipeline:openalex_analytics.gold_citation_gini_by_subfield

# Daily bytes billed per identity
bq --location=EU query --use_legacy_sql=false '
select date(creation_time) as day, user_email, count(*) as jobs,
       round(sum(total_bytes_billed)/pow(1024,3), 2) as gib_billed
from `region-eu`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
where creation_time > timestamp_sub(current_timestamp(), interval 180 day)
  and job_type = "QUERY"
group by day, user_email order by gib_billed desc'
```
