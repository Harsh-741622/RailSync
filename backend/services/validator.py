from __future__ import annotations
from collections import defaultdict
from typing import Any

def validate_timetable(entries: list[dict[str, Any]], trains: list[dict[str, Any]], platforms: list[str], closures: list[dict[str, Any]], hard_instructions: list[dict[str, Any]], minimum_gap: int, horizon_start: int = 0, horizon_end: int = 180) -> dict[str, Any]:
    """Independently validate a schedule using plain Python, not solver internals."""
    violations: list[dict[str, Any]] = []
    train_by_id = {str(t["train_id"]): t for t in trains}
    entry_by_train: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in entries:
        entry_by_train[str(row.get("train_id", ""))].append(row)

    def add(code: str, message: str, train_ids=None, platform_id=None, start_min=None, end_min=None):
        violations.append({"code": code, "severity": "HARD", "message": message,
                           "train_ids": list(train_ids or []), "platform_id": platform_id,
                           "start_min": start_min, "end_min": end_min})

    for train_id in train_by_id:
        rows = entry_by_train.get(train_id, [])
        if not rows:
            add("MISSING_ASSIGNMENT", f"Train {train_id} has no timetable assignment.", [train_id])
        elif len(rows) > 1:
            add("DUPLICATE_ASSIGNMENT", f"Train {train_id} has {len(rows)} assignments; exactly one is required.", [train_id])
    for train_id, rows in entry_by_train.items():
        if train_id not in train_by_id:
            add("UNKNOWN_TRAIN", f"Assignment references unknown train {train_id}.", [train_id])
        for row in rows:
            p = str(row.get("platform_id", ""))
            arr = row.get("arrival_min")
            dep = row.get("departure_min")
            if p not in platforms:
                add("INVALID_PLATFORM", f"Train {train_id} uses unknown platform {p}.", [train_id], p, arr, dep)
            train = train_by_id.get(train_id)
            if train and p not in train.get("allowed_platforms", []):
                add("PLATFORM_INCOMPATIBLE", f"Train {train_id} is not permitted to use {p}.", [train_id], p, arr, dep)
            if not isinstance(arr, int) or not isinstance(dep, int) or arr >= dep:
                add("INVALID_TIMES", f"Train {train_id} must arrive before it departs.", [train_id], p, arr, dep)
                continue
            if arr < horizon_start or dep > horizon_end:
                add("OUTSIDE_OPERATING_HORIZON", f"Train {train_id} is outside the 09:00–12:00 operating horizon.", [train_id], p, arr, dep)
            for c in closures:
                if c.get("platform_id") == p and arr < int(c["end_min"]) and dep > int(c["start_min"]):
                    add("PLATFORM_CLOSED", f"Train {train_id} occupies {p} while it is closed ({c['reason']}).", [train_id], p, max(arr, int(c["start_min"])), min(dep, int(c["end_min"])))

    by_platform: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in entries:
        if row.get("platform_id") in platforms and isinstance(row.get("arrival_min"), int) and isinstance(row.get("departure_min"), int) and row["arrival_min"] < row["departure_min"]:
            by_platform[row["platform_id"]].append(row)
    for p, rows in by_platform.items():
        rows.sort(key=lambda r: (r["arrival_min"], r["departure_min"], str(r["train_id"])))
        for prev, nxt in zip(rows, rows[1:]):
            if nxt["arrival_min"] < prev["departure_min"]:
                add("OVERLAP", f"Trains {prev['train_id']} and {nxt['train_id']} overlap on {p}.", [str(prev["train_id"]), str(nxt["train_id"])], p, nxt["arrival_min"], min(prev["departure_min"], nxt["departure_min"]))
            elif nxt["arrival_min"] < prev["departure_min"] + minimum_gap:
                add("MINIMUM_SEPARATION", f"Only {nxt['arrival_min'] - prev['departure_min']} minutes separate trains {prev['train_id']} and {nxt['train_id']} on {p}; {minimum_gap} required.", [str(prev["train_id"]), str(nxt["train_id"])], p, prev["departure_min"], nxt["arrival_min"])

    for inst in hard_instructions:
        train_id = str(inst["train_id"])
        p = str(inst["platform_id"])
        rows = entry_by_train.get(train_id, [])
        if rows and rows[0].get("platform_id") != p:
            add("HARD_INSTRUCTION", f"Hard instruction requires Train {train_id} to use {p}.", [train_id], p, rows[0].get("arrival_min"), rows[0].get("departure_min"))
        if train_id not in train_by_id:
            add("HARD_INSTRUCTION_UNKNOWN_TRAIN", f"Hard instruction references unknown train {train_id}.", [train_id], p)

    return {"status": "PASS" if not violations else "FAIL", "valid": not violations,
            "hard_violation_count": len(violations), "violations": violations,
            "summary": "All independent checks passed." if not violations else f"{len(violations)} hard violation(s) found."}
