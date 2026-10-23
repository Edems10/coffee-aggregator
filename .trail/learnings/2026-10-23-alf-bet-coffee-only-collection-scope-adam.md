---
title: "Alf & Bet coffee-only collection scope"
author: Adam
date: 2026-10-23
branch: ft/200-alf-and-bet
touches:
  - src/coffee_aggregator/sites/configs/alfabet.toml
  - tests/test_alfabet_shopify.py
---

## Decided

Alf & Bet's `sladke-jemne` and `stavnate-svezi` Shopify collections covered all seven individual coffees in `kava` on 2026-10-23, in two disjoint sets of three and four products. Both page 2 responses were empty. Keep bag and tube variants as the shop states them; each product is yielded once. The Machine product page states 950 CZK for 1000 g, matching the feed; the home page states Shopify.currency.active=CZK.

## Tried and ruled out

`kava` also contains `8793928073564`, a set of three coffees. `espresso-roast` and `filtr-roast` additionally include subscription products. `hrave-funky` adds no coffee beyond the two selected flavour collections. The unfiltered catalogue is unnecessary.

## Watch out

Collection membership can change. The checked-in fixtures preserve the measured seven products and existing discovery deduplication. New shops require a rebuild and their next crawl, with no schema migration or backfill. The separate La Boheme issue has conflicting grams versus option titles; this Alf & Bet config does not change Shopify weight precedence.
