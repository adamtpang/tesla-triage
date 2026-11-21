"""Apply the fault urgency rules to the overnight message batch.

Every message is validated as a FaultMessage, tagged safety_urgent, soon or
routine by the rules in rules.py, and given that tag's fix path. Each tag
carries the exact evidence that caused it, so an advisor can check it fast.

Usage:
    python triage.py data/overnight_fault_messages_2026-11-16.csv
"""

from __future__ import annotations

import csv
import html
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from rules import RULES, TAG_ORDER, FaultMessage, Tag, UrgencyRules

# Signs the driver has already stopped driving, or is asking if it is safe to.
# Orders messages inside a tag; never changes the tag.
OFF_THE_ROAD = re.compile(
    r"stopped driving|not driven it|have not driven|haven't driven|parked (it )?at home|"
    r"off the road|until someone|before i drive|is it safe|should i (keep|leave)|"
    r"keep driving|went to (the )?floor|dropped to the floor|towed|today|tonight|scared",
    re.I)

# Tone that often hides a safety fault. Reported, never used to lower a tag.
SOFT_TONE = re.compile(
    r"no rush|not urgent|happy to wait|when convenient|whenever|sorry to bother|"
    r"quick question|no hurry|at my next visit|hope your week", re.I)

SIGN_OFF = re.compile(r"(thanks|thank you|cheers|regards)\b[\w ,]{0,20}$", re.I)


@dataclass
class Decision:
    msg: FaultMessage
    tag: Tag = Tag.ROUTINE
    evidence: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    off_the_road: bool = False
    soft_tone: bool = False

    @property
    def sort_key(self):
        return (TAG_ORDER[self.tag], not self.off_the_road, self.msg.received_at)


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def looks_cut_off(text: str) -> bool:
    """True when a message stops mid-sentence. "Thanks, Dana" is a normal ending."""
    t = text.strip()
    if not t or re.search(r"[.!?)\"']$", t):
        return False
    return not SIGN_OFF.match(re.split(r"[.!?]\s+", t)[-1])


def hidden_safety_evidence(text: str, rules: UrgencyRules) -> list[str]:
    hidden = rules.hidden_safety_rule
    found: dict[str, str] = {}
    for sentence in sentences(text):
        if any(re.search(p, sentence, re.I) for p in hidden.skip_sentences_mentioning):
            continue
        for p in hidden.normal_phrases:
            sentence = re.sub(p, " ", sentence, flags=re.I)
        for symptom in hidden.symptoms:
            hit = symptom.match(sentence)
            if hit and symptom.name not in found:
                found[symptom.name] = hit
    return [f'{name}: "{hit}"' for name, hit in found.items()]


def tag_message(msg: FaultMessage, rules: UrgencyRules = RULES) -> Decision:
    d = Decision(msg=msg)
    text = f"{msg.message_subject}. {msg.message_text}"
    candidates: list[Tag] = [rules.default_tag]

    code = msg.vehicle_alert_code.strip()
    if code and code.upper() != "NONE":
        alert = rules.alert(code)
        if alert:
            candidates.append(alert.tag)
            d.evidence.append(f"alert {code}: {alert.system}"
                              + (" (safety fault)" if alert.safety_fault else ""))
        else:
            candidates.append(rules.unknown_alert_code_tag)
            d.flags.append(f"unknown alert code {code}, check the rules")

    hidden = hidden_safety_evidence(text, rules)
    if hidden:
        candidates.append(Tag.SAFETY_URGENT)
        d.evidence.extend(f"hidden safety rule, {e}" for e in hidden)

    for symptom in rules.soon_symptoms:
        hit = symptom.match(text)
        if hit:
            candidates.append(Tag.SOON)
            d.evidence.append(f'{symptom.name}: "{hit}"')

    if looks_cut_off(msg.message_text):
        candidates.append(rules.cut_off_message_tag)
        d.flags.append("message is cut off, call back for the missing details")

    d.tag = min(candidates, key=TAG_ORDER.get)
    d.off_the_road = bool(OFF_THE_ROAD.search(text))
    d.soft_tone = bool(SOFT_TONE.search(text))
    return d


def load(path: Path) -> tuple[list[FaultMessage], list[str]]:
    messages, errors = [], []
    with path.open(encoding="utf-8-sig") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            try:
                messages.append(FaultMessage.model_validate(row))
            except ValidationError as e:
                errors.append(f"line {line} ({row.get('message_id', '?')}): "
                              + "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}"
                                          for x in e.errors()))
    return messages, errors


def vin_conflicts(messages: list[FaultMessage]) -> dict[str, set[str]]:
    seen: dict[str, set[str]] = defaultdict(set)
    for m in messages:
        seen[m.vin_last6].add(f"{m.vehicle_model} {m.model_year}")
    return {vin: cars for vin, cars in seen.items() if len(cars) > 1}


