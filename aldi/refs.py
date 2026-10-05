"""ALDI input parsing: the country table, ONE param per input that
auto-detects its forms (tripadvisor QueryOrLinkField convention — never a
sibling `url`/`id` pair) and the link builders the parsers share.

  country   uk | au | ie | de | ch | hu | si      (gb / ISO names accepted)
  product   000000000000543221                     (18-digit SKU)
            | 543221                               (SKU without the zero padding)
            | cowbelle-chocolate-milk-000000000000543221   (slug from a link)
            | https://www.aldi.co.uk/product/cowbelle-chocolate-milk-000000000000543221
  category  1588161416978051001                    (category id)
            | chilled-food/milk | milk             (slug path / last segment / name)
            | https://www.aldi.co.uk/products/chilled-food/milk/k/1588161416978051001
  store     C092 | G452 | BN42                     (store id)
  location  51.5074,-0.1278                        (latitude,longitude)
            | SW1A 1AA | 80331                     (postcode)
            | London | Chapel Street Belper        (city / address text)

A link names its shop, so it also fixes the country (and, on the Swiss shop,
the language): `product=https://www.aldi-sued.de/produkt/...` needs no
`country=de`.
"""
import re
from urllib.parse import quote, unquote, urlparse

# code -> shop. `paths` maps a language to the (product, category) path
# segments of the shop's links; `proxy` is the proxy-exit country for the
# block fallback; `postcode` matches a whole postcode of that country.
COUNTRIES = {
    "uk": {
        "name": "United Kingdom", "iso": "GB", "banner": "ALDI", "currency": "GBP",
        "api": "api.aldi.co.uk", "site": "www.aldi.co.uk", "proxy": "gb",
        "languages": ["en"], "paths": {"en": ("product", "products")}, "language_prefix": False,
        "postcode": r"[A-Za-z]{1,2}\d[A-Za-z\d]? ?\d[A-Za-z]{2}", "distance_unit": "mi",
        "timezone": "Europe/London",
    },
    "au": {
        "name": "Australia", "iso": "AU", "banner": "ALDI", "currency": "AUD",
        "api": "api.aldi.com.au", "site": "www.aldi.com.au", "proxy": "au",
        "languages": ["en"], "paths": {"en": ("product", "products")}, "language_prefix": False,
        "postcode": r"\d{4}", "distance_unit": "km", "timezone": "Australia/Sydney",
    },
    "ie": {
        "name": "Ireland", "iso": "IE", "banner": "ALDI", "currency": "EUR",
        "api": "api.aldi.ie", "site": "www.aldi.ie", "proxy": "ie",
        "languages": ["en"], "paths": {"en": ("product", "products")}, "language_prefix": False,
        "postcode": r"[A-Za-z]\d[\dWw] ?[A-Za-z\d]{4}", "distance_unit": "km",
        "timezone": "Europe/Dublin",
    },
    "de": {
        "name": "Germany", "iso": "DE", "banner": "ALDI SÜD", "currency": "EUR",
        "api": "api.aldi-sued.de", "site": "www.aldi-sued.de", "proxy": "de",
        "languages": ["de"], "paths": {"de": ("produkt", "produkte")}, "language_prefix": False,
        "postcode": r"\d{5}", "distance_unit": "km", "timezone": "Europe/Berlin",
    },
    "ch": {
        "name": "Switzerland", "iso": "CH", "banner": "ALDI SUISSE", "currency": "CHF",
        "api": "api.aldi-suisse.ch", "site": "www.aldi-suisse.ch", "proxy": "ch",
        "languages": ["de", "fr", "it"],
        "paths": {"de": ("produkt", "produkte"), "fr": ("produit", "produits"), "it": ("prodotto", "prodotti")},
        "language_prefix": True,
        "postcode": r"\d{4}", "distance_unit": "km", "timezone": "Europe/Zurich",
    },
    "hu": {
        "name": "Hungary", "iso": "HU", "banner": "ALDI", "currency": "HUF",
        "api": "api.aldi.hu", "site": "www.aldi.hu", "proxy": "hu",
        "languages": ["hu"], "paths": {"hu": ("termek", "termekek")}, "language_prefix": False,
        "postcode": r"\d{4}", "distance_unit": "km", "timezone": "Europe/Budapest",
    },
    "si": {
        "name": "Slovenia", "iso": "SI", "banner": "HOFER", "currency": "EUR",
        "api": "api.hofer.si", "site": "www.hofer.si", "proxy": "si",
        "languages": ["sl"], "paths": {"sl": ("izdelek", "izdelki")}, "language_prefix": False,
        "postcode": r"\d{4}", "distance_unit": "km", "timezone": "Europe/Ljubljana",
    },
}
# Literal copies (schemas + the listing tooling read them as enums).
COUNTRY_CODES = ["uk", "au", "ie", "de", "ch", "hu", "si"]
DEFAULT_COUNTRY = "uk"
LANGUAGES = ["en", "de", "fr", "it", "hu", "sl"]
SORTS = ["relevance", "price_asc", "price_desc", "name_asc", "name_desc"]

