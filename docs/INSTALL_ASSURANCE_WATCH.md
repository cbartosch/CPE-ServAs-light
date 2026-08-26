# 24-Hour Install Assurance Watch

## Purpose

The **24-Hour Install Assurance Watch** actively supervises new HFC and PON
installations after commissioning. It is deliberately modelled as an
**assurance episode**, not as a fault incident.

A healthy installation therefore completes as `PASSED_24H` without creating an
incident. A persistent or severe defect is promoted idempotently to one root
incident, with customer contacts, Clean Boots work, maintenance requests and
validation linked to the same identity chain.

## Identity chain

```text
installation work order
  -> install assurance episode
  -> NXT/provisioning/short-horizon observations
  -> optional Genesys contact and DvSum CADDI context
  -> optional root incident
  -> optional Clean Boots work order
  -> optional tap/ODP maintenance request
  -> repair and validation
  -> assurance result
```

The parent Digital Twin run remains immutable. Install-watch data is stored as
an immutable child artifact under:

```text
RUN-*/install_assurance/IAW-*/
```

## Lifecycle and health

Lifecycle states are mutually exclusive:

- `PENDING_BASELINE`
- `ACTIVE`
- `RECOVERING`
- `PASSED_24H`
- `PROMOTED_TO_INCIDENT`
- `INVALIDATED`

Health is a separate dimension:

- `GREEN`
- `AMBER`
- `RED`

An active episode can therefore be `ACTIVE + AMBER`, while an episode recovering
from a remote action can be `RECOVERING + GREEN`.

## Minimum observation policy

The nominal maturity time is 24 hours after the watch starts. A late
service-affecting action extends the effective maturity time:

```text
effective maturity = max(
    start + 24 hours,
    last service-affecting action + stability tail
)
```

The default stability tail is four hours and is configurable from one to twelve
hours. The 24-hour boundary never closes an open operational incident.

## Short-horizon evidence

The demo uses adaptive synthetic observations:

- every five minutes during the first two hours;
- every fifteen minutes through hour six;
- every thirty minutes through hour twenty-four;
- hourly for extended observation.

The short-horizon detector is intentionally separate from the seven-to-sixty-day
predictive scanner. It evaluates commissioning thresholds, persistence,
volatility, events, post-action recovery and common-cause correlation.

HFC evidence includes receive/transmit power, MER, uncorrectable errors and T3
timeouts. PON evidence includes optical receive power, BER, LOS and dying-gasp
events. Common service evidence includes registration, reboots, packet loss,
latency, throughput and Wi-Fi onboarding state.

## Synthetic acceptance stories

The deterministic cohort includes:

1. Healthy HFC install.
2. Healthy PON install.
3. Remote stabilization without incident creation.
4. Persistent HFC impairment promoted to an incident, Clean Boots and MR.
5. Persistent PON impairment promoted to an incident, Clean Boots and MR.
6. Wi-Fi onboarding impairment resolved without a break/fix incident.
7. Two HFC installations sharing one common-cause tap incident.
8. A service-affecting action at hour 23 that extends the watch.
9. Active green, amber and red episodes.
10. An open promoted incident that is not closed by watch maturity.

## DvSum CADDI and Genesys

The LPR assurance layer remains authoritative for the episode lifecycle. The
artifact produces a customer-safe **DvSum CADDI** projection containing watch
status, health, leading finding, completed actions, current owner, root incident,
work order/MR references and the next update.

Genesys remains the interaction channel. A contact is attached to the existing
assurance episode and, where present, the existing root incident. Completed
diagnostics are not restarted and no duplicate incident is created.

This is a contract projection only. The demo does not claim a live DvSum CADDI
endpoint or write path.

## Metrics

Install metrics are separate from break/fix KPIs.

| Metric | Grain and denominator |
|---|---|
| Episodes entering watch | Distinct assurance episodes opened |
| Baseline acceptance rate | Accepted baselines / episodes opened |
| 24-hour pass rate | Passed episodes / effectively matured episodes |
| Intervention rate | Episodes with an action / episodes opened |
| Remote stabilization rate | Passed after remote action / intervened episodes |
| Incident conversion rate | Promoted episodes / episodes opened |
| Network-before-call rate | Contacts preceded by a finding / watch contacts |
| Mean time to stable service | Start to final stable interval |

Active episodes are not included in the pass-rate denominator.

## API

```text
POST /api/runs/{run_id}/install-assurance/watches
GET  /api/runs/{run_id}/install-assurance/watches
GET  /api/runs/{run_id}/install-assurance/watches/{watch_id}
GET  /api/runs/{run_id}/install-assurance/projection
GET  /api/install-assurance/projection
```

Example request:

```json
{
  "population": 12,
  "as_of_hours": 24,
  "stability_tail_hours": 4,
  "seed": 17
}
```

All generated actions are simulation-only and carry `production_write: false`.
