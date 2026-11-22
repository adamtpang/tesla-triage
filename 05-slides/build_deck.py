"""Build the Morning fault queue slide deck from the repo's own data.

    python build_deck.py

Every number on a slide is computed here from the stage 01 to 04 data and results,
then written into deck.html (a self-contained deck, arrow keys to move) and deck.pdf.
"""

from __future__ import annotations

import base64
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "04-queue-page"))

from queue_core import (ACCEPTANCE_CSV, late_safety, load, load_everything, place,  # noqa: E402
                        row_from_rules)

SAFETY_CODES = ("BRK", "ABS", "ESP", "EPAS")


def numbers() -> dict:
    rows, slots, base = load_everything()
    tag = {r.msg.message_id: r.tag.value for r in rows}

    # Before: first come, first served, in arrival order.
    fifo = sorted(rows, key=lambda r: (r.msg.received_at, r.msg.message_id))
    pos = {r.msg.message_id: i for i, r in enumerate(fifo, 1)}
    safety = [m for m, t in tag.items() if t == "safety_urgent"]
    fifo_pos = sorted(pos[m] for m in safety)
    others_ahead = [sum(1 for x, t in tag.items() if t != "safety_urgent" and pos[x] < pos[m])
                    for m in safety]
    wipers = [r.msg.message_id for r in rows if r.msg.vehicle_alert_code.startswith("WIP")]
    behind_wiper = sum(1 for m in safety if any(pos[w] < pos[m] for w in wipers))

    # After: the queue page order.
    page = sorted(base, key=lambda m: base[m].rank)

    hand = [r for r in rows if r.msg.hand_checked_safety_fault]
    alert_only = sum(r.msg.vehicle_alert_code.split("_")[0] in SAFETY_CODES for r in hand)
    none_code = sum(r.msg.vehicle_alert_code.upper() == "NONE" for r in hand)

    summary02 = json.loads((ROOT / "02-classify-messages/results/summary.json").read_text(encoding="utf-8"))
    summary03 = json.loads((ROOT / "03-book-slots/results/summary.json").read_text(encoding="utf-8"))

    accept, _ = load(ACCEPTANCE_CSV)
    acc = {m.message_id: place(row_from_rules(m), rows, slots, base) for m in accept}
    acc_match = sum((p.row.tag.value == "safety_urgent") == p.row.msg.hand_checked_safety_fault
                    for p in acc.values())

    def card(mid):
        p = acc[mid]
        s = p.booking.slot
        return {"id": mid, "subject": p.row.msg.message_subject, "tag": p.row.tag.value,
                "path": p.row.fix_path.value.replace("_", " "), "rank": p.booking.rank,
                "slot": f"{s.slot_date:%a %d %b} {s.slot_start_time}"}

    return {
        "n": len(rows), "n_safety": len(safety),
        "fifo_tags": [tag[r.msg.message_id] for r in fifo],
        "page_tags": [tag[m] for m in page],
        "fifo_median": int(statistics.median(fifo_pos)), "fifo_worst": max(fifo_pos),
        "fifo_outside": sum(p > len(safety) for p in fifo_pos),
        "others_ahead_avg": round(statistics.mean(others_ahead)), "others_ahead_max": max(others_ahead),
        "behind_wiper": behind_wiper,
        "page_last_safety_rank": max(base[m].rank for m in safety),
        "hand": len(hand), "alert_only": alert_only, "none_code": none_code,
        "rules_caught": sum(tag[r.msg.message_id] == "safety_urgent" for r in hand),
        "model_caught": summary02["caught_by_model_alone"],
        "summary02": summary02,
        "booked": sum(b.slot is not None for b in base.values()),
        "by_day": summary03["bookings_by_day"],
        "checks_passed": sum(summary03["checks"].values()), "checks": len(summary03["checks"]),
        "late": len(late_safety(rows, base)),
        "acc_n": len(accept), "acc_match": acc_match,
        "c10309": card("MSG-10309"), "c10301": card("MSG-10301"), "c10305": card("MSG-10305"),
    }


def img(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def main() -> int:
    data = numbers()
    print(json.dumps({k: v for k, v in data.items() if not k.endswith("_tags") and k != "summary02"}, indent=1))
    html = (HERE / "deck_template.html").read_text(encoding="utf-8")
    html = (html.replace("/*DATA*/null", json.dumps(data))
                .replace("{{IMG_TOP}}", img(ROOT / "04-queue-page/screenshots/queue-top.png"))
                .replace("{{IMG_10309}}", img(ROOT / "04-queue-page/screenshots/msg-10309.png")))
    out = HERE / "deck.html"
    out.write_text(html, encoding="utf-8")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(channel="msedge")
            pg = b.new_page(viewport={"width": 1600, "height": 900})
            pg.goto(out.as_uri() + "?print")
            pg.wait_for_timeout(800)
            pg.pdf(path=str(HERE / "deck.pdf"), width="1600px", height="900px",
                   print_background=True, margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
            b.close()
        print("wrote deck.html and deck.pdf")
    except ImportError:
        print("wrote deck.html (install playwright for deck.pdf)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
