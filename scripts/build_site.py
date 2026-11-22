"""Build the static site for tesla-triage.vercel.app into site/.

    python scripts/build_site.py

The site is a read-only snapshot: the headline results, the morning queue as the page
orders it (message IDs, tags, fix paths, slots and subjects, no names or message text),
and the slide deck. Every number comes from the repo's data, the same way the deck does.
Streamlit can't run on Vercel, so the live page with the paste box stays local.

After building, the shared PostHog snippet is added with tools/analytics/posthog-rollout.mjs
from the Aether workspace, when it's there.
"""

from __future__ import annotations

import html
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
sys.path.insert(0, str(ROOT / "05-slides"))
sys.path.insert(0, str(ROOT / "04-queue-page"))

from build_deck import numbers  # noqa: E402
from queue_core import days_out, load_everything  # noqa: E402

REPO = "https://github.com/adamtpang/tesla-triage"
ROLLOUT = ROOT.parent.parent.parent / "tools/analytics/posthog-rollout.mjs"  # Aether/tools/...
LABEL = {"safety_urgent": "safety urgent", "soon": "soon", "routine": "routine"}


def queue_rows() -> list[dict]:
    rows, _, base = load_everything()
    by_id = {r.msg.message_id: r for r in rows}
    out = []
    for mid, b in sorted(base.items(), key=lambda kv: kv[1].rank):
        r = by_id[mid]
        out.append({"rank": b.rank, "id": mid, "tag": r.tag.value,
                    "alert": r.msg.vehicle_alert_code, "subject": r.msg.message_subject,
                    "path": r.fix_path.value.replace("_", " "),
                    "slot": f"{b.slot.slot_date:%a %d %b} {b.slot.slot_start_time}",
                    "type": b.slot.slot_type.replace("_", " "), "days": days_out(b),
                    "offroad": r.off_the_road})
    return out


def page(d: dict, q: list[dict]) -> str:
    def esc(x):
        return html.escape(str(x))
    trs = "\n".join(
        f'<tr data-tag="{r["tag"]}"><td>{r["rank"]}</td><td><span class="pill {r["tag"]}">{LABEL[r["tag"]]}</span></td>'
        f'<td class="mono">{r["id"]}</td><td class="mono">{esc(r["alert"])}</td><td>{esc(r["subject"])}</td>'
        f'<td>{r["path"]}</td><td>{r["slot"]}</td><td>{r["type"]}</td>'
        f'<td>{"yes" if r["offroad"] else ""}</td></tr>' for r in q)
    c = d["c10309"]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tesla Triage: brake warnings first</title>
