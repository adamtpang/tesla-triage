# Book a service slot for every fault message

Every one of the 300 tagged fault messages gets a service slot in the week of 16 to 21 November 2026. A free OpenRouter model books each one by calling a `book_slot` tool. The tool enforces the slot rules, so the model can choose a slot but can't break a rule. Then the safety tags are compared with the 60 messages Hannah Lindqvist checked by hand.

```bash
python book.py
```

This needs the stage 01 fault batch in `../01-urgency-rules/data/`, the slots CSV in `data/open_service_slots_2026-11-16.csv`, and the OpenRouter key in `../.env`. Both CSVs are simulation data and are gitignored. It only calls `:free` models.

**Deliverables:** [`results/schedule.csv`](results/schedule.csv) (all 300 bookings) and [`results/safety_report.md`](results/safety_report.md) (recall, misses, the NONE-code and calm-tone breakdown, and the next batch for Hannah). Regenerate the report offline with `python safety_check.py`.

## The problem: same day for 105 safety messages doesn't fit

| Slot type | Monday 16 Nov | Whole week | Needed |
| --- | --- | --- | --- |
| Service center bay | **24** | 194 | 105 safety tows + 78 routine visits = 183 |
| Mobile service | 8 | 64 | 62 |
| Remote / OTA | 10 | 38 | **55** remote fix |
| Support callback | 6 | 24 | overflow |

All 320 slots are open and none are double-booked, so 300 messages fit this week in total. But "safety faults get booked the same day" can't hold for all 105: Monday has 24 bays. I didn't fix that by narrowing the safety tag. The 45 safety messages Hannah didn't check include a brake pedal that "dropped to the floor" (MSG-10018), and a tag shouldn't drop just because the schedule is full.

## The slot rules: a tiered safety queue

1. **Every safety urgent driver is handled the same day.** They get a call on Monday, are told not to drive, and get a tow timed to their slot.
2. **Tier 1 gets the 24 Monday bays.** These are the most severe cases: cars already off the road first, then the worst symptoms (pedal to the floor, brake fluid, a sinking pedal, locking wheels, heavy steering), then hand-checked faults, then oldest first.
3. **Tier 2, the other 81, take the earliest bays after that**, ahead of every soon and routine booking. A safety message must take the earliest open bay, and the tool rejects any soon or routine message that asks for a bay while a safety message is still unbooked.
4. **Soon, then routine**, go on the earliest day that still has a slot of their type.
5. **The fix path decides the slot type:** tow and service center visit use a bay, mobile service uses a mobile van, and remote fix uses the remote desk.
6. **Overflow is allowed only once the primary type is full.** Remote fix overflows to a support callback, where a technician walks the driver through the fix by phone. Safety tows never overflow: it's a bay or nothing.

The rules are Pydantic models (`SlotRules`, `Slot`, `BookSlotArgs`) and fail on load if, for example, a fix path has no slot type, or a safety tow is allowed anywhere except a bay.

The bay hold for safety used to depend only on queue order: safety messages are sent to the model first, so no lower tag ever reached a bay early. It is now a hard rule in `book_slot` too, so a change to batching can't quietly break it. `python -m pytest test_book.py` covers it, including a check that the real schedule never gives a soon or routine message a bay before the last safety bay.

## How the model books

- The queue is sorted in priority order and sent in batches of 10, together with the earliest open slots that fit.
- The model calls `book_slot(message_id, slot_id)` once per message. The tool returns `ok`, or the exact rule the booking broke ("safety message must take the earliest open bay: 2026-11-16 07:00"), and the model tries again.
- After 4 turns, any message still unbooked is booked by code into the earliest valid slot, and marked `fallback` in the schedule.

## Result

| Day | Safety urgent | Soon | Routine |
| --- | --- | --- | --- |
| Mon 16 | 24 | 8 | 16 |
| Tue 17 | 34 | 12 | 16 |
| Wed 18 | 42 | 14 | 10 |
| Thu 19 | 5 | 14 | 45 |
| Fri 20 | 0 | 12 | 43 |
| Sat 21 | 0 | 2 | 3 |

- **All 300 messages are booked this week.** The model booked 288 through the tool. 12 went to the code fallback, and all 12 are routine, so the model itself booked every safety and soon message.
- **All five schedule checks pass:** every message is booked, no slot is double-booked, every booking uses a slot type its fix path allows, every safety message is in a bay, and no safety message is booked after a lower-ranked one.
- **24 safety cars get a Monday bay. The last safety booking is Thursday 19 November at 08:00.** No soon or routine message got a bay before that.
- Monday's 16 routine bookings use only the remote desk and support callbacks, never a bay a safety car could have had.
- **17 remote fixes overflowed to support callbacks**, because the remote desk has 38 slots for 55 remote fixes.

## Compared with Hannah Lindqvist's 60 hand-checked messages

- **60 of 60** hand-checked safety faults are tagged safety urgent. None was missed.
- 13 of them are in the Monday tier. The other 47 are in tier 2, and all 60 are booked by Wednesday 18 November. No hand-checked fault was missed, and the report breaks them down by code NONE (37 of 37 caught) and calm tone (19 of 19 caught).
- **45 safety urgent messages were never hand-checked.** Hannah's set has no confirmed non-safety rows, so they can't be scored right or wrong. The report lists their IDs as the next set to send her.

## What I'd change next

- **Tier 2 waits up to three days with the car parked.** If the center can add Monday or Tuesday bay capacity, or a mobile technician can safely inspect some brake complaints, that's where it should go first.
- **The order of the safety queue is a judgment call.** It's a keyword severity score plus "off the road". An advisor's two-minute call on Monday should be able to move a car between tiers.
