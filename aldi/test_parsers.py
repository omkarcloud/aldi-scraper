"""Offline tests: parsers, input resolution, schemas and response
classification against saved API payloads (aldi/fixtures/, captured
2026-10-05).

    python -m pytest aldi/test_parsers.py -q
"""
import json
import os
from datetime import date

import pytest

from aldi import categories, fetch, parsers, refs, schemas
from schema_fields import load_query

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


# ---- input resolution --------------------------------------------------------------

@pytest.mark.parametrize("value, sku, country, language", [
    ("000000000000543221", "000000000000543221", None, None),
    ("543221", "000000000000543221", None, None),
    ("cowbelle-chocolate-milk-000000000000543221", "000000000000543221", None, None),
    ("https://www.aldi.co.uk/product/cowbelle-chocolate-milk-000000000000543221?x=1#top", "000000000000543221", "uk", None),
    ("aldi.com.au/product/pure-vita-sunflower-oil-1l-000000000000200347", "000000000000200347", "au", None),
    ("https://www.aldi-sued.de/produkt/milsani-frische-vollmilch-3-5-1-l-000000000330654001", "000000000330654001", "de", None),
    ("https://www.aldi-suisse.ch/fr/produit/mikado-lait-000000000000290628", "000000000000290628", "ch", "fr"),
    ("https://www.hofer.si/izdelek/milfina-sveze-polnomastno-mleko-000000000000310893", "000000000000310893", "si", None),
    ("https://api.aldi.hu/v2/products/000000000699723001", "000000000699723001", "hu", None),
])
def test_resolve_product(value, sku, country, language):
    assert refs.resolve_product(value) == {"sku": sku, "country": country, "language": language}


@pytest.mark.parametrize("value", ["", "milk", "cowbelle-chocolate-milk", "https://www.tesco.com/product/1234567", "12"])
def test_resolve_product_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_product(value)


@pytest.mark.parametrize("value, expected", [
    ("1588161416978051001", {"key": "1588161416978051001", "slug": None, "country": None, "language": None}),
    ("Chilled-Food/Milk", {"key": None, "slug": "chilled-food/milk", "country": None, "language": None}),
    ("https://www.aldi.co.uk/products/chilled-food/milk/k/1588161416978051001",
     {"key": "1588161416978051001", "slug": None, "country": "uk", "language": None}),
    ("https://www.aldi-suisse.ch/it/prodotti/promozioni/k/1588161418433031",
     {"key": "1588161418433031", "slug": None, "country": "ch", "language": "it"}),
    ("https://www.aldi-sued.de/produkte/alkoholische-getraenke/bier",
     {"key": None, "slug": "alkoholische-getraenke/bier", "country": "de", "language": None}),
])
def test_resolve_category(value, expected):
    assert refs.resolve_category(value) == expected


@pytest.mark.parametrize("value, country, expected", [
    ("51.5074,-0.1278", "uk", {"kind": "coordinates", "latitude": 51.5074, "longitude": -0.1278}),
    ("-33.87 151.21", "au", {"kind": "coordinates", "latitude": -33.87, "longitude": 151.21}),
    ("sw1a 1aa", "uk", {"kind": "postcode", "postcode": "SW1A 1AA"}),
    ("80331", "de", {"kind": "postcode", "postcode": "80331"}),
    ("80331", "uk", {"kind": "text", "text": "80331"}),
    ("D06 KF20", "ie", {"kind": "postcode", "postcode": "D06 KF20"}),
    ("  Chapel   Street Belper ", "uk", {"kind": "text", "text": "Chapel Street Belper"}),
])
def test_resolve_location(value, country, expected):
    assert refs.resolve_location(value, country) == expected


def test_resolve_misc():
    assert refs.resolve_country("GB") == "uk" and refs.resolve_country("Germany") == "de"
    assert refs.resolve_store("c092") == "C092"
    with pytest.raises(ValueError):
        refs.resolve_country("fr")
    with pytest.raises(ValueError):
        refs.resolve_store("not a store id")
    with pytest.raises(ValueError):
        refs.resolve_location("95.0,10.0", "uk")
    with pytest.raises(ValueError):
        refs.check_language("uk", "fr")
    assert refs.check_language("ch", None) == "de" and refs.check_language("ch", "it") == "it"


