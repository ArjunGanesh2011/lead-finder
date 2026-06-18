"""Brave Search API client with a persistent monthly query budget.

The free Brave plan grants $5/mo in credits (~1,000 searches). We cap usage at
MONTHLY_BUDGET and persist the running count in docs/usage.json so the limit
holds across the many short GitHub Actions runs over a month.
"""
import os
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
USAGE_FILE = Path(__file__).resolve().parent.parent / "docs" / "usage.json"
MONTHLY_BUDGET = 950          # safely under the ~1,000 free searches/month
MIN_INTERVAL_SEC = 1.1        # respect Brave's 1 req/sec free-tier rate limit


class BudgetExceeded(Exception):
    pass


class BraveClient:
    def __init__(self, api_key=None, budget=MONTHLY_BUDGET):
        self.api_key = api_key or os.environ.get("BRAVE_API_KEY")
        if not self.api_key:
            raise RuntimeError("BRAVE_API_KEY is not set")
        self.budget = budget
        self._last_call = 0.0
        self.month, self.used = self._load_usage()

    # --- usage persistence -------------------------------------------------
    def _load_usage(self):
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        if USAGE_FILE.exists():
            try:
                data = json.loads(USAGE_FILE.read_text())
                if data.get("month") == month:
                    return month, int(data.get("used", 0))
            except (ValueError, OSError):
                pass
        return month, 0

    def _save_usage(self):
        USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        USAGE_FILE.write_text(
            json.dumps({"month": self.month, "used": self.used,
                        "budget": self.budget}, indent=2)
        )

    def remaining(self):
        return max(self.budget - self.used, 0)

    # --- search ------------------------------------------------------------
    def _respect_rate_limit(self):
        delta = time.time() - self._last_call
        if delta < MIN_INTERVAL_SEC:
            time.sleep(MIN_INTERVAL_SEC - delta)
        self._last_call = time.time()

    def search(self, query, count=20, country="us"):
        """Return a list of web results ([] on error). Counts against budget."""
        if self.used >= self.budget:
            raise BudgetExceeded(f"Monthly budget of {self.budget} reached")
        self._respect_rate_limit()
        try:
            resp = requests.get(
                BRAVE_ENDPOINT,
                headers={"Accept": "application/json",
                         "X-Subscription-Token": self.api_key},
                params={"q": query, "count": min(count, 20),
                        "country": country, "search_lang": "en"},
                timeout=15,
            )
        except requests.RequestException as e:
            print(f"  [brave] network error: {e}")
            return []

        # Request reached Brave -> it counts against the quota.
        self.used += 1
        self._save_usage()

        if resp.status_code == 429:
            print("  [brave] rate limited (429); backing off")
            time.sleep(2)
            return []
        if resp.status_code != 200:
            print(f"  [brave] HTTP {resp.status_code}: {resp.text[:120]}")
            return []
        try:
            return resp.json().get("web", {}).get("results", [])
        except ValueError:
            return []
