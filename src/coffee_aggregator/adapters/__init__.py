from __future__ import annotations

from coffee_aggregator.adapters.build import (
    gallery,
    keep,
    package,
    schema_stock,
    schema_token,
    stock_state,
    stock_wording,
)
from coffee_aggregator.adapters.facts import (
    Facts,
    read_blocks,
    read_pairs,
    read_text,
    table_rows,
    vocabulary,
)
from coffee_aggregator.adapters.microdata import ratings, reviews, value
from coffee_aggregator.adapters.payload import (
    as_dict,
    as_list,
    as_number,
    as_str,
    embedded_json,
    first_record,
    json_object,
    localised,
    looks_like_json,
    records,
    strings,
)
from coffee_aggregator.adapters.refs import id_from, product_ref, sitemap_refs
from coffee_aggregator.adapters.walk import walk_listing

__all__ = [
    "Facts",
    "as_dict",
    "as_list",
    "as_number",
    "as_str",
    "embedded_json",
    "first_record",
    "gallery",
    "id_from",
    "json_object",
    "keep",
    "localised",
    "looks_like_json",
    "package",
    "product_ref",
    "ratings",
    "read_blocks",
    "read_pairs",
    "read_text",
    "records",
    "reviews",
    "schema_stock",
    "schema_token",
    "sitemap_refs",
    "stock_state",
    "stock_wording",
    "strings",
    "table_rows",
    "value",
    "vocabulary",
    "walk_listing",
]
