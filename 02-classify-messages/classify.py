"""Tag all 300 overnight fault messages with a free OpenRouter model.

The model reads each message and returns an urgency tag and a fix path,
following the stage 01 urgency rules. Every answer is validated with
Pydantic. Then the stage 01 rules run as a backstop: if the rules find a
brake or steering symptom the model missed, the message is raised to
safety_urgent and flagged, because a missed brake warning stays missed.

Usage:
    python classify.py ../01-urgency-rules/data/overnight_fault_messages_2026-11-16.csv

Needs OPENROUTER_API_KEY in ../.env. Only models ending in ":free" are
allowed, so a run never spends money.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, model_validator

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "01-urgency-rules"))

from rules import RULES, TAG_ORDER, FaultMessage, PathName, Tag  # noqa: E402
from triage import load, tag_message  # noqa: E402

MODELS = [
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3.5-super-vl:free",
    "baidu/ernie-5.5-flash-preview:free",
]
BATCH_SIZE = 10
API = "https://openrouter.ai/api/v1/chat/completions"

PATH_TAG = {f.name: f.tag for f in RULES.fix_paths}


class Classification(BaseModel):
    """One model answer. The fix path must belong to the tag."""
    message_id: str = Field(pattern=r"^MSG-\d{5}$")
    tag: Tag
    fix_path: PathName
    symptom: str = Field(max_length=200)
    reason: str = Field(max_length=300)

    @model_validator(mode="after")
    def path_matches_tag(self):
        if PATH_TAG[self.fix_path] is not self.tag:
            raise ValueError(f"{self.fix_path.value} does not belong to {self.tag.value}")
        return self


class BatchAnswer(BaseModel):
    results: list[Classification]


def system_prompt() -> str:
    codes = "\n".join(f"- {a.code} ({a.system}): {a.tag.value}"
                      + (" [safety fault]" if a.safety_fault else "") for a in RULES.alert_codes)
    paths = "\n".join(f"- {f.name.value} -> {f.tag.value}: {f.booking}" for f in RULES.fix_paths)
    return f"""You triage overnight fault messages for a Tesla service center. Tag every message by urgency and give it a fix path, following these rules exactly.

