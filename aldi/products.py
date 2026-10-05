"""/aldi/products/* and /aldi/brands* — search, product details, bulk
lookups, search filters, autocomplete, in-store stock and the brand index.

Every read is anonymous. Without `store` a shop answers with its default
store's range and prices (prices are national on most shops; the UK applies
minimum unit pricing in Scotland and Wales, which a Scottish / Welsh `store`
shows)."""
import config
from cache import cached_call
from aldi import cache_config as ttl
from aldi import categories, fetch, parsers, refs
from aldi.shared import (UNKNOWN_STORE_CODE, product_listing, product_search, shop_name, store_params,
                         unknown_store)

STOCK_PER_PAGE = 10            # the availability API refuses a larger limit
DEFAULT_STOCK_RADIUS = 25
VARIANT_LOOKUP_MAX = 60        # /v2/products?skus= takes 60 SKUs a call


# ---- search ------------------------------------------------------------------------

def search(query, country, language, page, sort, category, brand, theme, store):
    category_key = categories.resolve(category, country, language)[0] if category else None
    payload = product_search(country, language, page, query=query, category_key=category_key,
                             brands=brand, theme=theme, sort=sort, store=store)
    return product_listing(payload, country, language, page, {"query": query, "country": country})


def filters(query, category, country, language, store):
    """The filter values (with product counts) and sort options a search or
    category listing offers."""
    category_key, row = categories.resolve(category, country, language) if category else (None, None)
    payload = product_search(country, language, 1, query=query, category_key=category_key, store=store, per_page=12)
    blocks, sort_options = parsers.parse_filters(payload)
    return {
        "query": query,
        "country": country,
        "category_id": category_key,
        "category_name": row["name"] if row else None,
        "total_count": parsers.pagination(payload, 1, 12)["total_count"],
        "filters": blocks,
        "sort_options": sort_options,
    }


def autocomplete(query, country, language, store):
    payload = fetch.api(country, "/v3/product-search-suggestion", {"q": query, **store_params(store)}, language)
    return {"query": query, "country": country, **parsers.parse_suggestions(payload, country, language)}


# ---- details -----------------------------------------------------------------------

def _summaries_by_sku(skus, country, language, store):
    """List-level rows for up to VARIANT_LOOKUP_MAX SKUs in one call."""
    skus = skus[:VARIANT_LOOKUP_MAX]
    params = {"skus": ",".join(skus), "limit": len(skus), **store_params(store)}
    payload = fetch.api(country, "/v2/products", params, language)
    return {row["id"]: row for row in parsers.products(payload, country, language)}


def _attach_variants(detail, country, language, store):
    """Fill each variant with its name, link, image and price (one extra
    upstream call). A failed lookup leaves the ids and options in place."""
    variants = detail.get("variants") or {}
    rows = variants.get("products") or []
    found = {}
    if rows:
        try:
            found = _summaries_by_sku([row["id"] for row in rows], country, language, store)
        except (fetch.AldiUpstreamError, fetch.AldiNotFound, fetch.AldiBadRequest) as e:
            print(f"aldi: variant lookup failed for {detail.get('id')}: {e}")
    for row in rows:
        summary = found.get(row["id"]) or {}
        price = summary.get("price") or {}
        row.update({
            "name": summary.get("name"),
            "link": summary.get("link"),
            "image": summary.get("image"),
            "size": summary.get("size"),
            "price": {"amount": price.get("amount"), "currency": price.get("currency")},
        })


def _fetch_detail(product, country, language, store):
    try:
        payload = fetch.api(country, f"/v2/products/{product}", store_params(store), language)
    except fetch.AldiNotFound as e:
        if store and e.code in ("3204", "3501", "35099"):
            raise unknown_store(store, country)
        raise fetch.AldiNotFound(f"{shop_name(country)} has no product '{product}'.")
    return parsers.product_detail(payload.get("data"), country, language)


def details(product, country, language, store):
    detail = _fetch_detail(product, country, language, store)
    _attach_variants(detail, country, language, store)
    return {**detail, "country": country}


