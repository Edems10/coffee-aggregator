-- Keep the availability a page stated, beside the boolean we read out of it.
--
-- `available` is derived: `InStock`, `PreOrder` and `LimitedAvailability` all
-- collapse into true, because the catalogue lists all three for sale. The
-- website then has nothing left to draw a pre-order banner from, and the stock
-- wording a Shoptet option states in words ("Skladom >5 ks",
-- "IHNED K ODESLÁNÍ") is thrown away the moment the page is parsed. The typed
-- column means "what the shop said", so the token gets a column of its own.
--
-- No backfill: a parsing change rewrites no stored row, and the next crawl
-- upserts every product, so the column fills itself on the first run after
-- this migration.
--
-- `price_history` carries `available` too and deliberately does not get this
-- column. It is one row per product per day, answering what a bag cost on a
-- given day; the banner reads the current state out of `coffee`, and nobody
-- has asked what wording a shop used last March.
ALTER TABLE coffee ADD COLUMN IF NOT EXISTS availability_raw text;
ALTER TABLE coffee_variant ADD COLUMN IF NOT EXISTS availability_raw text;
