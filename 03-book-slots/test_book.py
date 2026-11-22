"""Tests for the book_slot rules. Offline, no model calls."""

import csv
from datetime import date
from pathlib import Path

from book import SLOT_RULES, Item, Scheduler, Slot
from rules import PathName, Tag

HERE = Path(__file__).resolve().parent


def slot(sid, day, time, kind="service_center_bay"):
    return Slot(slot_id=sid, slot_date=day, slot_start_time=time, duration_minutes=60,
                slot_type=kind, bay_id="B1", technician_id="TECH-01", status="open")


def item(mid, tag, path, rank):
    return Item(message_id=mid, tag=tag, fix_path=path, tier="t", rank=rank,
                hand_checked_safety_fault=False)


MON, TUE = date(2026, 11, 16), date(2026, 11, 17)


def scheduler():
    slots = [slot("SLOT-0001", MON, "08:00"), slot("SLOT-0002", TUE, "08:00"),
             slot("SLOT-0003", TUE, "09:00")]
    items = [item("MSG-00001", Tag.SAFETY_URGENT, PathName.TOW, 1),
             item("MSG-00002", Tag.ROUTINE, PathName.SERVICE_CENTER, 2)]
    return Scheduler(slots, items, SLOT_RULES)


def test_routine_cannot_take_bay_while_safety_waits():
    s = scheduler()
    result = s.book("MSG-00002", "SLOT-0001", "model")
    assert result.startswith("error: bays are held for safety: 1")
    assert "MSG-00002" not in s.booked


def test_routine_can_take_bay_once_safety_is_booked():
    s = scheduler()
    assert s.book("MSG-00001", "SLOT-0001", "model").startswith("ok")
    assert s.book("MSG-00002", "SLOT-0002", "model").startswith("ok")


def test_safety_still_must_take_earliest_bay():
    s = scheduler()
    assert "earliest open bay" in s.book("MSG-00001", "SLOT-0002", "model")


def test_real_schedule_holds_bays_for_safety():
    """In results/schedule.csv, no soon or routine bay starts before the last safety bay."""
    path = HERE / "results/schedule.csv"
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    bays = [r for r in rows if r["slot_type"] == "service_center_bay"]
    last_safety = max((r["slot_date"], r["slot_start_time"]) for r in bays
                      if r["tag"] == "safety_urgent")
    early = [r["message_id"] for r in bays if r["tag"] != "safety_urgent"
             and (r["slot_date"], r["slot_start_time"]) < last_safety]
    assert not early