def bulk(products, country, language, store):
    """Full details for up to 30 products, read in parallel. Products the
    shop does not have come back under `not_found`; the rest are returned."""
    def one(sku):
        params = {"product": sku, "country": country, "language": language, "store": store}
        return cached_call("aldi.products.details", params, details, ttl.DETAILS_CACHE)

    outcomes = fetch.run_parallel([lambda sku=sku: one(sku) for sku in products], config.ALDI_BULK_WORKERS)
    found, missing, failed = [], [], []
    for sku, (status, value) in zip(products, outcomes):
        if status == "ok":
            found.append({k: v for k, v in value.items() if k != "country"})
        elif isinstance(value, fetch.AldiNotFound):
            if store and value.code == UNKNOWN_STORE_CODE:
                raise value                    # the store is unknown, not the products
            missing.append(sku)
        else:
            failed.append({"id": sku, "error": str(value) or type(value).__name__})
    if failed and not found and not missing:
        raise fetch.AldiUpstreamError(failed[0]["error"])
    return {
        "country": country,
        "requested_count": len(products),
        "found_count": len(found),
        "products": found,
        "not_found": missing,
        "failed": failed,
    }


# ---- in-store stock ----------------------------------------------------------------

def availability(product, store, location, radius, only_in_stock, page, country, language):
    """Stock level of one product in one store, or in the stores around a
    place; with neither, in the shop's default store (/aldi/countries
    `default_store_id`). The shops publish stock only for part of their range
    (a product's `has_stock_information`); anything else answers 404."""
    if not store and not location:
        from aldi import stores
        store = stores.shop_config(country).get("default_store_id")
        if not store:
            raise ValueError("Pass `location` (a postcode, a city or latitude,longitude) or `store` (a store id).")
    params = {"productSku": product, "limit": STOCK_PER_PAGE, "offset": (page - 1) * STOCK_PER_PAGE}
    if only_in_stock:
        params["onlyInStock"] = "true"
    if store:
        params["servicePointReference"] = store
    elif location["kind"] == "coordinates":
        params.update({"latitude": location["latitude"], "longitude": location["longitude"],
                       "radius": radius or DEFAULT_STOCK_RADIUS})
    else:
        params["fullTextSearch"] = location.get("postcode") or location["text"]
    try:
        payload = fetch.api(country, "/v2/service-point-product-availability", params, language)
    except fetch.AldiNotFound as e:
        if e.code == fetch.NO_STOCK_DATA_CODE:
            raise fetch.AldiNotFound(f"{shop_name(country)} publishes no stock information for product '{product}'.")
        if store:
            raise unknown_store(store, country)
        raise
    except fetch.AldiBadRequest as e:
        if store and "servicePointReference" in str(e):
            raise unknown_store(store, country)
        raise
    pagination = parsers.pagination(payload, page, STOCK_PER_PAGE)
    if page > 1 and page > pagination["total_pages"]:
        raise ValueError(f"page {page} is past the last page ({pagination['total_pages']}).")
    return {
        "product_id": product,
        "country": country,
        "distance_unit": refs.shop(country)["distance_unit"],
        "stores": parsers.stock_rows(payload),
        "pagination": pagination,
    }


# ---- brands ------------------------------------------------------------------------

def _fetch_brands(country, language):
    payload = product_search(country, language, 1, per_page=12)
    return sorted(parsers.brand_list(payload), key=lambda b: b["name"] or "")


def brands(query, country, language):
    """Every brand a shop carries with its product count (the Slovenian shop
    publishes no brand index)."""
    rows = fetch.dataset("brands", {"country": country, "language": language}, _fetch_brands, ttl.BRANDS_CACHE)
    if query:
        needle = query.lower()
        rows = [row for row in rows if needle in (row["name"] or "").lower()]
    return {"country": country, "count": len(rows), "brands": rows}


def brand_products(brand, category, sort, store, page, country, language):
    name = brand.upper()
    category_key = categories.resolve(category, country, language)[0] if category else None
    payload = product_search(country, language, page, category_key=category_key, brands=[name],
                             sort=sort, store=store)
    return product_listing(payload, country, language, page, {"brand": name, "country": country})
