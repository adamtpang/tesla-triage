"""Book a service slot this week for every tagged fault message.

A free OpenRouter model books each message by calling a `book_slot` tool.
The tool enforces the slot rules, so the model can choose but cannot break
them: a booking with the wrong slot type, a taken slot, a safety message
skipping past an earlier open bay, or a soon or routine message taking a bay
while a safety message is still unbooked is rejected and the model retries.

The slot rules (the tiered safety queue):
- 105 messages are safety urgent, but Monday 16 November has only 24 bays.
  Every safety driver is called the same day and told not to drive. The
  Monday bays go to the most severe cases first; the rest get the earliest
  bays after that, and the tow is timed to their slot.
- Safety bookings come first and must take the earliest open bay.
- Soon, then routine, fill what is left, on the earliest day with room.
- Remote fix overflows to support callbacks when the remote desk is full.

Usage:
    python book.py
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "01-urgency-rules"))
sys.path.insert(0, str(ROOT / "02-classify-messages"))

from classify import api_key  # noqa: E402
from rules import PathName, Tag  # noqa: E402
from triage import load, tag_message  # noqa: E402

MODELS = [
    "nvidia/nemotron-3.5-super-vl:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "baidu/ernie-5.5-flash-preview:free",
]
API = "https://openrouter.ai/api/v1/chat/completions"
BATCH_SIZE = 10
MAX_TURNS = 4

SlotType = Literal["service_center_bay", "mobile_service_visit",
                   "remote_ota_or_diagnostic", "support_callback"]

# Signs a safety case is the most severe. Used to order the safety queue.
SEVERE = re.compile(r"\bfloor\b|\bfluid\b|went long|goes long|sinks?|spongy|grabs|"
                    r"\block\w*\b|slid\b|jerks?\b|heavy|stiff|unsettled|cut power", re.I)


class Slot(BaseModel):
    slot_id: str = Field(pattern=r"^SLOT-\d{4}$")
    slot_date: date
    slot_start_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    duration_minutes: int = Field(gt=0)
    slot_type: SlotType
    bay_id: str
    technician_id: str = Field(pattern=r"^TECH-\d{2}$")
    status: Literal["open"]

    @property
    def start(self) -> tuple[date, str]:
        return (self.slot_date, self.slot_start_time)


class SlotRules(BaseModel):
    """Which slot types each fix path may use, in order of preference.
    Later types are overflow, allowed only when earlier types are full."""
    same_day: date
    path_slot_types: dict[PathName, list[SlotType]]

    @model_validator(mode="after")
    def complete(self):
        missing = set(PathName) - set(self.path_slot_types)
        if missing:
            raise ValueError(f"no slot types for {sorted(m.value for m in missing)}")
        if self.path_slot_types[PathName.TOW] != ["service_center_bay"]:
            raise ValueError("safety tows must go to a service center bay, nothing else")
        return self


SLOT_RULES = SlotRules(
    same_day=date(2026, 11, 16),
    path_slot_types={
        PathName.TOW: ["service_center_bay"],
        PathName.MOBILE_SERVICE: ["mobile_service_visit", "service_center_bay"],
        PathName.SERVICE_CENTER: ["service_center_bay"],
        PathName.REMOTE_FIX: ["remote_ota_or_diagnostic", "support_callback"],
    },
)


class BookSlotArgs(BaseModel):
    """Arguments the model passes to the book_slot tool."""
    message_id: str = Field(pattern=r"^MSG-\d{5}$")
    slot_id: str = Field(pattern=r"^SLOT-\d{4}$")


BOOK_SLOT_TOOL = {
    "type": "function",
    "function": {
        "name": "book_slot",
        "description": "Book one open service slot for one fault message. Returns ok, or the "
                       "rule the booking broke so you can pick another slot.",
        "parameters": BookSlotArgs.model_json_schema(),
    },
}


class Item(BaseModel):
    message_id: str
    tag: Tag
    fix_path: PathName
    tier: str
    rank: int
    hand_checked_safety_fault: bool


class Scheduler:
    """Holds the open slots and enforces the slot rules on every booking."""

    def __init__(self, slots: list[Slot], items: list[Item], rules: SlotRules):
        self.open = {s.slot_id: s for s in slots}
        self.slots = {s.slot_id: s for s in slots}
        self.items = {i.message_id: i for i in items}
        self.rules = rules
        self.booked: dict[str, tuple[str, str]] = {}

    def allowed_types(self, item: Item) -> list[SlotType]:
        """Primary type while it has room, then overflow types in order."""
        for t in self.rules.path_slot_types[item.fix_path]:
            if any(s.slot_type == t for s in self.open.values()):
                return [t]
        return []

    def eligible(self, item: Item) -> list[Slot]:
        types = self.allowed_types(item)
        return sorted((s for s in self.open.values() if s.slot_type in types),
                      key=lambda s: (s.start, s.slot_id))

    def safety_waiting(self) -> int:
        """Safety messages that still have no bay."""
        return sum(1 for i in self.items.values()
                   if i.tag is Tag.SAFETY_URGENT and i.message_id not in self.booked)

    def check(self, item: Item, slot: Slot) -> str | None:
        eligible = self.eligible(item)
        if not eligible:
            return "no open slot of an allowed type is left this week"
        if slot.slot_type not in self.allowed_types(item):
            return (f"{item.fix_path.value} must use {self.allowed_types(item)[0]} now, "
                    f"not {slot.slot_type}")
        if (slot.slot_type == "service_center_bay" and item.tag is not Tag.SAFETY_URGENT
                and self.safety_waiting()):
            return (f"bays are held for safety: {self.safety_waiting()} safety "
                    f"message(s) still need a bay")
        if item.tag is Tag.SAFETY_URGENT and slot.start > eligible[0].start:
            return (f"safety message must take the earliest open bay: "
                    f"{eligible[0].slot_date} {eligible[0].slot_start_time}")
        if slot.slot_date > eligible[0].slot_date:
            return f"book on the earliest day with room: {eligible[0].slot_date}"
        return None

    def book(self, message_id: str, slot_id: str, source: str) -> str:
        item = self.items.get(message_id)
        if item is None:
            return f"error: unknown message {message_id}"
        if message_id in self.booked:
            return f"error: {message_id} is already booked"
        slot = self.open.get(slot_id)
        if slot is None:
            return f"error: {slot_id} is not open"
        problem = self.check(item, slot)
        if problem:
            return f"error: {problem}"
        del self.open[slot_id]
        self.booked[message_id] = (slot_id, source)
        return f"ok: {message_id} booked into {slot_id} ({slot.slot_type}, {slot.slot_date} {slot.slot_start_time})"

    def fallback(self, item: Item) -> str:
        eligible = self.eligible(item)
        if not eligible:
            return "unbooked"
        self.book(item.message_id, eligible[0].slot_id, "fallback")
        return eligible[0].slot_id


def build_queue(messages, tags) -> list[Item]:
    """Safety first, most severe first; then soon; then routine."""
    rows = []
    for m in messages:
        t = tags[m.message_id]
        d = tag_message(m)
        text = f"{m.message_subject}. {m.message_text}"
        severe = bool(SEVERE.search(text))
        rows.append((m, Tag(t["tag"]), PathName(t["fix_path"]), d.off_the_road, severe))

    order = {Tag.SAFETY_URGENT: 0, Tag.SOON: 1, Tag.ROUTINE: 2}
    rows.sort(key=lambda r: (order[r[1]], not r[3], not r[4],
                             not r[0].hand_checked_safety_fault, r[0].received_at))
    monday_bays = sum(1 for s in SLOTS if s.slot_type == "service_center_bay"
                      and s.slot_date == SLOT_RULES.same_day)
    items, safety_rank = [], 0
    for rank, (m, tag, path, off_road, severe) in enumerate(rows, 1):
        if tag is Tag.SAFETY_URGENT:
            safety_rank += 1
            tier = "safety_tier_1_same_day" if safety_rank <= monday_bays else "safety_tier_2_next_bay"
        else:
            tier = tag.value
        items.append(Item(message_id=m.message_id, tag=tag, fix_path=path, tier=tier, rank=rank,
                          hand_checked_safety_fault=m.hand_checked_safety_fault))
    return items


SYSTEM = """You book service slots for a Tesla service center. You get a short queue of fault messages, already in priority order, and the open slots that fit them. Call the book_slot tool once for every message in the queue.

