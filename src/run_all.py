"""
Orchestrator - runs the three agents in sequence and writes all outputs.

  Agent 1  -> find + verify + score 10 leads
  Agent 3  -> deep recon + paste-ready Claude Code prompt per lead
  Agent 2  -> calendar (.ics) for iPhone subscription
  + dashboard data (docs/leads.json) and dedupe memory (docs/seen.json)

Env: BRAVE_API_KEY (required).
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from brave_client import BraveClient, BudgetExceeded
import agent1_lead_finder as a1
import agent2_calendar as a2
import agent3_brief_generator as a3

DOCS = Path(__file__).resolve().parent.parent / "docs"
LEADS_FILE = DOCS / "leads.json"
SEEN_FILE = DOCS / "seen.json"
TARGET = 10
SEEN_KEEP = 1000


def _load_seen():
    if SEEN_FILE.exists():
        try:
            return list(json.loads(SEEN_FILE.read_text()))
        except (ValueError, OSError):
            pass
    return []


def main():
    DOCS.mkdir(parents=True, exist_ok=True)
    run_dt = datetime.now(timezone.utc)
    client = BraveClient()
    print(f"Budget: {client.remaining()}/{client.budget} searches left this month")

    seen = _load_seen()
    seen_set = set(seen)

    try:
        leads = a1.find_leads(client, target=TARGET, seen_slugs=seen_set)
    except BudgetExceeded as e:
        print(f"Stopped early: {e}")
        leads = []

    # Agent 3: enrich + write per-lead prompt (no Brave queries used here).
    for lead in leads:
        a3.write_brief(lead)

    # Agent 2: calendar.
    if leads:
        a2.build_calendar(leads, run_dt)

    # Dashboard data.
    LEADS_FILE.write_text(json.dumps({
        "generated": run_dt.isoformat(),
        "count": len(leads),
        "queries_used_this_month": client.used,
        "query_budget": client.budget,
        "leads": leads,
    }, indent=2))

    # Dedupe memory.
    seen.extend(l["slug"] for l in leads if l["slug"] not in seen_set)
    SEEN_FILE.write_text(json.dumps(seen[-SEEN_KEEP:], indent=2))

    print(f"\nDone: {len(leads)} leads | {client.used}/{client.budget} "
          f"searches used this month")


if __name__ == "__main__":
    main()
