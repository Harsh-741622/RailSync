from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

def utcnow():
    return datetime.now(timezone.utc)

class Station(Base):
    __tablename__ = "stations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, default="Central Junction")
    horizon_start: Mapped[int] = mapped_column(Integer, default=0)
    horizon_end: Mapped[int] = mapped_column(Integer, default=180)
    minimum_gap: Mapped[int] = mapped_column(Integer, default=5)
    timezone_name: Mapped[str] = mapped_column(String(80), default="Asia/Kolkata")

class Platform(Base):
    __tablename__ = "platforms"
    id: Mapped[str] = mapped_column(String(8), primary_key=True)  # P1..P5
    number: Mapped[int] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

class Train(Base):
    __tablename__ = "trains"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # train number
    name: Mapped[str] = mapped_column(String(120))
    allowed_platforms_json: Mapped[str] = mapped_column(Text, default='["P1","P2","P3","P4","P5"]')
    direction: Mapped[str] = mapped_column(String(16), default="through")
    priority: Mapped[int] = mapped_column(Integer, default=1)

class TimetableVersion(Base):
    __tablename__ = "timetable_versions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="CURRENT")
    base_version_id: Mapped[int | None] = mapped_column(ForeignKey("timetable_versions.id"), nullable=True)
    source_proposal_id: Mapped[int | None] = mapped_column(ForeignKey("proposals.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str] = mapped_column(String(80), default="Demo Station Master")
    note: Mapped[str] = mapped_column(Text, default="Seeded approved timetable")
    entries: Mapped[list["TimetableEntry"]] = relationship(back_populates="version", cascade="all, delete-orphan", foreign_keys="TimetableEntry.version_id")
    __table_args__ = (UniqueConstraint("version_number", name="uq_timetable_version_number"),)

class TimetableEntry(Base):
    __tablename__ = "timetable_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("timetable_versions.id", ondelete="CASCADE"), index=True)
    train_id: Mapped[str] = mapped_column(ForeignKey("trains.id"), index=True)
    arrival_min: Mapped[int] = mapped_column(Integer)
    departure_min: Mapped[int] = mapped_column(Integer)
    platform_id: Mapped[str] = mapped_column(ForeignKey("platforms.id"), index=True)
    additional_delay_min: Mapped[int] = mapped_column(Integer, default=0)
    platform_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    preference_satisfied: Mapped[bool] = mapped_column(Boolean, default=True)
    train: Mapped[Train] = relationship()
    platform: Mapped[Platform] = relationship()
    version: Mapped[TimetableVersion] = relationship(back_populates="entries", foreign_keys=[version_id])
    __table_args__ = (UniqueConstraint("version_id", "train_id", name="uq_version_train"), Index("ix_entry_platform_arrival", "version_id", "platform_id", "arrival_min"))

class Scenario(Base):
    __tablename__ = "scenarios"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str] = mapped_column(String(80), default="Demo Station Master")
    disruptions: Mapped[list["Disruption"]] = relationship(back_populates="scenario", cascade="all, delete-orphan")
    instructions: Mapped[list["StationInstruction"]] = relationship(back_populates="scenario", cascade="all, delete-orphan")

class Disruption(Base):
    __tablename__ = "disruptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # train_delay | platform_closure
    train_id: Mapped[str | None] = mapped_column(ForeignKey("trains.id"), nullable=True, index=True)
    platform_id: Mapped[str | None] = mapped_column(ForeignKey("platforms.id"), nullable=True, index=True)
    delay_min: Mapped[int] = mapped_column(Integer, default=0)
    start_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str] = mapped_column(String(240), default="Operational disruption")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    scenario: Mapped[Scenario] = relationship(back_populates="disruptions")

class StationInstruction(Base):
    __tablename__ = "station_instructions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_id: Mapped[int] = mapped_column(ForeignKey("scenarios.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # HARD_PLATFORM | SOFT_PLATFORM
    train_id: Mapped[str] = mapped_column(ForeignKey("trains.id"), index=True)
    platform_id: Mapped[str] = mapped_column(ForeignKey("platforms.id"))
    instruction_text: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    scenario: Mapped[Scenario] = relationship(back_populates="instructions")

class Proposal(Base):
    __tablename__ = "proposals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    base_version_id: Mapped[int] = mapped_column(ForeignKey("timetable_versions.id"))
    scenario_id: Mapped[int | None] = mapped_column(ForeignKey("scenarios.id"), nullable=True)
    version_id: Mapped[int | None] = mapped_column(ForeignKey("timetable_versions.id"), nullable=True)
    state: Mapped[str] = mapped_column(String(24), default="PROPOSED", index=True)
    solver_status: Mapped[str] = mapped_column(String(24), default="UNKNOWN")
    is_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    objective_json: Mapped[str] = mapped_column(Text, default="{}")
    validation_json: Mapped[str] = mapped_column(Text, default="{}")
    changes_json: Mapped[str] = mapped_column(Text, default="[]")
    inputs_json: Mapped[str] = mapped_column(Text, default="{}")
    infeasibility_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str] = mapped_column(String(80), default="Demo Station Master")
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    optimization_run: Mapped["OptimizationRun | None"] = relationship(back_populates="proposal", uselist=False, cascade="all, delete-orphan")

class ValidationRun(Base):
    __tablename__ = "validation_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id"), index=True)
    status: Mapped[str] = mapped_column(String(12))
    hard_violation_count: Mapped[int] = mapped_column(Integer, default=0)
    report_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    actor: Mapped[str] = mapped_column(String(80), default="Demo Station Master")
    entity_type: Mapped[str] = mapped_column(String(60), default="system")
    entity_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

class OptimizationRun(Base):
    __tablename__ = "optimization_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id"), unique=True)
    status: Mapped[str] = mapped_column(String(24))
    wall_time_seconds: Mapped[float] = mapped_column(default=0.0)
    objective_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    best_bound: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    proposal: Mapped[Proposal] = relationship(back_populates="optimization_run")

class SimulationState(Base):
    __tablename__ = "simulation_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    clock_min: Mapped[int] = mapped_column(Integer, default=5)  # derived from the first seeded arrival
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    speed: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