_COUNTRY_ALIASES = {
    "gb": "uk", "united kingdom": "uk", "great britain": "uk", "britain": "uk", "england": "uk",
    "australia": "au", "ireland": "ie", "germany": "de", "deutschland": "de",
    "switzerland": "ch", "schweiz": "ch", "suisse": "ch", "hungary": "hu", "slovenia": "si",
}
_SITE_HOSTS = {}
for _code, _shop in COUNTRIES.items():
    _bare = _shop["site"][4:]
    for _host in (_shop["site"], _bare, _shop["api"]):
        _SITE_HOSTS[_host] = _code

SKU_LENGTH = 18
_SKU_TAIL_RE = re.compile(r"(?:^|-)(\d{6,18})$")
_CATEGORY_KEY_RE = re.compile(r"^\d{6,24}$")
_CATEGORY_LINK_KEY_RE = re.compile(r"/k/(\d{6,24})(?:/|$)")
_STORE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{1,11}$")
_COORDS_RE = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*[,; ]\s*(-?\d{1,3}(?:\.\d+)?)\s*$")


def shop(country):
    return COUNTRIES[country]


def resolve_country(value):
    """'uk' | 'GB' | 'Germany' -> the shop code."""
    key = " ".join((value or "").strip().lower().split())
    key = _COUNTRY_ALIASES.get(key, key)
    if key not in COUNTRIES:
        raise ValueError(f"Must be one of: {', '.join(COUNTRY_CODES)}.")
    return key


def default_language(country):
    return COUNTRIES[country]["languages"][0]


def check_language(country, language):
    """The language to read `country`'s shop in: the given one when the shop
    has it, its first language when none is given. Raises ValueError for a
    language the shop does not publish."""
    languages = COUNTRIES[country]["languages"]
    if not language:
        return languages[0]
    if language not in languages:
        raise ValueError(f"The {COUNTRIES[country]['name']} shop is published in: {', '.join(languages)}.")
    return language


def locale(country, language):
    """('ch', 'fr') -> 'fr-CH' (the Accept-Language value and the key of the
    API's per-language slug maps)."""
    return f"{language}-{COUNTRIES[country]['iso']}"


# ---- links in ------------------------------------------------------------------

def _parse_link(value):
    """An ALDI shop link -> (country, language or None, path), or None when
    `value` is not a link. Raises ValueError for a link to another site."""
    raw = (value or "").strip()
    if not re.match(r"^(?:https?:)?//", raw, re.I) and not re.match(r"^(?:www\.|api\.)?(?:aldi|hofer)[\w.-]*\.[a-z.]{2,6}/", raw, re.I):
        return None
    candidate = raw if "://" in raw else ("https:" + raw if raw.startswith("//") else "https://" + raw)
    try:
        parsed = urlparse(candidate)
    except ValueError:
        raise ValueError(f"'{raw}' is not a valid link.")
    host = (parsed.hostname or "").lower()
    country = _SITE_HOSTS.get(host)
    if country is None:
        sites = ", ".join(s["site"][4:] for s in COUNTRIES.values())
        raise ValueError(f"Links must be from a supported ALDI shop ({sites}).")
    path = unquote(parsed.path or "").strip("/")
    language = None
    first = path.split("/", 1)[0].lower()
    if COUNTRIES[country]["language_prefix"] and first in COUNTRIES[country]["languages"]:
        language = first
        path = path.split("/", 1)[1] if "/" in path else ""
    return country, language, path


