-- What kind of product a row is: beans, capsules, merch and so on.
--
-- The catalogue holds more than coffee. About one row in twenty is a paper cup,
-- a capsule, a barista course or a test product, and the crawl stored all of
-- them alike, so the recommender returned them as neighbours. The kind is stored
-- instead of used to delete rows: a deleted row loses the evidence it was judged
-- on, and the next crawl would judge it again from nothing.
--
-- Three columns, because a kind is only as trustworthy as its record of where it
-- came from:
--
-- * product_kind is what the product is. NULL means no decision has reached the
--   row yet, which is the truthful answer for a row nothing has looked at.
-- * product_kind_source is where the decision came from. Once a rule exists, its
--   answer and a labelled seed's answer must not be mistaken for each other.
-- * product_kind_name_hash is the name the decision was made from. When a shop
--   renames a product the hash stops matching, so the renamed product is not
--   silently kept under the kind it had as something else.
--
-- No CHECK constraint on product_kind: the vocabulary lives in product_kind.py,
-- beside the code that enforces it, so adding a kind is a code change and not a
-- migration. No default and no backfill: a crawl does not decide kinds, and the
-- seed loader fills the rows it labelled.
ALTER TABLE coffee ADD COLUMN IF NOT EXISTS product_kind text;
ALTER TABLE coffee ADD COLUMN IF NOT EXISTS product_kind_source text;
ALTER TABLE coffee ADD COLUMN IF NOT EXISTS product_kind_name_hash text;
