"""ALDI transport: plain curl_cffi with Chrome-impersonated TLS against the
JSON API behind the ALDI SÜD group's shop sites. No browser, no cookies, no
login in the normal path (validated 2026-10-05 from direct Indian egress:
~0.3 s a call, 490 product reads at 12 in parallel all 200).

Every shop runs the same API on its own host (refs.COUNTRIES):

  GET /v3/product-search             q | categoryKey | promotionKey, brandName[],
                                     theme[], categoryTree[], sort, limit, offset
                                     -> products + facets + sort options.
                                     limit must be one of 12/16/24/30/32/48/60
                                     and offset a multiple of it (else 400).
                                     No q = the whole range ("*" matches nothing).
  GET /v3/product-search-suggestion  q -> completions + products + categories
  GET /v2/products/<sku>             one product, full detail
  GET /v2/products?skus=a,b          up to 60 products, list detail
  GET /v2/product-category-tree      the category tree
  GET /v2/promotion-tree             Special Buys dates and their themes
  GET /v2/service-points             stores: fullTextSearch | addressZipcode
                                     (+includeNearbyServicePoints) |
                                     latitude+longitude+radius; limit <= 500
  GET /v2/service-points/<id>        one store
  GET /v2/service-point-product-availability
                                     productSku + servicePointReference |
                                     latitude+longitude+radius | fullTextSearch
                                     -> stock traffic light per store
  GET /v1/stores/<ISO>               shop config (currency, default store)

`servicePoint` (a store id) prices a product read for that store;
`Accept-Language` picks the language on the Swiss shop (de-CH / fr-CH / it-CH).

Blocks (defensive — none was seen): a 403 / 429 or an HTML body marks the
shop's country as blocked, so new sessions for it ride a sticky residential
exit in that country (config.aldi_proxy) for config.ALDI_BLOCK_COOLDOWN
seconds. When every curl attempt of a call was refused, one headful
patchright load of the same API URL on a fresh exit takes over.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  AldiUpstreamError  transport failure / 5xx / unparseable body  — retryable
  AldiBlocked        403 / 429 / HTML instead of JSON            — retryable on a new exit
  AldiBadRequest     API 400 / 422 (bad params)                  — never retried
  AldiNotFound       API 404, or an "… not found" error code     — never retried
"""
import html as html_lib
import json
import os
import re
import sys
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from aldi import refs
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError

IMPERSONATE = "chrome"
TIMEOUT = 30
BROWSER_EXITS = 2                 # fresh exits one fallback call tries

# API error codes that mean "that entity does not exist" whatever the HTTP
# status: 3202 concrete product, 3204 / 35099 service point, 3501 merchant
# (an unknown `servicePoint`), 3306 no stock data for the product.
NOT_FOUND_CODES = {"3202", "3204", "35099", "3501", "3306", "007"}
NO_STOCK_DATA_CODE = "3306"
STOCK_CHECK_FAILED_CODE = "3305"  # the shop's stock backend timed out (~10 s) — transient
PAGE_PAST_END_CODE = "3739"
INVALID_POSTCODE_CODE = "3508"


class AldiUpstreamError(UpstreamError):
    """Transport failure, 5xx or an unparseable body — retryable."""


class AldiBlocked(AldiUpstreamError, Blocked):
    """403 / 429 / HTML instead of JSON — retryable on a fresh exit."""


class AldiBadRequest(BadRequest):
    """The API rejected the params (400 / 422) — never retried."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class AldiNotFound(NotFound):
    """The API has no such product / store / category — never retried."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


# ---- sessions --------------------------------------------------------------------
# One curl session per worker thread and country (a curl handle must not be
# shared across threads; each shop is its own host).
_local = threading.local()
_blocked_until = {}
_blocked_lock = threading.Lock()


