# Classify every fault message by urgency

A free OpenRouter model tags all 300 overnight fault messages with an urgency tag and a fix path, following the [stage 01 urgency rules](../01-urgency-rules/). Then the stage 01 rules run as a backstop, because the service schedule books repairs from these tags, and a missed brake warning stays missed.

## Setup: OpenRouter key

1. Get a free key at [openrouter.ai/keys](https://openrouter.ai/keys).
2. From the repo root, copy the template and paste the key after the `=`:

   ```bash
   cp .env.example .env
   ```

   ```
   OPENROUTER_API_KEY=sk-or-...
   ```

3. Run it:

   ```bash
   pip install -r ../requirements.txt
   python classify.py ../01-urgency-rules/data/overnight_fault_messages_2026-11-16.csv
   ```

`.env` is gitignored, so the key never reaches GitHub. The script reads it from `../.env` and never prints it.

**It never spends money.** The script refuses to call any model whose ID doesn't end in `:free`. It tries `nvidia/nemotron-3-ultra-550b-a55b:free` first, and falls back to two other free models when that one is rate-limited.

## How it works

1. **Validate the input.** Every CSV row is checked as a `FaultMessage` (the stage 01 Pydantic model) before anything is sent.
2. **Classify in batches of 10.** The prompt is built from the stage 01 rules, so the tags, fix paths and alert codes always match them.
3. **Validate every answer.** Each reply must parse as a `Classification` (Pydantic): a valid tag, a valid fix path, and **a fix path that belongs to its tag**. It must also return exactly one answer per message ID. Invalid answers are retried, or sent to the next free model.
4. **Backstop.** The stage 01 rules tag every message too. If they find a more urgent tag than the model did, the rules win, and the row is marked `source = rules backstop`.
5. **Cache.** Answers are saved by prompt version, so a rerun only calls the model for answers it doesn't have yet. Changing the prompt reclassifies everything.

## What the prompt says about the hard cases

- **Calm messages with a brake or steering symptom are safety urgent**, with the tow path. "No rush", "happy to wait" and "sorry to bother you" never lower the tag. Two calm, hand-checked safety faults are in the prompt as examples.
- **A safety alert code (BRK, ABS, ESP, EPAS) is safety urgent on its own**, even when the driver sounds relaxed ("probably a dirty sensor", "the car felt fine").
- **The highest tag wins.** The code, the symptom and a cut-off each suggest a tag, and the most urgent one is kept. A cut-off note like MSG-10297 (an ABS code, cut off while describing the pedal) is safety urgent with a call-back. A cut-off note with no safety signal is soon.
- **Mirror image:** a scary-sounding wiper is never safety urgent, and "brakes feel normal" is not a symptom.

## Output

- `results/tags.csv`: every message ID with its final tag, fix path, source (model or rules backstop), the model's tag and the rules' tag. Public, with no message text or names.
- `results/summary.json`: counts, and how many hand-checked safety faults the model caught by itself versus after the backstop.
- `output/`: full answers with symptoms and reasons. Gitignored, because it quotes the messages.

## Result on the overnight batch

One run, all 300 messages through `nvidia/nemotron-3-ultra-550b-a55b:free`, at a cost of $0.

| Tag | Fix path | Messages |
| --- | --- | --- |
| Safety urgent | Tow to service center | 105 |
| Soon | Mobile service | 62 |
| Routine | Service center visit | 78 |
| Routine | Remote fix | 55 |

- **The model caught all 60 hand-checked safety faults by itself.** The backstop raised 0 messages. It's still there for the run where a calm message slips past.
- The calm and tricky cases were all tagged safety urgent with the tow path: MSG-10002 (polite soft pedal), MSG-10165 (grinding at the lights, no alert code), MSG-10229 (ABS code, driver guesses "a dirty wheel sensor"), MSG-10284 (stability warning, car "felt fine"), and MSG-10297 (ABS code, cut off mid-sentence, tagged with a call-back).
- **The model and the rules agree on 294 of 300.** In all 6 disagreements the model was more cautious (soon where the rules said routine), never less.

### What the disagreements taught me

- **MSG-10051:** the model was right. "Skipping across the windscreen and leaving a streak" blocks the driver's view, but the stage 01 pattern for streaking missed that wording.
- **MSG-10004, 10108, 10225:** wiper judgment calls (stuck up, chattering, grinding when parked). These are defensible either way.
- **MSG-10182 and MSG-10204 show a prompt bug.** The model reasoned "alert code NONE not listed, so soon". My prompt says "Any code not listed: soon", and the model read NONE (no alert at all) as an unlisted code. The fix is one line: "NONE means no alert. It is not an unknown code." I left the prompt unchanged so these results match the code that produced them. This fix is the first change for the next run.
