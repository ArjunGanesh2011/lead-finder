"""
Agent 1 - Lead Finder
=====================
Finds US local businesses that have NO website, verifies the absence with a
two-step check, estimates affordability from public buyer signals, then scores
and ranks the best leads.

Website verification (two steps, to avoid the false negatives the user has hit
with raw LLMs):
  1. Search '"Business Name" City' and inspect results. A non-directory domain
     whose page actually references the business == they HAVE a site -> reject.
  2. Guess common domains (slug.com, slugcity.com, ...) and DNS-resolve them;
     if one resolves to a real (non-parked) page -> they HAVE a site -> reject.
Only businesses that fail BOTH checks are kept.
"""
import re
import html
import socket
import requests

from util import (clean_business_name, slugify, extract_phone, domain_of,
                  is_directory, SOCIAL_DOMAINS)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

US_CITIES = [
    "Atlanta GA", "Austin TX", "Birmingham AL", "Boise ID", "Buffalo NY",
    "Charlotte NC", "Chattanooga TN", "Cincinnati OH", "Cleveland OH",
    "Colorado Springs CO", "Columbus OH", "Dallas TX", "Dayton OH", "Denver CO",
    "Des Moines IA", "Detroit MI", "El Paso TX", "Fort Wayne IN",
    "Fort Worth TX", "Fresno CA", "Grand Rapids MI", "Greensboro NC",
    "Houston TX", "Indianapolis IN", "Jacksonville FL", "Kansas City MO",
    "Knoxville TN", "Las Vegas NV", "Lexington KY", "Louisville KY",
    "Lubbock TX", "Memphis TN", "Mesa AZ", "Miami FL", "Milwaukee WI",
    "Minneapolis MN", "Mobile AL", "Nashville TN", "New Orleans LA",
    "Oklahoma City OK", "Omaha NE", "Orlando FL", "Philadelphia PA",
    "Phoenix AZ", "Pittsburgh PA", "Portland OR", "Raleigh NC", "Reno NV",
    "Richmond VA", "Sacramento CA", "Salt Lake City UT", "San Antonio TX",
    "San Diego CA", "Savannah GA", "Seattle WA", "Shreveport LA",
    "Spokane WA", "Springfield MO", "St Louis MO", "Tampa FL", "Toledo OH",
    "Tucson AZ", "Tulsa OK", "Virginia Beach VA", "Wichita KS",
    "Winston-Salem NC", "Worcester MA",
]

# niche -> (default growth tier shown, baseline earning weight 0-100)
NICHES = {
    "plumber": 70, "electrician": 70, "roofing company": 80,
    "HVAC company": 80, "landscaping company": 60, "lawn care service": 50,
    "auto repair shop": 65, "auto detailing": 50, "hair salon": 55,
    "barbershop": 45, "nail salon": 45, "day spa": 60, "massage therapist": 45,
    "restaurant": 60, "cafe": 50, "bakery": 50, "catering company": 60,
    "food truck": 35, "boutique": 50, "florist": 45, "gift shop": 40,
    "accounting firm": 80, "bookkeeping service": 65, "insurance agency": 80,
    "general contractor": 80, "painting company": 60, "flooring company": 65,
    "fence company": 60, "carpet cleaning": 45, "pressure washing": 45,
    "pest control": 65, "tree service": 60, "junk removal": 50,
    "moving company": 60, "dog grooming": 45, "pet boarding": 50,
    "veterinary clinic": 80, "dental office": 85, "chiropractor": 70,
    "physical therapy clinic": 70, "tattoo shop": 45, "photography studio": 50,
    "bridal shop": 55, "jewelry store": 60, "furniture store": 60,
    "hardware store": 55, "locksmith": 50, "garage door company": 65,
    "pool service": 60, "appliance repair": 55, "window cleaning": 45,
}

PARKED_MARKERS = ("domain is for sale", "buy this domain", "parked free",
                  "this domain may be for sale", "domain for sale",
                  "godaddy.com/domainsearch", "sedoparking", "hugedomains")

# Title fragments that signal a listicle / category page / forum, not a business.
# (No bare "best "/"top " — those reject real names like "Top Notch Roofing";
# listicles are caught by " in " and the number pattern in harvest_candidates.)
JUNK_TERMS = ("near me", "near ", "nearby", "servicing", "service area",
              "reviews", " in ", "directory", "list of", "vs ", "things to do",
              "reddit", " on reddit", "wikipedia", "craigslist", "quora",
              "tripadvisor", "groupon")

# Listicle headers like "Top 10 Plumbers" / "5 Best Roofers".
LISTICLE_RE = re.compile(r"\b(?:top|best)\s+\d+|\b\d+\s+best\b", re.I)