def _proxy_for_new_session(country):
    if config.ALDI_PROXY_ALWAYS or time.time() < _blocked_until.get(country, 0.0):
        return config.aldi_proxy(refs.shop(country)["proxy"])
    return None


def _session(country):
    sessions = getattr(_local, "sessions", None)
    if sessions is None:
        sessions = _local.sessions = {}
    sess = sessions.get(country)
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        proxy = _proxy_for_new_session(country)
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        sessions[country] = sess
    return sess


def _drop_session(country):
    sess = (getattr(_local, "sessions", None) or {}).pop(country, None)
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _note_block(country):
    """Refused on this egress: send the country's new sessions through a
    residential exit for a while (no-op when the fallback is off)."""
    if config.ALDI_FALLBACK_PROXY:
        with _blocked_lock:
            _blocked_until[country] = time.time() + config.ALDI_BLOCK_COOLDOWN


def dump_debug(name, text):
    """Keep the last body of each failure kind when ALDI_DEBUG_DIR is set."""
    dbg = os.environ.get("ALDI_DEBUG_DIR", "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass


# ---- classification ----------------------------------------------------------------

def _headers(country, language):
    site = "https://" + refs.shop(country)["site"]
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": refs.locale(country, language) + f",{language};q=0.9",
        "origin": site,
        "referer": site + "/",
    }


def _first_error(body):
    errors = body.get("errors") if isinstance(body, dict) else None
    first = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else {}
    code = first.get("code")
    return (str(code) if code is not None else None), (first.get("message") or first.get("detail") or "")


def classify(status, text, url):
    """Raise the failure a response represents, or return its parsed JSON."""
    text = text or ""
    body = None
    if text.lstrip()[:1] in ("{", "["):
        try:
            body = json.loads(text)
        except ValueError:
            body = None
    if status in (403, 429) or (body is None and status < 500 and "<html" in text[:2000].lower()):
        dump_debug("blocked", text)
        raise AldiBlocked(f"HTTP {status} on {url}")
    code, message = _first_error(body)
    if status == 404 or (code in NOT_FOUND_CODES and status in (400, 422)):
        raise AldiNotFound(message or "Not found", code=code)
    if code == STOCK_CHECK_FAILED_CODE:
        raise AldiUpstreamError(f"the shop's stock service did not answer ({message or code})")
    if status in (400, 422):
        raise AldiBadRequest(message or f"HTTP {status}", code=code)
    if status >= 500:
        raise AldiUpstreamError(f"HTTP {status} on {url}")
    if status != 200 or body is None:
        dump_debug("unexpected", text)
        raise AldiUpstreamError(f"HTTP {status} with an unexpected body on {url}")
    return body


# ---- fetching --------------------------------------------------------------------

def _url(country, path, params):
    query = urlencode({k: v for k, v in (params or {}).items() if v is not None}, doseq=True)
    return f"https://{refs.shop(country)['api']}{path}" + (f"?{query}" if query else "")


def _curl_once(country, language, url):
    try:
        resp = _session(country).get(url, headers=_headers(country, language), timeout=TIMEOUT)
    except Exception as e:
        raise AldiUpstreamError(f"request failed: {type(e).__name__}: {e}")
    return classify(resp.status_code, resp.text, url)


_browser_slots = threading.BoundedSemaphore(max(1, config.ALDI_BROWSER_CONCURRENCY))
_PRE_RE = re.compile(r"<pre[^>]*>(.*?)</pre>", re.S | re.I)


