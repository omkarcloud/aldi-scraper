"""Cache TTL per /aldi/* endpoint (cache.py, keyed on the validated params —
marshmallow fills the defaults, so `?page=1` and no `page` share a row).

Tiers follow how fast the shops move each surface: shelf prices change with
the weekly offers (new Special Buys go on sale twice a week), the range and
its category tree move slowly, stock levels and a store's open/closed flag
move through the day.
"""
from datetime import timedelta

# --- products ------------------------------------------------------------------
SEARCH_CACHE = timedelta(hours=2)           # search / category / brand / Special Buys listings
DETAILS_CACHE = timedelta(hours=6)
AUTOCOMPLETE_CACHE = timedelta(hours=12)
FILTERS_CACHE = timedelta(hours=6)
AVAILABILITY_CACHE = timedelta(minutes=15)  # the stock traffic light moves through the day

# --- catalogue structure ---------------------------------------------------------
CATEGORIES_CACHE = timedelta(hours=12)
BRANDS_CACHE = timedelta(hours=12)
SPECIAL_BUYS_CACHE = timedelta(hours=3)     # the calendar gains a date twice a week

# --- stores --------------------------------------------------------------------
STORES_CACHE = timedelta(minutes=30)        # rows carry is_open_now
SHOP_CONFIG_CACHE = timedelta(days=1)
