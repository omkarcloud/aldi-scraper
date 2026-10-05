"""Configuration for the Aldi Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT        port the API listens on (default 8000)
    ALDI_PROXY  proxy URL for every request, e.g. http://user:pass@host:port
                (default: none — direct). Aldi's shop API answered 490
                product reads at 12 in parallel from one IP without a single
                block, so you very likely don't need this. Set it only if you
                start seeing HTTP 403 / 429 at high volume.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

ALDI_PROXY = os.environ.get("ALDI_PROXY") or None

# Names the aldi/ package reads.
ALDI_MAX_ATTEMPTS = MAX_RETRIES
ALDI_PROXY_ALWAYS = bool(ALDI_PROXY)   # with ALDI_PROXY set, every request goes through it
ALDI_FALLBACK_PROXY = False            # no automatic proxy switch on a block
ALDI_BLOCK_COOLDOWN = 900
# The browser fallback needs Chrome + patchright; this kit is plain HTTP.
ALDI_BROWSER_FALLBACK = False
ALDI_BROWSER_CONCURRENCY = 1
ALDI_BULK_WORKERS = 6                  # parallel product reads in /products/details/bulk


def aldi_proxy(country=None):
    return os.environ.get("ALDI_PROXY") or None
