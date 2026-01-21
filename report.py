def build_integration_map_rows(intake: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """
    Builds the canonical integration map from intake-confirmed statuses.

    This function NEVER guesses integration status:
    - If intake contains integrations[] entries for canonical flows, use them.
    - If a canonical flow is missing from intake.integrations, default it to unknown_not_confirmed.
    Returns:
      - integration_rows: full list of canonical flows with explicit status
      - unknowns: only flows still unknown_not_confirmed (for targeted follow-ups)
    """
    # Canonical flows (source of truth)
    canonical_flows = [
        ("booking_engine", "pms", "reservations"),
        ("channel_manager_crs", "pms", "rates/availability"),
        ("rms", "pms", "pricing/forecast inputs & outputs"),
        ("pms", "crm_guest_db", "guest profiles/stay history"),
        ("crm_guest_db", "email_lifecycle", "segments/triggers"),
        ("pms", "finance_accounting", "posting"),
        ("pms", "reporting_bi", "KPIs/reporting"),
    ]

    def label(cat: str) -> str:
        names = {
            "pms": "PMS",
            "booking_engine": "Booking engine",
            "channel_manager_crs": "Channel manager / CRS",
            "rms": "RMS",
            "crm_guest_db": "CRM / guest database",
            "email_lifecycle": "Email / lifecycle marketing",
            "finance_accounting": "Finance / accounting",
            "reporting_bi": "Reporting / BI",
        }
        return names.get(cat, cat)

    # Build an index from intake['integrations'] if present
    # Keyed by (from, to)
    provided = {}
    for item in intake.get("integrations", []) or []:
        f = item.get("from")
        t = item.get("to")
        if f and t:
            provided[(f, t)] = item

    rows: List[Dict[str, Any]] = []
    unknowns: List[Dict[str, str]] = []

    def default_symptom(data: str) -> str:
        if "reservations" in data:
            return "Reservations may require manual entry or reconciliation."
        if "rates" in data or "availability" in data:
            return "Rate or availability updates may be slow or inconsistent across channels."
        if "pricing" in data or "forecast" in data:
            return "Pricing decisions may be manual or not auditable across properties."
        if "guest" in data or "profiles" in data:
            return "Guest profiles may be fragmented, limiting repeat marketing."
        if "segments" in data or "triggers" in data:
            return "Lifecycle comms may be manual or inconsistent."
        if "posting" in data:
            return "Finance reporting may require manual exports and reconciliation."
        if "KPIs" in data or "reporting" in data:
            return "Leadership reporting may be inconsistent or delayed."
        return "Manual work or reporting gaps."

    for f, t, data in canonical_flows:
        item = provided.get((f, t))

        # Default values
        status = "unknown_not_confirmed"
        confirmed_by = "Not confirmed"
        symptom = default_symptom(data)

        # If provided, use strictly
        if item:
            status = item.get("status", "unknown_not_confirmed")
            # confirmed_by is optional but helpful
            confirmed_by = item.get("confirmed_by") or (
                "Hotel confirmation" if status in {"active_confirmed", "not_active_confirmed"} else "Not confirmed"
            )
            symptom = item.get("symptom_if_broken") or symptom

        rows.append(
            {
                "from": f,
                "to": t,
                "data": data,
                "status": status,
                "confirmed_by": confirmed_by,
                "symptom_if_broken": symptom,
            }
        )

        if status == "unknown_not_confirmed":
            unknowns.append({"from_label": label(f), "to_label": label(t), "data": data})

    return rows, unknowns
