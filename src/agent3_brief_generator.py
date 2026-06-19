"""
Agent 3 - Website Brief Generator
=================================
For each lead, gathers what's publicly available (socials carried over from
Agent 1, plus a best-effort logo + brand palette pulled from the business's
social og:image) and writes a complete, paste-ready Claude Code prompt to
docs/prompts/<slug>.md for building a stunning Growth-tier site.

Logo/palette extraction is best-effort: businesses with no website often have
no clean logo online. When extraction fails, the generated prompt instructs
Claude Code to design an on-brand identity for the niche, so the brief is always
complete and actionable.
"""
import re
from io import BytesIO
from pathlib import Path

import requests

from util import extract_email, extract_owner

DOCS = Path(__file__).resolve().parent.parent / "docs"
PROMPTS_DIR = DOCS / "prompts"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _fetch(url):
    try:
        return requests.get(url, headers={"User-Agent": UA}, timeout=10).text
    except requests.RequestException:
        return ""


def _og_image_from(html):
    for pat in (r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']'):
        m = re.search(pat, html, re.I)
        if m:
            return m.group(1)
    return None


def _email_from(html):
    m = re.search(r'mailto:([^"\'?>]+)', html, re.I)
    if m:
        e = extract_email(m.group(1))
        if e:
            return e
    return extract_email(html)


def _palette(image_url):
    try:
        from colorthief import ColorThief
        data = requests.get(image_url, headers={"User-Agent": UA}, timeout=10).content
        ct = ColorThief(BytesIO(data))
        return ["#%02x%02x%02x" % c for c in ct.get_palette(color_count=5)]
    except Exception:
        return None


def gather_brand(lead):
    """Best-effort logo/palette + email/owner from the lead's social pages
    (free HTTP scraping — no search-API calls). Fills gaps left by Agent 1."""
    logo, palette = None, None
    for key in ("facebook", "instagram", "yelp"):
        url = lead.get("socials", {}).get(key)
        if not url:
            continue
        html = _fetch(url)
        if not html:
            continue
        if not lead.get("email"):
            lead["email"] = _email_from(html)
        if not lead.get("contact_name"):
            lead["contact_name"] = extract_owner(re.sub(r"<[^>]+>", " ", html))
        if not logo:
            img = _og_image_from(html)
            if img:
                logo = img
                palette = _palette(img)
        if logo and palette and lead.get("email"):
            break
    lead["logo_image"] = logo
    lead["palette"] = palette
    lead.setdefault("email", None)
    lead.setdefault("contact_name", None)
    return lead


# Page set per tier, mirroring arjunganesh.com.
TIER_PAGES = {
    "Starter": ["Home", "About", "Contact"],
    "Growth": ["Home", "About", "Services", "Gallery / Work",
               "Testimonials", "Contact"],
    "Premium": ["Home", "About", "Services", "Gallery / Work",
                "Testimonials", "Pricing", "FAQ", "Blog",
                "Booking / Appointments", "Contact"],
}

TIER_EXTRAS = {
    "Starter": "Keep it tight and high-impact: one strong scrolling home page "
               "experience plus About and Contact. Every section animated.",
    "Growth": "Full marketing site with rich service detail, a motion gallery, "
              "and social-proof testimonials.",
    "Premium": "Flagship build: add a blog, FAQ, pricing, and an "
               "appointment/booking flow. Leave a clean, documented slot for a "
               "chatbot widget and a reviews-automation embed (Premium AI Ops "
               "add-ons) without wiring a backend.",
}


def build_prompt(lead):
    s = lead.get("socials", {})
    social_lines = "\n".join(
        f"  - {k.title()}: {v}" for k, v in s.items()) or "  - (none found online)"
    palette = (", ".join(lead["palette"]) if lead.get("palette")
               else "none extracted - derive a tasteful palette fitting the niche")
    logo = lead.get("logo_image") or ("none found - design a clean wordmark/logo "
                                      "for the business")
    phone = lead.get("phone") or "(confirm with client)"
    email = lead.get("email") or "(not found - confirm with client)"
    contact = lead.get("contact_name") or "(owner name not found)"
    desc = lead.get("description") or "(no public description found)"
    tier = lead.get("suggested_tier", "Growth")
    pages = TIER_PAGES.get(tier, TIER_PAGES["Growth"])
    extras = TIER_EXTRAS.get(tier, TIER_EXTRAS["Growth"])

    return f"""# Website Build Brief - {lead['business_name']}

You are building a **visually STUNNING**, conversion-focused marketing website
for a local business. Use the **ui-ux-pro-max** and **high-end-visual-design**
skills. This is a paid **{tier}** client site ({lead.get('suggested_price', '')})
- it must look the part.

## Business
- **Name:** {lead['business_name']}
- **Industry:** {lead['niche']}
- **Location:** {lead['city']}
- **Owner / contact:** {contact}
- **Phone:** {phone}
- **Email:** {email}
- **Public description:** {desc}
- **Socials (wire ALL of these as buttons/icons - no dead links):**
{social_lines}

## Brand
- **Logo:** {logo}
- **Suggested palette (extracted from their socials):** {palette}
- If the logo image is a URL, fetch it and base the palette + favicon on it.
  If none, design a cohesive identity (logo wordmark + palette + type scale)
  appropriate for a {lead['niche']} in {lead['city']}.

## Tech stack (non-negotiable)
- **Next.js (App Router) + TypeScript + Tailwind CSS**
- **Framer Motion** for all animation
- **shadcn/ui** for base components, **lucide-react** for icons
- Fully responsive, light/dark aware, WCAG AA, Lighthouse 95+ on mobile

## Pages ({tier} tier - build all)
{chr(10).join('- ' + p for p in pages)}

{extras}

## Design direction (make it stunning)
- Bold hero with a real value prop headline, animated gradient/mesh background,
  and a primary CTA ("Call now" -> `tel:` and "Get a quote" -> contact form).
- Scroll-reveal animations (stagger), parallax on hero/section imagery,
  magnetic/hover micro-interactions on buttons and cards.
- Sticky, condensing navbar; smooth in-page anchor scrolling.
- Services as animated cards; Gallery as a motion grid/lightbox; Testimonials
  as an auto-playing carousel; trust badges (Licensed/Insured/Years) where the
  description supports them.
- A sticky mobile "Call" bar. Embed a Google Map for {lead['city']}.
- Real, specific copy for a {lead['niche']} - no lorem ipsum.

## Every interactive element must work
- Phone -> `tel:{re.sub(r'[^0-9]', '', phone) or 'PHONE'}`
- Contact form (name/email/phone/message) with validation + success state
- All social icons -> the URLs above (open in new tab, `rel="noopener"`)
- Footer with hours, address placeholder, socials, and copyright

## Deliverable
A complete, runnable Next.js project. After building, run it and confirm every
button, link, and animation works. Then summarize what you built.

---
*Lead score {lead['overall_score']} | no-website confidence {lead['no_website_confidence']}% | buyer signal {lead['buyer_signal_score']} | {lead['affordability']}*
"""


def write_brief(lead):
    gather_brand(lead)
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    path = PROMPTS_DIR / f"{lead['slug']}.md"
    path.write_text(build_prompt(lead), encoding="utf-8")
    lead["prompt_file"] = f"prompts/{lead['slug']}.md"
    return path
