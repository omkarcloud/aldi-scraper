"""The 16 Aldi endpoints. Every path is served with and without the `/aldi`
prefix, so code generated against the hosted API on RapidAPI (paths like
/products/details) runs unchanged against this server.

Params are validated by the marshmallow schemas in aldi/schemas.py: unknown
or invalid params answer 400 with the reason."""
import json
from urllib.parse import urlencode

from bottle import request, response, route

from aldi import cache_config as ttl
from aldi import categories, products, special_buys, stores
from aldi import schemas as S
from cache import cached_call
from schema_fields import load_query
from scraper_errors import BadRequest, NotFound


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The query as unicode strings (bottle 0.12's .get() hands back latin-1
    decoded bytes, so a UTF-8 "München" would arrive as "MÃ¼nchen")."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def _page_link(params, page):
    if not page:
        return None
    query = {k: v for k, v in params.items() if v not in (None, "")}
    query["page"] = page
    host = request.headers.get("Host") or "localhost"
    return f"{request.urlparts.scheme}://{host}{request.path}?{urlencode(query)}"


def paginate(result, params):
    """Lift the `pagination` block into count / per_page / current_page /
    total_pages / next / previous, like the hosted API."""
    result = dict(result)
    pagination = result.pop("pagination", None) or {}
    result.pop("count", None)
    page = int(pagination.get("page") or params.get("page") or 1)
    total_pages = int(pagination.get("total_pages") or 0)
    out = {
        "count": pagination.get("total_count"),
        "per_page": pagination.get("items_per_page"),
        "current_page": page,
        "total_pages": total_pages,
        "next": _page_link(params, page + 1 if page < total_pages else None),
        "previous": _page_link(params, page - 1 if page > 1 else None),
    }
    out.update(result)
    return out


def call(path, schema, fn, paginated, cache):
    """Validate, run, map errors: bad params -> 400, missing entity -> 404,
    retries exhausted / blocked -> 500."""
    raw = query_dict()
    data, error = load_query(schema, raw)
    if error:
        return json_response(error, 400)
    try:
        result = cached_call(f"{fn.__module__}.{fn.__name__}", data, fn, cache)
    except ValueError as e:
        return json_response({"error": str(e)}, 400)
    except BadRequest as e:
        return json_response({"error": f"aldi rejected the request: {e}"}, 400)
    except NotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Exception as e:
        return json_response({"error": f"aldi {path.strip('/')} failed: {e}"}, 500)
    return json_response(paginate(result, raw) if paginated else result)


ENDPOINTS = [
    # (path, schema, function, paginated, cache)
    ("/products/details", S.ProductSchema, products.details, False, ttl.DETAILS_CACHE),
    ("/products/search", S.SearchSchema, products.search, True, ttl.SEARCH_CACHE),
    ("/products/autocomplete", S.AutocompleteSchema, products.autocomplete, False, ttl.AUTOCOMPLETE_CACHE),
    ("/products/filters", S.FiltersSchema, products.filters, False, ttl.FILTERS_CACHE),
    ("/products/details/bulk", S.BulkProductsSchema, products.bulk, False, None),
    ("/products/availability", S.AvailabilitySchema, products.availability, True, ttl.AVAILABILITY_CACHE),
    ("/categories", S.ShopOnlySchema, categories.tree, False, ttl.CATEGORIES_CACHE),
    ("/categories/products", S.CategoryProductsSchema, categories.category_products, True, ttl.SEARCH_CACHE),
    ("/brands", S.BrandsSchema, products.brands, False, ttl.BRANDS_CACHE),
    ("/brands/products", S.BrandProductsSchema, products.brand_products, True, ttl.SEARCH_CACHE),
    ("/special-buys", S.ShopOnlySchema, special_buys.calendar, False, ttl.SPECIAL_BUYS_CACHE),
    ("/special-buys/products", S.SpecialBuyProductsSchema, special_buys.products, True, ttl.SEARCH_CACHE),
    ("/stores/search", S.StoreSearchSchema, stores.search, True, ttl.STORES_CACHE),
    ("/stores/details", S.StoreSchema, stores.details, False, ttl.STORES_CACHE),
    ("/stores", S.StoreListSchema, stores.list_all, True, ttl.STORES_CACHE),
    ("/countries", S.EmptySchema, stores.countries, False, ttl.SHOP_CONFIG_CACHE),
]


def mount(path, schema, fn, paginated, cache):
    """Serve a handler at /path and /aldi/path."""
    def handler():
        return call(path, schema, fn, paginated, cache)
    handler.__name__ = "aldi_" + path.strip("/").replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route("/aldi" + path, method="GET")(handler)


for _endpoint in ENDPOINTS:
    mount(*_endpoint)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [e[0] for e in ENDPOINTS]})
