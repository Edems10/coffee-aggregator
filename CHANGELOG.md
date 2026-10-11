# Changelog

Every change that reaches `main` moves the version and adds its entry here,
newest first. The version is `version` in `pyproject.toml`. `coffee-aggregator
--version` prints it, and so does the User-Agent the crawler sends to shops
(`coffee-aggregator/<version>`). A shop's `robots.txt` rules are matched on the
product name alone, so a new version never changes which rules apply.

Stored rows change only when a crawl rewrites them. A release does not touch the
database, so an entry that says a value is now `NULL` describes what the next
crawl writes.

## 0.1.2 (2026-10-11)

### Changed

- The migration runner orders a version-named migration such as
  `0.8.0_add_decaf.sql` by its version, not by its text, so `0.10.0` applies
  after `0.9.0`; the text order would have put it first. Nothing changes for the
  existing `0001_` migrations: they keep their order, names and checksums, so no
  database runs one again. A `.sql` file named in neither form stops the runner
  with an error rather than being placed by guess.

## 0.1.1 (2026-10-11)

The first entry. It covers the changes merged from 8 October that change what a
stored row means, or what a reader can rely on. Everything here landed while the
version stayed at 0.1.0, so it is listed under the first number this rule gives
rather than split into versions nobody recorded. Earlier history, and the merges
of that week that are not listed, are in `git log`.

### Added

- `decaf` is set from a yes or no printed beside a decaf question, where the
  name and categories say nothing (#126).
- `product_kind` and `product_kind_source` on every row. Null until a seed or a
  rule decides the kind, and a crawl never clears one. `coffee-aggregator
  seed-kinds` writes a labelled seed onto rows already stored (#102, #107).
- Two report findings. `name-weight-contradiction` flags a live row whose name
  states at least ten times its stored `weight_g`. `contradictory-duplicate`
  flags two live rows of one shop, with the same name, that differ tenfold in
  price per kilogram or weight. Findings are kept in `crawl_finding`, so their
  history survives the nightly rewrite of `coffee` (#50, #82, #85).
- `availability_raw` holds the availability wording the shop used, beside the
  boolean `available` (#51).
- The image is pushed as `sha-<commit>`, and as `main` while that commit is the
  head of `main`. A date tag (`YYYY.MM.DD`) is pushed as itself and as `latest`
  (#123).

### Changed

- The crawl skips merchandise, vouchers, courses, capsules and body care (#59,
  #61). On the 30 September snapshot the capsule marker alone dropped ten more
  rows. A complete crawl delists stored rows it no longer sees, as it does for
  any product a shop stops listing.
- A package stated in millilitres has no per-kilogram price. No density is
  assumed, so a drink gets no figure from its volume (#64).
- Unstated is `NULL`, not `false`. A shop that said nothing about caffeine,
  grading or blends was stored as `false`, so `decaf = false` selected coffees
  whose shop never said so. These are `NULL` now (#89, #104, #116).

### Fixed

- A weight that a label states is refused when it contradicts the product name
  and nothing on the page says which bag is priced. Seven rows on the 9 October
  snapshot now store a `NULL` `weight_g` rather than a figure nobody could
  compare. Each refusal is a `refused-weight` finding (#128).
- A carton that restates its bag size keeps it. `BANUA Café 5 kg (20x250g)` was
  stored as 250 g and priced at 17,160 CZK/kg, where the true figure is 858
  (#72).
- A separating comma no longer joins two numbers. `intenzita 10, 450g` was read
  as 10 450 g and is now 450 g (#87).
- A variety count is not a share. `Zmes 6-7 arabík` was stored as 7 % arabica
  and 93 % robusta; the percentage sign is now required (#132).
- Grind words are no longer read as brewing methods (#101).
- A run that discovers no products is recorded as an error, and it never
  delists the catalogue (#76).

### Known gap

Every crawl publishes `null` for six contract fields: `first_seen_at`, `decaf`,
`product_kind`, `product_kind_source`, `arabica_pct` and `robusta_pct`. The
aggregator is pinned to `coffee-contracts` 2.4.0, which declares them, but the
crawl's event builder does not fill them, so a stream consumer sees them empty
even where the row holds a value. Tracked in #142.
