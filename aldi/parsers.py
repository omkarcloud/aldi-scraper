"""Pure parsers: ALDI API JSON -> clean API dicts. No network here.

Every parser tolerates a partial payload (a missing block yields null / [])
and never raises on odd values; fixtures live in aldi/fixtures/.

Response conventions: snake_case, `link` for URLs, `is_*` / `has_*`
booleans, ISO dates (YYYY-MM-DD), numbers as numbers, prices as a numeric
amount in the major unit (0.95, not 95) with a separate `currency`, null for
missing values.

Fields intentionally NOT exposed (and why):
  products   every `*Display` string once its value is parsed (amountRelevantDisplay,
             bottleDepositDisplay, wasPriceDisplay, savingsDisplay,
             comparisonDisplay, perUnitDisplay — presentation forms of
             numbers that are returned as numbers); `currencySymbol`;
             `urlSlugText` / `urlSlugTextAlternatives` / `canonical` /
             `useAbstractForCanonical` (only used to build `link`);
             `metaTitle` / `metaDescription` / `metaKeywords` / `metaRobots`
             (SEO tags, mostly empty); `quantityDefault` (always equals the
             minimum); `isDropship`, `isCustomerFacingApproved`,
             `discontinuedNote`, `notForSaleReason`, `sellingUnitDisplay`,
             `countryExtensions` (internal / always null on these shops);
             asset `maxWidth` / `maxHeight` / `mimeType` (folded into the
             ready-to-use image link); badge `position` (layout slot).
  stores     `geofencing` (app check-in radii, the same on every store).
  search     `meta.debug`, `meta.pinned` (merchandising internals), facet
             `config.component*` (widget names) and `activeValue`.
  categories `order` (the tree is already returned in display order) and
             `urlSlugTextAlternatives` (only used to build `link`).
  shop       cart / checkout / payment settings and the region list of
             /v1/stores.
"""
import html as html_lib
import math
import re
from datetime import date, datetime
from urllib.parse import quote

from aldi import refs

IMAGE_WIDTH = 1500

# Asset type prefix -> what the picture shows (the shop's own gallery order).
_ASSET_TYPES = [
    ("FR", "front"), ("BA", "back"), ("LE", "left"), ("RI", "right"), ("LI", "lifestyle"),
    ("GR", "group"), ("AC", "accessory"), ("DE", "detail"), ("NU", "nutrition"), ("IN", "ingredients"),
]
_WEIGHT_TYPES = {"0": "fixed", "1": "packaged_by_weight", "2": "loose_small", "3": "loose_large"}
_STOCK_LEVELS = {"green": "high", "orange": "medium", "yellow": "medium", "red": "low"}
_FACET_NAMES = {"categoryTree": "category", "brandName": "brand", "theme": "theme",
                "countryOrigin": "country_of_origin", "label": "label"}
_EMPTY_TEXT = {"n/a", "na", "-", "--", "none", "null"}

_TAG_RE = re.compile(r"<[^>]+>")
_BREAK_RE = re.compile(r"<\s*(?:br\s*/?|/?(?:p|div|li|ul|ol|h\d)\b[^>]*)>", re.I)
_LIST_RE = re.compile(r"<\s*(?:ul|ol)\b[^>]*>.*?<\s*/\s*(?:ul|ol)\s*>", re.I | re.S)
_ITEM_RE = re.compile(r"<\s*li\b[^>]*>(.*?)(?=<\s*/\s*li\s*>|<\s*li\b|<\s*/\s*(?:ul|ol)\s*>|$)", re.I | re.S)
_NUMBER_RE = re.compile(r"\d[\d.,'’   ]*\d|\d")
_UNIT_PRICE_RE = re.compile(r"(?:/|\bper\b)\s*([^/]+?)\s*$", re.I)
_AMOUNT_UNIT_RE = re.compile(r"^\s*([<>≤≥~]?)\s*(\d[\d.,]*)\s*(.*?)\s*$")


# ---- value helpers ---------------------------------------------------------------

