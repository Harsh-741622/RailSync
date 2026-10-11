from __future__ import annotations
import time
from collections import defaultdict
from typing import Any

class SchedulerUnavailable(RuntimeError):
    pass

try:
    from ortools.sat.python import cp_model
except Exception as exc:  # Let the API start and explain a missing dependency instead of fabricating a result.
    cp_model = None
    _ortools_error = str(exc)
else:
    _ortools_error = ""


def solver_status_name(status: int) -> str:
    """Expose CP-SAT's terminal states without calling every failure infeasible."""
    if cp_model is None:
        return "UNAVAILABLE"
    return {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.UNKNOWN: "UNKNOWN",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
    }.get(status, "UNKNOWN")

def optimize_timetable(trains: list[dict[str, Any]], entries: list[dict[str, Any]], platforms: list[str], closures: list[dict[str, Any]], hard_instructions: list[dict[str, Any]], soft_preferences: list[dict[str, Any]], minimum_gap: int = 5, horizon_start: int = 0, horizon_end: int = 180, max_time_seconds: float = 5.0) -> dict[str, Any]:
    """Run a genuine CP-SAT assignment/retiming model. No fallback/mock optimizer is used."""
    if cp_model is None:
        raise SchedulerUnavailable(f"Google OR-Tools is not installed in this environment: {_ortools_error}. Install requirements.txt to enable CP-SAT optimization.")
    started = time.perf_counter()
    current = {str(r["train_id"]): r for r in entries}
    train_by_id = {str(t["train_id"]): t for t in trains}
    if set(train_by_id) != set(current):
        missing = sorted(set(train_by_id) - set(current))
        extra = sorted(set(current) - set(train_by_id))
        return {"solver_status": "INFEASIBLE", "has_schedule": False, "entries": [],
                "objective": {}, "wall_time_seconds": time.perf_counter() - started,
                "diagnostics": {"reason": "The base timetable must have exactly one entry for every configured train.", "missing_train_ids": missing, "unknown_train_ids": extra}}

    # Apply the disruption layer to expected times first. The optimizer's additional
    # delay is a separate decision variable and is reported separately in the result.
    effective_base = {}
    for tid, row in current.items():
        effective_base[tid] = dict(row)
        effective_base[tid]["arrival_min"] = int(row["arrival_min"])
        effective_base[tid]["departure_min"] = int(row["departure_min"])
    outside_horizon = []
    for tid, row in effective_base.items():
        arrival, departure = row["arrival_min"], row["departure_min"]
        if arrival < horizon_start or departure > horizon_end:
            outside_horizon.append({
                "code": "OUTSIDE_OPERATING_HORIZON", "train_id": tid,
                "arrival_min": arrival, "departure_min": departure,
                "horizon_start": horizon_start, "horizon_end": horizon_end,
                "scenario_delay_min": int(row.get("scenario_delay_min", 0)),
            })
    if outside_horizon:
        train_ids = [item["train_id"] for item in outside_horizon]
        return {"solver_status": "INFEASIBLE", "has_schedule": False, "entries": [], "objective": {},
                "wall_time_seconds": time.perf_counter() - started,
                "diagnostics": {
                    "reason": "A submitted delay places one or more required services outside the operating horizon.",
                    "affected_train_ids": train_ids, "affected_platform_ids": [],
                    "constraint_conflicts": outside_horizon,
                    "constraints_to_review": ["Review the listed delay input(s) or extend the operating horizon before generating a new proposal."],
                }}
    # Caller attaches per-train disruption delay as a synthetic input field.
    model = cp_model.CpModel()
    x: dict[tuple[str, str], Any] = {}
    arrivals: dict[str, Any] = {}
    extra_delays: dict[str, Any] = {}
    platform_changed: dict[str, Any] = {}
    preference_misses: list[Any] = []
    merged_closures: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    for c in closures:
        if c.get("platform_id") and c.get("start_min") is not None and c.get("end_min") is not None:
            merged_closures[str(c["platform_id"])].append((int(c["start_min"]), int(c["end_min"]), str(c.get("reason", "closure"))))
    # Overlapping closure intervals are merged so the solver doesn't treat two
    # overlapping closure records as a physical conflict with one another.
    for p, intervals in list(merged_closures.items()):
        intervals.sort()
        merged = []
        for a, b, reason in intervals:
            if merged and a <= merged[-1][1]:
                prev_a, prev_b, prev_reason = merged[-1]
                merged[-1] = (prev_a, max(prev_b, b), f"{prev_reason}; {reason}")
            else:
                merged.append((a, b, reason))
        merged_closures[p] = merged

    base_arrivals = {}
    dwell = {}
    for tid, t in train_by_id.items():
        row = effective_base[tid]
        base_arrivals[tid] = int(row["arrival_min"])
        dwell[tid] = int(row["departure_min"]) - int(row["arrival_min"])
        if dwell[tid] <= 0:
            return {"solver_status": "INFEASIBLE", "has_schedule": False, "entries": [], "objective": {}, "wall_time_seconds": time.perf_counter() - started,
                    "diagnostics": {"reason": f"Train {tid} has invalid dwell duration."}}
        earliest = horizon_start
        latest = horizon_end - dwell[tid]
        if latest < horizon_start:
            model.Add(0 == 1)
            latest = horizon_start
        arrivals[tid] = model.NewIntVar(earliest, latest, f"arrival_{tid}")
        extra_delays[tid] = model.NewIntVar(0, max(0, horizon_end - base_arrivals[tid]), f"extra_delay_{tid}")
        model.Add(arrivals[tid] == base_arrivals[tid] + extra_delays[tid])
        for p in platforms:
            x[(tid, p)] = model.NewBoolVar(f"assign_{tid}_{p}")
            if p not in t.get("allowed_platforms", []):
                model.Add(x[(tid, p)] == 0)
        model.Add(sum(x[(tid, p)] for p in platforms if p in t.get("allowed_platforms", [])) == 1)
        original_p = str(current[tid]["platform_id"])
        if original_p in platforms:
            changed = model.NewBoolVar(f"platform_changed_{tid}")
            model.Add(changed + x[(tid, original_p)] == 1)
        else:
            changed = model.NewConstant(1)
        platform_changed[tid] = changed

    for inst in hard_instructions:
        tid, p = str(inst["train_id"]), str(inst["platform_id"])
        if tid not in train_by_id or p not in platforms:
            model.Add(0 == 1)
        else:
            model.Add(x[(tid, p)] == 1)

    # Occupancy intervals enforce no occupancy during closures and no overlap.
    # Clearance intervals are separate, enforcing departure + gap <= next arrival
    # without incorrectly extending platform closures by the clearance time.
    for p in platforms:
        occupancy_intervals = []
        clearance_intervals = []
        for tid in train_by_id:
            pres = x[(tid, p)]
            occ = model.NewOptionalIntervalVar(arrivals[tid], dwell[tid], arrivals[tid] + dwell[tid], pres, f"occ_{tid}_{p}")
            clear = model.NewOptionalIntervalVar(arrivals[tid], dwell[tid] + minimum_gap, arrivals[tid] + dwell[tid] + minimum_gap, pres, f"clear_{tid}_{p}")
            occupancy_intervals.append(occ)
            clearance_intervals.append(clear)
        for idx, (a, b, _reason) in enumerate(merged_closures.get(p, [])):
            if b > a:
                occupancy_intervals.append(model.NewIntervalVar(a, b - a, b, f"closure_{p}_{idx}"))
        model.AddNoOverlap(occupancy_intervals)
        model.AddNoOverlap(clearance_intervals)

    for pref in soft_preferences:
        tid, p = str(pref["train_id"]), str(pref["platform_id"])
        miss = model.NewBoolVar(f"preference_miss_{len(preference_misses)}")
        if tid not in train_by_id or p not in platforms:
            model.Add(miss == 1)
        else:
            model.Add(miss + x[(tid, p)] == 1)
        preference_misses.append(miss)

    # Exact weighted priority: one minute of total extra delay costs more than
    # every possible lower-priority platform-change/preference penalty combined.
    n = len(train_by_id)
    m = len(preference_misses)
    platform_weight = m + 1
    delay_weight = (n + 1) * platform_weight
    total_extra_delay = sum(extra_delays.values())
    total_platform_changes = sum(platform_changed.values())
    total_pref_misses = sum(preference_misses) if preference_misses else 0
    model.Minimize(total_extra_delay * delay_weight + total_platform_changes * platform_weight + total_pref_misses)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_time_seconds
    solver.parameters.num_search_workers = 1  # repeatability for the demo
    solver.parameters.random_seed = 17
    status = solver.Solve(model)
    status_name = solver_status_name(status)
    wall_time = time.perf_counter() - started
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        affected_trains = set()
        affected_platforms = set()
        if status == cp_model.INFEASIBLE:
            for inst in hard_instructions:
                tid, p = str(inst.get("train_id")), str(inst.get("platform_id"))
                affected_trains.add(tid); affected_platforms.add(p)
                if tid in train_by_id and p not in train_by_id[tid].get("allowed_platforms", []):
                    affected_trains.add(tid)
            for c in closures:
                p = str(c.get("platform_id", ""))
                a, b = int(c.get("start_min", 0)), int(c.get("end_min", 0))
                for tid, t in train_by_id.items():
                    row = effective_base[tid]
                    if p in t.get("allowed_platforms", []) and int(row["arrival_min"]) < b and int(row["departure_min"]) > a:
                        affected_trains.add(tid); affected_platforms.add(p)
        reason = {
            "INFEASIBLE": "No feasible timetable was found under the submitted hard constraints.",
            "UNKNOWN": "Solver stopped before finding a feasible timetable.",
            "MODEL_INVALID": "The solver rejected the model before searching for a timetable.",
        }.get(status_name, "The solver did not return a timetable.")
        diagnostics = {"reason": reason, "solver_status": status_name,
                      "affected_train_ids": sorted(affected_trains), "affected_platform_ids": sorted(affected_platforms),
                      "constraints_to_review": ["Check allowed-platform sets", "Review platform closures that overlap required occupancy", "Review mandatory station-master platform instructions"] if status == cp_model.INFEASIBLE else []}
        return {"solver_status": status_name, "has_schedule": False, "entries": [], "objective": {}, "wall_time_seconds": wall_time, "diagnostics": diagnostics}

    output = []
    for tid, t in train_by_id.items():
        assigned = next((p for p in platforms if solver.Value(x[(tid, p)]) == 1), None)
        base_row = effective_base[tid]
        revised_arr = solver.Value(arrivals[tid])
        revised_dep = revised_arr + dwell[tid]
        prefs = [q for q in soft_preferences if str(q["train_id"]) == tid]
        output.append({"train_id": tid, "name": t["name"], "arrival_min": revised_arr, "departure_min": revised_dep,
                       "platform_id": assigned, "additional_delay_min": solver.Value(extra_delays[tid]),
                       "scenario_delay_min": int(base_row.get("scenario_delay_min", 0)),
                       "platform_changed": assigned != str(current[tid]["platform_id"]),
                       "preference_satisfied": all(q["platform_id"] == assigned for q in prefs) if prefs else True})
    objective = {"weighted_objective": int(round(solver.ObjectiveValue())),
                 "total_additional_delay_min": sum(r["additional_delay_min"] for r in output),
                 "platform_changes": sum(1 for r in output if r["platform_changed"]),
                 "soft_preference_violations": sum(1 for r in output for q in soft_preferences if str(q["train_id"]) == r["train_id"] and q["platform_id"] != r["platform_id"]),
                 "best_bound": float(solver.BestObjectiveBound()), "objective_priority_weights": {"delay": delay_weight, "platform_change": platform_weight, "preference_violation": 1}}
    return {"solver_status": status_name, "has_schedule": True, "entries": output, "objective": objective,
            "wall_time_seconds": wall_time, "diagnostics": {"reason": None, "solver_wall_time_seconds": solver.WallTime()}}