def test_links():
    assert refs.product_link("uk", "en", "cowbelle-chocolate-milk", "000000000000543221") == \
        "https://www.aldi.co.uk/product/cowbelle-chocolate-milk-000000000000543221"
    assert refs.product_link("uk", "en", "cowbelle-chocolate-milk-000000000000543221", "000000000000543221") == \
        "https://www.aldi.co.uk/product/cowbelle-chocolate-milk-000000000000543221"
    assert refs.product_link("ch", "it", "mikado-latte", "000000000000290628") == \
        "https://www.aldi-suisse.ch/it/prodotto/mikado-latte-000000000000290628"
    assert refs.category_link("hu", "hu", "hus-hal-felvagott/hal", "158816141849408007044") == \
        "https://www.aldi.hu/termekek/hus-hal-felvagott/hal/k/158816141849408007044"
    assert refs.category_link("uk", "en", None, "1") is None


# ---- schemas -----------------------------------------------------------------------

def test_search_schema_defaults_and_link_country():
    data, error = load_query(schemas.SearchSchema, {"query": " oat   milk ", "brand": "cowbelle, Dairyfine"})
    assert error is None
    assert data == {"query": "oat milk", "country": "uk", "language": "en", "category": None,
                    "brand": ["COWBELLE", "DAIRYFINE"], "theme": None, "sort": "relevance", "store": None, "page": 1}
    data, error = load_query(schemas.ProductSchema, {
        "product": "https://www.aldi-suisse.ch/fr/produit/mikado-lait-000000000000290628", "country": "uk"})
    assert error is None and data == {"product": "000000000000290628", "country": "ch", "language": "fr", "store": None}
    data, error = load_query(schemas.CategoryProductsSchema, {"category": "Milk", "country": "ie", "sort": "PRICE_ASC"})
    assert error is None and data["category"] == {"key": None, "slug": "milk"} and data["sort"] == "price_asc"


def test_schema_errors():
    assert load_query(schemas.SearchSchema, {})[1]["errors"]["query"]
    assert load_query(schemas.SearchSchema, {"query": "milk", "language": "fr"})[1]["errors"]["language"]
    assert load_query(schemas.SearchSchema, {"query": "milk", "contry": "de"})[1]["errors"]["contry"]
    assert load_query(schemas.ProductSchema, {"product": "milk"})[1]["errors"]["product"]
    assert load_query(schemas.AvailabilitySchema, {"product": "543221"})[0]["store"] is None   # default store
    assert load_query(schemas.AvailabilitySchema, {"product": "543221", "store": "C092", "location": "London"})[1]
    mixed = "https://www.aldi.co.uk/product/a-000000000000543221,https://www.aldi.ie/product/b-000000000000422541"
    assert load_query(schemas.BulkProductsSchema, {"products": mixed})[1]["errors"]["products"]
    assert load_query(schemas.BulkProductsSchema, {"products": ",".join(str(100000 + i) for i in range(31))})[1]


def test_bulk_and_location_schemas():
    data, error = load_query(schemas.BulkProductsSchema, {"products": "543221, 000000000000543221,422329"})
    assert error is None and data["products"] == ["000000000000543221", "000000000000422329"]
    data, error = load_query(schemas.StoreSearchSchema, {"location": "80331", "country": "de", "radius": "10"})
    assert error is None and data["location"] == {"kind": "postcode", "postcode": "80331"} and data["radius"] == 10
    data, error = load_query(schemas.AvailabilitySchema, {"product": "387288", "location": "51.5,-0.12", "only_in_stock": "true"})
    assert error is None and data["location"]["kind"] == "coordinates" and data["only_in_stock"] is True


# ---- value helpers -----------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("£2.89", 2.89), ("1,89 €", 1.89), ("CHF 3.79", 3.79), ("129 Ft", 129.0), ("2 499 Ft", 2499.0),
    ("172,00 Ft", 172.0), ("CHF 1’299.00", 1299.0), ("1.299,50 €", 1299.5), ("£1,299", 1299.0),
    ("20 %", 20.0), ("13%", 13.0), ("0.125 kg", 0.125), ("0,5 l", 0.5), ("no digits", None), (None, None),
])
def test_parse_number(value, expected):
    assert parsers.parse_number(value) == expected


