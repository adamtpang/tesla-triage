# Slides: the Morning fault queue

A 14-slide deck for the service team: the problem, the tools, what was built, the results, and what's next.

**[deck.pdf](deck.pdf)** (opens on GitHub) · [deck.html](deck.html) (download and open in a browser, arrow keys to move)

```bash
python build_deck.py
```

Every number on the slides is computed by `build_deck.py` from the repo's own data and results (stages 01 to 04), then written into `deck_template.html`. Nothing is typed in by hand, so the deck can't drift from the code. It needs the gitignored simulation data. The PDF is printed with Playwright and Microsoft Edge.

## Storyboard

| # | Slide | Headline (the one thing to remember) | Evidence |
| --- | --- | --- | --- |
| 0 | Cover | Brake warnings first | 300 messages, 105 safety urgent, 60 of 60 caught, safety at #1 to #105 |
| 1 | The problem | In arrival order, the typical safety message sat #160 of 300, behind 99 other messages | Every message's position, arrival order vs the page |
| 2 | Why it is hard | 37 of 60 confirmed safety faults had no dashboard alert, so alert codes alone catch 23 | Alert codes vs model vs model plus rules |
| 3 | Tools and approach | Four stages, each built on the one before | Rules, classify, book, page, and the tool behind each |
| 4 | Urgency rules and tagging | Three tags and four fix paths, and every message is tagged twice: by the model and by the rules | The rules table with counts, the tagging flow, 294 of 300 agree |
| 5 | The safety alert list | One test decides the list: can a fault in this system stop the car braking, steering or staying stable? | Each alert system, the test, and its tag |
| 6 | What we built | One page for the morning: safety on top, a call list, a not-enough-bays warning | Page screenshot |
| 7 | Live demo | A calm note about a soft brake pedal jumps the line, an angry wiper message doesn't | A two-minute demo script on the live page |
| 8 | Results | Every hand-checked safety fault is caught, and all 105 sit above everything else | Six result tiles |
| 9 | Key insight | The tag comes from the fault, not the tone | MSG-10309 vs the angry wiper and touchscreen messages |
| 10 | Service schedule and safety check | Every message is booked by rule, and all 60 hand-checked safety faults land in a bay by Wednesday | Booking rules, 300 of 300 booked, recall 60 of 60 |
| 11 | Data quality and missed faults | No known safety fault is missed, and every data problem found is flagged | Validation, missing alert codes, cut-off messages, VIN clashes, and the limits of the labels |
| 12 | The constraint | Monday has 24 bays for 105 safety cars, so 47 wait more than a day | Bookings by day and tag |
| 13 | Next steps | Four next steps, starting with bay capacity | Capacity, precision, one prompt fix, advisor override |

The order is one story: the problem (1 to 2), how it works (3 to 5), what was built and a live demo (6 to 7), the proof (8 to 11), and the limit and the ask (12 to 13). Each slide has a headline that states the point, one exhibit that proves it, and a "so what" line. Slide and exhibit numbers are counted automatically. If the live demo fails, slides 6 and 9 show the same screens.

## Key insights to highlight

1. **Brake warnings now sit at the top of the queue.** In arrival order, 101 of 105 safety messages had a wiper message ahead of them, and the typical one sat #160. On the page, all 105 are at #1 to #105.
2. **Most real safety faults have no dashboard alert.** 37 of the 60 hand-checked faults had alert code `NONE`. Reading the driver's words is what catches them: 60 of 60.
3. **Tone never decides the tag.** The calm Tahoe note (MSG-10309) is safety urgent with a tow. The "lose my mind" wiper message is soon, and the "honestly furious" touchscreen message is routine.
4. **The real limit is bays, not sorting.** 24 Monday bays for 105 safety cars means 47 wait more than a day. That's the ask for the service team.
