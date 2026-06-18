"""
Orchestrator - runs the three agents in sequence and writes all outputs.

  Agent 1  -> find + verify + score 10 leads
  Agent 3  -> deep recon + paste-ready Claude Code prompt per lead
  Agent 2  -> calendar (.ics) for iPhone subscription
  + dashboard data (docs/leads.json) and dedupe memory (docs/seen.json)

Env: BRAVE_API_KEY (required).
"""
import os
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
SEEN_KEEP = 2000
LEADS_KEEP = 300          # rolling cap on accumulated leads shown on dashboard


def _load_seen():
    if SEEN_FILE.exists():
        try:
            return list(json.loads(SEEN_FILE.read_text()))
        except (ValueError, OSError):
            pass
    return []


def _load_existing_leads():
    if LEADS_FILE.exists():
        try:
            return list(json.loads(LEADS_FILE.read_text()).get("leads", []))
        except (ValueError, OSError):
            pass
    return []


def main():
    DOCS.mkdir(parents=True, exist_ok=True)
    run_dt = datetime.now(timezone.utc)
    maps_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not maps_key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is not set")
    client = BraveClient()
    print(f"Budget: {client.remaining()}/{client.budget} searches left this month")

    seen = _load_seen()
    seen_set = set(seen)
    existing = _load_existing_leads()

    try:
        new_leads = a1.find_leads(maps_key, client, target=TARGET,
                                  seen_slugs=seen_set)
    except BudgetExceeded as e:
        print(f"Stopped early: {e}")
        new_leads = []

    today = run_dt.date().isoformat()
    for lead in new_leads:
        lead["added"] = today
        # Agent 3: enrich + write per-lead prompt (no Brave queries here).
        a3.write_brief(lead)

    # Agent 2: calendar — only the new leads (UID dedupe keeps it idempotent).
    if new_leads:
        a2.build_calendar(new_leads, run_dt)

    # Accumulate: new leads on top, keep leftovers from prior days, cap the list.
    # (seen.json already prevents the same business reappearing.)
    all_leads = (new_leads + existing)[:LEADS_KEEP]

    LEADS_FILE.write_text(json.dumps({
        "generated": run_dt.isoformat(),
        "count": len(all_leads),
        "new_today": len(new_leads),
        "queries_used_this_month": client.used,
        "query_budget": client.budget,
        "leads": all_leads,
    }, indent=2))

    # Dedupe memory.
    seen.extend(l["slug"] for l in new_leads if l["slug"] not in seen_set)
    SEEN_FILE.write_text(json.dumps(seen[-SEEN_KEEP:], indent=2))

    print(f"\nDone: +{len(new_leads)} new ({len(all_leads)} total shown) | "
          f"{client.used}/{client.budget} searches used this month")


if __name__ == "__main__":
    main()