def _browser_get(country, url):
    """One headful patchright load of the API URL per fresh exit (up to
    BROWSER_EXITS). Chrome renders a JSON response inside <pre>."""
    from chrome_manager import create_scope
    from patchright_driver import PatchrightDriver

    last = None
    with _browser_slots:
        for _ in range(BROWSER_EXITS):
            driver = None
            try:
                with create_scope():
                    driver = PatchrightDriver(proxy_url=config.aldi_proxy(refs.shop(country)["proxy"]),
                                              headless=False, geoip_timezone=True)
                result = driver.nav(url, referer="https://" + refs.shop(country)["site"] + "/", mode="blocked")
                page = result.get("html") or ""
                match = _PRE_RE.search(page)
                text = html_lib.unescape(match.group(1)) if match else page
                return classify(result.get("status") or 200, text, url)
            except (AldiNotFound, AldiBadRequest):
                raise
            except Exception as e:
                last = e
                print(f"aldi: browser fallback failed on {url}: {type(e).__name__}: {e}")
            finally:
                if driver is not None:
                    try:
                        driver.close()
                    except Exception:
                        pass
    if isinstance(last, AldiUpstreamError):
        raise last
    raise AldiBlocked(f"browser fallback could not load {url}: {last}")


def api(country, path, params=None, language=None):
    """GET one API path of `country`'s shop -> the parsed JSON body. A block
    moves the country to residential exits; when every attempt was blocked a
    headful browser load takes over."""
    language = language or refs.default_language(country)
    url = _url(country, path, params)
    last = None
    blocked_only = True
    for attempt in range(1, config.ALDI_MAX_ATTEMPTS + 1):
        try:
            return _curl_once(country, language, url)
        except AldiBlocked as e:
            last = e
            _note_block(country)
        except AldiUpstreamError as e:
            last = e
            blocked_only = False
        print(f"aldi: attempt {attempt}/{config.ALDI_MAX_ATTEMPTS} on {country} {path} failed: {last}")
        _drop_session(country)
        if attempt < config.ALDI_MAX_ATTEMPTS:
            time.sleep(0.4 * attempt)
    if blocked_only and config.ALDI_BROWSER_FALLBACK:
        print(f"aldi: every curl attempt on {country} {path} was blocked; loading it in a browser")
        return _browser_get(country, url)
    raise last


# ---- memo + fan-out ---------------------------------------------------------------
# The category tree, the Special Buys calendar and the brand list are read by
# several routes; this memo lets them share a fetch for a few minutes even
# with the response cache off.
_memo = OrderedDict()
_memo_lock = threading.Lock()
MEMO_TTL = 300
MEMO_MAX = 256


def memoized(key, fn, ttl=MEMO_TTL):
    now = time.monotonic()
    with _memo_lock:
        hit = _memo.get(key)
        if hit and now - hit[0] < ttl:
            _memo.move_to_end(key)
            return hit[1]
    value = fn()
    with _memo_lock:
        _memo[key] = (now, value)
        _memo.move_to_end(key)
        while len(_memo) > MEMO_MAX:
            _memo.popitem(last=False)
    return value


def dataset(name, params, build, ttl):
    """One parsed upstream document shared by several routes: in-process memo
    first, then the response cache (so pods share it), then build(**params)."""
    from cache import cached_call
    seconds = ttl.total_seconds() if hasattr(ttl, "total_seconds") else ttl
    key = ("dataset", name, tuple(sorted(params.items())))
    return memoized(key, lambda: cached_call(f"aldi.dataset.{name}", params, build, ttl),
                    ttl=min(seconds, MEMO_TTL))


def run_parallel(fns, workers):
    """Run zero-arg callables in parallel; results align with `fns`.
    Each result is ("ok", value) or ("error", exception)."""
    def guard(fn):
        try:
            return ("ok", fn())
        except Exception as e:
            return ("error", e)
    if not fns:
        return []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(fns)))) as ex:
        return list(ex.map(guard, fns))


if __name__ == "__main__":
    # Smoke test: python aldi/fetch.py [country] [query]
    code = sys.argv[1] if len(sys.argv) > 1 else "uk"
    term = sys.argv[2] if len(sys.argv) > 2 else "milk"
    data = api(code, "/v3/product-search", {"q": term, "limit": 12, "offset": 0})
    print(code, term, data["meta"]["pagination"], [p["name"] for p in data["data"][:3]])