def test_value_helpers():
    assert parsers.money(95) == 0.95 and parsers.money(12900) == 129.0 and parsers.money(None) is None
    assert parsers.text("  N/A ") is None and parsers.text("a\xa0 b") == "a b"
    assert parsers.to_float("-0.16336001000") == -0.16336001
    assert parsers.number(1.0) == 1 and parsers.number("0.9") == 0.9
    assert parsers.measure("1.6 mi") == {"value": 1.6, "unit": "mi"}
    assert parsers.measure("1,3 km") == {"value": 1.3, "unit": "km"}
    assert parsers.parse_amount("<0.5 g") == (0.5, "g") and parsers.parse_amount("3,1 g") == (3.1, "g")
    assert parsers.split_list("Egypt; Italy; Spain") == ["Egypt", "Italy", "Spain"]
    assert parsers.html_text("Tasty.<ul><li>1 Litre</li><li>Fresh</li></ul>") == "Tasty.\n1 Litre\nFresh"
    assert parsers.html_list_items("Tasty.<ul><li>1 Litre</li><li>Fresh</li></ul>") == ["1 Litre", "Fresh"]
    assert parsers.iso_date("2026-10-08T00:00:00+00:00") == "2026-10-08" and parsers.iso_date("soon") is None


# ---- products ----------------------------------------------------------------------

def test_search_listing():
    payload = fixture("search_uk_milk.json")
    products = parsers.products(payload, "uk", "en")
    first = products[0]
    assert first["id"] == "000000000000543221" and first["name"] == "Chocolate Milk" and first["brand"] == "COWBELLE"
    assert first["link"] == "https://www.aldi.co.uk/product/cowbelle-chocolate-milk-000000000000543221"
    assert first["image"].startswith("https://dm.emea.cms.aldi.cx/") and "{" not in first["image"]
    assert first["price"] == {"amount": 0.95, "currency": "GBP", "was_amount": None, "discount_percent": None,
                              "unit_price": {"amount": 0.95, "per": "1 L"}, "per_weight": None, "deposit": None,
                              "note": None}
    assert first["categories"][-1]["link"] == "https://www.aldi.co.uk/products/chilled-food/milk/k/1588161416978051001"
    assert first["is_sold_online"] is False and first["weight_type"] == "fixed"
    assert first["order_quantity"] == {"minimum": 1, "maximum": 99, "step": 1, "unit": "ea"}
    assert parsers.pagination(payload, 2, 30) == {"page": 2, "items_per_page": 30, "total_pages": 3, "total_count": 88}
    filters, sort_options = parsers.parse_filters(payload)
    assert [f["name"] for f in filters] == ["category", "theme", "brand"]
    assert filters[0]["values"][0]["children"] and filters[2]["values"][0]["count"]
    assert [s["value"] for s in sort_options] == refs.SORTS[:1] + ["name_asc", "name_desc", "price_asc", "price_desc"]
    assert parsers.search_meta(payload) == {"spelling_suggestion": None, "redirect_link": None}


def test_swiss_language_links():
    payload = fixture("search_ch_milch.json")
    german = parsers.products(payload, "ch", "de")[0]
    french = parsers.products(payload, "ch", "fr")[0]
    assert german["link"] == "https://www.aldi-suisse.ch/de/produkt/mikado-milch-000000000000290628"
    assert french["link"] == "https://www.aldi-suisse.ch/fr/produit/mikado-lait-000000000000290628"
    assert german["price"]["currency"] == "CHF"


def test_detail_beer_with_deposit_and_nutrition():
    detail = parsers.product_detail(fixture("product_de_beer.json")["data"], "de", "de")
    assert detail["name"] == "Premium Pils 0,5 l" and detail["minimum_age"] == 16 and detail["alcohol_percent"] == 4.8
    assert detail["price"]["amount"] == 0.99 and detail["price"]["deposit"] == {"amount": 0.25, "type": "EINWEG"}
    assert detail["price"]["unit_price"] == {"amount": 1.98, "per": "1 l"}
    table = detail["nutrition"][0]
    assert table["basis"] == "pro 100 ml"
    assert table["values"][0] == {"name": "Energie [kJ]", "value": "170 kJ", "amount": 170.0, "unit": "kJ"}
    assert {"name": "Kohlenhydrate", "value": "3,1 g", "amount": 3.1, "unit": "g"} in table["values"]
    assert detail["dietary_claims"] == [{"type": "Enthält", "value": "Laktose"}]
    assert detail["ingredients"].startswith("Zutaten: Wasser")
    assert detail["link"].startswith("https://www.aldi-sued.de/produkt/") and detail["link"].endswith("-000000000000182390")
    assert detail["variants"] is None and detail["parent_id"] is None


