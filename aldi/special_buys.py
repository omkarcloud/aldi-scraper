"""/aldi/special-buys* — the Special Buys calendar (Specialbuys in the UK and
Ireland, Special Buys in Australia, Aktionen / akciók / akcije elsewhere):
the on-sale dates a shop has announced, each with its themes, and the
products of one date."""
from datetime import datetime
from zoneinfo import ZoneInfo

from aldi import cache_config as ttl
from aldi import fetch, parsers, refs
from aldi.shared import product_listing, product_search, shop_name, store_params


def _today(country):
    try:
        return datetime.now(ZoneInfo(refs.shop(country)["timezone"])).date()
    except Exception:
        return datetime.utcnow().date()


def _fetch_calendar(country, language):
    payload = fetch.api(country, "/v2/promotion-tree", store_params(None), language)
    return parsers.promotions(payload, _today(country))


def _calendar(country, language):
    rows = fetch.dataset("special_buys", {"country": country, "language": language}, _fetch_calendar,
                         ttl.SPECIAL_BUYS_CACHE)
    today = _today(country).isoformat()
    # `is_on_sale` is relative to the day of the request, not of the cached fetch.
    return [{**row, "is_on_sale": (row["on_sale_date"] <= today) if row["on_sale_date"] else None} for row in rows]


def calendar(country, language):
    rows = _calendar(country, language)
    return {"country": country, "count": len(rows), "special_buys": rows}


def _pick(rows, date, country):
    if date:
        for row in rows:
            if row["date"] == date:
                return row
        known = ", ".join(row["date"] for row in rows if row["date"]) or "none"
        raise ValueError(f"{shop_name(country)} has no Special Buys for {date}. Announced dates: {known}.")
    on_sale = [row for row in rows if row["is_on_sale"] and row["on_sale_date"]]
    if on_sale:
        return max(on_sale, key=lambda row: row["on_sale_date"])
    upcoming = [row for row in rows if row["on_sale_date"]]
    if upcoming:
        return min(upcoming, key=lambda row: row["on_sale_date"])
    raise fetch.AldiNotFound(f"{shop_name(country)} has no Special Buys announced right now.")


def _theme_key(row, theme):
    wanted = theme.lower()
    for candidate in row["themes"]:
        if wanted in ((candidate["name"] or "").lower(), (candidate["slug"] or "").lower()):
            return candidate["name"]
    known = ", ".join(t["name"] for t in row["themes"]) or "none"
    raise ValueError(f"No theme '{theme}' in the Special Buys of {row['date']}. Themes: {known}.")


def products(date, theme, sort, store, page, country, language):
    """Products of one Special Buys date (default: the newest date already
    on sale), optionally narrowed to one of its themes."""
    row = _pick(_calendar(country, language), date, country)
    theme_key = _theme_key(row, theme) if theme else None
    payload = product_search(country, language, page, promotion=row["date"], theme=theme_key, sort=sort, store=store)
    return product_listing(payload, country, language, page, {"country": country, "special_buy": row, "theme": theme_key})
