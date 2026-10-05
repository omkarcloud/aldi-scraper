"""/aldi/stores* and /aldi/countries — the store finder (by postcode, city /
address text or coordinates), one store, a shop's full store list and the
supported shops."""
from cache import DontCache
from aldi import cache_config as ttl
from aldi import fetch, parsers, refs
from aldi.shared import unknown_store

SEARCH_PER_PAGE = 20
LIST_PER_PAGE = 100
DEFAULT_RADIUS = 25


def _page(country, params, page, per_page):
    payload = fetch.api(country, "/v2/service-points", {**params, "limit": per_page, "offset": (page - 1) * per_page})
    pagination = parsers.pagination(payload, page, per_page)
    if page > 1 and page > pagination["total_pages"]:
        raise ValueError(f"page {page} is past the last page ({pagination['total_pages']}).")
    return parsers.stores(payload), pagination


def search(location, radius, page, country, language):
    """Stores near a place, nearest first for a postcode or coordinates
    (rows then carry `distance`); a city / address text matches store
    addresses instead and has no distance."""
    if location["kind"] == "coordinates":
        params = {"latitude": location["latitude"], "longitude": location["longitude"],
                  "radius": radius or DEFAULT_RADIUS}
        rows, pagination = _page(country, params, page, SEARCH_PER_PAGE)
    elif location["kind"] == "postcode":
        params = {"addressZipcode": location["postcode"], "includeNearbyServicePoints": "true"}
        if radius:
            params["radius"] = radius
        try:
            rows, pagination = _page(country, params, page, SEARCH_PER_PAGE)
        except (fetch.AldiBadRequest, fetch.AldiNotFound):
            # A well-formed postcode the shop's geocoder does not know.
            rows, pagination = _page(country, {"fullTextSearch": location["postcode"]}, page, SEARCH_PER_PAGE)
    else:
        rows, pagination = _page(country, {"fullTextSearch": location["text"]}, page, SEARCH_PER_PAGE)
    return {
        "country": country,
        "location": location,
        "distance_unit": refs.shop(country)["distance_unit"],
        "stores": rows,
        "pagination": pagination,
    }


def details(store, country, language):
    try:
        payload = fetch.api(country, f"/v2/service-points/{store}")
    except fetch.AldiNotFound:
        raise unknown_store(store, country)
    data = payload.get("data")
    if not isinstance(data, dict) or not parsers.is_real_store(data):
        raise unknown_store(store, country)
    return {**parsers.store(data), "country": country}


def list_all(page, country, language):
    """Every store of a shop, 100 a page."""
    rows, pagination = _page(country, {}, page, LIST_PER_PAGE)
    return {"country": country, "stores": rows, "pagination": pagination}


# ---- supported shops ---------------------------------------------------------------

def _fetch_shop_config(country):
    payload = fetch.api(country, f"/v1/stores/{refs.shop(country)['iso']}")
    return parsers.shop_config(payload)


def shop_config(country):
    """A shop's live settings ({default_store_id, services}), shared by
    /aldi/countries and the default store of a stock lookup."""
    return fetch.dataset("shop_config", {"country": country}, _fetch_shop_config, ttl.SHOP_CONFIG_CACHE)


def countries():
    """The shops this API reads, with the default store each one prices from."""
    outcomes = fetch.run_parallel([lambda code=code: shop_config(code) for code in refs.COUNTRY_CODES], len(refs.COUNTRY_CODES))
    rows = []
    for code, (status, value) in zip(refs.COUNTRY_CODES, outcomes):
        info = refs.shop(code)
        live = value if status == "ok" else {}
        rows.append({
            "country": code,
            "name": info["name"],
            "country_code": info["iso"],
            "banner": info["banner"],
            "link": refs.site_link(code),
            "currency": info["currency"],
            "languages": list(info["languages"]),
            "distance_unit": info["distance_unit"],
            "timezone": info["timezone"],
            "default_store_id": live.get("default_store_id"),
            "services": live.get("services") or [],
        })
    result = {"count": len(rows), "countries": rows}
    # A shop whose config read failed has no default store: serve it, do not cache it.
    return result if all(status == "ok" for status, _value in outcomes) else DontCache(result)
