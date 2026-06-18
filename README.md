# Lead Finder

Three coordinated agents that run daily (free) on GitHub Actions:

1. **Lead Finder** — finds US local businesses with **no website**, double-verifies
   the absence (search + DNS/domain check), estimates affordability from public
   buyer signals, and ranks the top 10.
2. **Calendar** — writes `docs/leads.ics`, a follow-up calendar your iPhone
   subscribes to.
3. **Brief Generator** — writes a paste-ready Claude Code prompt per lead
   (`docs/prompts/<slug>.md`) to build a stunning Growth-tier site.

Outputs land in `docs/` and publish to a GitHub Pages dashboard.

---

## One-time setup

### 1. Push this code to your `lead-finder` repo
```bash
cd lead-finder
git init -b main
git add .
git commit -m "Initial lead finder"
git remote add origin https://github.com/ArjunGanesh2011/lead-finder.git
git push -u origin main
```

### 2. Add your Brave API key as a secret
Repo → **Settings → Secrets and variables → Actions → New repository secret**
- Name: `BRAVE_API_KEY`
- Value: *(your Brave Search API key)*

### 3. Turn on GitHub Pages
Repo → **Settings → Pages** → Source: **Deploy from a branch** →
Branch: **main**, Folder: **/docs** → Save.

Dashboard will be at: **https://arjunganesh2011.github.io/lead-finder/**

### 4. Run it once
Repo → **Actions → Daily Lead Finder → Run workflow**.
After ~1 minute the dashboard fills with 10 ranked leads.

### 5. Subscribe to the calendar on iPhone
Open the dashboard on your phone → tap **Subscribe in Apple Calendar**.
(Or: Settings → Calendar → Accounts → Add Account → Other → Add Subscribed
Calendar → `https://arjunganesh2011.github.io/lead-finder/leads.ics`.)
It auto-refreshes every 12h.

---

## How it works / tuning

| Setting | Where | Default |
|---|---|---|
| Daily run time | `.github/workflows/daily.yml` cron | 13:00 UTC |
| Leads per run | `src/run_all.py` `TARGET` | 10 |
| Monthly query cap | `src/brave_client.py` `MONTHLY_BUDGET` | 950 |
| Niches / cities | `src/agent1_lead_finder.py` | broad US set |

**Query budget:** usage is tracked in `docs/usage.json` and resets monthly.
A typical run uses ~25–30 searches, so a full month stays well under the free
1,000. The cap is a hard stop regardless of run count.

## Run locally (optional)
```bash
pip install -r requirements.txt
set BRAVE_API_KEY=your_key   # PowerShell: $env:BRAVE_API_KEY="your_key"
python src/run_all.py
```

## Notes
- Affordability is a **heuristic** from public review/age signals, not real
  financials — use it as a sorting aid.
- Logo/brand-color extraction is best-effort (many no-website businesses lack a
  clean logo online); when it fails, the generated prompt tells Claude Code to
  design an on-brand identity.