def test_detail_sold_by_weight():
    detail = parsers.product_detail(fixture("product_au_grapes.json")["data"], "au", "en")
    assert detail["is_sold_by_weight"] is True and detail["weight_type"] == "loose_large"
    assert detail["price"]["amount"] == 9.89
    assert detail["price"]["per_weight"] == {"amount": 10.99, "unit": "kg", "typical_item_weight": 0.9}
    assert detail["price"]["unit_price"] == {"amount": 10.99, "per": "1 kg"}
    assert detail["order_quantity"] == {"minimum": 0.9, "maximum": 99, "step": 0.9, "unit": "kg"}


def test_detail_variants():
    detail = parsers.product_detail(fixture("product_uk_variants.json")["data"], "uk", "en")
    variants = detail["variants"]
    assert detail["parent_id"] == "000000000000747889" and detail["is_variant_parent"] is False
    assert [a["name"] for a in variants["attributes"]] == ["Colour", "Design"]
    assert variants["attributes"][0]["selected"] == "High Liner"
    assert len(variants["products"]) == 7
    current = [v for v in variants["products"] if v["is_current"]]
    assert current == [{"id": "000000000747889001", "options": {"Colour": "High Liner", "Design": "Rectangular"},
                        "is_current": True}]
    assert detail["on_sale_date"] and detail["availability_note"]


def test_detail_was_price_and_badges():
    was = parsers.product_detail(fixture("product_ch_was_price.json")["data"], "ch", "de")
    assert was["price"]["amount"] == 3.59 and was["price"]["was_amount"] == 3.79
    assert was["price"]["discount_percent"] == 5.3 and was["price"]["unit_price"] is None
    badge = parsers.product_detail(fixture("product_ch_badge.json")["data"], "ch", "de")
    assert {"label": "Tiefpreis", "color": "red", "image": None} in badge["badges"]


def test_detail_milk_description():
    detail = parsers.product_detail(fixture("product_uk_milk.json")["data"], "uk", "en")
    assert detail["description"] == "Creamy Chocolate Milk that’s rich, smooth, and oh-so-satisfying."
    assert detail["features"] == ["1 Litre (approx.)"]
    assert detail["has_stock_information"] is False and detail["documents"] == []
    assert list(detail)[:4] == ["id", "name", "brand", "link"]


def test_partial_payloads_never_raise():
    empty = parsers.product_detail({}, "uk", "en")
    assert empty["id"] is None and empty["price"]["amount"] is None and empty["images"] == [] and empty["nutrition"] == []
    odd = parsers.product_detail({"sku": 5, "price": "free", "assets": [None, {"url": None}], "badges": "x",
                                  "categories": [None, {}], "variants": {"buckets": None, "options": [[None]]},
                                  "multiInformations": [{"nutritionalValues": [None, [{}]]}], "description": 7}, "uk", "en")
    assert odd["id"] == "5" and odd["variants"] is None and odd["categories"] == [{"id": None, "name": None, "slug": None, "link": None}]
    assert parsers.products(None, "uk", "en") == [] and parsers.stores({}) == [] and parsers.stock_rows(None) == []
    assert parsers.promotions({}) == [] and parsers.category_tree(None, "uk", "en") == []
    assert parsers.parse_suggestions({}, "uk", "en") == {"suggestions": [], "products": [], "categories": []}
    assert parsers.pagination({}, 1, 30)["total_count"] == 0


def test_suggestions():
    result = parsers.parse_suggestions(fixture("suggest_uk_milk.json"), "uk", "en")
    assert result["suggestions"][0] == "Milk" and result["products"][0]["id"] == "000000000000543221"


# ---- categories / Special Buys -----------------------------------------------------

def test_category_tree():
    tree = parsers.category_tree(fixture("category_tree_uk.json"), "uk", "en")
    assert tree[0]["name"] == "SpecialBuys" and tree[0]["link"] == "https://www.aldi.co.uk/products/specialbuys/k/1588161416584096"
    rows = parsers.flatten_categories(tree)
    child = rows[1]
    assert child["parent_id"] == tree[0]["id"] and child["level"] == 2 and rows[0]["child_count"] == 3
    italian = parsers.category_tree(fixture("category_tree_ch.json"), "ch", "it")
    assert "/it/prodotti/" in italian[0]["link"]


