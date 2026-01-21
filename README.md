# Hotel Tech Stacker

Executive-safe, evidence-based technology stack mapping for hotels and hotel groups.

## What this does
- Captures a **complete stack register** from hotel-provided inputs (10 mandatory categories).
- Builds a **current-state integration map** with explicit statuses: Active / Not active / Unknown.
- Produces **CEO-aligned grades** and a **gap register** (only where gaps block decisions).
- Recommends tools **only when a gap is confirmed**.

## What this does NOT do
- It does not guess system vendors from websites.
- It does not use "likely" or "inferred".
- It does not fabricate ROI, uplift or savings without hotel-supplied performance data + explicit assumptions.

## Phase model
### Phase-1: Stack Confirmation (Success = no unknown systems)
A Phase-1 output is successful only if each of the following is either:
- Vendor named (hotel-provided), or
- None (not in use), or
- Not provided (missing input)

Mandatory categories:
1) PMS
2) Booking engine
3) Channel manager / CRS
4) RMS
5) CRM / guest database
6) Email / lifecycle marketing
7) In-stay guest tools
8) Housekeeping & maintenance / tasks
9) Finance / accounting
10) Reporting / BI

### Phase-2: Integration Read (Success = explicit flow map)
Canonical flows (each must be Active / Not active / Unknown):
- Booking engine → PMS
- Channel manager/CRS ↔ PMS
- RMS ↔ PMS
- PMS → CRM
- CRM → Email
- PMS/POS → Finance
- Systems → BI

## Truth standard
- Hotel inputs are treated as **facts** (with evidence tags).
- Public sources (reviews/forums/vendor docs) are **market signals only**.
- Market signals can inform risk notes; they cannot assert presence, integrations, or performance.

## QA gating
The API will **block final report output** if any QA gate fails, including:
- missing any stack category
- any named system missing an evidence label
- missing integration flows or missing statuses
- a gap without decision impairment + symptom + owner + close-gap action
- numeric ROI/uplift without hotel data + explicit assumptions + user request

## Schemas
- `schemas/stack_intake.schema.json`
- `schemas/report_output.schema.json`

All outputs are validated against the schemas.

## Running locally
```bash
pip install -r requirements.txt
uvicorn app:app --reload
