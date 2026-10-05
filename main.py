"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. A product can be an Aldi product ID or any Aldi product link;
`country` picks the shop (uk, au, ie, de, ch, hu, si).
"""
import json
import os

from aldi import products, refs, stores

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # price, unit price, nutrition, ingredients, dietary claims, images
    save("product_milk_chocolate.json", products.details(
        product="000000000307934001", country="uk", language="en", store=None))

    # 30 products a page, with brand / category filters and price sorting
    save("search_chocolate.json", products.search(
        query="chocolate", country="uk", language="en", page=1, sort="price_asc",
        category=None, brand=None, theme=None, store=None))

    # stores near a postcode, a city or coordinates
    save("stores_manchester.json", stores.search(
        location=refs.resolve_location("Manchester", "uk"), radius=None, page=1,
        country="uk", language="en"))
