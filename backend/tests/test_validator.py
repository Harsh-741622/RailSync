from backend.services.validator import validate_timetable
from backend.seed import TRAINS


def fixture_data():
    trains = [{"train_id": n, "name": name, "allowed_platforms": allowed} for n, name, a, d, p, allowed in TRAINS]
    entries = [{"train_id": n, "name": name, "arrival_min": a, "departure_min": d, "platform_id": p} for n, name, a, d, p, allowed in TRAINS]
    return trains, entries


def test_seed_timetable_passes_independent_validator():
    trains, entries = fixture_data()
    report = validate_timetable(entries, trains, ["P1", "P2", "P3", "P4", "P5"], [], [], 5)
    assert report["status"] == "PASS"
    assert report["hard_violation_count"] == 0


def test_closure_overlap_is_reported():
    trains, entries = fixture_data()
    report = validate_timetable(entries, trains, ["P1", "P2", "P3", "P4", "P5"],
                                 [{"platform_id": "P2", "start_min": 10, "end_min": 22, "reason": "maintenance"}], [], 5)
    assert report["status"] == "FAIL"
    assert any(v["code"] == "PLATFORM_CLOSED" and "12951" in v["train_ids"] for v in report["violations"])


def test_closure_uses_half_open_occupancy_boundaries():
    trains = [{"train_id": "T", "allowed_platforms": ["P2"]}]
    closure = [{"platform_id": "P2", "start_min": 60, "end_min": 105, "reason": "signal issue"}]

    def report(arrival, departure):
        return validate_timetable([{"train_id": "T", "arrival_min": arrival, "departure_min": departure, "platform_id": "P2"}],
                                  trains, ["P2"], closure, [], 0)

    assert not any(v["code"] == "PLATFORM_CLOSED" for v in report(45, 60)["violations"])  # departs at closure start
    assert any(v["code"] == "PLATFORM_CLOSED" for v in report(59, 70)["violations"])  # closure begins while present
    assert any(v["code"] == "PLATFORM_CLOSED" for v in report(60, 70)["violations"])  # arrives at closure start
    assert any(v["code"] == "PLATFORM_CLOSED" for v in report(104, 110)["violations"])
    assert not any(v["code"] == "PLATFORM_CLOSED" for v in report(105, 115)["violations"])  # arrives at closure end


def test_hard_instruction_is_enforced_by_validator():
    trains, entries = fixture_data()
    report = validate_timetable(entries, trains, ["P1", "P2", "P3", "P4", "P5"], [],
                                 [{"train_id": "12951", "platform_id": "P3"}], 5)
    assert any(v["code"] == "HARD_INSTRUCTION" for v in report["violations"])


def test_minimum_separation_violation_detected():
    trains, entries = fixture_data()
    # Move 12139 to P2 arrival 22; Train 12951 departs P2 at 20, so only 2 minutes.
    row = next(r for r in entries if r["train_id"] == "12139")
    row["arrival_min"], row["departure_min"], row["platform_id"] = 22, 30, "P2"
    report = validate_timetable(entries, trains, ["P1", "P2", "P3", "P4", "P5"], [], [], 5)
    assert any(v["code"] == "MINIMUM_SEPARATION" for v in report["violations"])
