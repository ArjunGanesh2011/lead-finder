"""
Agent 1 - Lead Finder
=====================
Sources businesses straight from Google Maps (Places API), which gives the
canonical name, correct phone, and an authoritative website field. Then it
double-checks the no-website candidates on web search (Brave) to catch sites
that exist but aren't linked on the Maps listing.

Two gates, in order:
  1. Google Maps (Places): if the listing has a REAL website (not a Facebook/
     Yelp/directory link) -> they have a site -> reject. Authoritative + free
     of the snippet-scraping errors that plagued the old approach.
  2. Web search double-check: for the businesses Maps shows with no real site,
     search '"Name" City'. If a real, resolving site surfaces (or a guessed
     domain resolves) -> reject. Otherwise it's a confirmed no-website lead.

A business whose only online presence is a Facebook/Instagram page is kept -
that's exactly the prospect who needs a real site.
"""
import re
import html
import socket
from itertools import zip_longest

import requests

from util import slugify, domain_of, is_directory, SOCIAL_DOMAINS

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

PLACES_ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
PLACES_FIELDS = ",".join((
    "places.id", "places.displayName", "places.formattedAddress",
    "places.nationalPhoneNumber", "places.websiteUri", "places.rating",
    "places.userRatingCount", "places.businessStatus", "places.googleMapsUri",
))

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

# niche search term -> baseline earning weight (0-100) for the buyer signal
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

NATIONAL_CHAINS = (
    "havertys", "ashley furniture", "mattress firm", "ati physical",
    "massage envy", "great clips", "supercuts", "sport clips", "jiffy lube",
    "midas", "meineke", "valvoline", "aspen dental", "heartland dental",
    "western dental", "pearle vision", "planet fitness", "anytime fitness",
    "european wax", "petsmart", "petco", "banfield", "h&r block",
    "jackson hewitt", "merry maids", "molly maid", "servpro", "roto-rooter",
    "terminix", "orkin", "two men and a truck", "les schwab", "discount tire",
)

PARKED_MARKERS = ("domain is for sale", "buy this domain", "parked free",
                  "this domain may be for sale", "domain for sale",
                  "godaddy.com/domainsearch", "sedoparking", "hugedomains")


# ---------------------------------------------------------------------------
def places_text_search(api_key, query, max_results=20):
    """Google Maps Places (New) text search. Returns a list of place dicts."""
    try:
        r = requests.post(
            PLACES_ENDPOINT,
            headers={"Content-Type": "application/json",
                     "X-Goog-Api-Key": api_key,
                     "X-Goog-FieldMask": PLACES_FIELDS},
            json={"textQuery": query, "regionCode": "US", "languageCode": "en",
                  "maxResultCount": min(max_results, 20)},
            timeout=15,
        )
    except requests.RequestException as e:
        print(f"  [places] network error: {e}")
        return []
    if r.status_code != 200:
        print(f"  [places] HTTP {r.status_code}: {r.text[:200]}")
        return []
    try:
        return r.json().get("places", [])
    except ValueError:
        return []


# ---------------------------------------------------------------------------
def _dns_resolves(domain):
    try:
        socket.setdefaulttimeout(5)
        socket.gethostbyname(domain)
        return True
    except (socket.error, UnicodeError):
        return False


def _page_is_real(url, business_name):
    """True if the URL loads and isn't a parked/for-sale placeholder."""
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