def text(value):
    """Any scalar -> stripped, whitespace-collapsed string, or None for
    empty values and placeholders such as "N/A"."""
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    value = " ".join(html_lib.unescape(str(value)).replace("\xa0", " ").split())
    if not value or value.lower() in _EMPTY_TEXT:
        return None
    return value


def html_text(value):
    """An HTML fragment -> plain text with one line per block / list item."""
    if not isinstance(value, str) or not value.strip():
        return None
    marked = _BREAK_RE.sub("\n", value)
    plain = html_lib.unescape(_TAG_RE.sub(" ", marked)).replace("\xa0", " ")
    lines = [" ".join(line.split()) for line in plain.split("\n")]
    joined = "\n".join(line for line in lines if line)
    if not joined or joined.lower() in _EMPTY_TEXT:
        return None
    return joined


def html_list_items(value):
    """The <li> texts of an HTML fragment (the bullet points under a
    product description)."""
    if not isinstance(value, str):
        return []
    items = []
    for raw in _ITEM_RE.findall(value):
        item = html_text(raw)
        if item:
            items.append(item.replace("\n", " "))
    return items


def to_int(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    match = re.search(r"-?\d+", str(value))
    return int(match.group()) if match else None


def to_float(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    try:
        parsed = float(str(value).strip())         # "-0.16336001000" (coordinates keep their sign)
    except ValueError:
        return parse_number(str(value))
    return parsed if math.isfinite(parsed) else None


def number(value):
    """A quantity as int when it is whole (1, 99), else float (0.5)."""
    value = to_float(value)
    if value is None:
        return None
    return int(value) if value == int(value) else value


def money(minor):
    """Minor units (95, 12900) -> major units (0.95, 129.0). Every shop,
    the forint included, reports hundredths."""
    if isinstance(minor, bool) or not isinstance(minor, (int, float)):
        return None
    return round(minor / 100, 2)


def parse_number(value):
    """A localized number inside a display string -> float: '£2.89',
    '1,89 €', 'CHF 1’299.00', '2 499 Ft', '20 %', '1.299,50'. The last
    separator followed by one or two digits is the decimal mark; anything
    else groups thousands."""
    if not isinstance(value, str):
        return None
    match = _NUMBER_RE.search(value)
    if not match:
        return None
    token = re.sub(r"['’   ]", "", match.group())
    last = max(token.rfind("."), token.rfind(","))
    if last == -1:
        digits, decimals = token, ""
    else:
        tail = token[last + 1:]
        head = re.sub(r"[.,]", "", token[:last])
        # Three digits after the last separator group thousands ("1,299"),
        # unless nothing but a zero precedes it ("0.125").
        if tail and (len(tail) != 3 or head.strip("0") == ""):
            digits, decimals = token[:last], tail
        else:
            digits, decimals = token, ""
    digits = re.sub(r"[.,]", "", digits)
    if not digits.isdigit() or (decimals and not decimals.isdigit()):
        return None
    try:
        return float(f"{digits}.{decimals}") if decimals else float(digits)
    except ValueError:
        return None


def iso_date(value):
    """'2026-10-08' / '2026-10-08T00:00:00+00:00' -> 'YYYY-MM-DD' or None."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def split_list(value, separator=";"):
    """'Egypt; Italy; Spain' -> ['Egypt', 'Italy', 'Spain']."""
    cleaned = text(value)
    if not cleaned:
        return []
    return [part for part in (p.strip() for p in cleaned.split(separator)) if part]


def measure(value):
    """'1.6 mi' / '1,3 km' -> {"value": 1.6, "unit": "mi"} or None."""
    cleaned = text(value)
    if not cleaned:
        return None
    number = parse_number(cleaned)
    if number is None:
        return None
    unit = re.sub(r"^[\d.,\s]+", "", cleaned).strip() or None
    return {"value": number, "unit": unit}


def _dicts(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


# ---- products --------------------------------------------------------------------

def _localized_slug(raw, country, language):
    alternatives = raw.get("urlSlugTextAlternatives")
    if isinstance(alternatives, dict):
        localized = alternatives.get(refs.locale(country, language))
        if localized:
            return localized
    return raw.get("urlSlugText")


def _image_link(template, slug):
    if not isinstance(template, str) or not template:
        return None
    return template.replace("{width}", str(IMAGE_WIDTH)).replace("{slug}", quote(slug or "image"))


def _asset_rank(asset_type):
    for index, (prefix, _name) in enumerate(_ASSET_TYPES):
        if prefix in asset_type:
            try:
                return index + int(re.sub(r"\D", "", asset_type) or 0) / 1000
            except ValueError:
                return index
    return len(_ASSET_TYPES)


def _asset_kind(asset_type):
    for prefix, name in _ASSET_TYPES:
        if prefix in asset_type:
            return name
    return "other"


def parse_assets(assets, slug):
    """assets[] -> (images, documents). Images come back in the shop's
    gallery order (front first); anything that is not an image (a PDF data
    sheet, a manual) is a document."""
    images, documents = [], []
    ordered = sorted(_dicts(assets), key=lambda a: _asset_rank(str(a.get("assetType") or "")))
    for asset in ordered:
        link = _image_link(asset.get("url"), slug)
        if not link:
            continue
        mime = str(asset.get("mimeType") or "image/*")
        caption = text(asset.get("alt")) or text(asset.get("displayName"))
        if mime.startswith("image"):
            images.append({"link": link, "type": _asset_kind(str(asset.get("assetType") or "")), "caption": caption})
        else:
            documents.append({"name": caption, "link": link, "mime_type": mime})
    return images, documents


def parse_badges(badges):
    """badges[].items[] -> flat [{label, color, image}] (text badges such as
    "Vegan" or "Tiefpreis", image badges such as quality seals)."""
    out = []
    for badge in _dicts(badges):
        for item in _dicts(badge.get("items")):
            label = text(item.get("displayText")) or text(item.get("alt"))
            image = item.get("url") if isinstance(item.get("url"), str) and item.get("url") else None
            if not label and not image:
                continue
            entry = {"label": label, "color": text(item.get("color")), "image": image}
            if entry not in out:
                out.append(entry)
    return out


def parse_price(price, quantity_unit=None):
    """The API price block -> numbers.

    `amount` is what one item costs at the till. For goods sold by weight
    the shop prices a typical piece: `per_weight` then carries the price per
    weight unit and the typical piece weight."""
    price = price if isinstance(price, dict) else {}
    amount = money(price.get("amountRelevant"))
    if amount is None:
        amount = money(price.get("amount"))
    unit_price = None
    comparison = money(price.get("comparison"))
    if comparison is not None:
        match = _UNIT_PRICE_RE.search(text(price.get("comparisonDisplay")) or "")
        unit_price = {"amount": comparison, "per": match.group(1) if match else None}
    per_weight = None
    piece = to_float(price.get("perUnit"))
    if piece is not None:
        per_weight = {"amount": money(price.get("amount")), "unit": text(quantity_unit), "typical_item_weight": piece}
    deposit = None
    deposit_amount = money(price.get("bottleDeposit"))
    if deposit_amount:
        deposit_type = text(price.get("bottleDepositType"))
        deposit = {"amount": deposit_amount, "type": deposit_type.lstrip("/ ").strip() or None if deposit_type else None}
    was = parse_number(price.get("wasPriceDisplay")) if text(price.get("wasPriceDisplay")) else None
    discount = parse_number(price.get("savingsDisplay")) if text(price.get("savingsDisplay")) else None
    if discount is None and was and amount is not None and was > amount:
        discount = round((was - amount) / was * 100, 1)
    return {
        "amount": amount,
        "currency": text(price.get("currencyCode")),
        "was_amount": was,
        "discount_percent": discount,
        "unit_price": unit_price,
        "per_weight": per_weight,
        "deposit": deposit,
        "note": text(price.get("additionalInfo")) or text(price.get("feeText")),
    }


def parse_categories(categories, country, language):
    out = []
    for cat in _dicts(categories):
        key = text(cat.get("id") if cat.get("id") is not None else cat.get("key"))
        slug = _localized_slug(cat, country, language)
        out.append({
            "id": key,
            "name": text(cat.get("name")),
            "slug": slug or None,
            "link": refs.category_link(country, language, slug, key),
        })
    return out


def product_summary(raw, country, language):
    """One product as the search / list / suggestion payloads carry it."""
    raw = raw if isinstance(raw, dict) else {}
    sku = text(raw.get("sku"))
    slug = _localized_slug(raw, country, language)
    images, _documents = parse_assets(raw.get("assets"), slug)
    weight_type = str(raw.get("weightType")) if raw.get("weightType") is not None else None
    return {
        "id": sku,
        "name": text(raw.get("name")),
        "brand": text(raw.get("brandName")),
        "link": refs.product_link(country, language, text(raw.get("canonical")) or slug, sku),
        "image": images[0]["link"] if images else None,
        "size": text(raw.get("sellingSize")),
        "price": parse_price(raw.get("price"), raw.get("quantityUnit")),
        "on_sale_date": iso_date(raw.get("onSaleDate")),
        "availability_note": text(raw.get("onSaleDateDisplay")),
        "minimum_age": to_int(raw.get("ageRestriction")),
        "alcohol_percent": parse_number(raw.get("alcohol")) if isinstance(raw.get("alcohol"), str) else to_float(raw.get("alcohol")),
        "energy_class": text(raw.get("energyClass")),
        "is_sold_online": (not raw.get("notForSale")) if isinstance(raw.get("notForSale"), bool) else None,
        "is_discontinued": raw.get("discontinued") if isinstance(raw.get("discontinued"), bool) else None,
        "is_sold_by_weight": weight_type in ("1", "2", "3") if weight_type is not None else None,
        "weight_type": _WEIGHT_TYPES.get(weight_type),
        "order_quantity": {
            "minimum": number(raw.get("quantityMin")),
            "maximum": number(raw.get("quantityMax")),
            "step": number(raw.get("quantityInterval")),
            "unit": text(raw.get("quantityUnit")),
        },
        "categories": parse_categories(raw.get("categories"), country, language),
        "badges": parse_badges(raw.get("badges")),
        "images": images,
    }


def parse_amount(value):
    """'22.53 g' / '3,1 g' / '<0.5 g' / '170 kJ' -> (amount, unit)."""
    cleaned = text(value)
    if not cleaned:
        return None, None
    match = _AMOUNT_UNIT_RE.match(cleaned)
    if not match:
        return None, None
    return parse_number(match.group(2)), (match.group(3) or None)


def parse_nutrition(multi_informations):
    """multiInformations[] -> [{basis, values: [{name, value, amount, unit}]}].
    `value` keeps the label as printed ("<0.5 g"); `amount` / `unit` are its
    parsed parts."""
    tables = []
    for info in _dicts(multi_informations):
        values = []
        rows = info.get("nutritionalValues")
        for row in rows if isinstance(rows, list) else []:
            cells = row if isinstance(row, list) else [row]
            for cell in _dicts(cells):
                name = text(cell.get("name"))
                printed = text(cell.get("amountDisplay"))
                if not name and not printed:
                    continue
                amount, unit = parse_amount(printed)
                values.append({"name": name, "value": printed, "amount": amount, "unit": unit})
        basis = text(info.get("nutritionalValueBasisDisplay"))
        if values or basis:
            tables.append({"basis": basis, "values": values})
    return tables


def _named_values(items):
    """[{label, value}] / ['x'] / [{name}] -> [{type, value}] for claims and
    allergens, whatever shape the shop sends."""
    out = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict):
            value = text(item.get("value")) or text(item.get("name")) or text(item.get("displayText"))
            kind = text(item.get("label")) or text(item.get("type"))
        else:
            value, kind = text(item), None
        if value:
            out.append({"type": kind, "value": value})
    return out


def _walk_variant_options(node, path, buckets, out):
    if isinstance(node, list):
        for index, child in enumerate(node):
            _walk_variant_options(child, path + [index], buckets, out)
        return
    if not isinstance(node, dict):
        return
    sku = text(node.get("sku"))
    if not sku:
        return
    options = {}
    for depth, index in enumerate(path):
        if depth >= len(buckets):
            break
        values = buckets[depth].get("values")
        label = text(buckets[depth].get("label")) or f"option_{depth + 1}"
        if isinstance(values, list) and index < len(values):
            options[label] = text(values[index])
    out.append({"id": sku, "options": options})


def parse_variants(variants, sku=None):
    """variants -> {"attributes": [{name, values, selected}], "products":
    [{id, options, is_current}]}. The API's `options` matrix is indexed by
    the attribute values in order; empty cells (no such combination) drop out."""
    if not isinstance(variants, dict):
        return None
    buckets = _dicts(variants.get("buckets"))
    attributes = [{
        "name": text(bucket.get("label")),
        "values": [v for v in (text(x) for x in (bucket.get("values") if isinstance(bucket.get("values"), list) else [])) if v],
        "selected": text(bucket.get("selected")),
    } for bucket in buckets]
    products = []
    _walk_variant_options(variants.get("options"), [], buckets, products)
    for product in products:
        product["is_current"] = bool(sku) and product["id"] == sku
    if not attributes and not products:
        return None
    return {"attributes": attributes, "products": products}


def product_detail(raw, country, language):
    """One product with everything /v2/products/<sku> knows."""
    raw = raw if isinstance(raw, dict) else {}
    summary = product_summary(raw, country, language)
    sku = summary["id"]
    slug = _localized_slug(raw, country, language)
    _images, documents = parse_assets(raw.get("assets"), slug)
    description_html = raw.get("description") if isinstance(raw.get("description"), str) else None
    features = html_list_items(description_html)
    description = html_text(_LIST_RE.sub(" ", description_html)) if description_html else None
    if description is None:
        description = html_text(description_html)
    parent = text(raw.get("abstractSku"))
    if not parent or not parent.isdigit() or parent == sku:
        parent = None
    detail = {}
    for key, value in summary.items():
        if key == "categories":
            # Detail-only content sits between the list fields and the nested blocks.
            detail.update({
                "description": description,
                "features": features,
                "ingredients": html_text(raw.get("ingredients")),
                "allergens": _named_values(raw.get("allergens")),
                "dietary_claims": _named_values(raw.get("nutritionalClaims")),
                "nutrition": parse_nutrition(raw.get("multiInformations")),
                "storage_instructions": html_text(raw.get("storageInstructions")),
                "usage_instructions": html_text(raw.get("usageInstructions")),
                "warnings": html_text(raw.get("warnings")) if isinstance(raw.get("warnings"), str)
                else ("\n".join(v["value"] for v in _named_values(raw.get("warnings"))) or None),
                "legal_disclaimer": html_text(raw.get("legalDisclaimer")),
                "countries_of_origin": split_list(raw.get("countryOrigin")),
                "grade": text(raw.get("grade")),
                "has_stock_information": raw.get("stockInformationAvailable")
                if isinstance(raw.get("stockInformationAvailable"), bool) else None,
                "is_variant_parent": raw.get("isAbstract") if isinstance(raw.get("isAbstract"), bool) else None,
                "parent_id": parent,
            })
        detail[key] = value
    detail["documents"] = documents
    detail["variants"] = parse_variants(raw.get("variants"), sku)
    return detail


def products(payload, country, language):
    return [product_summary(item, country, language) for item in _dicts((payload or {}).get("data"))]


# ---- search meta -----------------------------------------------------------------

def pagination(payload, page, per_page):
    """meta.pagination -> the block route_glue.paginate lifts into the
    gateway's flat fields."""
    meta = (payload or {}).get("meta")
    block = meta.get("pagination") if isinstance(meta, dict) else None
    total = to_int(block.get("totalCount")) if isinstance(block, dict) else None
    total = total or 0
    return {
        "page": page,
        "items_per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
        "total_count": total,
    }


def _facet_values(values):
    out = []
    for value in _dicts(values):
        entry = {
            "value": text(value.get("key")),
            "label": text(value.get("label")) or text(value.get("key")),
            "count": to_int(value.get("docCount")),
        }
        children = _facet_values(value.get("children"))
        if children:
            entry["children"] = children
        if entry["value"]:
            out.append(entry)
    return out


def parse_filters(payload):
    """meta.facets + meta.sort -> the filters a search accepts right now.
    `name` is the query param of /aldi/products/search that takes `value`."""
    meta = (payload or {}).get("meta")
    meta = meta if isinstance(meta, dict) else {}
    filters = []
    for facet in _dicts(meta.get("facets")):
        config = facet.get("config") if isinstance(facet.get("config"), dict) else {}
        values = _facet_values(facet.get("values"))
        if not values:
            continue
        parameter = text(config.get("parameterName"))
        filters.append({
            "name": _FACET_NAMES.get(parameter, parameter),
            "label": text(facet.get("localizedName")),
            "is_multi_select": bool(config.get("isMultiValue")),
            "values": values,
        })
    sort_options = [{
        "value": text(option.get("parameterValue")),
        "label": text(option.get("localizedName")),
    } for option in _dicts(meta.get("sort")) if text(option.get("parameterValue"))]
    return filters, sort_options


def brand_list(payload):
    """The brand facet of an unfiltered search -> [{name, product_count}]."""
    filters, _sort = parse_filters(payload)
    for block in filters:
        if block["name"] == "brand":
            return [{"name": v["value"], "product_count": v["count"]} for v in block["values"]]
    return []


def search_meta(payload):
    meta = (payload or {}).get("meta")
    meta = meta if isinstance(meta, dict) else {}
    redirect = meta.get("keywordRedirect")
    if isinstance(redirect, dict):
        redirect = redirect.get("url") or redirect.get("target")
    return {
        "spelling_suggestion": text(meta.get("spellingSuggestion")),
        "redirect_link": text(redirect),
    }


def parse_suggestions(payload, country, language):
    data = (payload or {}).get("data")
    data = data if isinstance(data, dict) else {}
    completions = [c for c in (text(x) for x in (data.get("completions") if isinstance(data.get("completions"), list) else [])) if c]
    return {
        "suggestions": completions,
        "products": [product_summary(item, country, language) for item in _dicts(data.get("products"))],
        "categories": parse_categories(data.get("categories"), country, language),
    }


# ---- categories ------------------------------------------------------------------

def category_node(raw, country, language):
    key = text(raw.get("key"))
    slug = _localized_slug(raw, country, language)
    thumbnail = raw.get("thumbnail")
    if isinstance(thumbnail, dict):
        thumbnail = _image_link(thumbnail.get("url"), slug)
    return {
        "id": key,
        "name": text(raw.get("name")),
        "slug": slug or None,
        "link": refs.category_link(country, language, slug, key),
        "image": thumbnail if isinstance(thumbnail, str) and thumbnail else None,
        "children": [category_node(child, country, language) for child in _dicts(raw.get("children"))],
    }


def category_tree(payload, country, language):
    return [category_node(node, country, language) for node in _dicts((payload or {}).get("data"))]


def flatten_categories(tree, parent=None):
    """Tree -> flat rows with `parent_id` and `level`, depth-first."""
    rows = []
    for node in tree:
        level = (parent["level"] + 1) if parent else 1
        row = {k: v for k, v in node.items() if k != "children"}
        row.update({"parent_id": parent["id"] if parent else None, "level": level,
                    "child_count": len(node["children"])})
        rows.append(row)
        rows.extend(flatten_categories(node["children"], row))
    return rows


# ---- Special Buys ----------------------------------------------------------------

def promotions(payload, today=None):
    """/v2/promotion-tree -> [{date, title, is_on_sale, themes}] newest first
    as the shop lists them. `date` is the id /aldi/special-buys/products takes."""
    data = (payload or {}).get("data")
    today = today or date.today()
    out = []
    for promo in _dicts(data.get("promotions") if isinstance(data, dict) else None):
        on_sale = iso_date(promo.get("onSaleDateFrom")) or iso_date(promo.get("key"))
        out.append({
            "date": text(promo.get("key")),
            "title": text(promo.get("title")),
            "on_sale_date": on_sale,
            "is_on_sale": (on_sale <= today.isoformat()) if on_sale else None,
            "themes": [{
                "name": text(theme.get("key")),
                "slug": text(theme.get("urlSlugText")),
            } for theme in _dicts(promo.get("themes")) if text(theme.get("key"))],
        })
    return out


# ---- stores ----------------------------------------------------------------------

def parse_address(address):
    address = address if isinstance(address, dict) else {}
    return {
        "line1": text(address.get("address1")),
        "line2": text(address.get("address2")),
        "line3": text(address.get("address3")),
        "city": text(address.get("city")),
        "district": text(address.get("district")),
        "region": text(address.get("regionName")),
        "region_code": text(address.get("regionIsoCode")),
        "postcode": text(address.get("zipCode")),
        "country": text(address.get("countryName")),
        "country_code": text(address.get("countryIsoCode")),
    }


def _coordinates(address):
    address = address if isinstance(address, dict) else {}
    latitude, longitude = to_float(address.get("latitude")), to_float(address.get("longitude"))
    if latitude is None or longitude is None:
        return None
    return {"latitude": latitude, "longitude": longitude}


def _strings(values):
    return [v for v in (text(x) for x in (values if isinstance(values, list) else [])) if v]


def store(raw):
    raw = raw if isinstance(raw, dict) else {}
    return {
        "id": text(raw.get("id")),
        "name": text(raw.get("name")),
        "phone": text(raw.get("publicPhoneNumber")),
        "is_open_now": raw.get("isOpenNow") if isinstance(raw.get("isOpenNow"), bool) else None,
        "distance": measure(raw.get("distance")),
        "services": _strings(raw.get("availableCustomerServiceTypes")),
        "alcohol_sold": _strings(raw.get("alcoholAvailability")),
        "facilities": _strings(raw.get("facilities")),
        "address": parse_address(raw.get("address")),
        "coordinates": _coordinates(raw.get("address")),
    }


def is_real_store(raw):
    """The Australian feed carries a placeholder row ("service-point-merchant-dummy",
    no address) that is not a shop."""
    address = raw.get("address") if isinstance(raw, dict) and isinstance(raw.get("address"), dict) else {}
    return bool(address.get("city") or address.get("address1") or address.get("zipCode"))


def stores(payload):
    return [store(item) for item in _dicts((payload or {}).get("data")) if is_real_store(item)]


def stock_rows(payload):
    """/v2/service-point-product-availability -> one row per store.
    `stock_level` is the shop's traffic light (high / medium / low — low
    also covers out of stock, the shop does not tell them apart)."""
    rows = []
    for item in _dicts((payload or {}).get("data")):
        light = text(item.get("availabilityTrafficLight"))
        rows.append({
            "stock_level": _STOCK_LEVELS.get((light or "").lower(), light),
            "stock_note": text(item.get("stockInfoDisplay")),
            "store": {
                "id": text(item.get("servicePointReference")),
                "name": text(item.get("servicePointName")),
                "distance": measure(item.get("distance")),
                "services": _strings(item.get("availableCustomerServiceTypes")),
                "address": parse_address(item.get("address")),
                "coordinates": _coordinates(item.get("address")),
            },
        })
    return rows


# ---- shop config -----------------------------------------------------------------

def shop_config(payload):
    """/v1/stores/<ISO> -> the settings worth knowing: the shop's default
    store (whose range and prices a read without `store` shows) and the
    service types it offers."""
    data = (payload or {}).get("data")
    attributes = data.get("attributes") if isinstance(data, dict) and isinstance(data.get("attributes"), dict) else {}
    return {
        "default_store_id": text(attributes.get("defaultMerchant")),
        "services": _strings(attributes.get("availableServiceTypes")),
    }
