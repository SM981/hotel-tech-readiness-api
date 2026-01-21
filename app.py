"""
Hotel Tech Stacker GPT - API Orchestrator

- Validates intake JSON against schemas/stack_intake.schema.json
- Builds an evidence-based integration map (no guessing)
- Generates an executive-safe report JSON + Markdown
- Enforces QA gating: if QA fails, returns "blocked" with minimal questions
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from jsonschema import Draft202012Validator

from scoring import compute_grades
from interpretation import build_gap_register, build_recommendations
from priorities import build_next_steps
from report import (
    build_stack_register_rows,
    build_integration_map_rows,
    build_executive_summary,
    render_markdown_report,
    run_qa_gates,
)

SCHEMAS_DIR = Path(__file__).parent / "schemas"
INTAKE_SCHEMA_PATH = SCHEMAS_DIR / "stack_intake.schema.json"
OUTPUT_SCHEMA_PATH = SCHEMAS_DIR / "report_output.schema.json"

app = FastAPI(title="Hotel Tech Stacker", version="2.0.0")


def _load_schema(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Schema not found: {path}. Create schemas/stack_intake.schema.json and schemas/report_output.schema.json"
        )
    return json.loads(path.read_text(encoding="utf-8"))


INTAKE_SCHEMA = _load_schema(INTAKE_SCHEMA_PATH)
OUTPUT_SCHEMA = _load_schema(OUTPUT_SCHEMA_PATH)

INTAKE_VALIDATOR = Draft202012Validator(INTAKE_SCHEMA)
OUTPUT_VALIDATOR = Draft202012Validator(OUTPUT_SCHEMA)


def _validate_with(validator: Draft202012Validator, payload: Dict[str, Any]) -> List[Dict[str, str]]:
    errors = []
    for e in sorted(validator.iter_errors(payload), key=lambda x: x.path):
        loc = ".".join([str(p) for p in e.path]) if e.path else "(root)"
        errors.append({"location": loc, "message": e.message})
    return errors


def _canonical_system_categories() -> List[str]:
    return [
        "pms",
        "booking_engine",
        "channel_manager_crs",
        "rms",
        "crm_guest_db",
        "email_lifecycle",
        "in_stay_tools",
        "housekeeping_maintenance",
        "finance_accounting",
        "reporting_bi",
    ]


def _extract_system(payload: Dict[str, Any], key: str) -> Dict[str, Any]:
    """Return a normalized system entry for single or multi categories."""
    entry = payload["stack"][key]

    # Multi entries have {"systems": [...]}
    if isinstance(entry, dict) and "systems" in entry:
        return entry

    # Single entries are already systemEntry shape
    return {"systems": [entry]}


def _build_minimum_followups(missing: List[str], unknown_links: List[Dict[str, str]]) -> List[str]:
    qs: List[str] = []
    if missing:
        labels = {
            "pms": "PMS",
            "booking_engine": "Booking engine",
            "channel_manager_crs": "Channel manager / CRS",
            "rms": "RMS",
            "crm_guest_db": "CRM / guest database",
            "email_lifecycle": "Email / lifecycle marketing",
            "in_stay_tools": "In-stay guest tools",
            "housekeeping_maintenance": "Housekeeping & maintenance",
            "finance_accounting": "Finance / accounting",
            "reporting_bi": "Reporting / BI",
        }
        qs.append("Please confirm the following stack items (vendor name, ownership property/group, and whether it is in use):")
        for k in missing:
            qs.append(f"- {labels.get(k, k)}")

    if unknown_links:
        qs.append("Please confirm the following integrations (Active / Not active):")
        for l in unknown_links:
            qs.append(f"- {l['from_label']} → {l['to_label']} ({l['data']})")

    return qs


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/report")
def generate_report(payload: Dict[str, Any]) -> JSONResponse:
    # 1) Validate intake
    intake_errors = _validate_with(INTAKE_VALIDATOR, payload)
    if intake_errors:
        raise HTTPException(status_code=422, detail={"schema": "stack_intake", "errors": intake_errors})

    # 2) Build stack register rows (complete, no unknown systems)
    stack_rows = build_stack_register_rows(payload)

    # Identify any categories still "not_provided"
    missing_categories = []
    for cat in _canonical_system_categories():
        sys_block = _extract_system(payload, cat)
        # If all entries are not_provided, treat as missing
        all_not_provided = all(s.get("evidence_level") == "not_provided" for s in sys_block["systems"])
        if all_not_provided:
            missing_categories.append(cat)

    # 3) Build integration map rows (unknown allowed but must be explicit)
    integration_rows, integration_unknowns = build_integration_map_rows(payload)

    # 4) Compute CEO-aligned grades (deterministic, based on confirmed statuses only)
    grades = compute_grades(stack_rows=stack_rows, integration_rows=integration_rows)

    # 5) Build gaps (CEO-valid gaps only)
    gaps = build_gap_register(
        stack_rows=stack_rows,
        integration_rows=integration_rows,
    )

    # 6) Build recommendations (only eligible gaps)
    recommendations = build_recommendations(
        gaps=gaps,
        stack_rows=stack_rows,
    )

    # 7) Next steps (prioritised actions)
    next_steps = build_next_steps(gaps=gaps, recommendations=recommendations)

    # 8) Executive summary
    exec_summary = build_executive_summary(
        payload=payload,
        stack_rows=stack_rows,
        integration_rows=integration_rows,
        gaps=gaps,
        next_steps=next_steps,
        missing_categories=missing_categories,
        integration_unknowns=integration_unknowns,
    )

    # 9) Assemble report JSON (output contract)
    report_json: Dict[str, Any] = {
        "meta": {
            "entity_name": payload["entity"]["name"],
            "scope": payload["entity"]["scope"],
            "report_date": exec_summary["report_date"],
            "truth_standard": "facts_and_market_signals",
        },
        "stack_register": stack_rows,
        "integration_map": integration_rows,
        "grades": grades,
        "gaps": gaps,
        "recommendations": recommendations,
        "commercial_impact": {
            "quantified": False,
            "statement": "Commercial impact has not been quantified because internal performance inputs were not provided.",
        },
        "next_steps": next_steps,
        "sources": {
            "hotel_provided": exec_summary["hotel_provided_evidence"],
            "public_market_signals": exec_summary["public_market_signals"],
        },
    }

    # 10) Validate report output schema (machine-checkable)
    out_errors = _validate_with(OUTPUT_VALIDATOR, report_json)
    if out_errors:
        raise HTTPException(status_code=500, detail={"schema": "report_output", "errors": out_errors})

    # 11) QA gating: if fails, block and ask minimal questions
    qa = run_qa_gates(report_json)
    if not qa["pass"]:
        followups = _build_minimum_followups(missing_categories, integration_unknowns)
        return JSONResponse(
            status_code=200,
            content={
                "status": "blocked",
                "reason": "QA gates failed; additional confirmations required before an executive report can be issued.",
                "qa": qa,
                "confirmed_so_far": {
                    "stack_register": stack_rows,
                    "integration_map": integration_rows,
                },
                "questions_to_proceed": followups,
            },
        )

    # 12) Render markdown report (exec-safe) + return
    md = render_markdown_report(report_json, executive_summary=exec_summary)
    return JSONResponse(status_code=200, content={"status": "ok", "report_json": report_json, "report_md": md})
