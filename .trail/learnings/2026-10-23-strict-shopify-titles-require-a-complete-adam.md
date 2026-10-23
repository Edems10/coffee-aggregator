---
title: Strict Shopify titles require a complete size expression
author: Adam
date: 2026-10-23
branch: ft/189-la-boheme-cafe
touches:
  - src/coffee_aggregator/platforms/shopify.py
  - tests/test_labohemecafe_shopify.py
---

## Decided

PR266 finding 1 requires a completeness guard before converting strict Shopify option titles. All numeric parts must fit a supported shape: a single size, one multiplier, an equal-bag sum, or a parenthesized restatement whose parts reconcile. Existing normalize conversion and legacy grams mode stay unchanged.

## Tried and ruled out

Checking distinct parsed weights alone accepted partial readings: shared-unit ranges (250–500 g, 250 / 500 g), competing multipliers, and multiplication mixed with sums. All seven review cases now return unknown rather than publishing a partial total. Seven regression tests first failed against ee843bc and then passed through parse_product, checking variant weight, headline weight and price_per_kg. Seven companion cases retain simple units, grind suffixes, repeated units, equal-bag bundles and reconciled totals.

## Watch out

This is a strict-mode completeness filter, not an expansion of the shared arithmetic grammar. Unsupported compound arithmetic stays unknown. The captured 19 coffees / 37 variants still pass; every existing Shopify shop retains its configured grams-first default.