TAGS
- safety_urgent: brakes, steering or stability may be compromised. The driver must not drive.
- soon: not a safety fault, but the car is hard to use (charge port stuck, wipers smearing across the driver's view), or the message is cut off mid-sentence and needs a call back.
- routine: everything else.

FIX PATHS (each belongs to one tag)
{paths}
For routine, use remote_fix for software problems (touchscreen, app, phone key, pairing, updates) and service_center_visit for physical problems.

DASHBOARD ALERT CODES
{codes}
Any code not listed: soon.

THE MOST IMPORTANT RULE: JUDGE THE SYMPTOM, NEVER THE TONE
Calm, polite messages often describe real safety faults. If a message describes ANY brake or steering symptom, it is safety_urgent with fix path tow_to_service_center, no matter how calm it sounds and even if the alert code is NONE. Brake or steering symptoms include: a soft, spongy, sinking or long brake pedal, a pedal that goes to the floor or pulses, any vague problem with the pedal or brakes, grinding when stopping, the car pulling, tugging or drifting when braking, heavy, stiff, loose or jerking steering, stability or traction warnings, the car feeling unsettled.
Phrases like "no rush", "happy to wait", "sorry to bother you", "not urgent", "quick question" NEVER lower the tag.

A safety alert code (BRK, ABS, ESP or EPAS) makes the message safety_urgent on its own, even if the driver sounds relaxed, guesses it is "probably a dirty sensor", or says the car "felt fine".

THE HIGHEST TAG WINS
The alert code, the symptoms and a cut-off each suggest a tag. Use the most urgent one.
A message cut off mid-sentence is tagged on what did arrive, and the cut-off never lowers the tag: a cut-off note with a safety code or a brake or steering symptom is safety_urgent (mention in the reason that someone must call back for the rest). A cut-off note with no safety signal is soon, so someone calls back before it is booked.

Examples of calm messages that are safety_urgent:
- "No rush at all, the car is generally lovely. Only thing is the brake pedal feels a bit softer than it used to, and on the off-ramp it sinks a little further before it bites. Happy to wait."
- "Sorry to bother you. There's a grinding noise from the front wheels when I'm stopped at the lights. No warning lights on screen. Thanks so much."

The opposite also holds:
- Wiper noise is never a safety fault, however scary it sounds ("horrible grinding when the wiper parks, about to snap" is soon or routine, not safety_urgent).
- If the driver says the brakes or steering feel normal, that is not a symptom.
- Cold-weather range drops are routine.

OUTPUT
Return only JSON, no prose, in this shape:
{{"results": [{{"message_id": "MSG-00000", "tag": "safety_urgent|soon|routine", "fix_path": "tow_to_service_center|mobile_service|service_center_visit|remote_fix", "symptom": "the symptom in a few words", "reason": "one short sentence"}}]}}
Return exactly one result per message, using the message_id given."""


def user_prompt(batch: list[FaultMessage]) -> str:
    lines = [f"message_id: {m.message_id}\nalert_code: {m.vehicle_alert_code}\n"
             f"subject: {m.message_subject}\ntext: {m.message_text}" for m in batch]
    return "Tag these messages:\n\n" + "\n\n---\n\n".join(lines)


def api_key() -> str:
    env = HERE.parent / ".env"
    for line in env.read_text(encoding="utf-8-sig").splitlines():
        m = re.match(r"\s*OPENROUTER_API_KEY\s*=\s*(.+)", line)
        if m and m.group(1).strip():
            return m.group(1).strip().strip("\"'")
    raise SystemExit(f"OPENROUTER_API_KEY missing from {env}")


PROMPT_VERSION = __import__("hashlib").sha256(system_prompt().encode()).hexdigest()[:12]


def call(model: str, key: str, batch: list[FaultMessage]) -> str:
    if not model.endswith(":free"):
        raise SystemExit(f"refusing non-free model {model}")
    body = {"model": model, "temperature": 0, "messages": [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": user_prompt(batch)}]}
    req = urllib.request.Request(API, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "X-Title": "tesla-triage"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)["choices"][0]["message"]["content"] or ""


def parse(text: str, batch: list[FaultMessage]) -> list[Classification]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON in reply")
    answer = BatchAnswer.model_validate_json(m.group(0))
    got = {c.message_id for c in answer.results}
    want = {b.message_id for b in batch}
    if got != want:
        raise ValueError(f"ids mismatch, missing {sorted(want - got)}, extra {sorted(got - want)}")
    return answer.results


def classify_batch(batch, key, log) -> tuple[list[Classification], str]:
    for attempt in range(3):
        for model in MODELS:
            try:
                return parse(call(model, key, batch), batch), model
            except urllib.error.HTTPError as e:
                log(f"  {model}: HTTP {e.code}")
            except (ValidationError, ValueError, json.JSONDecodeError) as e:
                log(f"  {model}: invalid answer ({str(e).splitlines()[0][:100]})")
            except Exception as e:  # timeouts, dropped connections
                log(f"  {model}: {type(e).__name__}")
        time.sleep(20 * (attempt + 1))
    raise RuntimeError(f"no valid answer for {batch[0].message_id}..{batch[-1].message_id}")


def main(argv: list[str]) -> int:
    src = Path(argv[1]) if len(argv) > 1 else HERE.parent / "01-urgency-rules/data/overnight_fault_messages_2026-11-16.csv"
    out = HERE / "output"
    out.mkdir(exist_ok=True)
    cache = out / "model_answers.jsonl"

    messages, errors = load(src)
    if errors:
        print(f"{len(errors)} rows failed validation and were skipped")
    done: dict[str, dict] = {}
    if cache.exists():
        for line in cache.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("prompt_version") == PROMPT_VERSION:
                done[row["message_id"]] = row

    key = api_key()
    todo = [m for m in messages if m.message_id not in done]
    print(f"{len(messages)} messages, {len(done)} cached, {len(todo)} to classify")
    with cache.open("a", encoding="utf-8") as f:
        for i in range(0, len(todo), BATCH_SIZE):
            batch = todo[i:i + BATCH_SIZE]
            results, model = classify_batch(batch, key, print)
            for c in results:
                row = {**c.model_dump(mode="json"), "model": model,
                       "prompt_version": PROMPT_VERSION}
                done[c.message_id] = row
                f.write(json.dumps(row) + "\n")
            f.flush()
            print(f"  {i + len(batch)}/{len(todo)} via {model}")

    rows, stats = [], Counter()
    for m in messages:
        ans = Classification.model_validate(
            {k: v for k, v in done[m.message_id].items() if k not in ("model", "prompt_version")})
        rules = tag_message(m)
        final_tag, final_path, source = ans.tag, ans.fix_path, "model"
        if TAG_ORDER[rules.tag] < TAG_ORDER[ans.tag]:
            final_tag, final_path, source = rules.tag, rules.fix_path.name, "rules backstop"
            stats["raised by backstop"] += 1
        if ans.tag is rules.tag:
            stats["model and rules agree"] += 1
        rows.append({
            "message_id": m.message_id, "tag": final_tag.value, "fix_path": final_path.value,
            "source": source, "model_tag": ans.tag.value, "rules_tag": rules.tag.value,
            "symptom": ans.symptom, "reason": ans.reason, "model": done[m.message_id]["model"],
            "hand_checked_safety_fault": m.hand_checked_safety_fault})

    order = {t.value: TAG_ORDER[t] for t in Tag}
    rows.sort(key=lambda r: (order[r["tag"]], r["message_id"]))
    with (out / "tagged_messages.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    # Public results: IDs, tags and paths only. No message text or names.
    public = HERE / "results"
    public.mkdir(exist_ok=True)
    with (public / "tags.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["message_id", "tag", "fix_path", "source", "model_tag", "rules_tag"])
        w.writeheader()
        w.writerows({k: r[k] for k in w.fieldnames} for r in rows)

    positives = [r for r in rows if r["hand_checked_safety_fault"]]
    model_caught = sum(r["model_tag"] == "safety_urgent" for r in positives)
    final_caught = sum(r["tag"] == "safety_urgent" for r in positives)
    tags = Counter(r["tag"] for r in rows)
    paths = Counter(r["fix_path"] for r in rows)
    summary = {
        "messages": len(rows),
        "tags": dict(tags), "fix_paths": dict(paths),
        "hand_checked_safety_faults": len(positives),
        "caught_by_model_alone": model_caught,
        "caught_after_backstop": final_caught,
        "model_and_rules_agree": stats["model and rules agree"],
        "raised_by_backstop": stats["raised by backstop"],
        "model_more_cautious_than_rules": sum(order[r["model_tag"]] < order[r["rules_tag"]] for r in rows),
        "models_used": dict(Counter(r["model"] for r in rows)),
    }
    (public / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
