---
title: La Boheme net size differs from shipping grams
author: Adam
date: 2026-10-23
branch: ft/189-la-boheme-cafe
touches:
  - src/coffee_aggregator/platforms/shopify.py
  - src/coffee_aggregator/sites/configs/labohemecafe.toml
  - tests/test_labohemecafe_shopify.py
---

## Decided

BI's accepted source for La Bohème is the purchasable option's explicit net size, selected with the shop-scoped Shopify variant_weight_source="title". Current captured option labels and rendered pages agree: Peru Dwight Aguilar #5 is 150 g at 649 CZK, while Mocha Java is 226 g at 299 CZK or 1 kg at 1229 CZK. Shipping metadata carries grams=226 for Peru and both Mocha options. Other shops retain the existing grams-first default.

## Tried and ruled out

A config using the default would misprice Peru's net weight and misstate Mocha's kilogram variant. The title-only mode keeps missing, conflicting or implausible titles unknown instead of substituting shipping grams, a product name or a description weight. It uses the shared option parser for units, repeated units and bundle totals, rejecting conflicting distinct sizes before they can become the first parsed weight.

## Watch out

The current vsechny-kavy collection contains 20 entries: 19 bean coffees / 37 variants and one cascara excluded by the existing shared marker. Its second page is empty. Current product pages state CZK. A normal rebuild and the next crawl add the shop; no migration or backfill is required. Re-measure live scope if collection membership changes. The new active registry is 155 shops: 102 CZ / 53 SK, 96 Shoptet / 46 WooCommerce / 10 Shopify / 3 bespoke or roaster; 152 are config-driven.