<meta name="description" content="A morning fault queue that puts unsafe cars first: {d['rules_caught']} of {d['hand']} hand-checked safety faults caught, all {d['n_safety']} safety messages at the top, every car booked. A work simulation project.">
<meta property="og:title" content="Tesla Triage: brake warnings first">
<meta property="og:description" content="The typical safety message sat #{d['fifo_median']} of {d['n']}. Now all {d['n_safety']} sit at the top.">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='7' fill='%23d0302f'/><path d='M9 17l5 5 9-12' stroke='white' stroke-width='3.5' fill='none' stroke-linecap='round' stroke-linejoin='round'/></svg>">
<style>
:root{{--ink:#17212b;--muted:#5f6b78;--faint:#97a2ae;--line:#e3e7eb;--band:#f4f6f8;--bg:#fff;
  --safety:#d0302f;--soon:#d68a24;--routine:#3f8f63;--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,system-ui,sans-serif;}}
@media (prefers-color-scheme:dark){{:root{{--ink:#e8edf2;--muted:#a3adb8;--faint:#7c8794;--line:#2a3138;--band:#171c21;--bg:#0f1316;}}}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.5}}
.wrap{{max-width:1100px;margin:0 auto;padding:0 16px}}
header{{padding:56px 0 28px}} .eyebrow{{font-size:12px;font-weight:800;letter-spacing:.16em;text-transform:uppercase;color:var(--safety)}}
h1{{font-size:clamp(34px,6vw,56px);line-height:1.05;margin:.25em 0 .3em;letter-spacing:-.02em}}
.lede{{font-size:clamp(17px,2.2vw,20px);color:var(--muted);max-width:760px;margin:0}}
.links{{display:flex;flex-wrap:wrap;gap:10px;margin-top:22px}}
.btn{{display:inline-block;padding:10px 16px;border-radius:8px;border:1px solid var(--line);color:var(--ink);text-decoration:none;font-weight:700;font-size:15px}}
.btn.primary{{background:var(--safety);border-color:var(--safety);color:#fff}}
.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:8px 0 36px}}
.stat{{background:var(--band);border-radius:10px;padding:16px}} .stat .n{{font-size:28px;font-weight:800;letter-spacing:-.01em}}
.stat .l{{font-size:13px;color:var(--muted)}} .red{{color:var(--safety)}}
h2{{font-size:24px;margin:40px 0 8px;letter-spacing:-.01em}} .sub{{color:var(--muted);margin:0 0 16px;max-width:780px}}
.steps{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
.step{{border:1px solid var(--line);border-radius:10px;padding:14px}} .step b{{display:block;margin-bottom:4px}} .step span{{font-size:14px;color:var(--muted)}}
.filters{{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 12px}}
.filters button{{font:inherit;font-size:14px;padding:6px 12px;border-radius:99px;border:1px solid var(--line);background:var(--bg);color:var(--ink);cursor:pointer}}
.filters button.on{{background:var(--ink);color:var(--bg);border-color:var(--ink)}}
.tablewrap{{overflow-x:auto;border:1px solid var(--line);border-radius:10px;max-height:640px}}
table{{border-collapse:collapse;width:100%;font-size:14px}} th,td{{padding:8px 10px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}}
th{{position:sticky;top:0;background:var(--band);font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}}
td:nth-child(5){{white-space:normal;min-width:240px}} .mono{{font-family:ui-monospace,Consolas,monospace;font-size:13px}}
.pill{{display:inline-block;font-size:12px;font-weight:800;padding:2px 8px;border-radius:99px;color:#fff}}
.pill.safety_urgent{{background:var(--safety)}} .pill.soon{{background:var(--soon)}} .pill.routine{{background:var(--routine)}}
.callout{{background:var(--band);border-left:3px solid var(--safety);padding:14px 16px;border-radius:0 8px 8px 0;margin:16px 0}}
footer{{color:var(--faint);font-size:13px;padding:40px 0 56px}} footer a{{color:var(--muted)}}
@media (max-width:760px){{.stats,.steps{{grid-template-columns:1fr 1fr}}}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="eyebrow">Morning fault queue</div>
  <h1>Brake warnings first</h1>
  <p class="lede">Overnight fault messages were answered in arrival order, so the typical safety message sat #{d['fifo_median']} of {d['n']}, and {d['behind_wiper']} of {d['n_safety']} had a wiper question ahead of them. This queue puts all {d['n_safety']} at the top and books every car into a slot.</p>
  <div class="links"><a class="btn primary" href="deck.html">View the slides</a><a class="btn" href="deck.pdf">Slides (PDF)</a><a class="btn" href="{REPO}">Code on GitHub</a></div>
</header>

<div class="stats">
  <div class="stat"><div class="n red">#1 to #{d['page_last_safety_rank']}</div><div class="l">where the {d['n_safety']} safety messages sit, up from a typical #{d['fifo_median']}</div></div>
  <div class="stat"><div class="n">{d['rules_caught']} of {d['hand']}</div><div class="l">hand-checked safety faults caught ({d['alert_only']} with alert codes alone)</div></div>
  <div class="stat"><div class="n">{d['acc_match']} of {d['acc_n']}</div><div class="l">acceptance test messages with the right safety call</div></div>
  <div class="stat"><div class="n">{d['booked']} of {d['n']}</div><div class="l">messages booked into a slot this week</div></div>
</div>

<h2>How it works</h2>
<p class="sub">Four stages, each built on the one before. Python, Pydantic, a free OpenRouter model, tool calling and Streamlit, built with Claude Code.</p>
<div class="steps">
  <div class="step"><b>1. Urgency rules</b><span>Three tags, four fix paths, and a hidden rule: any brake, pedal or steering symptom is safety urgent, even with no alert and a calm tone.</span></div>
  <div class="step"><b>2. Classify</b><span>A free model tags all {d['n']} messages. Pydantic checks every answer, and the rules can only raise a tag. {d['agree']} of {d['n']} agree.</span></div>
  <div class="step"><b>3. Book slots</b><span>The model books through a tool that enforces the slot rules. No bay goes to a lower tag while a safety car waits.</span></div>
  <div class="step"><b>4. Queue page</b><span>Safety on top, a paste box for new messages, a call list, and a warning when bays run out.</span></div>
</div>

<div class="callout"><b>The calm one goes first.</b> {c['id']} is a thank-you note about a road trip, with no alert code and "no rush at all". It mentions the pedal going further down than it used to. It's tagged safety urgent: {c['path']}, {c['slot']}, ahead of every angry wiper and touchscreen message.</div>

<h2>The queue</h2>
<p class="sub">All {d['n']} overnight messages in the order the page puts them, with each booked slot. A read-only snapshot. The live page with the paste box runs locally with Streamlit.</p>
<div class="filters" id="filters">
  <button class="on" data-f="all">All {d['n']}</button>
  <button data-f="safety_urgent">Safety urgent</button><button data-f="soon">Soon</button><button data-f="routine">Routine</button>
</div>
<div class="tablewrap"><table>
<thead><tr><th>#</th><th>Tag</th><th>Message</th><th>Alert</th><th>Subject</th><th>Fix path</th><th>Slot</th><th>Slot type</th><th>Off the road</th></tr></thead>
<tbody id="q">
{trs}
</tbody></table></div>

<footer>
  Built for a 0.university work simulation. The data is simulated, and this project isn't affiliated with or endorsed by Tesla. No customer names or message text are published.
  <a href="{REPO}">Source on GitHub</a>.
</footer>
</div>
<script>
document.getElementById('filters').addEventListener('click',function(e){{
  var b=e.target.closest('button'); if(!b) return;
  this.querySelectorAll('button').forEach(function(x){{x.classList.toggle('on',x===b)}});
  var f=b.dataset.f; document.querySelectorAll('#q tr').forEach(function(tr){{tr.style.display=(f==='all'||tr.dataset.tag===f)?'':'none'}});
}});
</script>
</body>
</html>
"""


def main() -> int:
    d = numbers()
    q = queue_rows()
    if SITE.exists():
        for f in SITE.iterdir():
            if f.name != ".vercel":
                shutil.rmtree(f) if f.is_dir() else f.unlink()
    SITE.mkdir(exist_ok=True)
    (SITE / "index.html").write_text(page(d, q), encoding="utf-8")
    shutil.copy(ROOT / "05-slides/deck.html", SITE / "deck.html")
    shutil.copy(ROOT / "05-slides/deck.pdf", SITE / "deck.pdf")
    (SITE / "vercel.json").write_text(json.dumps({"cleanUrls": True}, indent=2) + "\n", encoding="utf-8")
    if ROLLOUT.exists():
        subprocess.run(["node", str(ROLLOUT), "--apply", str(SITE)], check=True, capture_output=True)
        print("added the PostHog snippet")
    print(f"built {SITE} with {len(q)} queue rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
