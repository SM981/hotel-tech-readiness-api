from __future__ import annotations

from typing import Any, Dict


def is_group_scope(intake: Dict[str, Any]) -> bool:
    return intake.get("entity", {}).get("scope") == "group"


def is_property_scope(intake: Dict[str, Any]) -> bool:
    return intake.get("entity", {}).get("scope") == "property"
