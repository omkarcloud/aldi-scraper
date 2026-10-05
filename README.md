# 🛒 Aldi Scraper

Aldi Scraper is a **free and open-source** scraper that gets you **unlimited** Aldi product, price, Special Buys and store data for free.

## ✨ What Can I Get?

- 🛒 **Search 18,000+ products in 7 countries** — live prices, unit prices, was-prices & discounts
- 🧾 **Full product details** — nutrition table, ingredients, dietary claims, images & variants
- 🏷️ **Special Buys before they hit the shelves** — every announced on-sale date, theme & product
- 🏬 **All 4,400+ stores** — addresses, coordinates, open-now flag & in-store stock levels

## 🎥 Example: A Full Aldi Product

```json
{
  "id": "000000000307934001",
  "name": "Milk Chocolate",
  "brand": "DAIRYFINE",
  "link": "https://www.aldi.co.uk/product/dairyfine-milk-chocolate-000000000307934001",
  "image": "https://dm.emea.cms.aldi.cx/is/image/aldiprodeu/product/jpg/scaleWidth/1500/63820525-b157-4bee-8272-8e2391e0c0ca/dairyfine-milk-chocolate",
  "size": "0.2 KG",
  "price": {
    "amount": 1.75,
    "currency": "GBP",
    "was_amount": 1.95,
    "discount_percent": 10.0,
    "unit_price": { "amount": 8.75, "per": "1 KG" }
  },
  "is_discontinued": false,
  "ingredients": "Sugar, Whole MILK Powder, Cocoa Butter*, Cocoa Mass*, Skimmed MILK Powder, Palm Fat, Sweet Whey Powder (MILK), Butterfat (MILK), Emulsifier (Lecithins (SOYA)), Vanilla Extract, Flavouring. ...",
  "dietary_claims": [
    { "type": "Contains", "value": "Lactose" }
  ],
  "nutrition": [
    {
      "basis": "per 100 g",
      "values": [
        { "name": "Energy kcal", "value": "528.39 kcal", "amount": 528.39, "unit": "kcal" },
        { "name": "Fat", "value": "29.99 g", "amount": 29.99, "unit": "g" },
        { "name": "Sugars", "value": "56.52 g", "amount": 56.52, "unit": "g" }
      ]
    }
  ],
  "storage_instructions": "Store in a cool, dry place.",
  "categories": [
    {
      "id": "1588161416978053003",
      "name": "Chocolate & Sweets",
      "slug": "food-cupboard/chocolate-sweets",
      "link": "https://www.aldi.co.uk/products/food-cupboard/chocolate-sweets/k/1588161416978053003"
    }
  ],
  "images": [
    { "link": "https://dm.emea.cms.aldi.cx/is/image/aldiprodeu/product/jpg/scaleWidth/1500/63820525-b157-4bee-8272-8e2391e0c0ca/dairyfine-milk-chocolate", "type": "front" }
  ],
  "country": "uk"
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Aldi Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/aldi-scraper
cd aldi-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/products/details?product=000000000307934001"
```

```json
{
  "id": "000000000307934001",
  "name": "Milk Chocolate",
  "brand": "DAIRYFINE",
  "link": "https://www.aldi.co.uk/product/dairyfine-milk-chocolate-000000000307934001",
  "size": "0.2 KG",
  "price": {
    "amount": 1.75,
    "currency": "GBP",
    "was_amount": 1.95,
    "discount_percent": 10.0,
    "unit_price": { "amount": 8.75, "per": "1 KG" }
  },
  "ingredients": "Sugar, Whole MILK Powder, Cocoa Butter*, Cocoa Mass*, Skimmed MILK Powder, Palm Fat, ...",
  "nutrition": [
    {
      "basis": "per 100 g",
      "values": [
        { "name": "Energy kcal", "value": "528.39 kcal", "amount": 528.39, "unit": "kcal" },
        { "name": "Sugars", "value": "56.52 g", "amount": 56.52, "unit": "g" }
      ]
    }
  ],
  "country": "uk"
}
```

All 16 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

16 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Product Details | `/products/details` | Everything about one product in a single call |
| Search Products | `/products/search` | 30 products per page with brand, category & price sorting |
| Autocomplete | `/products/autocomplete` | Search suggestions plus the top matching products |
| Search Filters | `/products/filters` | Brands, themes and categories with product counts |
| Bulk Product Details | `/products/details/bulk` | Full details for 30 products at once |
| Store Stock Availability | `/products/availability` | A product's stock level in the stores near you |
| Categories | `/categories` | The full category tree with IDs and links |
| Category Products | `/categories/products` | Every product in any category |
| Brands | `/brands` | Every brand a shop carries, with product counts |
| Brand Products | `/brands/products` | Every product of one brand |
| Special Buys Calendar | `/special-buys` | Announced Special Buys dates and their themes |
| Special Buys Products | `/special-buys/products` | The products of any Special Buys date or theme |
| Search Stores | `/stores/search` | Nearest stores to a postcode, city or coordinates |
| Store Details | `/stores/details` | Address, coordinates, services and open-now flag |
| All Stores | `/stores` | Every store of a country, 100 per page |
| Supported Countries | `/countries` | The 7 supported countries with currency and languages |

Every endpoint takes an optional `country`: `uk` (default), `au`, `ie`, `de`, `ch`, `hu` or `si`. Pass an Aldi product or category link instead of an ID and the country is picked for you.

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-aldi-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-aldi-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-aldi-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/products/details",
    params={"product": "000000000307934001"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Aldi Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Aldi%20Scraper%20API.)

[![Ask Us by Email about Aldi Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Aldi%20Scraper%20API&body=I%20need%20help%20using%20the%20Aldi%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/aldi-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/aldi-scraper)