Rules (the tool enforces them and tells you if a booking breaks one):
1. Book in the order given. Earlier messages are more urgent.
2. Fix path decides slot type: tow_to_service_center and service_center_visit -> service_center_bay; mobile_service -> mobile_service_visit; remote_fix -> remote_ota_or_diagnostic, or support_callback once the remote desk is full.
3. A safety_urgent message must take the earliest open service_center_bay. Never let a safety message wait behind a later one.
4. Other messages go on the earliest day that still has an open slot of their type. No soon or routine message may take a service_center_bay while any safety_urgent message is still unbooked.
5. Never book a slot twice. If the tool returns an error, read it and book a different slot.

Call book_slot for every message. Do not answer in prose."""


def queue_prompt(batch: list[Item], sched: Scheduler) -> str:
    lines = ["QUEUE (book in this order):"]
    for i in batch:
        lines.append(f"- {i.message_id}: tag={i.tag.value}, fix_path={i.fix_path.value}, tier={i.tier}")
    types = {t for i in batch for t in sched.allowed_types(i)}
    lines.append("\nOPEN SLOTS that fit (earliest first):")
    for t in sorted(types):
        open_t = sorted((s for s in sched.open.values() if s.slot_type == t),
                        key=lambda s: (s.start, s.slot_id))[:len(batch) + 8]
        for s in open_t:
            lines.append(f"- {s.slot_id}: {s.slot_type}, {s.slot_date} {s.slot_start_time}, "
                         f"{s.duration_minutes} min, {s.bay_id}, {s.technician_id}")
    return "\n".join(lines)


def chat(model: str, key: str, messages: list[dict]) -> dict:
    if not model.endswith(":free"):
        raise SystemExit(f"refusing non-free model {model}")
    body = {"model": model, "temperature": 0, "messages": messages,
            "tools": [BOOK_SLOT_TOOL], "tool_choice": "auto"}
    req = urllib.request.Request(API, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "X-Title": "tesla-triage"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)["choices"][0]["message"]


def book_batch(batch: list[Item], sched: Scheduler, key: str, log, model_index=[0]) -> None:
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": queue_prompt(batch, sched)}]
    for _ in range(MAX_TURNS):
        if all(i.message_id in sched.booked for i in batch):
            return
        reply = None
        for attempt in range(len(MODELS) * 2):
            model = MODELS[model_index[0] % len(MODELS)]
            try:
                reply = chat(model, key, msgs)
                break
            except urllib.error.HTTPError as e:
                log(f"  {model}: HTTP {e.code}, trying next model")
            except Exception as e:  # timeouts, dropped connections
                log(f"  {model}: {type(e).__name__}, trying next model")
            model_index[0] += 1
            time.sleep(5)
        if reply is None:
            return
        calls = reply.get("tool_calls") or []
        if not calls:
            remaining = [i.message_id for i in batch if i.message_id not in sched.booked]
            msgs += [{"role": "assistant", "content": reply.get("content") or ""},
                     {"role": "user", "content": f"Still unbooked: {remaining}. Call book_slot for each."}]
            continue
        msgs.append({"role": "assistant", "content": reply.get("content") or "", "tool_calls": calls})
        for c in calls:
            try:
                args = BookSlotArgs.model_validate_json(c["function"]["arguments"])
                result = sched.book(args.message_id, args.slot_id, f"model ({model})")
            except (ValidationError, KeyError, TypeError) as e:
                result = f"error: bad arguments ({str(e).splitlines()[0][:80]})"
            msgs.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": result})
        remaining = [i.message_id for i in batch if i.message_id not in sched.booked]
        if remaining:
            msgs.append({"role": "user", "content":
                         "Still unbooked: " + ", ".join(remaining) + "\n\n" +
                         queue_prompt([sched.items[r] for r in remaining], sched)})


def load_slots(path: Path) -> list[Slot]:
    with path.open(encoding="utf-8-sig") as f:
        return [Slot.model_validate(r) for r in csv.DictReader(f)]


SLOTS: list[Slot] = []


def main(argv: list[str]) -> int:
    global SLOTS
    faults = Path(argv[1]) if len(argv) > 1 else ROOT / "01-urgency-rules/data/overnight_fault_messages_2026-11-16.csv"
    slots_csv = Path(argv[2]) if len(argv) > 2 else HERE / "data/open_service_slots_2026-11-16.csv"
    tags_csv = ROOT / "02-classify-messages/results/tags.csv"

    SLOTS = load_slots(slots_csv)
    messages, errors = load(faults)
    with tags_csv.open(encoding="utf-8") as f:
        tags = {r["message_id"]: r for r in csv.DictReader(f)}
    assert not errors and len(messages) == len(tags) == 300, "inputs do not line up"

    items = build_queue(messages, tags)
    sched = Scheduler(SLOTS, items, SLOT_RULES)
    key = api_key()

    for i in range(0, len(items), BATCH_SIZE):
        batch = items[i:i + BATCH_SIZE]
        book_batch(batch, sched, key, print)
        missed = [b for b in batch if b.message_id not in sched.booked]
        for b in missed:
            sched.fallback(b)
        print(f"  {i + len(batch)}/{len(items)} booked"
              + (f" ({len(missed)} by fallback)" if missed else ""))

    write_outputs(items, sched, messages)
    return 0


def write_outputs(items: list[Item], sched: Scheduler, messages) -> None:
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    rows = []
    for item in items:
        slot_id, source = sched.booked.get(item.message_id, ("", "unbooked"))
        s = sched.slots.get(slot_id)
        rows.append({
            "rank": item.rank, "message_id": item.message_id, "tag": item.tag.value,
            "tier": item.tier, "fix_path": item.fix_path.value, "slot_id": slot_id,
            "slot_date": s.slot_date.isoformat() if s else "", "slot_start_time": s.slot_start_time if s else "",
            "slot_type": s.slot_type if s else "", "bay_id": s.bay_id if s else "",
            "technician_id": s.technician_id if s else "", "booked_by": source,
            "hand_checked_safety_fault": item.hand_checked_safety_fault,
        })
    with (out / "schedule.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    # Checks that must hold for the schedule to be trusted.
    slot_ids = [r["slot_id"] for r in rows if r["slot_id"]]
    safety = [r for r in rows if r["tag"] == "safety_urgent"]
    checks = {
        "every message booked": all(r["slot_id"] for r in rows),
        "no slot double-booked": len(slot_ids) == len(set(slot_ids)),
        "every booking is a slot type its fix path allows": all(
            r["slot_type"] in SLOT_RULES.path_slot_types[PathName(r["fix_path"])] for r in rows),
        "every safety message is in a service center bay": all(
            r["slot_type"] == "service_center_bay" for r in safety),
        "no safety message is booked after a later-ranked safety message": all(
            (a["slot_date"], a["slot_start_time"]) <= (b["slot_date"], b["slot_start_time"])
            for a, b in zip(safety, safety[1:])),
    }

    by_day = defaultdict(Counter)
    for r in rows:
        by_day[r["slot_date"]][r["tag"]] += 1
    hand = [r for r in rows if r["hand_checked_safety_fault"]]
    tier1 = [r for r in safety if r["tier"] == "safety_tier_1_same_day"]
    summary = {
        "messages": len(rows),
        "booked_by": dict(Counter(r["booked_by"].split(" (")[0] for r in rows)),
        "models_used": dict(Counter(r["booked_by"] for r in rows if r["booked_by"].startswith("model"))),
        "slot_types_used": dict(Counter(r["slot_type"] for r in rows)),
        "safety_urgent": len(safety),
        "safety_booked_monday": sum(r["slot_date"] == SLOT_RULES.same_day.isoformat() for r in safety),
        "last_safety_booking": max(r["slot_date"] + " " + r["slot_start_time"] for r in safety),
        "remote_fix_overflow_to_callback": sum(r["fix_path"] == "remote_fix" and r["slot_type"] == "support_callback" for r in rows),
        "hand_checked": len(hand),
        "hand_checked_tagged_safety": sum(r["tag"] == "safety_urgent" for r in hand),
        "hand_checked_in_monday_tier": sum(r["tier"] == "safety_tier_1_same_day" for r in hand),
        "checks": checks,
        "bookings_by_day": {d: dict(c) for d, c in sorted(by_day.items())},
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    import safety_check
    safety_check.main(["safety_check.py"])
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