def evaluate(decisions: list[Decision]) -> dict:
    """All hand-checked rows are confirmed safety faults (positive-only labels),
    so recall is measurable and precision is not."""
    positives = [d for d in decisions if d.msg.hand_checked and d.msg.hand_checked_safety_fault]
    missed = [d for d in positives if d.tag is not Tag.SAFETY_URGENT]
    no_alert = [d for d in positives if d.msg.vehicle_alert_code.upper() == "NONE"]
    return {"positives": len(positives), "caught": len(positives) - len(missed),
            "missed": missed, "no_alert": len(no_alert)}


def write_queue(decisions: list[Decision], path: Path, rules: UrgencyRules) -> None:
    cols = ["rank", "tag", "off_the_road", "message_id", "received_at", "channel",
            "customer_name", "vehicle_model", "model_year", "vin_last6", "service_center",
            "vehicle_alert_code", "message_subject", "evidence", "flags", "soft_tone",
            "respond_within_hours", "first_action", "driver_advice", "booking"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for i, d in enumerate(decisions, 1):
            fp = rules.fix_path(d.tag)
            m = d.msg.model_dump()
            w.writerow({"rank": i, "tag": d.tag.value, "off_the_road": d.off_the_road,
                        **{k: m[k] for k in cols if k in m},
                        "evidence": " | ".join(d.evidence), "flags": " | ".join(d.flags),
                        "soft_tone": d.soft_tone, "respond_within_hours": fp.respond_within_hours,
                        "first_action": fp.first_action, "driver_advice": fp.driver_advice,
                        "booking": fp.booking})


def write_report(decisions, stats, conflicts, errors, path: Path, rules: UrgencyRules) -> None:
    esc = html.escape
    counts = Counter(d.tag for d in decisions)
    safety = [d for d in decisions if d.tag is Tag.SAFETY_URGENT]
    off_road = sum(d.off_the_road for d in safety)
    soft = sum(d.soft_tone for d in safety)
    unchecked = sum(not d.msg.hand_checked for d in safety)
    label = {Tag.SAFETY_URGENT: "Safety urgent", Tag.SOON: "Soon", Tag.ROUTINE: "Routine"}

    def row_html(i, d):
        m = d.msg
        pills = ' <span class="pill">off the road</span>' if d.off_the_road else ""
        if d.soft_tone and d.tag is Tag.SAFETY_URGENT:
            pills += ' <span class="pill soft">polite tone</span>'
        why = "<br>".join(esc(x) for x in d.evidence + d.flags)
        return (f"<tr class='{d.tag.value}'><td>{i}</td><td>{label[d.tag]}{pills}</td>"
                f"<td>{esc(m.message_id)}<br><small>{esc(m.received_at[11:16])} {esc(m.channel)}</small></td>"
                f"<td>{esc(m.vehicle_model)} {m.model_year}<br><small>{esc(m.service_center)}</small></td>"
                f"<td><b>{esc(m.message_subject)}</b><br><small>{esc(m.message_text)}</small></td>"
                f"<td><small>{why}</small></td></tr>")

    fix_rows = "".join(
        f"<tr class='{f.tag.value}'><td>{label[f.tag]}</td><td>{f.respond_within_hours} h</td>"
        f"<td>{esc(f.first_action)}</td><td>{esc(f.driver_advice)}</td><td>{esc(f.booking)}</td></tr>"
        for f in rules.fix_paths)
    code_rows = "".join(
        f"<tr class='{a.tag.value}'><td><code>{esc(a.code)}</code></td><td>{esc(a.system)}</td>"
        f"<td>{'yes' if a.safety_fault else 'no'}</td><td>{label[a.tag]}</td><td>{esc(a.why)}</td></tr>"
        for a in rules.alert_codes)
    queue = "\n".join(row_html(i, d) for i, d in enumerate(decisions, 1) if d.tag is not Tag.ROUTINE)

    def li(items):
        return "".join(f"<li>{esc(x)}</li>" for x in items) or "<li>None</li>"

    missed = li(f"{d.msg.message_id}: {d.msg.message_subject}" for d in stats["missed"])
    vins = li(f"{v}: {', '.join(sorted(c))}" for v, c in sorted(conflicts.items()))

    path.write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Morning Fault Queue</title>
<style>
:root {{ --bg:#fafaf9; --fg:#1c1917; --muted:#57534e; --line:#e7e5e4; --red:#fee2e2; --amber:#fef3c7; --acc:#b91c1c; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#1c1917; --fg:#f5f5f4; --muted:#a8a29e; --line:#44403c; --red:#450a0a; --amber:#422006; --acc:#f87171; }} }}
body {{ background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,sans-serif; margin:0 auto; max-width:1100px; padding:24px 16px; }}
h1 {{ margin:0 0 4px; }} .muted {{ color:var(--muted); }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin:20px 0; }}
.stat {{ border:1px solid var(--line); border-radius:8px; padding:12px; }} .stat b {{ font-size:28px; display:block; }}
.wrap {{ overflow-x:auto; }} table {{ border-collapse:collapse; width:100%; min-width:720px; margin-bottom:24px; }}
td,th {{ border-bottom:1px solid var(--line); padding:8px; vertical-align:top; text-align:left; }}
tr.safety_urgent td:first-child, tr.safety_urgent td:nth-child(2) {{ background:var(--red); }}
tr.soon td:first-child, tr.soon td:nth-child(2) {{ background:var(--amber); }}
.pill {{ font-size:11px; border:1px solid var(--acc); color:var(--acc); border-radius:4px; padding:0 4px; white-space:nowrap; }}
.pill.soft {{ border-color:var(--muted); color:var(--muted); }}
</style></head><body>
<h1>Morning fault queue</h1>
<p class="muted">{len(decisions)} messages from {esc(min(d.msg.received_at for d in decisions))} to {esc(max(d.msg.received_at for d in decisions))}. Rules version {esc(rules.version)}.</p>
<div class="stats">
<div class="stat"><b>{counts[Tag.SAFETY_URGENT]}</b>Safety urgent</div>
<div class="stat"><b>{off_road}</b>of those: car off the road, or driver asking if it is safe</div>
<div class="stat"><b>{soft}</b>of those: written in a polite, no-rush tone</div>
<div class="stat"><b>{counts[Tag.SOON]}</b>Soon</div>
<div class="stat"><b>{counts[Tag.ROUTINE]}</b>Routine</div>
<div class="stat"><b>{stats['caught']}/{stats['positives']}</b>hand-checked safety faults tagged safety urgent</div>
</div>
<h2>Fix paths</h2>
<div class="wrap"><table><thead><tr><th>Tag</th><th>Respond within</th><th>First action</th><th>Driver advice</th><th>Booking</th></tr></thead><tbody>{fix_rows}</tbody></table></div>
<h2>Dashboard alert codes</h2>
<div class="wrap"><table><thead><tr><th>Code</th><th>System</th><th>Safety fault</th><th>Tag</th><th>Why</th></tr></thead><tbody>{code_rows}</tbody></table></div>
<h2>Hidden safety rule</h2>
<p><b>{esc(rules.hidden_safety_rule.name)}.</b> {esc(rules.hidden_safety_rule.why)}</p>
<p>{stats['no_alert']} of the {stats['positives']} hand-checked safety faults had alert code NONE. Without this rule they would wait behind wiper questions.</p>
<h2>Checks</h2>
<ul>
<li>All hand-checked rows are confirmed safety faults. None are confirmed safe, so recall is measured and precision is not. {unchecked} safety urgent messages were never hand-checked; unchecked does not mean safe.</li>
<li>Missed hand-checked safety faults:<ul>{missed}</ul></li>
<li>Rows that failed validation:<ul>{li(errors)}</ul></li>
<li>Same VIN suffix on different cars, confirm before booking:<ul>{vins}</ul></li>
</ul>
<h2>Queue (safety urgent and soon)</h2>
<div class="wrap"><table><thead><tr><th>#</th><th>Tag</th><th>Message</th><th>Vehicle</th><th>Driver wrote</th><th>Why</th></tr></thead>
<tbody>{queue}</tbody></table></div>
</body></html>
""", encoding="utf-8")


def main(argv: list[str]) -> int:
    src = Path(argv[1]) if len(argv) > 1 else Path("data/overnight_fault_messages_2026-11-16.csv")
    out = Path(argv[2]) if len(argv) > 2 else Path("output")
    out.mkdir(parents=True, exist_ok=True)

    messages, errors = load(src)
    decisions = sorted((tag_message(m) for m in messages), key=lambda d: d.sort_key)
    stats = evaluate(decisions)
    conflicts = vin_conflicts(messages)

    write_queue(decisions, out / "fault_queue.csv", RULES)
    write_report(decisions, stats, conflicts, errors, out / "report.html", RULES)
    (out / "urgency_rules.json").write_text(RULES.model_dump_json(indent=2), encoding="utf-8")

    counts = Counter(d.tag for d in decisions)
    print(f"{len(messages)} messages tagged, {len(errors)} rejected by validation: "
          + ", ".join(f"{t.value} {counts[t]}" for t in Tag))
    print(f"Hand-checked safety faults tagged safety_urgent: {stats['caught']}/{stats['positives']}")
    for d in stats["missed"]:
        print(f"  MISSED {d.msg.message_id}: {d.msg.message_subject}")
    for e in errors:
        print(f"  INVALID {e}")
    print(f"Wrote {out / 'fault_queue.csv'}, {out / 'report.html'}, {out / 'urgency_rules.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
