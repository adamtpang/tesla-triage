"""Fault urgency rules for the Morning fault queue, as Pydantic models.

Every later stage of the queue reads these rules, so they are validated on
load: a typo in a regex, a missing fix path, or a safety alert code that is
not tagged safety urgent fails loudly instead of quietly misrouting a driver.

Three tags, in order of who gets help first:
    safety_urgent  brakes, steering or stability may be compromised
    soon           not a safety fault, but the car is hard to use or the
                   message is incomplete
    routine        book at the next convenient visit
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Tag(str, Enum):
    SAFETY_URGENT = "safety_urgent"
    SOON = "soon"
    ROUTINE = "routine"


TAG_ORDER = {Tag.SAFETY_URGENT: 0, Tag.SOON: 1, Tag.ROUTINE: 2}


class FixPath(BaseModel):
    """How a tagged message gets handled."""
    tag: Tag
    respond_within_hours: int = Field(gt=0)
    first_action: str
    driver_advice: str
    booking: str


class AlertCodeRule(BaseModel):
    code: str = Field(pattern=r"^[A-Z]+_[aw]\d{3}$")
    system: str
    safety_fault: bool
    tag: Tag
    why: str

    @model_validator(mode="after")
    def safety_faults_are_urgent(self):
        if self.safety_fault and self.tag is not Tag.SAFETY_URGENT:
            raise ValueError(f"{self.code} is a safety fault but is tagged {self.tag.value}")
        if not self.safety_fault and self.tag is Tag.SAFETY_URGENT:
            raise ValueError(f"{self.code} is tagged safety_urgent but not marked a safety fault")
        return self


class SymptomRule(BaseModel):
    """A symptom described in the driver's own words, matched per sentence."""
    name: str
    system: str
    patterns: list[str] = Field(min_length=1)

    @field_validator("patterns")
    @classmethod
    def patterns_compile(cls, v: list[str]) -> list[str]:
        for p in v:
            try:
                re.compile(p)
            except re.error as e:
                raise ValueError(f"invalid regex {p!r}: {e}") from None
        return v

    def match(self, sentence: str) -> str | None:
        for p in self.patterns:
            m = re.search(p, sentence, re.I)
            if m:
                return m.group(0).strip()
        return None


class HiddenSafetyRule(BaseModel):
    """Safety faults with no dashboard alert. The car shows NONE, but the
    driver describes a brake, steering or stability problem."""
    name: str
    why: str
    tag: Literal[Tag.SAFETY_URGENT] = Tag.SAFETY_URGENT
    symptoms: list[SymptomRule] = Field(min_length=1)
    normal_phrases: list[str] = Field(
        description="Phrases saying a system works normally. Removed before matching.")
    skip_sentences_mentioning: list[str] = Field(
        description="Sentences about parts that sound alarming but are not safety systems.")

    @field_validator("normal_phrases")
    @classmethod
    def normals_compile(cls, v: list[str]) -> list[str]:
        for p in v:
            try:
                re.compile(p)
            except re.error as e:
                raise ValueError(f"invalid regex {p!r}: {e}") from None
        return v


class UrgencyRules(BaseModel):
    version: str
    fix_paths: list[FixPath]
    alert_codes: list[AlertCodeRule]
    hidden_safety_rule: HiddenSafetyRule
    soon_symptoms: list[SymptomRule]
    cut_off_message_tag: Tag = Tag.SOON
    unknown_alert_code_tag: Tag = Tag.SOON
    default_tag: Tag = Tag.ROUTINE

    @model_validator(mode="after")
    def complete_and_ordered(self):
        tags = [f.tag for f in self.fix_paths]
        if sorted(tags, key=TAG_ORDER.get) != list(Tag) or len(tags) != len(set(tags)):
            raise ValueError("need exactly one fix path per tag")
        hours = [self.fix_path(t).respond_within_hours for t in Tag]
        if hours != sorted(hours) or len(set(hours)) != len(hours):
            raise ValueError("response windows must get strictly longer: safety < soon < routine")
        codes = [a.code for a in self.alert_codes]
        if len(codes) != len(set(codes)):
            raise ValueError("duplicate alert code")
        return self

    def fix_path(self, tag: Tag) -> FixPath:
        return next(f for f in self.fix_paths if f.tag is tag)

    def alert(self, code: str) -> AlertCodeRule | None:
        return next((a for a in self.alert_codes if a.code == code), None)


