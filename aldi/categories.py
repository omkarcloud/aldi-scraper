"""/aldi/categories* — a shop's category tree and the products of one
category. The tree is one upstream document per shop and language, shared by
every route that needs it (category lookup by slug or name, breadcrumbs)."""
from aldi import cache_config as ttl
from aldi import fetch, parsers
from aldi.shared import product_listing, product_search, shop_name


def _fetch_tree(country, language):
    return parsers.category_tree(fetch.api(country, "/v2/product-category-tree", None, language), country, language)


def tree_nodes(country, language):
    """The parsed category tree of a shop (memo + response cache)."""
    return fetch.dataset("categories", {"country": country, "language": language}, _fetch_tree, ttl.CATEGORIES_CACHE)


def tree(country, language):
    nodes = tree_nodes(country, language)
    return {
        "country": country,
        "language": language,
        "total_count": len(parsers.flatten_categories(nodes)),
        "categories": nodes,
    }


def _normalize(value):
    return " ".join((value or "").lower().replace("-", " ").replace("&", " ").split())


def find(category, country, language):
    """A resolved `category` ref ({"key", "slug"}) -> its flat tree row
    ({id, name, slug, link, image, parent_id, level, child_count}), or None
    when an id is not in the tree (ids of hidden / seasonal categories still
    list products). Raises ValueError for a slug / name that matches nothing."""
    rows = parsers.flatten_categories(tree_nodes(country, language))
    if category.get("key"):
        return next((row for row in rows if row["id"] == category["key"]), None)
    wanted = (category.get("slug") or "").strip("/")
    for row in rows:                                    # full slug path
        if (row["slug"] or "").lower() == wanted:
            return row
    for row in rows:                                    # last path segment
        if (row["slug"] or "").lower().rsplit("/", 1)[-1] == wanted:
            return row
    for row in rows:                                    # display name
        if _normalize(row["name"]) == _normalize(wanted):
            return row
    raise ValueError(f"{shop_name(country)} has no category '{wanted}' (see /aldi/categories).")


def resolve(category, country, language):
    """-> (category key, tree row or None)."""
    row = find(category, country, language)
    return (row["id"] if row else category["key"]), row


def category_products(category, country, language, page, sort, brand, theme, store):
    key, row = resolve(category, country, language)
    payload = product_search(country, language, page, category_key=key, brands=brand, theme=theme,
                             sort=sort, store=store)
    return product_listing(payload, country, language, page, {
        "country": country,
        "category": row or {"id": key, "name": None, "slug": None, "link": None, "image": None,
                            "parent_id": None, "level": None, "child_count": None},
    })