def _pad_sku(digits):
    return digits.zfill(SKU_LENGTH)


def resolve_product(value):
    """A SKU, a product slug ending in its SKU, or a product link ->
    {"sku", "country", "language"} (country / language are None unless a
    link names them)."""
    raw = (value or "").strip()
    link = _parse_link(raw)
    country = language = None
    target = raw
    if link is not None:
        country, language, path = link
        target = path.rstrip("/").rsplit("/", 1)[-1]
    target = target.split("?")[0].split("#")[0].strip()
    match = _SKU_TAIL_RE.search(target)
    if not match:
        raise ValueError("Must be a product id (000000000000543221), a product slug ending in its id, "
                         "or a product link from an ALDI shop.")
    return {"sku": _pad_sku(match.group(1)), "country": country, "language": language}


def resolve_category(value):
    """A category id, a category link, or a slug / name ->
    {"key", "slug", "country", "language"}. `key` is None for a slug or name;
    categories.resolve_key() then looks it up in the shop's category tree."""
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Must be a category id, slug or link.")
    link = _parse_link(raw)
    if link is not None:
        country, language, path = link
        match = _CATEGORY_LINK_KEY_RE.search("/" + path)
        if match:
            return {"key": match.group(1), "slug": None, "country": country, "language": language}
        parts = [p for p in path.split("/") if p]
        listing_roots = {segments[1] for segments in COUNTRIES[country]["paths"].values()}
        if parts and parts[0].lower() in listing_roots:
            parts = parts[1:]
        if not parts:
            raise ValueError("That link does not point at a category.")
        return {"key": None, "slug": "/".join(parts).lower(), "country": country, "language": language}
    if _CATEGORY_KEY_RE.match(raw):
        return {"key": raw, "slug": None, "country": None, "language": None}
    if len(raw) > 150:
        raise ValueError("Must be a category id, slug or link.")
    return {"key": None, "slug": raw.strip("/").lower(), "country": None, "language": None}


def resolve_store(value):
    """'c092' -> 'C092'. Store ids are short alphanumeric references."""
    raw = (value or "").strip()
    if not _STORE_ID_RE.match(raw):
        raise ValueError("Must be a store id such as C092 (see /aldi/stores/search).")
    return raw.upper()


def resolve_location(value, country):
    """A place a customer types into the store finder ->
    {"kind": "coordinates", "latitude", "longitude"} |
    {"kind": "postcode", "postcode"} | {"kind": "text", "text"}."""
    raw = " ".join((value or "").split())
    if not raw:
        raise ValueError("Must be a postcode, a city / address, or 'latitude,longitude'.")
    match = _COORDS_RE.match(raw)
    if match:
        latitude, longitude = float(match.group(1)), float(match.group(2))
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError("Coordinates must be 'latitude,longitude' (e.g. 51.5074,-0.1278).")
        return {"kind": "coordinates", "latitude": latitude, "longitude": longitude}
    if re.fullmatch(COUNTRIES[country]["postcode"], raw):
        return {"kind": "postcode", "postcode": raw.upper()}
    if len(raw) > 100:
        raise ValueError("Location is too long (100 characters at most).")
    return {"kind": "text", "text": raw}


# ---- links out -----------------------------------------------------------------

def _site_base(country, language):
    info = COUNTRIES[country]
    base = "https://" + info["site"]
    if info["language_prefix"]:
        base += "/" + (language or info["languages"][0])
    return base


def _segments(country, language):
    info = COUNTRIES[country]
    return info["paths"].get(language) or info["paths"][info["languages"][0]]


def product_link(country, language, slug, sku):
    """Shop link of a product; `slug` may already end in the SKU (the API's
    `canonical`)."""
    if not sku and not slug:
        return None
    tail = slug or ""
    if sku and not tail.endswith(sku):
        tail = f"{tail}-{sku}" if tail else sku
    return f"{_site_base(country, language)}/{_segments(country, language)[0]}/{quote(tail)}"


def category_link(country, language, slug, key):
    if not slug or not key:
        return None
    return f"{_site_base(country, language)}/{_segments(country, language)[1]}/{quote(slug, safe='/')}/k/{key}"


def site_link(country, language=None):
    return _site_base(country, language) if COUNTRIES[country]["language_prefix"] else "https://" + COUNTRIES[country]["site"]
