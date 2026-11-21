# Fault Urgency Rules

Urgency rules for a Tesla service center's Morning fault queue. Today, fault messages get answered in the order they arrive, so a brake warning can wait behind a question about wipers. These rules sort every message into one of three tags, give each tag a fix path, and decide which dashboard alerts count as safety faults.

The rules are Pydantic models in [`rules.py`](rules.py) and are validated when they load. [`triage.py`](triage.py) applies them to the overnight batch of 300 messages from 15 to 16 November 2026.

```bash
pip install -r requirements.txt
python triage.py data/overnight_fault_messages_2026-11-16.csv
python -m unittest
```

The batch CSV is simulation data and is not in this repo. Put it in `data/` to run `triage.py`. The tests run without it.

## The three tags and their fix paths

| Tag | Respond within | First action | Driver advice | Booking |
| --- | --- | --- | --- | --- |
| **Safety urgent** | 1 hour | Phone the driver before any other message is answered. | Do not drive until inspected. | Same day. Tow or mobile service if the car is parked. |
| **Soon** | 24 hours | Reply today. Call back if the message is cut off. | Safe to drive. Use the workaround (key card, portable charger). | Mobile service or a slot within 3 days. |
| **Routine** | 72 hours | Reply in normal order. | Safe to drive. | Next convenient visit, or a remote fix. |

## Which dashboard alerts are safety faults

| Code | System | Safety fault | Tag |
| --- | --- | --- | --- |
| `BRK_a001` | Brakes, including low fluid | Yes | Safety urgent |
| `BRK_w003` | Brakes | Yes | Safety urgent |
| `ABS_w002` | Anti-lock brakes | Yes | Safety urgent |
| `ESP_w003` | Stability control | Yes | Safety urgent |
| `EPAS_w202` | Power steering | Yes | Safety urgent |
| `EPAS_a191` | Power steering | Yes | Safety urgent |
| `WIP_w001` | Wipers | No | Soon (it can block the driver's view in rain) |
| `CP_a004` | Charge port | No | Soon (the car may not charge) |
| `UI_a004` | Touchscreen | No | Routine |
| `HVAC_w003` | Climate | No | Routine |

The test is simple: can a fault in this system stop the car from braking, steering or staying stable? Brakes, ABS, stability control and power steering can. Wipers, charging, the screen and the heating can't.

## The hidden safety rule

**A safety symptom with no dashboard alert is still safety urgent.**

Of the 60 hand-checked safety faults, **37 had alert code `NONE`**. Sorting on alert codes alone would leave more than half of the real safety faults behind wiper questions. The hidden rule reads the driver's own words for:

- a brake pedal that feels soft, sinks, goes long or drops to the floor
- grinding when stopping
- the car pulling or drifting under braking
- heavy, loose or jerking steering
- stability or traction events

Three refinements keep this rule honest:

1. **Tone never lowers the tag.** The most dangerous messages are often the politest: "No rush at all... the brake pedal sinks a little further before it bites." 21 safety urgent messages read this way, and the report flags them.
2. **Alarming words never raise it.** "Horrible grinding, sounds like something is about to snap" is almost always a wiper arm. Sentences about wipers are skipped by the safety rule.
3. **Saying it's normal counts against it.** "The brakes feel just the same as always" mentions brakes but describes no fault. Phrases like that are removed before matching.

## Other rules

- **The highest tag wins.** If any rule says safety urgent, the message is safety urgent.
- **Cut-off messages are Soon at minimum.** Some notes stop mid-sentence because a call dropped. Someone has to call back for the rest. If the part that did arrive already shows a safety fault, it stays safety urgent.
- **Unknown alert codes are Soon and flagged.** A new code never falls quietly into Routine.
- **Within a tag, cars already off the road go first**, then drivers asking whether it's safe to drive, then oldest first.

## Result on the overnight batch

| Tag | Messages |
| --- | --- |
| Safety urgent | 105 |
| Soon | 56 |
| Routine | 139 |

- **60 of 60** hand-checked safety faults are tagged safety urgent.
- 33 of the safety urgent drivers have already parked the car or are asking whether it's safe to drive.
- All 300 rows pass `FaultMessage` validation.

**How far to trust the numbers.** Every hand-checked row is a confirmed safety fault, and no row is confirmed safe. That means the batch can show the rules catch every known fault, but it can't show how many messages they over-flag. 45 safety urgent messages were never hand-checked, and they include a brake pedal that "dropped to the floor" (MSG-10018). Unchecked does not mean safe.

**Data issue found:** three VIN suffixes each appear on two different cars (for example, 72XA55 is both a 2024 Model X and a 2020 Model S). The report lists them so nobody books the wrong vehicle.

## Why the rules are validated

Every later part of the Morning fault queue reads these rules, so a mistake here would quietly send drivers to the wrong queue. Pydantic rejects the rules on load if:

- a safety alert code is tagged anything other than safety urgent
- a tag has no fix path, or response windows don't get longer from safety urgent to soon to routine
- an alert code appears twice, or a pattern is not a valid regex

Each incoming message is also validated as a `FaultMessage` (ID format, channel, model, year, VIN suffix), so a bad row is reported instead of being tagged.

## Judgment calls

- **Recall over precision.** Every stability warning is safety urgent, even when the driver says the car "felt fine". An extra phone call costs minutes. A missed brake fault costs far more.
- **Range drops in cold weather are Routine.** That's normal battery behavior, not a fault.
- **A touchscreen that reboots while driving is Routine.** The driving controls still work. This one is arguable.
- **Rules, not a trained model.** 60 labels that are all safety faults are too few to train on honestly, and a safety call has to be explainable. Every tag quotes the phrase that caused it.

## Files

```
rules.py           urgency rules and message schema, as Pydantic models
triage.py          applies the rules and writes the queue and report
test_triage.py     rule validation and the traps above (18 tests)
data/              the overnight batch (not published, gitignored)
output/            generated: fault_queue.csv, report.html, urgency_rules.json (gitignored)
```
