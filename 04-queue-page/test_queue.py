"""Tests for the morning fault queue logic. Offline. Skips if the gitignored data is missing."""

from datetime import datetime

import pytest

from queue_core import (ACCEPTANCE_CSV, FAULTS_CSV, SLOTS_CSV, Row, load, load_everything,
                        parse_pasted, place, row_from_rules)

pytestmark = pytest.mark.skipif(not (FAULTS_CSV.exists() and SLOTS_CSV.exists()),
                                reason="simulation data is gitignored")


@pytest.fixture(scope="module")
def world():
    return load_everything()


def test_all_300_booked_and_safety_on_top(world):
    rows, slots, base = world
    assert len(base) == 300 and all(b.slot for b in base.values())
    tags = {r.msg.message_id: r.tag.value for r in rows}
    ranked = sorted(base, key=lambda m: base[m].rank)
    n_safety = sum(t == "safety_urgent" for t in tags.values())
    assert all(tags[m] == "safety_urgent" for m in ranked[:n_safety])


def test_no_lower_tag_takes_a_bay_before_the_last_safety_bay(world):
    rows, slots, base = world
    tags = {r.msg.message_id: r.tag.value for r in rows}
    bays = [(m, b.slot.start) for m, b in base.items() if b.slot.slot_type == "service_center_bay"]
    last = max(s for m, s in bays if tags[m] == "safety_urgent")
    assert not [m for m, s in bays if tags[m] != "safety_urgent" and s < last]


def test_tiebreak_ignores_the_answer_key(world):
    rows, _, _ = world
    r = rows[0]
    flipped = Row(r.msg.model_copy(update={"hand_checked": not r.msg.hand_checked,
                                           "hand_checked_safety_fault": not r.msg.hand_checked_safety_fault}),
                  r.tag, r.fix_path, r.off_the_road, r.severe, r.evidence, r.source)
    assert flipped.key() == r.key()


def test_acceptance_set_matches_hand_check():
    msgs, errors = load(ACCEPTANCE_CSV)
    assert not errors and len(msgs) == 18
    wrong = [m.message_id for m in msgs
             if (row_from_rules(m).tag.value == "safety_urgent") != m.hand_checked_safety_fault]
    assert not wrong


def test_hidden_brake_message_lands_in_safety(world):
    rows, slots, base = world
    m = next(m for m in load(ACCEPTANCE_CSV)[0] if m.message_id == "MSG-10309")
    p = place(row_from_rules(m), rows, slots, base)
    n_safety = sum(r.tag.value == "safety_urgent" for r in rows)
    assert p.row.tag.value == "safety_urgent"
    assert p.row.fix_path.value == "tow_to_service_center"
    assert p.booking.rank <= n_safety + 1  # ahead of every soon and routine message
    assert p.booking.slot.slot_type == "service_center_bay"


def test_paste_csv_row_and_plain_text():
    line = ACCEPTANCE_CSV.read_text(encoding="utf-8").splitlines()[9]  # MSG-10309
    msgs, errors = parse_pasted(line)
    assert not errors and msgs[0].message_id == "MSG-10309"
    msgs, _ = parse_pasted("no rush, but the brake pedal feels soft", datetime(2026, 11, 16, 8))
    assert row_from_rules(msgs[0]).tag.value == "safety_urgent"
