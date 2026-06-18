"""Shared helpers."""
import re

DIRECTORY_DOMAINS = [
    "yelp.com", "facebook.com", "instagram.com", "linkedin.com", "twitter.com",
    "x.com", "yellowpages.com", "mapquest.com", "bbb.org", "nextdoor.com",
    "google.com", "g.page", "goo.gl", "apple.com", "foursquare.com",
    "tripadvisor.com", "thumbtack.com", "angi.com", "angieslist.com",
    "homeadvisor.com", "manta.com", "chamberofcommerce.com", "indeed.com",
    "glassdoor.com", "zomato.com", "doordash.com", "ubereats.com",
    "grubhub.com", "opentable.com", "booksy.com", "vagaro.com", "wikipedia.org",
    "youtube.com", "tiktok.com", "pinterest.com", "alignable.com", "cylex.us.com",
    "yellowbook.com", "citysearch.com", "superpages.com", "merchantcircle.com",
]

SOCIAL_DOMAINS = {
    "facebook.com": "facebook", "instagram.com": "instagram", "yelp.com": "yelp",
    "linkedin.com": "linkedin", "tiktok.com": "tiktok", "twitter.com": "twitter",
    "x.com": "twitter", "youtube.com": "youtube",
}

# Suffixes that appear in result titles from directories / social pages.
_TITLE_NOISE = re.compile(
    r"\s*[-|–—]\s*(yelp|facebook|instagram|linkedin|yellow\s*pages|bbb|"
    r"better business bureau|mapquest|the real yellow pages|home|homepage|"
    r"angi|thumbtack|nextdoor|tripadvisor|google maps|google business).*$",
    re.I,
)


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "lead"


def clean_business_name(title: str) -> str:
    """Turn a search-result title into a plausible business name."""
    if not title:
        return ""
    t = _TITLE_NOISE.sub("", title)
    # Drop a trailing ", City, ST" or ", ST" fragment.
    t = re.sub(r",\s*[A-Za-z .]+,\s*[A-Z]{2}\b.*$", "", t)
    # Cut at the first separator that usually precedes a tagline.
    for sep in ("|", " - ", " – ", " — ", ":"):
        if sep in t:
            t = t.split(sep)[0]
            break
    t = re.sub(r"\s+", " ", t).strip(" .,-|")
    return t


PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.\-]?)?\(?([2-9]\d{2})\)?[\s.\-]?(\d{3})[\s.\-]?(\d{4})(?!\d)")


def extract_phone(text: str):
    if not text:
        return None
    m = PHONE_RE.search(text)
    if not m:
        return None
    return f"({m.group(1)}) {m.group(2)}-{m.group(3)}"


def domain_of(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "", re.I)
    host = (m.group(1) if m else "").lower()
    return host[4:] if host.startswith("www.") else host


def is_directory(url: str) -> bool:
    host = domain_of(url)
    return any(host == d or host.endswith("." + d) for d in DIRECTORY_DOMAINS)
