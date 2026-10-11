from fastapi.testclient import TestClient

from backend.main import app


def test_simulation_starts_at_first_seeded_arrival_and_reset_is_data_derived():
    with TestClient(app) as client:
        initial = client.get("/api/simulation")
        assert initial.status_code == 200
        assert initial.json()["clock_min"] == 5
        assert initial.json()["initial_clock_min"] == 5
        assert initial.json()["initial_clock"] == "09:05"

        moved = client.patch("/api/simulation", json={"advance_minutes": 20})
        assert moved.json()["clock_min"] == 25
        reset = client.patch("/api/simulation", json={"reset": True})
        assert reset.json()["clock_min"] == 5
        assert reset.json()["paused"] is False
        assert reset.json()["speed"] == 1


def test_pause_resume_speed_and_replay_keep_the_demo_running():
    with TestClient(app) as client:
        client.patch("/api/simulation", json={"reset": True, "start_min": 5})
        paused = client.patch("/api/simulation", json={"paused": True})
        assert paused.json()["paused"] is True
        frozen = client.patch("/api/simulation", json={"advance_minutes": 10})
        assert frozen.json()["clock_min"] == 5

        resumed = client.patch("/api/simulation", json={"paused": False, "speed": 5})
        assert resumed.json()["paused"] is False
        assert resumed.json()["speed"] == 5
        advanced = client.patch("/api/simulation", json={"advance_minutes": 1})
        assert advanced.json()["clock_min"] == 10

        # The fixed current dataset ends at 12:00 (minute 180).  A completed
        # cycle must restart instead of leaving the station empty and paused.
        replayed = client.patch("/api/simulation", json={"advance_minutes": 34, "loop_start_min": 5})
        assert replayed.json()["replaying"] is True
        assert replayed.json()["clock_min"] == 5
        assert replayed.json()["paused"] is False


def test_selected_timetable_can_supply_its_own_reset_and_replay_start():
    with TestClient(app) as client:
        reset = client.patch("/api/simulation", json={"reset": True, "start_min": 15})
        assert reset.status_code == 200
        assert reset.json()["clock_min"] == 15
        replayed = client.patch("/api/simulation", json={"advance_minutes": 165, "loop_start_min": 15})
        assert replayed.json()["replaying"] is True
        assert replayed.json()["clock_min"] == 15


def test_seek_updates_only_the_clock_and_preserves_paused_playback_state():
    with TestClient(app) as client:
        client.patch("/api/simulation", json={"reset": True, "start_min": 5})
        client.patch("/api/simulation", json={"paused": True, "speed": 5})
        sought = client.patch("/api/simulation", json={"seek_min": 60})
        assert sought.status_code == 200
        assert sought.json()["clock_min"] == 60
        assert sought.json()["paused"] is True
        assert sought.json()["speed"] == 5

        # Seeking itself neither runs the timetable solver nor changes the
        # selected clock into a replay; playback continues normally after resume.
        client.patch("/api/simulation", json={"paused": False})
        advanced = client.patch("/api/simulation", json={"advance_minutes": 1})
        assert advanced.json()["clock_min"] == 65
        invalid = client.patch("/api/simulation", json={"seek_min": 181})
        assert invalid.status_code == 422