class FaultMessage(BaseModel):
    """One row of the overnight batch, validated before it is tagged."""
    message_id: str = Field(pattern=r"^MSG-\d{5}$")
    received_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$")
    channel: Literal["mobile_app", "email", "phone", "service_center_walk_in"]
    customer_name: str = Field(min_length=1)
    vehicle_model: Literal["Model 3", "Model Y", "Model S", "Model X"]
    model_year: int = Field(ge=2012, le=2027)
    vin_last6: str = Field(pattern=r"^[A-Z0-9]{6}$")
    odometer_km: int = Field(ge=0)
    service_center: str
    vehicle_alert_code: str
    message_subject: str
    message_text: str = Field(min_length=1)
    hand_checked: bool
    hand_checked_safety_fault: bool


# The rules themselves. Edit here; validation runs on import.
RULES = UrgencyRules(
    version="2026-11-16",
    fix_paths=[
        FixPath(tag=Tag.SAFETY_URGENT, respond_within_hours=1,
                first_action="Phone the driver before any other message is answered.",
                driver_advice="Do not drive the car until it is inspected.",
                booking="Same-day inspection. Offer a tow or mobile service if the car is parked."),
        FixPath(tag=Tag.SOON, respond_within_hours=24,
                first_action="Reply today. For a cut-off message, call back to get the missing details.",
                driver_advice="Safe to drive. Use the workaround (key card, portable charger) meanwhile.",
                booking="Mobile service or a service center slot within 3 days."),
        FixPath(tag=Tag.ROUTINE, respond_within_hours=72,
                first_action="Reply in normal order.",
                driver_advice="Safe to drive.",
                booking="Next convenient visit, or fix remotely where possible."),
    ],
    alert_codes=[
        AlertCodeRule(code="BRK_a001", system="brakes", safety_fault=True, tag=Tag.SAFETY_URGENT,
                      why="Brake system fault, including low brake fluid. Stopping power at risk."),
        AlertCodeRule(code="BRK_w003", system="brakes", safety_fault=True, tag=Tag.SAFETY_URGENT,
                      why="Brake system warning. Paired with soft or sinking pedals in this batch."),
        AlertCodeRule(code="ABS_w002", system="anti-lock brakes", safety_fault=True, tag=Tag.SAFETY_URGENT,
                      why="Wheels can lock under hard braking, especially on wet roads."),
        AlertCodeRule(code="ESP_w003", system="stability control", safety_fault=True, tag=Tag.SAFETY_URGENT,
                      why="Stability and traction control may not catch a slide."),
        AlertCodeRule(code="EPAS_w202", system="power steering", safety_fault=True, tag=Tag.SAFETY_URGENT,
                      why="Steering assist can drop out, making the wheel suddenly heavy."),
        AlertCodeRule(code="EPAS_a191", system="power steering", safety_fault=True, tag=Tag.SAFETY_URGENT,
                      why="Steering assist fault. Drivers report a heavy or jerking wheel."),
        AlertCodeRule(code="WIP_w001", system="wipers", safety_fault=False, tag=Tag.SOON,
                      why="Streaking across the driver's view in rain. Not a control system, but needs a quick swap."),
        AlertCodeRule(code="CP_a004", system="charge port", safety_fault=False, tag=Tag.SOON,
                      why="Car may not charge or release the cable. Blocks daily use, not safety."),
        AlertCodeRule(code="UI_a004", system="touchscreen", safety_fault=False, tag=Tag.ROUTINE,
                      why="Screen and app faults. Driving controls are unaffected."),
        AlertCodeRule(code="HVAC_w003", system="climate", safety_fault=False, tag=Tag.ROUTINE,
                      why="Cabin slow to heat. Comfort issue."),
    ],
    hidden_safety_rule=HiddenSafetyRule(
        name="Safety symptom with no dashboard alert",
        why=("Most hand-checked safety faults arrive with alert code NONE. A soft brake "
             "pedal, grinding when stopping, or the car pulling under braking is a safety "
             "fault whatever the dashboard says, and whatever tone the driver uses. "
             "'No rush, happy to wait' does not lower the tag."),
        symptoms=[
            SymptomRule(name="brake pedal feel", system="brakes", patterns=[
                r"\bpedal\b[^.]{0,60}\b(soft|softer|sinks?|sinking|spongy|long|floor|odd|off|"
                r"different|pulses?|pulsed|further|bites?)\b",
                r"\b(soft|spongy|long)\b[^.]{0,20}\bpedal\b"]),
            SymptomRule(name="brake warning or fault", system="brakes", patterns=[
                r"\bbrake\b[^.]{0,30}\b(warning|light|alert|fault|fluid|message)\b",
                r"\b(warning|alert)\b[^.]{0,20}\bbrake"]),
            SymptomRule(name="brakes behaving abnormally", system="brakes", patterns=[
                r"\bbrakes?\b[^.]{0,30}\b(grabby|grabs|lock|locking|feel different|feel odd)\b",
                r"\bwheels?\b[^.]{0,30}\block\b", r"\bgrabs\b"]),
            SymptomRule(name="grinding when braking or stopping", system="brakes", patterns=[
                r"\bgrind(ing)?\b[^.]{0,60}\b(stop|stopped|stopping|lights|brak\w*)\b",
                r"\b(stop|stopped|stopping|brak\w*)\b[^.]{0,40}\bgrind(ing)?\b"]),
            SymptomRule(name="pulls or drifts", system="brakes or steering", patterns=[
                r"\b(pulls?|pulling|tugs?|tugging|drifts?|drifting|jerks?)\b[^.]{0,40}"
                r"\b(left|right|one side|brak\w*|stopping|stops)\b"]),
            SymptomRule(name="steering feel", system="steering", patterns=[
                r"\bsteering\b[^.]{0,40}\b(heavy|stiff|loose|light|odd|off|jerks?|warning|assist|fault|pulls?)\b",
                r"\b(heavy|stiff|loose)\b[^.]{0,20}\bsteering\b",
                r"\bwheel\b[^.]{0,30}\b(shimmy|jerks?|heavy|light for a moment)\b", r"\bshimmy\b"]),
            SymptomRule(name="stability or traction event", system="stability", patterns=[
                r"\b(stability|traction)\b[^.]{0,30}\b(warning|light|control)\b",
                r"\bunsettled\b", r"\bslid\b", r"\bfelt loose\b", r"\bcut power\b"]),
            SymptomRule(name="ABS warning", system="anti-lock brakes", patterns=[r"\bABS\b"]),
        ],
        normal_phrases=[
            r"\b(brakes?|pedal|steering|steers?|tracks straight)\b[^.;]{0,40}?"
            r"\b(normal(ly)?|fine|the same|just the same|exactly as before|as always|ok|okay)\b"],
        skip_sentences_mentioning=[r"\bwipers?\b"],
    ),
    soon_symptoms=[
        SymptomRule(name="charge port stuck", system="charge port", patterns=[
            r"\bcharge (port|flap|cable)\b[^.]{0,60}\b(latch|release|stuck|sticks|won't|will not|locked|open)\b",
            r"\b(latch|cable)\b[^.]{0,40}\b(stuck|locked|won't release|will not release)\b"]),
        SymptomRule(name="view blocked in rain", system="wipers", patterns=[
            r"\bstreak\w*\b[^.]{0,40}\b(eyeline|view|across)\b"]),
    ],
)


if __name__ == "__main__":
    print(RULES.model_dump_json(indent=2))
