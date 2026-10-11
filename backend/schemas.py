from __future__ import annotations
from pydantic import BaseModel, Field, model_validator
from typing import Literal

class DisruptionIn(BaseModel):
    kind: Literal["train_delay", "platform_closure"]
    train_id: str | None = None
    platform_id: str | None = None
    delay_min: int = Field(default=0, ge=0, le=180)
    start_min: int | None = Field(default=None, ge=0, le=180)
    end_min: int | None = Field(default=None, ge=0, le=180)
    reason: str = Field(default="Operational disruption", max_length=240)

    @model_validator(mode="after")
    def valid_shape(self):
        if self.kind == "train_delay" and not self.train_id:
            raise ValueError("train_delay requires train_id")
        if self.kind == "platform_closure":
            if not self.platform_id or self.start_min is None or self.end_min is None:
                raise ValueError("platform_closure requires platform_id, start_min, and end_min")
            if self.start_min >= self.end_min:
                raise ValueError("closure start_min must be earlier than end_min")
        return self

class InstructionIn(BaseModel):
    kind: Literal["HARD_PLATFORM", "SOFT_PLATFORM"]
    train_id: str
    platform_id: str
    instruction_text: str = Field(min_length=3, max_length=500)

class ScenarioIn(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=1000)
    disruptions: list[DisruptionIn] = Field(default_factory=list)
    instructions: list[InstructionIn] = Field(default_factory=list)
    activate: bool = True

class OptimizeIn(BaseModel):
    scenario_id: int | None = None
    aggregate: bool = False
    minimum_gap: int = Field(default=5, ge=0, le=30)
    max_time_seconds: float = Field(default=5.0, gt=0.1, le=30.0)

    @model_validator(mode="after")
    def explicit_scenario_scope(self):
        if self.scenario_id is None and not self.aggregate:
            raise ValueError("Provide scenario_id for selected-scenario optimization or set aggregate=true")
        if self.scenario_id is not None and self.aggregate:
            raise ValueError("scenario_id and aggregate=true cannot be combined")
        return self

class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)

class AlternativeIn(BaseModel):
    reason: str = Field(default="Station master requested another feasible option", max_length=1000)
    instruction: InstructionIn | None = None
    minimum_gap: int = Field(default=5, ge=0, le=30)
    max_time_seconds: float = Field(default=5.0, gt=0.1, le=30.0)

class SimulationPatch(BaseModel):
    paused: bool | None = None
    speed: int | None = Field(default=None, ge=1, le=5)
    advance_minutes: int = Field(default=0, ge=0, le=180)
    # The browser supplies these from the timetable it is actually rendering.
    # They are deliberately optional so existing API clients keep their current contract.
    start_min: int | None = Field(default=None, ge=0, le=1440)
    loop_start_min: int | None = Field(default=None, ge=0, le=1440)
    seek_min: int | None = Field(default=None, ge=0, le=1440)
    reset: bool = False

class AssistantInterpretIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)

class AssistantConfirmIn(BaseModel):
    scenario_id: int | None = None
    instruction: InstructionIn | None = None
    disruption: DisruptionIn | None = None
    title: str = "Assistant instruction"

VoiceExplanationType = Literal[
    "current_status", "disruption_summary", "proposal_summary", "platform_changes",
    "delay_analysis", "validation_summary", "approval_summary", "rejection_summary",
    "infeasibility_summary", "train_summary", "question",
]

class VoiceExplainIn(BaseModel):
    kind: VoiceExplanationType
    proposal_id: int | None = Field(default=None, ge=1)
    train_id: str | None = Field(default=None, max_length=16)
    question: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def voice_request_shape(self):
        if self.kind == "train_summary" and not self.train_id:
            raise ValueError("train_summary requires train_id")
        if self.kind == "question" and not (self.question and self.question.strip()):
            raise ValueError("question requires question text")
        return self

class VoiceSpeakIn(VoiceExplainIn):
    """Speech is generated only from a bounded, server-generated explanation."""
