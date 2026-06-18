"""
Agent 2 - Calendar
==================
Turns each lead into a follow-up event and writes docs/leads.ics, a calendar
your iPhone subscribes to (Settings/Calendar -> Add Subscribed Calendar ->
webcal://arjunganesh2011.github.io/lead-finder/leads.ics). Events are kept in
docs/events.json so the subscribed calendar shows a rolling 30-day history
instead of being wiped to only today's batch on every run.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
EVENTS_FILE = DOCS / "events.json"
ICS_FILE = DOCS / "leads.ics"
DASHBOARD_URL = "https://arjunganesh2011.github.io/lead-finder/"
ROLLING_DAYS = 30
MAX_EVENTS = 500


def _esc(text):
    return (str(text or "").replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def _fold(line):
    """Fold lines to <=75 octets per RFC 5545."""
    out = []
    while len(line.encode("utf-8")) > 75:
        cut = 75
        while len(line[:cut].encode("utf-8")) > 75:
            cut -= 1
        out.append(line[:cut])
        line = " " + line[cut:]
    out.append(line)
    return "\r\n".join(out)


def _load_events():
    if EVENTS_FILE.exists():
        try:
            return json.loads(EVENTS_FILE.read_text())
        except (ValueError, OSError):
            pass
    return []


def add_events(leads, run_dt=None):
    """Append today's leads as events; return the merged event list."""
    run_dt = run_dt or datetime.now(timezone.utc)
    events = _load_events()
    existing = {e["uid"] for e in events}
    # First follow-up slot: tomorrow 9:00am, then every 30 minutes.
    base = (run_dt + timedelta(days=1)).replace(hour=9, minute=0, second=0,
                                                microsecond=0)
    for i, lead in enumerate(leads):
        uid = f"{lead['slug']}-{run_dt:%Y%m%d}@lead-finder"
        if uid in existing:
            continue
        start = base + timedelta(minutes=30 * i)
        socials = " | ".join(f"{k}: {v}" for k, v in lead.get("socials", {}).items())
        # Escape every dynamic value (commas/semicolons are special in ICS) and
        # join with the literal "\n" sequence that ICS uses for line breaks.
        parts = [
            f"Tier: {_esc(lead['suggested_tier'])} ({_esc(lead['suggested_price'])})",
            f"Score: {lead['overall_score']}  |  "
            f"No-website confidence: {lead['no_website_confidence']}%  |  "
            f"Buyer signal: {lead['buyer_signal_score']}",
            f"Affordability: {_esc(lead['affordability'])}",
            f"Phone: {_esc(lead.get('phone') or 'n/a')}",
            f"Niche: {_esc(lead['niche'])}  |  City: {_esc(lead['city'])}",
        ]
        if socials:
            parts.append(f"Socials: {_esc(socials)}")
        parts.append(f"Dashboard: {DASHBOARD_URL}")
        desc = "\\n".join(parts)
        events.append({
            "uid": uid,
            "start": start.strftime("%Y%m%dT%H%M%S"),
            "end": (start + timedelta(minutes=30)).strftime("%Y%m%dT%H%M%S"),
            "stamp": run_dt.strftime("%Y%m%dT%H%M%SZ"),
            "summary": f"Lead: {lead['business_name']} ({lead['city']})",
            "location": lead["city"],
            "description": desc,
        })
    events = events[-MAX_EVENTS:]
    EVENTS_FILE.write_text(json.dumps(events, indent=2))
    return events


def write_ics(events, run_dt=None):
    run_dt = run_dt or datetime.now(timezone.utc)
    cutoff = (run_dt - timedelta(days=ROLLING_DAYS)).strftime("%Y%m%dT%H%M%S")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//arjunganesh.com//Lead Finder//EN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "X-WR-CALNAME:Website Leads",
        "X-WR-CALDESC:Daily ranked leads - businesses with no website",
        "X-PUBLISHED-TTL:PT12H", "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
    ]
    for e in events:
        if e["start"] < cutoff:
            continue
        lines += [
            "BEGIN:VEVENT", f"UID:{e['uid']}", f"DTSTAMP:{e['stamp']}",
            f"DTSTART:{e['start']}", f"DTEND:{e['end']}",
            _fold(f"SUMMARY:{_esc(e['summary'])}"),
            _fold(f"LOCATION:{_esc(e['location'])}"),
            _fold(f"DESCRIPTION:{e['description']}"),
            "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Follow up on lead",
            "TRIGGER:PT0M", "END:VALARM", "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    ICS_FILE.write_text("\r\n".join(lines) + "\r\n", newline="")
    return ICS_FILE


def build_calendar(leads, run_dt=None):
    run_dt = run_dt or datetime.now(timezone.utc)
    events = add_events(leads, run_dt)
    return write_ics(events, run_dt)