def verify_no_site_via_search(brave, name, city):
    """Gate 2: search the web for a site Maps may not have linked.

    Returns has_site(bool), confidence(0-1 that NO site exists),
    socials(dict), description(str).
    """
    results = brave.search(f'"{name}" {city}', count=10)
    socials, description, real_site = {}, "", None

    for item in results:
        url = item.get("url", "")
        desc = item.get("description", "") or ""
        host = domain_of(url)
        if not description and desc:
            description = html.unescape(html.unescape(re.sub(r"<[^>]+>", "", desc))).strip()

        for dom, key in SOCIAL_DOMAINS.items():
            if (host == dom or host.endswith("." + dom)) and key not in socials:
                socials[key] = url

        if url and not is_directory(url) and real_site is None:
            toks = [t for t in re.split(r"\W+", name.lower()) if len(t) > 2]
            blob = (url + " " + item.get("title", "") + " " + desc).lower()
            if toks and sum(t in blob for t in toks) >= max(1, len(toks) // 2):
                if _dns_resolves(host) and _page_is_real(url, name):
                    real_site = url

    if real_site:
        return {"has_site": True, "confidence": 0.0,
                "socials": socials, "description": description}

    # Guess a few obvious domains for the unlinked-site case.
    slug = re.sub(r"[^a-z0-9]", "", name.lower())
    city_slug = re.sub(r"[^a-z0-9]", "", city.split()[0].lower())
    for dom in (f"{slug}.com", f"{slug}.net", f"{slug}{city_slug}.com",
                f"the{slug}.com"):
        if len(dom) >= 8 and _dns_resolves(dom) and _page_is_real(f"http://{dom}", name):
            return {"has_site": True, "confidence": 0.0,
                    "socials": socials, "description": description}

    return {"has_site": False, "confidence": 0.92 if results else 0.80,
            "socials": socials, "description": description}


# ---------------------------------------------------------------------------
def buyer_signal(place, niche):
    """0-100 affordability/buy-readiness from Maps rating + review volume."""
    base = NICHES.get(niche, 55)
    count = place.get("userRatingCount") or 0
    rating = place.get("rating") or 0
    vol = min(count // 5, 30)                        # review volume -> up to +30
    qual = max(0.0, rating - 4.0) * 16 if rating else 0   # 4.0-5.0 -> 0-16
    return int(max(0, min(0.5 * base + vol + qual, 100)))


def assign_tier(signal):
    """Map the buyer signal to the tier the business can likely afford."""
    if signal >= 72:
        return {"tier": "Premium", "build": "$3,500", "monthly": "$499/mo",
                "fit": "High earner - comfortably fits Premium"}
    if signal >= 48:
        return {"tier": "Growth", "build": "$1,800", "monthly": "$299/mo",
                "fit": "Established - good fit for Growth"}
    return {"tier": "Starter", "build": "$800", "monthly": "$150/mo",
            "fit": "Lean / early-stage - best pitched Starter"}


# ---------------------------------------------------------------------------
def find_leads(maps_key, brave, target=10, seen_slugs=None, max_searches=60,
               max_checks=30, min_brave_remaining=5):
    """Find up to `target` ranked businesses with no real website.

    `max_searches` bounds (cheap) Maps calls; `max_checks` bounds (budgeted)
    Brave double-checks so a single run can't blow the monthly search quota.
    """
    import random
    seen = set(seen_slugs or [])
    leads, searches, checks = [], 0, 0

    # Round-robin niches across earning tiers (high/mid/low base) so a run
    # samples a spread -> more variety of Starter/Growth/Premium prospects.
    hi = [n for n, w in NICHES.items() if w >= 70]
    mid = [n for n, w in NICHES.items() if 50 <= w < 70]
    lo = [n for n, w in NICHES.items() if w < 50]
    for grp in (hi, mid, lo):
        random.shuffle(grp)
    niche_order = [n for trio in zip_longest(hi, mid, lo) for n in trio if n]
    cities = US_CITIES[:]
    random.shuffle(cities)
    combos = [(n, cities[i % len(cities)]) for i, n in enumerate(niche_order)]
    extra = [(n, c) for n in NICHES for c in US_CITIES]
    random.shuffle(extra)
    combos += extra                       # fallback pool if we need more

    for niche, city in combos:
        if len(leads) >= target or searches >= max_searches:
            break
        if checks >= max_checks or brave.remaining() <= min_brave_remaining:
            break
        print(f"[places] {niche} in {city}")
        places = places_text_search(maps_key, f"{niche} in {city}")
        searches += 1

        for p in places:
            if len(leads) >= target:
                break
            name = (p.get("displayName") or {}).get("text", "").strip()
            if not (3 <= len(name) <= 70):
                continue
            low = name.lower()
            if any(ch in low for ch in NATIONAL_CHAINS):
                continue
            if p.get("businessStatus") not in (None, "OPERATIONAL"):
                continue
            slug = slugify(f"{name}-{city}")
            if slug in seen:
                continue

            website = p.get("websiteUri")
            # Gate 1: a real (non-social/directory) website means skip.
            if website and not is_directory(website):
                continue
            # Gate 2: web double-check for an unlinked site.
            if checks >= max_checks or brave.remaining() <= min_brave_remaining:
                break
            checks += 1
            chk = verify_no_site_via_search(brave, name, city)
            if chk["has_site"]:
                print(f"   -> {name}: site found on search, skip")
                continue

            seen.add(slug)
            socials = dict(chk["socials"])
            # If Maps listed a social page as the "website", keep it as a social.
            if website and is_directory(website):
                for dom, key in SOCIAL_DOMAINS.items():
                    if dom in website and key not in socials:
                        socials[key] = website

            signal = buyer_signal(p, niche)
            t = assign_tier(signal)
            no_site_conf = round(chk["confidence"] * 100, 1)
            overall = round(0.5 * no_site_conf + 0.5 * signal, 1)
            leads.append({
                "business_name": name,
                "niche": niche,
                "city": city,
                "slug": slug,
                "phone": p.get("nationalPhoneNumber"),
                "instagram": socials.get("instagram"),
                "address": p.get("formattedAddress"),
                "maps_url": p.get("googleMapsUri"),
                "rating": p.get("rating"),
                "review_count": p.get("userRatingCount"),
                "description": chk["description"][:300],
                "socials": socials,
                "no_website_confidence": no_site_conf,
                "buyer_signal_score": signal,
                "affordability": t["fit"],
                "overall_score": overall,
                "suggested_tier": t["tier"],
                "suggested_price": f"{t['build']} build + {t['monthly']}",
            })
            print(f"   -> LEAD {name} (score {overall}, {t['tier']})")

    leads.sort(key=lambda x: x["overall_score"], reverse=True)
    return leads[:target]
