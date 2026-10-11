import pytest
from backend.services.scheduler import cp_model, optimize_timetable, solver_status_name
from backend.seed import TRAINS

pytestmark = pytest.mark.skipif(cp_model is None, reason="OR-Tools must be installed to run CP-SAT tests")


def data():
    trains = [{"train_id": n, "name": name, "allowed_platforms": allowed} for n, name, a, d, p, allowed in TRAINS]
    entries = [{"train_id": n, "name": name, "arrival_min": a, "departure_min": d, "platform_id": p} for n, name, a, d, p, allowed in TRAINS]
    return trains, entries


def test_cp_sat_finds_feasible_seed_solution():
    trains, entries = data()
    result = optimize_timetable(trains, entries, ["P1", "P2", "P3", "P4", "P5"], [], [], [], 5, max_time_seconds=2)
    assert result["has_schedule"]
    assert result["solver_status"] in {"OPTIMAL", "FEASIBLE"}
    assert len(result["entries"]) == 18


def test_cp_sat_reports_infeasible_mandatory_platform_closed():
    trains, entries = data()
    t = next(x for x in trains if x["train_id"] == "12951")
    t["allowed_platforms"] = ["P2"]
    result = optimize_timetable(trains, entries, ["P1", "P2", "P3", "P4", "P5"],
                                [{"platform_id": "P2", "start_min": 0, "end_min": 180, "reason": "maintenance"}],
                                [{"train_id": "12951", "platform_id": "P2"}], [], 5, max_time_seconds=2)
    assert not result["has_schedule"]
    assert result["solver_status"] == "INFEASIBLE"


def test_cp_sat_honors_half_open_closure_boundaries():
    train = [{"train_id": "T", "name": "Boundary test", "allowed_platforms": ["P2"]}]
    closure = [{"platform_id": "P2", "start_min": 60, "end_min": 105, "reason": "maintenance"}]

    def solve(arrival, departure):
        return optimize_timetable(train, [{"train_id": "T", "name": "Boundary test", "arrival_min": arrival,
                                            "departure_min": departure, "platform_id": "P2"}], ["P2"], closure, [], [],
                                  0, horizon_end=180, max_time_seconds=2)

    departs_at_start = solve(45, 60)
    assert departs_at_start["has_schedule"]
    assert departs_at_start["entries"][0]["departure_min"] == 60

    arrives_at_end = solve(105, 115)
    assert arrives_at_end["has_schedule"]
    assert arrives_at_end["entries"][0]["arrival_min"] == 105

    overlaps_end = solve(104, 114)
    assert overlaps_end["has_schedule"]
    assert overlaps_end["entries"][0]["arrival_min"] >= 105


def test_solver_status_mapping_keeps_model_invalid_distinct_from_unknown():
    assert solver_status_name(cp_model.INFEASIBLE) == "INFEASIBLE"
    assert solver_status_name(cp_model.UNKNOWN) == "UNKNOWN"
    assert solver_status_name(cp_model.MODEL_INVALID) == "MODEL_INVALID"