# Obvious national chains (have sites; not local small-business prospects).
NATIONAL_CHAINS = (
    "havertys", "ashley furniture", "mattress firm", "ati physical",
    "ati physicial", "massage envy", "great clips", "supercuts", "sport clips",
    "jiffy lube", "midas", "meineke", "valvoline", "aspen dental",
    "heartland dental", "western dental", "pearle vision", "planet fitness",
    "anytime fitness", "european wax", "the joint", "petsmart", "petco",
    "banfield", "h&r block", "jackson hewitt", "merry maids", "molly maid",
    "servpro", "roto-rooter", "terminix", "orkin", "two men and a truck",
)

# Words that don't make a title distinctive (used by _is_generic_title).
_GENERIC_STOP = {"near", "nearby", "servicing", "service", "best", "top", "the",
                 "and", "of", "a", "in", "llc", "inc", "co", "store", "shop",
                 "company", "center", "studio", "group", "solutions"}


def _sing(word):
    """Crude singularizer so 'trucks' matches 'truck'."""
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def _is_generic_title(name, city, niche):
    """True if, after removing niche + city + filler words, nothing distinctive
    (i.e. an actual business name) remains -> it's a category/SEO page title."""
    n = re.sub(r"\s*\(@[^)]+\)", "", name).lower()
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    words = [_sing(w) for w in n.split()]
    stop = {_sing(w) for w in _GENERIC_STOP}
    stop.update(_sing(w) for w in niche.lower().split())
    stop.update(_sing(w.lower()) for w in city.split())
    return not [w for w in words if w and w not in stop]


# ---------------------------------------------------------------------------
def _dns_resolves(domain):
    try:
        socket.setdefaulttimeout(5)
        socket.gethostbyname(domain)
        return True
    except (socket.error, UnicodeError):
        return False


def _page_is_real(url, business_name):
    """Fetch a URL; True if it loads and isn't a parked/for-sale page."""
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=8,
                         allow_redirects=True)
    except requests.RequestException:
        return False
    if r.status_code >= 400:
        return False
    body = r.text[:4000].lower()
    if any(m in body for m in PARKED_MARKERS):
        return False
    return len(body.strip()) > 200


