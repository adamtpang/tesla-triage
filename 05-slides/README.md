# Slides: the Morning fault queue

A 12-slide deck for the service team: the problem, the tools, what was built, the results, and what's next.

**[deck.pdf](deck.pdf)** (opens on GitHub) · [deck.html](deck.html) (download and open in a browser, arrow keys to move)

```bash
python build_deck.py
```

Every number on the slides is computed by `build_deck.py` from the repo's own data and results (stages 01 to 04), then written into `deck_template.html`. Nothing is typed in by hand, so the deck can't drift from the code. It needs the gitignored simulation data. The PDF is printed with Playwright and Microsoft Edge.

## Storyboard

| # | Slide | Headline (the one thing to remember) | Evidence |
| --- | --- | --- | --- |
| 0 | Cover | Brake warnings first | 300 messages, 105 safety urgent, 60 of 60 caught, safety at #1 to #105 |
| 1 | The problem | In arrival order, the typical safety message sat #160 of 300, behind 99 other messages | Exhibit 1: every message's position, arrival order vs the page |
| 2 | Why it is hard | 37 of 60 confirmed safety faults had no dashboard alert, so alert codes alone catch 23 | Exhibit 2: alert codes vs model vs model plus rules |
| 3 | Tools and approach | Four stages, each built on the one before | Exhibit 3: rules, classify, book, page, and the tool behind each |
| 4 | Urgency rules and tagging | Three tags and four fix paths, and every message is tagged twice: by the model and by the rules | Exhibit 4: the rules table with counts (105 / 62 / 78 / 55), the tagging flow, 294 of 300 agree |
| 5 | What we built | One page for the morning: safety on top, a call list, a not-enough-bays warning | Exhibit 5: page screenshot |
| 6 | Live demo | A calm brake note jumps the line, an angry wiper message doesn't | Exhibit 6: a two-minute demo script on the live page |
| 7 | Results | Every hand-checked safety fault is caught, and all 105 sit above everything else | Exhibit 7: six result tiles |
| 8 | Key insight | The tag comes from the fault, not the tone | Exhibit 8: MSG-10309 vs the angry wiper and touchscreen messages |
| 9 | Service schedule and safety check | Every message is booked by rule, and all 60 hand-checked safety faults land in a bay by Wednesday | Exhibit 9: booking rules, 300 of 300 booked, 5 of 5 checks, recall 60 of 60 (no alert 37 of 37, calm 19 of 19) |
| 10 | The constraint | Monday has 24 bays for 105 safety cars, so 47 wait more than a day | Exhibit 10: bookings by day and tag |
| 11 | Next steps | Four next steps, starting with bay capacity | Capacity, precision, one prompt fix, advisor override |

The order is the story: the problem first (1 to 2), then how it works, stage by stage (3 to 4), what was built and a live demo (5 to 6), the proof (7 to 9), and the limit and the ask (10 to 11). Each slide has a headline that states the point, one exhibit that proves it, and a "so what" line. Slide and exhibit numbers are counted automatically, so adding a slide never breaks them. If the live demo fails, slides 5 and 8 show the same screens.

## Key insights to highlight

1. **Brake warnings now sit at the top of the queue.** In arrival order, 101 of 105 safety messages had a wiper message ahead of them, and the typical one sat #160. On the page, all 105 are at #1 to #105.
2. **Most real safety faults have no dashboard alert.** 37 of the 60 hand-checked faults had alert code `NONE`. Reading the driver's words is what catches them: 60 of 60.
3. **Tone never decides the tag.** The calm Tahoe note (MSG-10309) is safety urgent with a tow. The "lose my mind" wiper message is soon, and the "honestly furious" touchscreen message is routine.
4. **The real limit is bays, not sorting.** 24 Monday bays for 105 safety cars means 47 wait more than a day. That's the ask for the service team.
