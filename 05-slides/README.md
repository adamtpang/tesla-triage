# Slides: the Morning fault queue

A 10-slide deck for the service team: the problem, the tools, what was built, the results, and what's next.

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
| 4 | What we built | One page for the morning: safety on top, a call list, a not-enough-bays warning | Exhibit 4: page screenshot |
| 5 | Live demo | A calm brake note jumps the line, an angry wiper message doesn't | Exhibit 5: a two-minute demo script on the live page |
| 6 | Results | Every hand-checked safety fault is caught, and all 105 sit above everything else | Exhibit 6: six result tiles |
| 7 | Key insight | The tag comes from the fault, not the tone | Exhibit 7: MSG-10309 vs the angry wiper and touchscreen messages |
| 8 | The constraint | Monday has 24 bays for 105 safety cars, so 47 wait more than a day | Exhibit 8: bookings by day and tag |
| 9 | Next steps | Four next steps, starting with bay capacity | Capacity, precision, one prompt fix, advisor override |

The order is the story: the problem first (1 to 2), then what was built and how (3 to 4), a live demo (5), the proof (6 to 7), and the limit and the ask (8 to 9). Each slide has a headline that states the point, one exhibit that proves it, and a "so what" line. If the live demo fails, slides 4 and 7 show the same screens.

## Key insights to highlight

1. **Brake warnings now sit at the top of the queue.** In arrival order, 101 of 105 safety messages had a wiper message ahead of them, and the typical one sat #160. On the page, all 105 are at #1 to #105.
2. **Most real safety faults have no dashboard alert.** 37 of the 60 hand-checked faults had alert code `NONE`. Reading the driver's words is what catches them: 60 of 60.
3. **Tone never decides the tag.** The calm Tahoe note (MSG-10309) is safety urgent with a tow. The "lose my mind" wiper message is soon, and the "honestly furious" touchscreen message is routine.
4. **The real limit is bays, not sorting.** 24 Monday bays for 105 safety cars means 47 wait more than a day. That's the ask for the service team.
