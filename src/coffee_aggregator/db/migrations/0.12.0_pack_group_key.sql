-- The key that two listings of one coffee in one shop share, and the version of
-- the rule that built it (`pack_group_key.PACK_GROUP_KEY_SOURCE`, `name:v1`).
--
-- Two keys are comparable only when they carry the same source, so the source
-- travels with the key, as `product_kind_source` does with `product_kind`.
-- Both are NULL together: a coffee whose name and URL give nothing to build a
-- key from has no key, and a source without a key would claim a rule ran.
--
-- No backfill, because a key needs Python: a row takes its key at its next
-- crawl. A delisted row is never crawled again and stays NULL.
--
-- No index: nothing in the aggregator queries by the key, and an index would
-- cost every insert.
ALTER TABLE coffee ADD COLUMN IF NOT EXISTS pack_group_key text;
ALTER TABLE coffee ADD COLUMN IF NOT EXISTS pack_group_key_source text;
