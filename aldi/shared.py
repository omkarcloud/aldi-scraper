"""Helpers shared by the /aldi/* routes: the product-search call every
listing route goes through, store pinning and error wording."""
from aldi import fetch, parsers, refs

PRODUCTS_PER_PAGE = 30          # the API takes 12 / 16 / 24 / 30 / 32 / 48 / 60 only
UNKNOWN_STORE_CODE = "3204"     # code of the AldiNotFound unknown_store() builds


def shop_name(country):
    return f"{refs.shop(country)['banner']} {refs.shop(country)['name']}"


def store_params(store):
    """`servicePoint` pins a product read to one store's range and prices."""
    return {"servicePoint": store} if store else {}


def unknown_store(store, country):
    return fetch.AldiNotFound(f"{shop_name(country)} has no store '{store}' (see /aldi/stores/search).",
                              code=UNKNOWN_STORE_CODE)


def product_search(country, language, page, *, query=None, category_key=None, promotion=None,
                   brands=None, theme=None, sort=None, store=None, per_page=PRODUCTS_PER_PAGE):
    """One /v3/product-search page -> the raw payload. No `query` lists the
    whole range (or the whole category / promotion)."""
    params = {"limit": per_page, "offset": (page - 1) * per_page}
    if query:
        params["q"] = query
    if category_key:
        params["categoryKey"] = category_key
    if promotion:
        params["promotionKey"] = promotion
    if brands:
        params["brandName[]"] = list(brands)
    if theme:
        params["theme[]"] = theme
    if sort and sort != "relevance":
        params["sort"] = sort
    params.update(store_params(store))
    try:
        return fetch.api(country, "/v3/product-search", params, language)
    except fetch.AldiBadRequest as e:
        if e.code == fetch.PAGE_PAST_END_CODE:
            raise ValueError(f"page {page} is past the last page.")
        raise
    except fetch.AldiNotFound:
        if store:
            raise unknown_store(store, country)
        raise


def product_listing(payload, country, language, page, head, per_page=PRODUCTS_PER_PAGE):
    """A search payload -> {**head, spelling_suggestion, redirect_link,
    products, pagination} (route_glue.paginate lifts `pagination`)."""
    pagination = parsers.pagination(payload, page, per_page)
    if page > 1 and page > pagination["total_pages"]:
        last = pagination["total_pages"]
        raise ValueError(f"page {page} is past the last page ({last})." if last else "No results, so there is no page 2.")
    return {
        **head,
        **parsers.search_meta(payload),
        "products": parsers.products(payload, country, language),
        "pagination": pagination,
    }
