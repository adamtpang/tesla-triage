# Tesla Triage: the Morning fault queue

A Tesla service center answers overnight fault messages in the order they arrive, so a brake warning can wait behind a question about wipers. This repo builds the Morning fault queue that fixes that, one stage at a time.

| Stage | What it does |
| --- | --- |
| [01 Urgency rules](01-urgency-rules/) | Tags every message safety urgent, soon or routine, routes it to one of four fix paths (tow, mobile service, service center, remote fix), decides which dashboard alerts are safety faults, and adds a hidden safety rule for faults with no alert. Validated Pydantic models. 60 of 60 hand-checked safety faults caught. |

Built with Python, Pydantic and Claude Code.

## Data

The overnight message batch is simulation data and is not included. To run a stage, put the CSV in that stage's `data/` folder.
