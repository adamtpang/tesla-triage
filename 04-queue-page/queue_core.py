"""The logic behind the morning fault queue page. No Streamlit here, so it can be tested.

It pulls the three earlier stages together:
- stage 01: the urgency rules (`tag_message`) tag any pasted message, offline;
- stage 02: the tags for the 300 overnight messages (`results/tags.csv`);
- stage 03: the slot rules and the `Scheduler` that enforces them.

Tiebreak for messages with the same tag (chosen for this page):
1) cars already off the road first (the driver says it is parked, towed or unsafe to drive),
2) then severe wording (pedal to the floor, brake fluid, locking wheels, heavy steering),
3) then oldest first.
Hand-checked status is NOT used: it is the answer key, and a new message never has it.
"""

from __future__ import annotations

import csv
import io
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for stage in ("01-urgency-rules", "03-book-slots"):
    sys.path.insert(0, str(ROOT / stage))

from book import SEVERE, SLOT_RULES, Item, Scheduler, Slot, load_slots  # noqa: E402
from rules import PathName, Tag, FaultMessage  # noqa: E402
from triage import TAG_ORDER, load, tag_message  # noqa: E402

FAULTS_CSV = ROOT / "01-urgency-rules/data/overnight_fault_messages_2026-11-16.csv"
TAGS_CSV = ROOT / "02-classify-messages/results/tags.csv"
SLOTS_CSV = ROOT / "03-book-slots/data/open_service_slots_2026-11-16.csv"
ACCEPTANCE_CSV = HERE / "data/acceptance_test_messages.csv"

FIELDS = list(FaultMessage.model_fields)


@dataclass
class Row:
    """One message in the queue, with everything the page shows."""
    msg: FaultMessage
    tag: Tag
    fix_path: PathName
    off_the_road: bool
    severe: bool
    evidence: list[str]
    source: str  # "stage 02 tags" or "stage 01 rules"

    def key(self):
        return (TAG_ORDER[self.tag], not self.off_the_road, not self.severe,
                self.msg.received_at, self.msg.message_id)


def is_severe(m: FaultMessage) -> bool:
    return bool(SEVERE.search(f"{m.message_subject}. {m.message_text}"))


def row_from_rules(m: FaultMessage) -> Row:
    """Tag a new message with the stage 01 rules."""
    d = tag_message(m)
    return Row(m, d.tag, d.fix_path.name, d.off_the_road, is_severe(m), d.evidence,
               "stage 01 rules")


def base_rows(faults: Path = FAULTS_CSV, tags_csv: Path = TAGS_CSV) -> list[Row]:
    """The 300 overnight messages with their stage 02 tags."""
    messages, errors = load(faults)
    if errors:
        raise ValueError(f"fault batch has {len(errors)} bad rows")
    with tags_csv.open(encoding="utf-8") as f:
        tags = {r["message_id"]: r for r in csv.DictReader(f)}
    rows = []
    for m in messages:
        d = tag_message(m)
        t = tags[m.message_id]
        rows.append(Row(m, Tag(t["tag"]), PathName(t["fix_path"]), d.off_the_road,
                        is_severe(m), d.evidence, "stage 02 tags"))
    return rows


@dataclass
class Booking:
    rank: int
    slot: Slot | None
    booked_by: str


def schedule(rows: list[Row], slots: list[Slot]) -> dict[str, Booking]:
    """Sort by tag and tiebreak, then book each message into the earliest slot the
    stage 03 rules allow, in that order. Deterministic, no model calls."""
    ordered = sorted(rows, key=Row.key)
    items = [Item(message_id=r.msg.message_id, tag=r.tag, fix_path=r.fix_path, tier="",
                  rank=i, hand_checked_safety_fault=False)
             for i, r in enumerate(ordered, 1)]
    sched = Scheduler(slots, items, SLOT_RULES)
    out = {}
    for it in items:
        slot_id = sched.fallback(it)
        slot = sched.slots.get(slot_id)
        out[it.message_id] = Booking(it.rank, slot, "rules" if slot else "unbooked")
    return out


@dataclass
class Placement:
    row: Row
    booking: Booking
    pushed_later: int  # messages already in the queue whose slot is now later
    total: int


def place(new: Row, rows: list[Row], slots: list[Slot],
          before: dict[str, Booking] | None = None) -> Placement:
    """Drop one new message into the queue and say where it lands."""
    taken = {r.msg.message_id for r in rows}
    if new.msg.message_id in taken:
        raise ValueError(f"{new.msg.message_id} is already in the queue")
    before = before or schedule(rows, slots)
    after = schedule(rows + [new], slots)
    pushed = sum(1 for mid, b in before.items()
                 if b.slot and (after[mid].slot is None or after[mid].slot.start > b.slot.start))
    return Placement(new, after[new.msg.message_id], pushed, len(rows) + 1)


def parse_pasted(text: str, now: datetime | None = None) -> tuple[list[FaultMessage], list[str]]:
    """Read pasted text. Either CSV rows in the fault batch format (header optional),
    or plain message text, which becomes one message with no alert code."""
    text = text.strip()
    if not text:
        return [], []
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if rows and rows[0] and rows[0][0].strip() == "message_id":
        rows = rows[1:]
    if rows and all(len(r) == len(FIELDS) for r in rows):
        msgs, errors = [], []
        for r in rows:
            data = dict(zip(FIELDS, (c.strip() for c in r)))
            for k in ("hand_checked", "hand_checked_safety_fault"):
                data[k] = data[k].upper() == "TRUE"
            try:
                msgs.append(FaultMessage.model_validate(data))
            except Exception as e:  # pydantic ValidationError, shown to the user
                errors.append(f"{data.get('message_id', '?')}: {str(e).splitlines()[0]}")
        return msgs, errors
    now = now or datetime.now()
    return [free_text_message(text, now)], []


def free_text_message(text: str, now: datetime, alert_code: str = "NONE") -> FaultMessage:
    first = text.split("\n", 1)[0][:80]
    return FaultMessage(
        message_id="MSG-99999", received_at=now.strftime("%Y-%m-%dT%H:%M"),
        channel="mobile_app", customer_name="Pasted message", vehicle_model="Model 3",
        model_year=2024, vin_last6="PASTED", odometer_km=0, service_center="Unknown",
        vehicle_alert_code=alert_code, message_subject=first, message_text=text,
        hand_checked=False, hand_checked_safety_fault=False)


def load_everything():
    rows = base_rows()
    slots = load_slots(SLOTS_CSV)
    return rows, slots, schedule(rows, slots)
