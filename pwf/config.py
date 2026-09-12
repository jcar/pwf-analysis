"""Paths, crawl politeness settings, and shared constants."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
DB_PATH = DATA / "pwf.sqlite"

BASE = "https://www.privatewaterfishing.com"
REPORT_URL = BASE + "/forums/view_report/{id}"
INDEX_URL = BASE + "/forums/reports/all/{offset}"
INDEX_FIRST = BASE + "/forums/reports"
LAKE_URL = BASE + "/view-property/{slug}"

# Politeness. robots.txt permits everything; these limits are courtesy to a
# small club's server, not an obligation. Do not raise them casually.
CONCURRENCY = 3
DELAY_SECONDS = 0.30
TIMEOUT = 30.0
MAX_RETRIES = 3
CONTACT = "jason.carter@valentpartners.com"
USER_AGENT = (
    f"pwf-analysis/0.1 (personal club-member research; contact {CONTACT})"
)

# The site returns HTTP 200 with a PHP warning page for report IDs that do not
# exist, so absence must be detected from the body rather than the status code.
MISSING_MARKERS = ("A PHP Error was encountered", "Attempt to read property")
MISSING_MAX_BYTES = 12000

INDEX_PAGE_SIZE = 12
HOURS_BY_SLOT = {"AM": 4.0, "PM": 4.0, "ALL_DAY": 8.0}
