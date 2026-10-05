"""Live endpoint smoke tests: one call per /aldi/* route against a running
service, with example values proven to return data (2026-10-05). The
listing tooling reads these calls as each route's working example.

Skipped unless ALDI_BASE points at a running service:

    ONLY_SCRAPER=aldi python run.py            # or any bottle runner
    ALDI_BASE=http://127.0.0.1:6002 python -m pytest aldi/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("ALDI_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set ALDI_BASE to run live endpoint tests")


def call(path, status=200, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=300)
    assert resp.status_code == status, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


# ---- products ----------------------------------------------------------------------

def test_search():
    body = call("/aldi/products/search", query="milk")
    assert body["count"] > 20 and len(body["products"]) == 30 and body["next"]
    first = body["products"][0]
    assert first["id"] and first["name"] and first["link"] and first["price"]["amount"] and first["price"]["currency"] == "GBP"
    german = call("/aldi/products/search", query="milch", country="de", sort="price_asc")["products"]
    prices = [p["price"]["amount"] for p in german]
    assert prices == sorted(prices) and german[0]["price"]["currency"] == "EUR"
    filtered = call("/aldi/products/search", query="milk", brand="cowbelle", category="chilled-food/milk")
    assert filtered["products"] and all(p["brand"] == "COWBELLE" for p in filtered["products"])
    assert call("/aldi/products/search", query="chocolte")["spelling_suggestion"] == "chocolate"
    french = call("/aldi/products/search", query="lait", country="ch", language="fr")["products"]
    assert "/fr/produit/" in french[0]["link"]
    assert call("/aldi/products/search", query="milk", store="C644")["products"]


def test_details():
    milk = call("/aldi/products/details", product="000000000000543221")
    assert milk["name"] == "Chocolate Milk" and milk["price"]["amount"] and milk["images"] and milk["country"] == "uk"
    beer = call("/aldi/products/details", product="https://www.aldi-sued.de/produkt/bitburger-pils-premium-pils-0-5-l-000000000000182390")
    assert beer["country"] == "de" and beer["nutrition"] and beer["minimum_age"] and beer["price"]["deposit"]
    grapes = call("/aldi/products/details", product="364044", country="au")
    assert grapes["is_sold_by_weight"] and grapes["price"]["per_weight"]["amount"]
    call("/aldi/products/details", status=404, product="999999")


def test_bulk_details():
    body = call("/aldi/products/details/bulk", products="543221,000000000000422329,999999")
    assert body["found_count"] == 2 and body["not_found"] == ["000000000000999999"]
    assert all(p["name"] and "description" in p and "nutrition" in p for p in body["products"])


def test_filters_and_autocomplete():
    filters = call("/aldi/products/filters", query="milk")
    assert {f["name"] for f in filters["filters"]} >= {"category", "brand"} and filters["sort_options"]
    assert call("/aldi/products/filters", category="chilled-food", country="ie")["filters"]
    suggestions = call("/aldi/products/autocomplete", query="milk")
    assert suggestions["suggestions"] and suggestions["products"]


def test_availability():
    # ALDI SUISSE publishes stock for its whole range; elsewhere only part of it.
    body = call("/aldi/products/availability", product="000000000000290628", country="ch", location="47.3769,8.5417")
    row = body["stores"][0]
    assert row["stock_level"] in ("high", "medium", "low") and row["store"]["id"] and row["store"]["distance"]
    assert call("/aldi/products/availability", product="000000000000290628", country="ch", location="Zürich")["stores"]
    one = call("/aldi/products/availability", product="000000000000290628", country="ch", store="E172")
    assert one["count"] == 1 and one["stores"][0]["store"]["id"] == "E172"
    default = call("/aldi/products/availability", product="000000000000290628", country="ch")   # the shop's default store
    assert default["count"] == 1 and default["stores"][0]["store"]["id"]
    call("/aldi/products/availability", status=404, product="543221", location="London")


# ---- categories / brands / Special Buys ----------------------------------------------

def test_categories():
    tree = call("/aldi/categories")
    assert tree["total_count"] > 50 and tree["categories"][0]["children"]
    assert "/it/prodotti/" in call("/aldi/categories", country="ch", language="it")["categories"][0]["link"]
    listing = call("/aldi/categories/products", category="https://www.aldi.co.uk/products/chilled-food/milk/k/1588161416978051001")
    assert listing["category"]["name"] == "Milk" and listing["products"]
    assert call("/aldi/categories/products", category="Milk", country="ie", sort="price_desc")["products"]


def test_brands():
    brands = call("/aldi/brands")
    assert brands["count"] > 100 and brands["brands"][0]["product_count"]
    assert call("/aldi/brands", query="cow")["brands"][0]["name"] == "COWBELLE"
    listing = call("/aldi/brands/products", brand="cowbelle")
    assert listing["brand"] == "COWBELLE" and all(p["brand"] == "COWBELLE" for p in listing["products"])


def test_special_buys():
    calendar = call("/aldi/special-buys")
    assert calendar["special_buys"] and calendar["special_buys"][0]["themes"]
    current = call("/aldi/special-buys/products")
    assert current["special_buy"]["is_on_sale"] and current["products"]
    theme = current["special_buy"]["themes"][0]["slug"]
    themed = call("/aldi/special-buys/products", date=current["special_buy"]["date"], theme=theme)
    assert themed["theme"] and themed["products"]
    assert call("/aldi/special-buys/products", country="de")["products"]


# ---- stores ------------------------------------------------------------------------

def test_stores():
    near = call("/aldi/stores/search", location="51.5074,-0.1278", radius=5)
    assert near["stores"][0]["distance"]["unit"] == "mi" and near["stores"][0]["coordinates"]["longitude"] < 0.5
    assert call("/aldi/stores/search", location="SW1A 1AA")["stores"][0]["distance"]
    assert call("/aldi/stores/search", location="München", country="de")["stores"]
    assert call("/aldi/stores/search", location="2000", country="au")["stores"][0]["address"]["region_code"] == "NSW"
    store = call("/aldi/stores/details", store="C092")
    assert store["name"] == "Chapel Street" and store["address"]["city"] == "Belper"
    call("/aldi/stores/details", status=404, store="ZZZ9")
    listing = call("/aldi/stores", country="ie")
    assert listing["count"] > 100 and listing["next"] and len(listing["stores"]) == 100


def test_countries():
    body = call("/aldi/countries")
    assert [c["country"] for c in body["countries"]] == ["uk", "au", "ie", "de", "ch", "hu", "si"]
    assert all(c["default_store_id"] and c["currency"] for c in body["countries"])
