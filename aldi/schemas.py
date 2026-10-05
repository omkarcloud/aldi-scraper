"""Marshmallow request schemas for every /aldi/* route.

Generic fields live in the shared top-level schema_fields.py; this module
adds the ALDI resolvers and the per-route schemas. Every schema's load()
output is the kwargs dict its endpoint function takes.

ONE param per input (tripadvisor QueryOrLinkField convention, never a
sibling `url`/`id` pair):

    product    000000000000543221 | 543221 | <slug>-<sku> | a product link
    products   up to 30 of the above, comma-separated
    category   a category id | a slug / name (chilled-food/milk) | a category link
    store      a store id (C092)
    location   a postcode | a city / address | latitude,longitude

`country` picks the shop (uk au ie de ch hu si; default uk). A link names its
shop, so a product or category link also sets the country — and, on the
Swiss shop, the language (`language` = de | fr | it there).
"""
from marshmallow import ValidationError, fields, post_load, validate, validates_schema

from aldi import refs
from schema_fields import (BaseSchema, ChoiceField, CommaListField, DateField, Flag, PageField,
                           QueryField, RefField, StrippedString)

MAX_BULK_PRODUCTS = 30
MAX_RADIUS = 500


class ProductRefField(RefField):
    """`product`: a SKU, a slug ending in it, or a product link."""
    resolver = staticmethod(refs.resolve_product)


class CategoryRefField(RefField):
    """`category`: a category id, a slug / name, or a category link."""
    resolver = staticmethod(refs.resolve_category)


class ProductListField(fields.Field):
    """`products`: comma-separated product refs -> resolved, deduped list."""

    def __init__(self, max_items=MAX_BULK_PRODUCTS, **kwargs):
        kwargs.setdefault("required", True)
        super().__init__(**kwargs)
        self.max_items = max_items

    def _deserialize(self, value, attr, data, **kwargs):
        items = []
        for raw in str(value or "").replace("\n", ",").split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                ref = refs.resolve_product(raw)
            except ValueError as e:
                raise ValidationError(f"'{raw}': {e}")
            if all(ref["sku"] != seen["sku"] for seen in items):
                items.append(ref)
        if not items:
            raise ValidationError("Pass at least one product id or link.")
        if len(items) > self.max_items:
            raise ValidationError(f"At most {self.max_items} products per request.")
        return items


def _store_field():
    return RefField(resolver=refs.resolve_store, required=False, load_default=None)


def _sort_field():
    return ChoiceField(refs.SORTS, load_default="relevance")


def _brand_field():
    # Brand names are upper-case on every shop (COWBELLE, HARVEST MORN).
    return CommaListField(upper=True, max_items=10)


def _theme_field():
    return StrippedString(load_default=None, validate=validate.Length(max=100))


class ShopSchema(BaseSchema):
    """`country` + `language`, reconciled with whatever shop a product /
    category link names. Subclass output always carries a concrete country
    and a language that shop publishes."""
    country = RefField(resolver=refs.resolve_country, required=False, load_default=None)
    language = ChoiceField(refs.LANGUAGES)

    @post_load
    def _settle_shop(self, data, **kwargs):
        country, language = data.get("country"), data.get("language")
        linked = [data.get("product"), data.get("category")] + list(data.get("products") or [])
        linked_countries = {ref["country"] for ref in linked if isinstance(ref, dict) and ref.get("country")}
        if len(linked_countries) > 1:
            raise ValidationError("All links must be from the same ALDI shop.", "products")
        for ref in linked:
            if isinstance(ref, dict):
                country = ref.get("country") or country
                language = ref.get("language") or language
        country = country or refs.DEFAULT_COUNTRY
        try:
            language = refs.check_language(country, language)
        except ValueError as e:
            raise ValidationError(str(e), "language")
        data["country"], data["language"] = country, language
        if isinstance(data.get("product"), dict):
            data["product"] = data["product"]["sku"]
        if data.get("products"):
            data["products"] = [ref["sku"] for ref in data["products"]]
        if isinstance(data.get("category"), dict):
            data["category"] = {"key": data["category"]["key"], "slug": data["category"]["slug"]}
        if isinstance(data.get("location"), str):
            try:
                data["location"] = refs.resolve_location(data["location"], country)
            except ValueError as e:
                raise ValidationError(str(e), "location")
        return data


# ---- products ----------------------------------------------------------------------

class SearchSchema(ShopSchema):
    query = QueryField()
    category = CategoryRefField(required=False, load_default=None)
    brand = _brand_field()
    theme = _theme_field()
    sort = _sort_field()
    store = _store_field()
    page = PageField(max_page=200)


class ProductSchema(ShopSchema):
    product = ProductRefField()
    store = _store_field()


class BulkProductsSchema(ShopSchema):
    products = ProductListField()
    store = _store_field()


class FiltersSchema(ShopSchema):
    query = QueryField(required=False, load_default=None)
    category = CategoryRefField(required=False, load_default=None)
    store = _store_field()


class AutocompleteSchema(ShopSchema):
    query = QueryField(max_length=100)
    store = _store_field()


class AvailabilitySchema(ShopSchema):
    product = ProductRefField()
    store = _store_field()
    location = StrippedString(load_default=None)
    radius = fields.Integer(load_default=None, strict=False, validate=validate.Range(min=1, max=MAX_RADIUS))
    only_in_stock = Flag(load_default=False)
    page = PageField(max_page=50)

    @validates_schema
    def _one_place(self, data, **kwargs):
        # Neither given = the shop's default store (see products.availability).
        if data.get("store") and data.get("location"):
            raise ValidationError("Pass either `location` or `store`, not both.", "location")


# ---- categories / brands / Special Buys ----------------------------------------------

class ShopOnlySchema(ShopSchema):
    pass


class CategoryProductsSchema(ShopSchema):
    category = CategoryRefField()
    brand = _brand_field()
    theme = _theme_field()
    sort = _sort_field()
    store = _store_field()
    page = PageField(max_page=200)


class BrandsSchema(ShopSchema):
    query = QueryField(required=False, load_default=None, max_length=60)


class BrandProductsSchema(ShopSchema):
    brand = StrippedString(required=True, validate=validate.Length(min=1, max=80))
    category = CategoryRefField(required=False, load_default=None)
    sort = _sort_field()
    store = _store_field()
    page = PageField(max_page=200)


class SpecialBuyProductsSchema(ShopSchema):
    date = DateField()
    theme = _theme_field()
    sort = _sort_field()
    store = _store_field()
    page = PageField(max_page=200)


# ---- stores ------------------------------------------------------------------------

class StoreSearchSchema(ShopSchema):
    location = StrippedString(required=True)
    radius = fields.Integer(load_default=None, strict=False, validate=validate.Range(min=1, max=MAX_RADIUS))
    page = PageField(max_page=100)


class StoreSchema(ShopSchema):
    store = RefField(resolver=refs.resolve_store)


class StoreListSchema(ShopSchema):
    page = PageField(max_page=100)


class EmptySchema(BaseSchema):
    pass
