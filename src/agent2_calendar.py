"""
Agent 2 - Calendar
==================
Writes docs/leads.ics, a standalone calendar your iPhone subscribes to
(webcal://arjunganesh2011.github.io/lead-finder/leads.ics). It books one call
per lead into fixed daily slots — **9:00 AM, 3:00 PM, 6:00 PM (3 per day)** —
filling forward day by day.

Scheduling is STABLE and CONTINUING: each lead is pinned to a slot by its slug
(stored in docs/events.json), so a lead keeps its time across runs, and newly
added leads pick up at the next open slot after the last booked one. Because
this is its own subscribed calendar at fixed times, it never shifts around based
on other things on your calendar.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs"
EVENTS_FILE = DOCS / "events.json"
ICS_FILE = DOCS / "leads.ics"
DASHBOARD_URL = "https://arjunganesh2011.github.io/lead-finder/"

SLOT_HOURS = [9, 15, 18]      # 9:00 AM, 3:00 PM, 6:00 PM
CALL_MINUTES = 30             # length of each call block
KEEP_PAST_DAYS = 7            # keep recently-past events visible
MAX_EVENTS = 1000

# Don't book any call before this date (Arjun is away until 2026-06-25; calls
# start 2026-06-26). The floor self-expires once today passes it, after which
# scheduling resumes normal "tomorrow onward" behavior. Set to None to disable.
START_FLOOR = datetime(2026, 6, 26, SLOT_HOURS[0])


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


def _first_slot(run_dt):
    """Earliest bookable slot: tomorrow's first slot, but not before START_FLOOR."""
    d = run_dt.date() + timedelta(days=1)
    tomorrow_first = datetime(d.year, d.month, d.day, SLOT_HOURS[0])
    if START_FLOOR and START_FLOOR > tomorrow_first:
        return START_FLOOR
    return tomorrow_first


def _advance(dt):
    """Next slot after `dt`: step through SLOT_HOURS, then roll to next day."""
    if dt.hour in SLOT_HOURS:
        i = SLOT_HOURS.index(dt.hour)
        if i < len(SLOT_HOURS) - 1:
            return dt.replace(hour=SLOT_HOURS[i + 1], minute=0,
                              second=0, microsecond=0)
    nd = dt.date() + timedelta(days=1)
    return datetime(nd.year, nd.month, nd.day, SLOT_HOURS[0])


def _make_event(lead, start, run_dt):
    socials = " | ".join(f"{k}: {v}" for k, v in lead.get("socials", {}).items())
    parts = [
        f"Contact: {_esc(lead.get('contact_name') or 'unknown - ask on call')}",
        f"Phone: {_esc(lead.get('phone') or 'n/a')}",
        f"Email: {_esc(lead.get('email') or 'not found')}",
        f"Tier: {_esc(lead['suggested_tier'])} ({_esc(lead['suggested_price'])})",
        f"Score: {lead['overall_score']}  |  "
        f"No-website confidence: {lead['no_website_confidence']}%  |  "
        f"Buyer signal: {lead['buyer_signal_score']}",
        f"Affordability: {_esc(lead['affordability'])}",
        f"Niche: {_esc(lead['niche'])}  |  City: {_esc(lead['city'])}",
    ]
    if lead.get("address"):
        parts.append(f"Address: {_esc(lead['address'])}")
    if socials:
        parts.append(f"Socials: {_esc(socials)}")
    parts.append(f"Dashboard: {DASHBOARD_URL}")
    return {
        "uid": f"{lead['slug']}@lead-finder",   # stable: one event per lead
        "slug": lead["slug"],
        "start": start.strftime("%Y%m%dT%H%M%S"),
        "end": (start + timedelta(minutes=CALL_MINUTES)).strftime("%Y%m%dT%H%M%S"),
        "stamp": run_dt.strftime("%Y%m%dT%H%M%SZ"),
        "summary": f"Call lead: {lead['business_name']} ({lead['city']})",
        "location": lead.get("address") or lead["city"],
        "description": "\\n".join(parts),
    }


def schedule(leads, run_dt=None):
    """Pin any not-yet-scheduled leads to the next open slots; return events."""
    run_dt = run_dt or datetime.now(timezone.utc)
    events = _load_events()
    scheduled = {e.get("slug") for e in events}

    # Cursor = latest already-booked slot (so new leads continue forward).
    cursor = None
    for e in events:
        try:
            dt = datetime.strptime(e["start"], "%Y%m%dT%H%M%S")
        except (KeyError, ValueError):
            continue
        if cursor is None or dt > cursor:
            cursor = dt

    earliest = _first_slot(run_dt)
    # Book the best leads soonest.
    new = sorted((l for l in leads if l["slug"] not in scheduled),
                 key=lambda x: x.get("overall_score", 0), reverse=True)
    for lead in new:
        start = earliest if cursor is None else _advance(cursor)
        if start < earliest:
            start = earliest
        cursor = start
        events.append(_make_event(lead, start, run_dt))

    events = events[-MAX_EVENTS:]
    EVENTS_FILE.write_text(json.dumps(events, indent=2))
    return events


def write_ics(events, run_dt=None):
    run_dt = run_dt or datetime.now(timezone.utc)
    cutoff = (run_dt - timedelta(days=KEEP_PAST_DAYS)).strftime("%Y%m%dT%H%M%S")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//arjunganesh.com//Lead Finder//EN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "X-WR-CALNAME:Website Leads",
        "X-WR-CALDESC:Lead calls - 9am / 3pm / 6pm, 3 per day",
        "X-PUBLISHED-TTL:PT6H", "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
    ]
    for e in sorted(events, key=lambda x: x["start"]):
        if e["start"] < cutoff:
            continue
        lines += [
            "BEGIN:VEVENT", f"UID:{e['uid']}", f"DTSTAMP:{e['stamp']}",
            f"DTSTART:{e['start']}", f"DTEND:{e['end']}",
            _fold(f"SUMMARY:{_esc(e['summary'])}"),
            _fold(f"LOCATION:{_esc(e['location'])}"),
            _fold(f"DESCRIPTION:{e['description']}"),
            "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:Call this lead",
            "TRIGGER:-PT15M", "END:VALARM", "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    ICS_FILE.write_text("\r\n".join(lines) + "\r\n", newline="")
    return ICS_FILE


def build_calendar(leads, run_dt=None):
    run_dt = run_dt or datetime.now(timezone.utc)
    events = schedule(leads, run_dt)
    return write_ics(events, run_dt)
