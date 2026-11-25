"""Morning fault queue page.

    streamlit run app.py

Shows the 300 overnight messages, safety urgent on top, each with its tag, fix path
and service slot. A paste box tags and places any new message. Logic lives in
queue_core.py; this file is only the page.
"""

from datetime import datetime

import pandas as pd
import streamlit as st

from queue_core import (ACCEPTANCE_CSV, MAX_SAFETY_WAIT_DAYS, QUEUE_DAY, days_out,
                        free_text_message, late_safety, load, load_called, load_everything,
                        parse_pasted, place, row_from_rules, save_called)

TAG_LABEL = {"safety_urgent": "🔴 safety urgent", "soon": "🟠 soon", "routine": "🟢 routine"}
FOCUS = "MSG-10309"

st.set_page_config(page_title="Morning fault queue", layout="wide")


@st.cache_resource
def data():
    return load_everything()


rows, slots, base = data()
by_id = {r.msg.message_id: r for r in rows}


def when(booking) -> str:
    s = booking.slot
    if s is None:
        return "no slot left this week"
    return f"{s.slot_date:%a %d %b} {s.slot_start_time}"


def queue_frame() -> pd.DataFrame:
    out = []
    for mid, b in sorted(base.items(), key=lambda kv: kv[1].rank):
        r = by_id[mid]
        out.append({
            "rank": b.rank, "tag": TAG_LABEL[r.tag.value], "message": mid,
            "received": r.msg.received_at.replace("T", " "),
            "alert": r.msg.vehicle_alert_code, "subject": r.msg.message_subject,
            "fix path": r.fix_path.value.replace("_", " "),
            "slot": when(b), "slot type": b.slot.slot_type.replace("_", " ") if b.slot else "",
            "days out": days_out(b),
            "off the road": r.off_the_road, "severe wording": r.severe,
        })
    return pd.DataFrame(out)


def show_placement(p) -> None:
    r, b = p.row, p.booking
    st.markdown(f"### {r.msg.message_id}: {TAG_LABEL[r.tag.value]}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Fix path", r.fix_path.value.replace("_", " "))
    c2.metric("Service slot", when(b))
    if b.slot:
        c2.caption(b.slot.slot_type.replace("_", " "))
    c3.metric("Place in queue", f"{b.rank} of {p.total}")
    safety_count = sum(1 for x in rows if x.tag.value == "safety_urgent")
    if r.tag.value == "safety_urgent":
        st.success(f"Safety urgent: placed ahead of every soon and routine message, among the "
                   f"{safety_count + 1} safety messages. Call the driver now, tell them not to "
                   f"drive, and time the tow to the slot.")
        wait = days_out(b)
        if wait is None or wait > MAX_SAFETY_WAIT_DAYS:
            st.warning(f"⚠️ This safety car waits {wait if wait is not None else 'past this week'} "
                       f"days for a bay. Not enough bays: ask for more capacity or a mobile "
                       f"inspection.")
    if r.evidence:
        st.markdown("**Why:** " + "; ".join(r.evidence))
    else:
        st.markdown("**Why:** no safety or soon rule matched, so it is routine.")
    tiebreak = []
    if r.off_the_road:
        tiebreak.append("car is off the road")
    if r.severe:
        tiebreak.append("severe wording")
    behind = p.total - b.rank
    if behind:
        st.info(f"In arrival order this message would be answered last, #{p.total} of {p.total}. "
                f"Here it jumps ahead of {behind} messages.")
    st.caption(f"Tiebreak inside its tag: {', '.join(tiebreak) or 'not off the road, no severe wording'}"
               f", received {r.msg.received_at.replace('T', ' ')}. "
               f"{p.pushed_later} existing bookings move later to make room.")


st.title("Morning fault queue")
safety = sum(1 for r in rows if r.tag.value == "safety_urgent")
last_safety = max(b.slot.start for m, b in base.items() if by_id[m].tag.value == "safety_urgent")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Overnight messages", len(rows))
c2.metric("Safety urgent", safety)
c3.metric("Booked this week", sum(b.slot is not None for b in base.values()))
c4.metric("Last safety booking", f"{last_safety[0]:%a %d %b} {last_safety[1]}")