def test_category_lookup(monkeypatch):
    tree = parsers.category_tree(fixture("category_tree_uk.json"), "uk", "en")
    monkeypatch.setattr(categories, "tree_nodes", lambda country, language: tree)
    by_slug = categories.find({"key": None, "slug": "specialbuys/diy"}, "uk", "en")
    by_tail = categories.find({"key": None, "slug": "diy"}, "uk", "en")
    by_name = categories.find({"key": None, "slug": "baby and toddler"}, "uk", "en")
    assert by_slug["id"] == by_tail["id"] and by_name["slug"] == "specialbuys/baby-and-toddler"
    assert categories.find({"key": "42", "slug": None}, "uk", "en") is None
    with pytest.raises(ValueError):
        categories.find({"key": None, "slug": "no-such-category"}, "uk", "en")


def test_promotions():
    rows = parsers.promotions(fixture("promotion_tree_uk.json"), today=date(2026, 10, 5))
    assert rows[0]["date"] == "2026-10-11" and rows[0]["is_on_sale"] is False
    assert {"name": "Halloween Fun", "slug": "halloween-fun"} in rows[1]["themes"]
    assert [r["date"] for r in rows if r["is_on_sale"]][0] == "2026-10-04"


# ---- stores ------------------------------------------------------------------------

def test_stores():
    near = parsers.stores(fixture("stores_uk_near.json"))
    assert near[0]["distance"]["unit"] == "mi" and near[0]["coordinates"]["longitude"] < 0
    assert near[0]["address"]["country_code"] == "GB" and near[0]["address"]["postcode"]
    australian = fixture("stores_au.json")
    assert any(not parsers.is_real_store(row) for row in australian["data"])     # the placeholder row
    assert all(s["address"]["city"] for s in parsers.stores(australian))
    one = parsers.store(fixture("store_uk.json")["data"])
    assert one["id"] == "C091" and one["alcohol_sold"] == ["Beer", "Wine"] and one["distance"] is None
    assert parsers.shop_config(fixture("shop_config_uk.json")) == {"default_store_id": "C091", "services": ["walk-in"]}


def test_stock_rows():
    rows = parsers.stock_rows(fixture("availability_ch.json"))
    assert rows[0]["stock_level"] in ("high", "medium", "low") and rows[0]["stock_note"]
    assert rows[0]["store"]["id"] and rows[0]["store"]["distance"]["unit"] == "km"
    assert rows[0]["store"]["coordinates"]["latitude"] > 40


# ---- response classification -------------------------------------------------------

def test_classify():
    ok = fetch.classify(200, '{"data": []}', "u")
    assert ok == {"data": []}
    missing = fixture("error_product_not_found.json")
    with pytest.raises(fetch.AldiNotFound):
        fetch.classify(missing["status"], json.dumps(missing["body"]), "u")
    past = fixture("error_page_past_end.json")
    with pytest.raises(fetch.AldiBadRequest) as bad:
        fetch.classify(past["status"], json.dumps(past["body"]), "u")
    assert bad.value.code == fetch.PAGE_PAST_END_CODE
    no_stock = fixture("error_no_stock_data.json")
    with pytest.raises(fetch.AldiNotFound) as none:
        fetch.classify(no_stock["status"], json.dumps(no_stock["body"]), "u")
    assert none.value.code == fetch.NO_STOCK_DATA_CODE
    store = fixture("error_unknown_store.json")
    with pytest.raises(fetch.AldiNotFound):
        fetch.classify(store["status"], json.dumps(store["body"]), "u")
    with pytest.raises(fetch.AldiBlocked):
        fetch.classify(403, "<html><body>Access Denied</body></html>", "u")
    with pytest.raises(fetch.AldiBlocked):
        fetch.classify(429, "", "u")
    with pytest.raises(fetch.AldiBlocked):
        fetch.classify(200, "<!DOCTYPE html><html><head></head></html>", "u")
    with pytest.raises(fetch.AldiUpstreamError):
        fetch.classify(503, "upstream down", "u")
    with pytest.raises(fetch.AldiUpstreamError):
        fetch.classify(422, '{"errors":[{"status":422,"code":"3305","message":"Stock availability check failed"}]}', "u")