def verify_website(client, name, city):
    """Two-step check.

    Returns dict: has_site(bool), confidence(0-1 that NO site exists),
    socials(dict), phone(str|None), description(str), site_url(str|None).
    """
    results = client.search(f'"{name}" {city}', count=10)
    socials, phone, description, real_site = {}, None, "", None

    for item in results:
        url = item.get("url", "")
        desc = item.get("description", "") or ""
        host = domain_of(url)
        if not description and desc:
            # Strip tags and decode entities (Brave sometimes double-encodes).
            description = html.unescape(html.unescape(re.sub(r"<[^>]+>", "", desc))).strip()
        if not phone:
            phone = extract_phone(desc)

        # Capture social links for later agents.
        for dom, key in SOCIAL_DOMAINS.items():
            if (host == dom or host.endswith("." + dom)) and key not in socials:
                socials[key] = url

        # A non-directory domain is a candidate real website.
        if url and not is_directory(url) and real_site is None:
            toks = [t for t in re.split(r"\W+", name.lower()) if len(t) > 2]
            blob = (url + " " + item.get("title", "") + " " + desc).lower()
            if toks and sum(t in blob for t in toks) >= max(1, len(toks) // 2):
                if _dns_resolves(host) and _page_is_real(url, name):
                    real_site = url

    if real_site:
        return {"has_site": True, "confidence": 0.0, "socials": socials,
                "phone": phone, "description": description, "site_url": real_site}

    # Step 2: guess domains.
    slug = re.sub(r"[^a-z0-9]", "", name.lower())
    city_slug = re.sub(r"[^a-z0-9]", "", city.split()[0].lower())
    guesses = [f"{slug}.com", f"{slug}.net", f"{slug}{city_slug}.com",
               f"the{slug}.com", f"{slug}llc.com"]
    for dom in guesses:
        if len(dom) < 8:
            continue
        if _dns_resolves(dom) and _page_is_real(f"http://{dom}", name):
            return {"has_site": True, "confidence": 0.0, "socials": socials,
                    "phone": phone, "description": description,
                    "site_url": f"http://{dom}"}

    # Failed both checks -> very likely no website.
    confidence = 0.92 if results else 0.80
    return {"has_site": False, "confidence": confidence, "socials": socials,
            "phone": phone, "description": description, "site_url": None}


# ---------------------------------------------------------------------------
def buyer_signal(name, description):
    """Heuristic 0-100 'can-they-afford-and-will-they-buy' score from snippets.

    This is a public-signal heuristic, NOT real financials. It rewards signs of
    an established, active, contactable business.
    """
    text = (name + " " + (description or "")).lower()
    score = 45
    for kw, pts in (("years", 8), ("family owned", 8), ("family-owned", 8),
                    ("since 19", 8), ("since 20", 6), ("licensed", 6),
                    ("insured", 6), ("certified", 5), ("award", 6),
                    ("voted", 6), ("trusted", 4), ("established", 6)):
        if kw in text:
            score += pts
    for neg in ("permanently closed", "temporarily closed", "out of business"):
        if neg in text:
            score -= 40
    # Review-count signal, e.g. "128 reviews".
    m = re.search(r"(\d{1,4})\s+reviews?", text)
    if m:
        score += min(int(m.group(1)) // 8, 18)
    # Star rating, e.g. "4.7 stars".
    m = re.search(r"([0-5]\.\d)\s*(?:star|out of 5|/5|★)", text)
    if m and float(m.group(1)) >= 4.3:
        score += 6
    return max(0, min(score, 100))


def assign_tier(signal):
    """Map the buyer/earnings signal to the tier the business can likely afford.

    Mirrors arjunganesh.com pricing:
      Premium $3,500 + $499/mo | Growth $1,800 + $299/mo | Starter $800 + $150/mo
    """
    if signal >= 72:
        return {"tier": "Premium", "build": "$3,500", "monthly": "$499/mo",
                "fit": "High earner - comfortably fits Premium"}
    if signal >= 48:
        return {"tier": "Growth", "build": "$1,800", "monthly": "$299/mo",
                "fit": "Established - good fit for Growth"}
    return {"tier": "Starter", "build": "$800", "monthly": "$150/mo",
            "fit": "Lean / early-stage - best pitched Starter"}


# ---------------------------------------------------------------------------
def harvest_candidates(client, niche, city, seen_slugs):
    """One discovery search -> list of (name, city, niche) candidates."""
    out, names = [], set()
    for item in client.search(f"{niche} in {city}", count=20):
        name = clean_business_name(item.get("title", ""))
        if not (3 <= len(name) <= 60):
            continue
        low = name.lower()
        # Drop listicles / category pages / forums.
        if any(w in low for w in JUNK_TERMS) or LISTICLE_RE.search(low):
            continue
        # Drop national chains (they have sites and aren't local prospects).
        if any(c in low for c in NATIONAL_CHAINS):
            continue
        # Drop page-title style names ending in a state code, e.g. "..., IN"
        # (anchored to end so a street like "..., SE 14th St" is kept).
        if re.search(r",\s*[A-Z]{2}\s*$", name):
            continue
        if _is_generic_title(name, city, niche):
            continue
        slug = slugify(f"{name}-{city}")
        if slug in seen_slugs or slug in names:
            continue
        names.add(slug)
        out.append({"name": name, "city": city, "niche": niche, "slug": slug})
    return out


def find_leads(client, target=10, seen_slugs=None, max_discovery=8,
               min_remaining=6):
    """Return up to `target` ranked leads with no website."""
    import random
    seen_slugs = seen_slugs or set()
    leads, candidates, discoveries = [], [], 0

    while len(leads) < target and client.remaining() > min_remaining:
        # Top up the candidate pool with a fresh discovery search.
        if not candidates and discoveries < max_discovery:
            niche = random.choice(list(NICHES))
            city = random.choice(US_CITIES)
            print(f"[discover] {niche} in {city}")
            candidates = harvest_candidates(client, niche, city, seen_slugs)
            discoveries += 1
            continue
        if not candidates:
            break  # discovery exhausted

        cand = candidates.pop(0)
        if client.remaining() <= min_remaining:
            break
        print(f"[verify] {cand['name']} ({cand['city']})")
        chk = verify_website(client, cand["name"], cand["city"])
        if chk["has_site"]:
            print(f"   -> has site ({chk['site_url']}), skip")
            continue

        signal = buyer_signal(cand["name"], chk["description"])
        no_site_conf = round(chk["confidence"] * 100, 1)
        overall = round(0.5 * no_site_conf + 0.5 * signal, 1)
        t = assign_tier(signal)
        leads.append({
            "business_name": cand["name"],
            "niche": cand["niche"],
            "city": cand["city"],
            "slug": cand["slug"],
            "phone": chk["phone"],
            "instagram": chk["socials"].get("instagram"),
            "description": chk["description"][:300],
            "socials": chk["socials"],
            "no_website_confidence": no_site_conf,
            "buyer_signal_score": signal,
            "affordability": t["fit"],
            "overall_score": overall,
            "suggested_tier": t["tier"],
            "suggested_price": f"{t['build']} build + {t['monthly']}",
        })
        print(f"   -> LEAD (score {overall})")

    leads.sort(key=lambda x: x["overall_score"], reverse=True)
    return leads[:target]