late = late_safety(rows, base)
if late:
    by_day = {}
    for m in late:
        b = base[m]
        key = f"{b.slot.slot_date:%a %d %b}" if b.slot else "no bay this week"
        by_day[key] = by_day.get(key, 0) + 1
    same_day = sum(1 for m, b in base.items() if by_id[m].tag.value == "safety_urgent"
                   and days_out(b) == 0)
    st.warning(f"⚠️ **{len(late)} of {safety} safety urgent cars wait more than "
               f"{MAX_SAFETY_WAIT_DAYS} day for a bay** "
               f"({', '.join(f'{d}: {n}' for d, n in by_day.items())}). "
               f"{QUEUE_DAY:%A} has {same_day} bays for {safety} safety cars. These drivers are "
               f"told not to drive, so every extra day is a day without a car. Add bay capacity "
               f"or send a mobile technician to inspect the brake complaints first.")
st.caption("Order: safety urgent, then soon, then routine. Same tag: cars already off the road "
           "first, then severe wording (pedal to the floor, brake fluid, locking wheels, heavy "
           "steering), then oldest first. Hand-checked status is never used, it's the answer key.")

st.header("Safety call list")
st.caption("Every safety urgent driver gets a phone call this morning: don't drive, a tow is "
           "coming, here's your slot. Tick a row once the call is done. Saved to "
           "output/called.json, so the whole team sees the same list.")
called = load_called()
call_rows = []
for mid, b in sorted(base.items(), key=lambda kv: kv[1].rank):
    r = by_id[mid]
    if r.tag.value != "safety_urgent":
        continue
    call_rows.append({"called": mid in called, "rank": b.rank, "message": mid,
                      "alert": r.msg.vehicle_alert_code, "subject": r.msg.message_subject,
                      "slot": when(b), "days out": days_out(b),
                      "off the road": r.off_the_road})
calls = pd.DataFrame(call_rows)
left, right = st.columns([3, 1])
left.metric("Still to call", f"{int((~calls['called']).sum())} of {len(calls)}")
hide = right.toggle("Hide called", value=False)
shown = calls[~calls["called"]] if hide else calls
edited = st.data_editor(shown, hide_index=True, width='stretch', height=320,
                        disabled=[c for c in calls.columns if c != "called"], key="calls")
new_called = (called - set(shown["message"])) | set(edited.loc[edited["called"], "message"])
if new_called != called:
    save_called(new_called)
    st.rerun()

st.header("Paste a message")
st.caption("Paste a row from the fault batch CSV (header optional, several rows OK), "
           "or just the message text.")
pasted = st.text_area("Message", height=140, label_visibility="collapsed",
                      placeholder="MSG-10309,2026-12-09T20:03,mobile_app,...  or  "
                                  "\"the pedal goes further down than it used to...\"")
code = st.text_input("Alert code (only for plain text)", value="NONE")
if st.button("Tag and place", type="primary") and pasted.strip():
    msgs, errors = parse_pasted(pasted)
    for e in errors:
        st.error(e)
    if len(msgs) == 1 and msgs[0].message_id == "MSG-99999":
        msgs = [free_text_message(pasted.strip(), datetime.now(), code.strip() or "NONE")]
    for m in msgs:
        try:
            show_placement(place(row_from_rules(m), rows, slots, base))
        except ValueError as e:
            st.error(str(e))

st.header("Acceptance test")
if ACCEPTANCE_CSV.exists():
    accept, errs = load(ACCEPTANCE_CSV)
    results = []
    for m in accept:
        p = place(row_from_rules(m), rows, slots, base)
        tagged_safety = p.row.tag.value == "safety_urgent"
        results.append({
            "message": m.message_id, "subject": m.message_subject, "alert": m.vehicle_alert_code,
            "tag": TAG_LABEL[p.row.tag.value], "fix path": p.row.fix_path.value.replace("_", " "),
            "slot": when(p.booking), "place": f"{p.booking.rank} of {p.total}",
            "hand-checked safety": m.hand_checked_safety_fault,
            "match": tagged_safety == m.hand_checked_safety_fault,
        })
    df = pd.DataFrame(results)
    st.metric("Tags matching the hand check", f"{int(df['match'].sum())} of {len(df)}")
    if FOCUS in set(df["message"]):
        focus = next(m for m in accept if m.message_id == FOCUS)
        with st.container(border=True):
            st.markdown(f"**The hidden brake message, {FOCUS}:** a thank-you note about a Tahoe "
                        "trip, no alert code, \"no rush at all\".")
            show_placement(place(row_from_rules(focus), rows, slots, base))
    st.dataframe(df, hide_index=True, width='stretch')
else:
    st.info("Put the acceptance CSV at data/acceptance_test_messages.csv to run it here.")

st.header("The queue")
df = queue_frame()
pick = st.multiselect("Show", list(TAG_LABEL.values()), default=list(TAG_LABEL.values()))
st.dataframe(df[df["tag"].isin(pick)], hide_index=True, width='stretch', height=600)
