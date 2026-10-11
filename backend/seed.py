from __future__ import annotations
import json
from sqlalchemy.orm import Session
from .models import Station, Platform, Train, TimetableVersion, TimetableEntry, SimulationState, AuditEvent

# Times are integer minutes after 09:00. All information is fictional demo data.
TRAINS = [
    ("12951", "Coastal Superfast", 10, 20, "P2", ["P1", "P2", "P3", "P4"]),
    ("12139", "Harbour Mail", 35, 45, "P2", ["P1", "P2", "P3", "P5"]),
    ("17031", "Hill Fort Express", 25, 35, "P1", ["P1", "P3", "P4"]),
    ("22618", "Deccan Intercity", 70, 78, "P1", ["P1", "P2", "P4", "P5"]),
    ("11057", "Konkan Express", 85, 95, "P2", ["P1", "P2", "P4"]),
    ("16345", "Netravati Express", 135, 145, "P5", ["P3", "P4", "P5"]),
    ("12008", "Riverside Local", 5, 12, "P1", ["P1", "P2", "P5"]),
    ("12010", "Westfield Express", 60, 70, "P2", ["P1", "P2", "P3"]),
    ("12627", "Karnataka Express", 90, 100, "P1", ["P1", "P3", "P4"]),
    ("22691", "Ernakulam SF Express", 15, 25, "P3", ["P2", "P3", "P4"]),
    ("59201", "Passenger Special", 45, 55, "P3", ["P1", "P3", "P5"]),
    ("51803", "City Passenger", 75, 85, "P3", ["P2", "P3", "P5"]),
    ("33028", "Valley Regional", 100, 110, "P3", ["P1", "P3", "P4"]),
    ("81506", "Northbound Shuttle", 5, 15, "P5", ["P4", "P5"]),
    ("22014", "Western Link", 30, 40, "P4", ["P2", "P4", "P5"]),
    ("44712", "Southern Connector", 60, 70, "P4", ["P1", "P4", "P5"]),
    ("59205", "Harbour Passenger", 90, 100, "P4", ["P2", "P4"]),
    ("22617", "Pune Intercity", 120, 130, "P4", ["P1", "P4", "P5"]),
]

def seed_database(db: Session):
    if db.query(Station).first():
        return
    db.add(Station(name="Central Junction", horizon_start=0, horizon_end=180, minimum_gap=5, timezone_name="Asia/Kolkata"))
    for i in range(1, 6):
        db.add(Platform(id=f"P{i}", number=i, name=f"Platform {i}", enabled=True))
    for number, name, arr, dep, platform, allowed in TRAINS:
        db.add(Train(id=number, name=name, allowed_platforms_json=json.dumps(allowed), direction="northbound" if int(number[-1]) % 2 else "southbound", priority=1 if "Express" in name or "Superfast" in name else 2))
    db.flush()
    version = TimetableVersion(version_number=1, status="CURRENT", created_by="Seed", note="Initial approved fictional timetable")
    db.add(version)
    db.flush()
    for number, name, arr, dep, platform, allowed in TRAINS:
        db.add(TimetableEntry(version_id=version.id, train_id=number, arrival_min=arr, departure_min=dep, platform_id=platform))
    # Start the demo beside the first scheduled arrivals, rather than in the
    # middle of an otherwise empty timetable horizon.
    db.add(SimulationState(id=1, clock_min=5, paused=False, speed=1))
    db.add(AuditEvent(event_type="SYSTEM_SEEDED", actor="System", entity_type="station", entity_id="1", details_json=json.dumps({"station": "Central Junction", "trains": len(TRAINS), "platforms": 5, "fictional": True})))
    db.commit()
