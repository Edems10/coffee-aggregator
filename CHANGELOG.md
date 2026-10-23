# Changelog

Every change that reaches `main` moves the version and adds its entry here,
newest first. The version is `version` in `pyproject.toml`. `coffee-aggregator
--version` prints it, and so does the User-Agent the crawler sends to shops
(`coffee-aggregator/<version>`). A shop's `robots.txt` rules are matched on the
product name alone, so a new version never changes which rules apply.

Stored rows change only when a crawl rewrites them. A release does not touch the
database, so an entry that says a value is now `NULL` describes what the next
crawl writes.

## 0.16.0 (2026-10-23)

### Added

- La Bohème Café's coffee collection is collected through the Shopify adapter
  (#189): 19 bean coffees and 37 variants at onboarding, with cascara excluded
  by the shared rule. Its option-stated net weight is selected by the new
  shop-scoped `variant_weight_source = "title"`: Peru's 649 CZK option is 150 g,
  and Mocha Java's 1229 CZK option is 1 kg even though both have shipping
  metadata of 226 g. Missing or conflicting option sizes stay unknown in this
  mode; the default for existing shops is unchanged. Normal deployment and the
  next crawl add the rows; no migration or backfill is required.

## 0.15.0 (2026-10-23)

### Added

- Alf & Bet's seven individual coffees are collected through the existing
  Shopify adapter (#200). The two flavour collections cover those coffees
  without the three-coffee set in the parent collection or the subscriptions
  in the roast collections. Each option keeps its stated CZK price, stock and
  pack weight; the first crawl after deployment adds the shop's rows.

## 0.14.7 (2026-10-22)

### Fixed

- The nightly backup now verifies each dump with a full read, `pg_restore -f
  /dev/null`, instead of `pg_restore --list` (#247). `--list` reads only the table
  of contents at the front of a custom-format dump, so a dump cut at 50 % or at
  99 % of its data passed it and was uploaded as the night's backup. Both now
  exit non-zero, keep the earlier dumps, upload nothing and leave no `.part`
  behind. A whole dump uploads, reads its size back and prunes as before.

## 0.14.6 (2026-10-22)

### Fixed

- A WooCommerce Store API variation now carries its own price (#237). The product
  listing names a product's variations but prices none, so under #172's rule no
  option could be chosen and the row kept the range minimum with the smallest bag.
  Discovery now reads `products?type=variation&per_page=100&include=<ids>` for the
  variations of every product that has more than one and copies each variation's
  `prices` into the product's payload, matched by id and `parent`. Products are
  held back while the held ones list at most 100 variations, or until the walk
  ends, so a shop costs about one request per 100 variations whatever its
  categories, and `--limit` or a deadline stop the walk within about one window (a
  shop with fewer variations than a window is walked to the end first); a
  product with one variation, a simple product and an ignored product are never
  asked about. A product takes the prices only when the listing states a price for every
  one of its variations, so the price and weight it is stored under come from one
  option: a variation the shop prices at `"0"` leaves the whole product as it
  was (`bonte/7956` and `bonte/4749` still store 7.90 EUR for 125 g). A listing
  that fails, is not a JSON array or answers for nothing leaves the crawl as it
  was, with one warning in the log and no discovery note. A malformed
  `currency_minor_unit` in a variation reads as the product's. `seriouscoffee/3532`
  now stores 250 g at 10.90 EUR and 1000 g at 27.90 EUR on its variants.
- Cost: one extra request per 100 variations of the shop's multi-variation coffee
  products, none for the non-coffee products a shop-wide listing would carry
  (`zlatezrnko`'s lists 138 variations for 97 that matter). Measured on 2026-10-22
  against 44 of the 47 Store API configs, with the crawler's own User-Agent and
  each host's robots.txt delay (`caffeoro` states 30 s, every other shop the 1 s
  default): 56 requests for 2 964 variations of 716 products with the walk batched
  whole, which is 36 shops at one request, `bonte` and `kavaloka` at five,
  `prazirnagrain` at four, `aurelica`, `caffe4u` and `kmen` at two, and `lubezna`
  and `networkcafe` at none. Every listing returned exactly the ids asked for. The
  shipped windows ask the same ids in smaller batches; replayed offline over the
  same 878 saved products they cost 59 requests (`bonte` 6 and `prazirnagrain` 6,
  the rest unchanged). The three Store API configs not measured are `goodtimes`
  and `spiritcoffee`, switched off, and `moritzcafe`, whose Store API pages were
  not in the cache the measurement replayed.
- Rows that move, re-parsed offline from the 878 saved Store API payloads of the
  44 shops with and without the variation prices: 86 products in 9 shops change
  `price`, `weight_g` or `price_per_kg` (`bonte` 36, `kavaloka` 17,
  `prazirnagrain` 11, `frisnakava` 10, `naturpark12` 5, `longberry` 3, `kmen` 2,
  `caffe4u` 1, `ciernaperla` 1), and 2 `twohands` rows lose an `original_price`
  of 16.01 EUR against a price of 16.00, which makes 88 rows in 10 shops. Weights:
  36 go 125 g to 250 g (`bonte`), 30 go 100 g to 250 g, 11 go 100 g to 300 g,
  5 go 150 g to 250 g, 4 keep their weight and change the price. Per kilogram of
  the 86: 8 go up, 69 down, 6 keep their figure and 3 have none before or after.
  Examples: `kavaloka/9059` 83 Kč per 100 g becomes 208 Kč per 250 g,
  `frisnakava/2427` 8.00 EUR per 100 g becomes 19.90 EUR per 250 g, `bonte/9992`
  7.90 EUR per 125 g becomes 14.90 EUR per 250 g.
  `seriouscoffee` moves nothing. The estimate in #237 was 46 rows in five shops;
  those five shops still move 46 (17, 11, 10, 5 and 3 against its 16, 11, 10, 6, 3).
  Stored rows change at the next crawl; no migration.

## 0.14.5 (2026-10-22)

### Fixed

- A Shoptet variant named by one hidden label that joins every parameter
  (`Druh kávy: Zrnková, Hmotnost: 250g`, or `Velikost balení: 250 g` where the
  shop has one parameter) now takes its weight from the label's size part (#260).
  Before, no weight was read from these pages, so under #172's rule (no option
  states a weight, so no price) a coffee whose page states 209 Kč for 250 g was
  stored with no price at all. Each offer is matched to its label through the
  radio value the page's tracking data states for the offer's sku. The size
  parameter is one the shared label vocabulary in `labels/` reads as a weight
  (`Velikost balení`, `Množství`, `Gramáž` and the rest, plus Shoptet's own
  `Hmotnost`), and a decimal comma such as `0,25 kg` stays one value. A variant
  takes the page's label as its name instead of its sku.
- Measured on the 2 621 Shoptet pages re-parsed from the 2026-10-21 cache: 15
  carry the joined-label shape (`cafegape` 10, `hippocafe` 4, `eshopmakacoffee`
  1). 41 variants gain a weight (`hippocafe` 32, `cafegape` 8, `eshopmakacoffee`
  1, whose `58/1KG` reads 1 000 g), 13 more already had it from their sku and
  keep it under the new name, and none changes or loses one. Eight products gain
  a price they did not have: `hippocafe/77` stores 330 Kč for 250 g (1 320
  Kč/kg), `cafegape/2166` 209 Kč for 250 g (836 Kč/kg), and `cafegape` 2172,
  2211, 2241 and `hippocafe` 83, 89, 107 likewise. They are eight of the nine
  products #172 would have stored without a price; the ninth is a Shopify drip
  sachet this fix does not touch. No variant price, no other field of any
  variant and no product outside the 15 pages changes, and no existing price is
  rewritten. Stored rows change at the next crawl; no migration.

## 0.14.4 (2026-10-22)

### Fixed

- A product that offers several packages at different prices is stored under one
  of them, the option nearest 250 g, with that option's own price, weight,
  currency and original price (#172). Before, every platform quoted its own
  headline (Shopify and WooCommerce the cheapest option, fathers the first,
  Shoptet the price the page prints) and the weight was read separately, so a
  row could carry a price and a weight from different options. `botacoffee/5524`
  offers 70 g at 115 Kč, 250 g at 359 Kč and 1 kg at 1 399 Kč; it stored the 70
  g sample and now stores 359 Kč for 250 g, 1 436 Kč/kg. The owner's rule
  (2026-10-18, completed 2026-10-21), applied by one function,
  `price_option.settle_price_option`, to every adapter's `parse_product` and so
  to `coffee-aggregator parse` too: among the options that state a price and a
  weight, skip any under 100 g when a larger one exists; among what is left
  prefer those known to be in stock; take the one nearest 250 g, the heavier on
  a tie; between options of that one weight at different prices (a grind, a
  roast, a returnable tin) take the page's default option, else the first in
  page order. Nothing is too far: a shop that sells only 500 g and 1 kg stores
  the 500 g. A product with one option, with none, or whose priced options all
  state one price is untouched, and so is one whose options state weights but no
  price; that is every WooCommerce Store API variable product until #237 prices
  its variations.
- Measured on 3 798 products (2 621 Shoptet pages re-parsed from the 2026-10-21
  cache, 1 177 products crawled from the other platforms on 2026-10-22): 1 343
  offer several prices and 450 of them change `price`, 439 also `weight_g`.
  Per-kilogram prices go up for 205, down for 196, stay the same for 48 and are
  lost for one (`kavakromeriz/1614` prints 218 Kč for both its 250 g and 100 g
  options, which `price_basis` still refuses to divide). The largest move is
  `danielasroastery/162`, 2 180 to 1 320 Kč/kg: the 100 g option it stored is
  now the 250 g one. The other 2 455 products are byte-identical on price,
  weight, per-kilogram price, original price and currency. The stock preference
  chose a different option for 11 products, the page order decided between
  options of one weight for 79, and the sample rule and the page's own default
  option decided none.
- Nine products lose their price: no option states a weight and the name does
  not either, so the "from" price they stored said nothing about any pack. They
  store NULL `price`, `weight_g`, per-kilogram price, `currency` and
  `original_price`: `cafegape` 2166, 2172, 2211, 2241; `cityroasters`
  6644243988542; `hippocafe` 77, 83, 89, 107. A product whose options state no
  weight but whose name or weight label states the pack (22: `kavaoliver`'s 250
  g tins and one `coffeespot` set) is priced at the default option, else the
  first; none of the 22 moves.
- 34 products keep their price but lose `original_price`: it belonged to another
  option (`cafemontana` 27: `115` stored 506 Kč, the 500 g option's
  struck-through price, beside its 250 g price of 253 Kč) or to none the page
  names (`kafista` 5, `melodyroastery` 1, `vrescaffe` 1). Each option's own
  struck-through price is now read from Shoptet's variant data, Shopify's
  `compare_at_price` and WooCommerce's `display_regular_price`.
- Removed: Shopify's `_cheapest` and the price it put on the discovery
  reference, which no parser read, and WooCommerce's `_cheapest_variant_price`;
  both fell back to the first priced option, which the chooser replaces whenever
  options differ in price.
- `price_history`: the next crawl records each of the 450 products at its new
  price, so the series jumps by one day for every product that moved (the
  largest, `danielasroastery/162`, by 860 Kč/kg). The jump is recorded here and
  in `deploy/notes/172-prices-take-the-250g-option-at-the-next-crawl.md`; it is
  neither reset nor flagged, as decided on #172, because nothing on the site
  reads price history yet and a reset would destroy the only record. No
  migration.

## 0.14.3 (2026-10-22)

### Fixed

- An option whose size value states several bags now stores their total weight
  (#250). `mohaji`'s `3x 1kg` was stored at 1000 g for a price that buys 3 kg,
  so its per-kilogram figure was three times too high; it now stores 3000 g.
  The owner's rule: a multiplied value (`3x1000g`, `3x 1kg`, `4x200 gramov`,
  `2 x 200 g`, `10x 500g`) or a sum of one size (`500g+500g`, `200g + 200 g`)
  stores the total, and a single size restated (`1000g ( 1Kg)`) or a total that
  reconciles with its parts (`1000g (4x250g)`) keeps that size. A sum is read
  only when every part is the same size, so `1 kg + 250 g` reads as before. One
  function, `normalize.parse_option_grams`, is used by every reader of an
  option's weight: Shoptet's keyed size value, combined-select label and
  positional label, WooCommerce's variation labels on both the API and HTML
  paths, Shopify's variant title (`grams` still wins) and the bespoke shops'
  `package`. `parse_weight_grams` and the product-name rules are unchanged.
  Re-parsing the 2 621 cached Shoptet pages moved 65 variants in 7 shops and
  no price, currency, availability or label: 48 gained a total (`ambere` 22,
  `coffeespot` 2, `johnnycoffee` 2, `lighthousecoffee` 3, `melodyroastery` 1,
  `mohaji` 16, `zhanecafe` 2), and 17 whose total exceeds the 5 000 g
  plausibility limit (`mohaji`'s `6x 1kg`, `melodyroastery`'s `20x 500g`) now
  store no weight instead of one bag's. Shopify's title fallback and the bespoke shops' labels pass through the same
  limit, so they store no weight there too. A live crawl of every WooCommerce and
  Shopify shop, `coffeein`, `fathers` and `nordbeans` moved 10 variants:
  `ciernaperla` 8 (`2x 250g zrnková` 250 g to 500 g, `3x100g` 100 g to 300 g)
  and `longberry`'s two `10x1kg` to no weight. Through the existing precedence 7
  products change `weight_g` and `price_per_kg` at the next crawl: `ambere` 6
  (`153` per-kilogram 1 458 to 729 Kč) and `lighthousecoffee` 1 (`480`, 167.20
  to 41.80 Kč).

## 0.14.2 (2026-10-22)

### Changed

- Pins `coffee-contracts` to `v3.3.0` (#251), which adds ten fields to
  `coffee.state`: `description`, `origin_farm`, `origin_producer`,
  `origin_washing_station`, `altitude_max_m`, `body`, `acidity`, `sweetness`,
  `bitterness` and `brewing_methods`. This repository publishes none of them yet,
  so every event carries each at its default (`null`, and `[]` for
  `brewing_methods`) on the crawl, delisting, retire and republish paths alike.
  Nothing a consumer reads changes: the stored `brewing_methods` and `body` can
  still hold values that `check` refuses, and `coffee-api` and `coffee-cupper`
  drop a message that fails it. Each field is released, from its column, by its
  own pull request (#252 to #255). No migration, and nothing to do on the server.

## 0.14.1 (2026-10-22)

### Fixed

- A Shoptet variant's size now comes from the parameter value its own key names,
  not from its position among the offers or from the sku suffix (#236). Shoptet
  keys every variant of a per-parameter product by the values it combines
  (`250-1838-252-1746`) and states each key's sku in the code spans and in the
  variant data the page ships, so an offer is matched to its key through its sku
  and named by the `parameterValueId[N]` select option or radio-button label
  that key points at. The label is now the values (`250 g / Zrnková káva`)
  instead of the sku, and the weight is the size axis's value. `botacoffee`'s
  115 Kč option is a 70 g pack that the page names in a hidden radio label; it
  was stored with no weight, and the product's 115 Kč was divided by the 250 g
  of the pack beside it. The sku suffix, and the positional pairing of offers
  with the weight select, stay only for an offer whose key the page does not
  state and for a page that states no key at all. A crawl on 2026-10-21 over the
  96 live Shoptet shops moved 2 106 of 11 132 variants in 20 shops and no price,
  currency or availability: 1 878 gained a weight, 228 changed one, none lost
  one (`belkocoffee` 693 was stored at 500 g for what the page sells as 250 g in
  a Turek grind, `donfranko` 462's `/130` at 250 g where the page states 125 g,
  and `pepecoffee`'s `/250` skus at 250 g where the page states 200 g). Through
  the existing precedence 52 products change `weight_g` (26 gain one) and 69
  change `price_per_kg` (43 gain one) at the next crawl; variants with no weight
  fell from 2 660 to 782 across the catalogue. The shops with a combined
  `priceId` select (`labcafe`, `vrescaffe`, `melodyroastery`, `angrybeans`) read
  exactly as before.

## 0.14.0 (2026-10-22)

### Changed

- `brewing_methods` now holds only `espresso`, `moka`, `filter`, `french_press`,
  `aeropress`, `turkish`, `automatic` and `cold_brew`, in the order a page first
  names them and without repeats (#242). It used to store the shop's own words, so
  one method appeared as `espresso`/`Espresso`/`espreso`/`Domáce espresso`, a
  bracketed list broke into `Filter (chemex` and `V60)`, and a fifth of the items
  were grinds (`zrnko`, `Zrnková káva`, `Celá zrna`). `fathers` stores its
  subcategory slug through the same mapper, so `filtr` is `filter`.
- Every method an item names is kept, so `espresso (automat)` is `espresso` and
  `automatic`, and `Mletá káva na filter (V60` is `filter`. The spellings are in
  `labels/terms.py` and are matched at the start of a word, so `džezvu`, `espressa`
  and `na turka` read too.
- Nothing is guessed. A grind with no method, and a word that could be either of
  two methods, names nothing and is dropped: `zalévaná`/`zalievaná` (pour-over or
  Czech turek), a bare `kávovar` (drip or espresso machine) and `alternativní
  příprava`. So are `cappuccino` and `vakuum pot`, which are outside the eight. An
  item that negates a suitability statement (`nevhodné`, `není vhodná`, `ne pro`,
  `nelze`, `nehodí se`, `nepoužívejte`, `není určena`, `nedoporučujeme`,
  `neodporúčame`, `not suitable`) is dropped whole, and so is one that names a
  capsule or instant product (`Dolce Gusto espresso kapsle`, `Instant espresso`),
  so a method a shop rules out, or that belongs to another product, is never
  stored. No stored item carries a negation yet.
- An item of five words or more used to be dropped as a sentence; that limit is
  gone, because the closed set is what keeps prose out, and a sentence now
  contributes the methods it names (`Kávu lze použít na espresso` is `espresso`).
  The #211/#213 sentence tests now expect those methods, because the vocabulary is
  closed and a sentence can no longer be stored as text.
- On the 2026-10-17 local crawl 7 196 stored items from 454 distinct strings give
  6 207 items under the eight values, and 108 strings (989 items) name no method.
  1 907 coffees had a list; 50 of them (18 of those at `coffegarden`, whose only
  item was `zrnková`) now have none.
- `roast_profile` is untouched: it is still read from the shop's own brewing
  label, not from this list.
- No consumer reads `brewing_methods`: it is not in a tagged `coffee-contracts`
  release (this repository pins `v3.2.0`), and `coffee-api`, `coffee-cupper`,
  `coffee-broker` and `coffee-web` do not read it, so no consumer saw the old
  meaning and the number is a minor. Rows change on each coffee's next crawl.

## 0.13.3 (2026-10-21)

### Fixed

- A taste score a shop states out of a number other than 5, or with a decimal
  point, is now rescaled onto the 0-5 scale instead of being stored as if it
  were out of 5 (#241). `bar` took the first integer of the value, so
  `penerini` `ACIDITA 1/3`, `HOŘKOST 2/3` and `SLADKOST 3/3` were stored as 1, 2
  and 3 (now 2, 3 and 5), `nejkafe` `SLADKOST 5/10` as 5 (now 3), `nejkafe` `TĚLO
  8/8` and `HOŘKOST 7/10` as `NULL` (now 5 and 4), and a `nejkafe` acidity of
  `1,5/5` or `2.5/5` as 1 or 2 (now 2 or 3). A fraction `a/b` with 3 <= `b` <= 10
  and no unit (`g`, `kg`, `ml`, `l`) after it is scored `a * 5 / b` rounded half
  up and wins over an intensity word in the same text; with `a` above `b` it is
  `NULL`, and a zero `b` is `NULL` too (`6/5`, `4/3`, `1/0`). Any other fraction is
  ignored and the value is read as before, by its first integer from 0 to 5, else
  its intensity word: a date such as `10/2024`, a harvest year such as `2023/24`
  and a ratio such as `1/2 kg` (`vysoká, sklizeň 2023/24` is 4). Percentages stay
  `NULL`, and `taste_scale_max` stays 5. Half up also moves a `0,5/5` or `0.5/5`
  from 0 to 1: seven `nejkafe` acidity scores worded "Absolutně minimální až
  nulová", "Absolutně nulová", "Téměř nulová" or "Téměř žádná" go from 0 to 1,
  while a value stated `0/5` stays 0. On the 2026-10-17 local crawl 79 stored
  scores change, at 75 coffees: `nejkafe` 76 (acidity 72, body 2, bitterness 1,
  sweetness 1) and `penerini` 3 (acidity, bitterness and sweetness, one coffee).

## 0.13.2 (2026-10-21)

### Fixed

- A single altitude written with a dot as the thousands separator is now read
  as thousands (#240). `1.200 m.n.m.` was stored as 200 m, `1.500 m.a.s.l` as
  500 m: the number pattern ended at the dot, so only the three digits after it
  were read. A local crawl of 2026-10-17 had 15 rows of 11 distinct texts stored
  this way, every one 1000 m or more too low (`1.700 m.n.m.` 700, `1.650 m.n.m.`
  650, `1.903 m.a.s.l.` 903), and `altitude_min_m` is in the published
  contract. Each now stores the figure it states (1700, 1650, 1903), with
  `altitude_max_m` equal to it. Ranges such as `1.500 - 2.000 m.n.m.` were
  already read correctly and do not change. A comma is not read as thousands:
  `1,800 m.a.s.l.` (11 rows of 3 texts) still stores 800, because a comma can be
  a decimal in Czech and Slovak. A coffee's stored altitude changes at its next
  crawl.

## 0.13.1 (2026-10-21)

### Fixed

- Variant prices at `nordbeans` and `angrybeans` are now the price the page
  charges a consumer, VAT included, as the product price beside them already
  was (#235). A crawl on 2026-10-21 found 63 variant prices of 34 coffees stored
  without VAT (`nordbeans` 41 of 21, `angrybeans` 22 of 13), mostly 12 % under
  the page: 334.82 for a bag the page sells at 375. `nordbeans` reads each
  variant from the package-size switcher, which states the price with VAT,
  instead of from the GA4 map, which states it without; a variation with no
  switcher entry now has no price rather than one without VAT. A Shoptet product
  whose weights live in one combined select takes each variant's price from the
  matching microdata offer when the offers and the options line up, because
  `angrybeans` displays prices without VAT in the select (`250 g (258 Kč)`)
  while the offer and the page say 289 Kč. When they do not line up the price
  still comes from the option text.

## 0.13.0 (2026-10-20)

### Added

- The catalogue event carries `pack_group_key` (#225), read from the stored
  column, so the key that coffee-web#172 needs to leave the same coffee out of
  its similar coffees reaches consumers. A crawl's event and the republish of the
  row it wrote carry the same value, and a row whose stored key is NULL
  publishes `null`. The value is opaque: a consumer compares it for
  equality and never parses it, and it is never the empty string, which the
  contract's schema refuses. It does not identify a coffee across shops.
- `pack_group_key_source` stays in the store and never goes on the wire: a
  consumer has no use for the version of the rule that built a key.

### Changed

- Pins `coffee-contracts` `v3.2.0`, the release that adds the field to
  `CoffeeState`. The wire version is still `v2` and the subject is unchanged. A
  consumer still on `v3.1.0` drops the field it does not know, so the order the
  two deploys happen in breaks nothing.

A key reaches a consumer at each row's next crawl after this deploy and after
that consumer's own move to `v3.2.0`, not before: consumers keep only an event
strictly newer than the state they hold, so `republish --all` does not carry it to
rows they already have. See `deploy/notes/225-pack-group-keys-reach-consumers-at-the-crawl.md`.

## 0.12.0 (2026-10-20)

### Added

- `coffee` stores `pack_group_key` and `pack_group_key_source` (migration
  `0.12.0_pack_group_key`), written by the upsert from `pack_group_key()` on
  every crawl. The key is what lets coffee-web#172 leave the same coffee in
  another pack out of its similar coffees (#225). It carries `name:v1`, the
  version of the rule that built it, because a change to the rule would
  otherwise leave keys of two rules side by side and nothing could tell which
  were comparable; the same reason `product_kind` carries its source.
- `pack_group_key()` now returns None where it used to return `<site>/` with
  nothing after the slash (or `<site>/~espresso`): a name with nothing in it
  and no usable URL slug. That bare form would have put every such listing of
  a shop in one group, so the column stores NULL, and the source is NULL with it.

Rows fill on their next crawl: the migration backfills nothing, because a key
needs Python. A delisted row is never crawled again and stays NULL. Nothing
publishes the key yet: the catalogue event is unchanged, the JSONL sink and the `parse`
output carry both fields like every other column, and `pack_group_key_source`
is never on the wire. The publish is #225's own pull request, after the
`coffee-contracts` release.

## 0.11.0 (2026-10-20)

### Added

- `pack_group_key(site, name, url)` in `coffee_aggregator.pack_group` returns
  one opaque string for the listings that are the same coffee from the same
  shop in another pack, and `PACK_GROUP_KEY_SOURCE = "name:v1"` names the rule
  that built it. A shop that publishes 250 g, 1 kg and 6 kg as separate pages
  (kava.cz does) gives three listings that share one key; coffee-web#172 needs
  that to leave the same coffee out of its similar coffees (#225). The owner
  decided what counts as the same coffee on 2026-10-20:
  - a bundle, carton, tin or portion pack is the same coffee as the single
    bag (`BANUA Café 250 g` and `5 kg (20x250g)`; `dóza`, `plechovka` and
    `7 porcí` are removed like a weight);
  - the ground version of the same beans is the same coffee (`Illy Classico
    zrnková` and `mletá`);
  - decaf is a different coffee: `decaf`, `dekaf`, `bez kofeinu` and
    `bezkofeinová` stay in the key;
  - an espresso roast and a filter roast of one origin are different coffees:
    the roast word in the name stays, and where the name states none, the one
    roast kind the URL path states (fathers' `kava/espresso/…` against
    `kava/filtr/…`) is appended as `~espresso` or `~filter`; the delimiter is
    `~` because a `#` is cut off when the key travels in a URL query.
- A name with nothing left but roast words, or nothing at all (kmen's four
  coffees all named `filtr`, two named `esko`, the Czech short form of
  espresso, which is a roast word here), takes its key from the last segment of the URL
  path instead, and an unparseable URL counts as no URL. A digit before a
  weight is kept (`n°4 250 g` and `n°3 250 g` stay apart).
- Nothing stores or publishes the key yet: the column is #228 and the event
  field is #225, so no stored row and no consumer changes with this release.
- Measured on the 17 October local snapshot (3 773 rows): 346 groups holding
  918 rows, against 355 groups and 934 rows for the investigation's first
  draft, which kept ground words and had no roast suffix. The 14 same-name
  espresso/filter twins (12 fathers, 2 ohmybean) now sit in separate groups,
  and four groups gain their ground version (kava.cz Illy Classico and
  Dallmayr Crema Prodomo, two at tokycaffe). Tins and portions join six more
  groups at kava.cz, nejkafe, kafista and zlatezrnko, and kmen's four `filtr`
  rows and two `esko` rows are six coffees.

## 0.10.0 (2026-10-20)

### Added

- The catalogue is published on the contract's v2 wire, pinned to
  coffee-contracts `v3.1.0`: every event now goes to
  `coffee.v2.catalogue.<site>.<external_id>`, which the broker keeps in the
  stream `CATALOGUE_V2`, and nothing more goes to the v1 stream `CATALOGUE`.
  Money is an integer count of minor units: `price` became `price_minor`
  (349.00 CZK is `34900`) and `price_per_kg_eur` became `price_per_kg_eur_cents`
  (24.50 EUR is `2450`). The new `price_history` field is always `[]`; both
  consumers drop it, and filling it is a separate task.
- The stored columns are unchanged: `price`, `price_per_kg_eur` and the
  `price_history` table are still `numeric`, and no migration ships. The
  conversion happens only when an event is built, and a crawl's event and the
  re-seed of the row it wrote come out identical. Over a local snapshot of 17
  October (3,773 coffees) every price and every per-kilogram price converts
  exactly.
- A price that is not a whole number of minor units — a shop's figure with more
  than two decimals — or whose currency has no known exponent (anything but CZK
  and EUR) is published as `null` with a warning naming the coffee, the field
  and the value. It is never rounded, and the coffee is still published.
- `v3.1.0` rather than `v3.0.0`: the wire is identical, but `v3.0.0` named its
  streams without the wire version, so provisioning it converted the running v1
  streams instead of adding the v2 pair; its own changelog says nobody should
  pin it.

`deploy/notes/169-v2-stream-fills-after-republish.md` is the cutover: the
consumers must already read `CATALOGUE_V2`, the outbox is drained before the
deploy, and `republish --all` afterwards fills the new stream and re-sends the
delistings the consumers missed (#223).

## 0.9.1 (2026-10-20)

### Fixed

- A delisting event now carries an `observed_at` the consumers accept. It used
  to carry the time of the last crawl that saw the coffee — the same
  `observed_at` as the state it replaced — and `coffee-api` and `coffee-cupper`
  keep an event only when it is strictly newer than what they hold, so both
  threw every delisting away without a word, from a crawl and from `retire`
  alike. A delisting is now stamped with `delisted_at`, the moment the crawl
  found the coffee gone (#223). A listed coffee's event, crawled or re-seeded,
  carries exactly the `observed_at` it did before. This changes only delistings
  from here on: the ones already lost are still listed in both consumers, and
  `deploy/notes/223-count-the-delistings-consumers-missed.md` says how to count
  them.
- `republish --all` now also re-sends delisted coffees, as delisted, so a
  consumer that missed a delisting is corrected by the re-seed and the stream
  holds every coffee ever seen in its latest state — which grows the stream and
  every consumer's store by the number of delisted rows in `coffee` (#223).
  It used to send only the listed ones, on the reasoning that a delisted coffee
  re-seeded was pointless; that held only while no consumer had missed one.

## 0.9.0 (2026-10-18)

### Added

- `coffee-aggregator retire --site <shop>` delists everything a shop that has
  stopped selling still has in the catalogue, and queues one `coffee.v1` event
  per row in the same transaction as the stamp (#214). The crawl cannot do this
  and is not being taught how: a run that discovers nothing delists nothing,
  because a 404 on a category page is not evidence that the products are gone.
  Two things stand between the command and a healthy shop — it refuses any shop
  whose config does not carry a `disabled` reason, so switching the shop off in
  a pull request is the first half of retiring it and a mistyped id reaches
  nothing; and without `--yes` it prints the rows it would delist and writes
  nothing. Nothing is deleted: `delisted_at` is a stamp, and the upsert clears
  it again, so a shop that comes back is restored by crawling it.

### Changed

- `goodtimes` is switched off rather than deleted. `goodtimes.coffee` still
  answers but its WordPress install is gone — no Store API, no sitemap, no
  category page — and what it serves is a notice that the roastery is now
  Rooster's Corner at `roosterscorner.coffee`, selling to businesses on enquiry
  with no prices and no cart (#214). The config file stays so that what was
  retired and why is on the record and re-adding it next year is a decision
  rather than an accident, and its saved pages go on regressing the WooCommerce
  parser. Its three stale rows, last seen on 2026-10-14, are **not** delisted by
  this release: the version moves no stored row, and
  `deploy/notes/214-goodtimes-is-retired-by-hand.md` says what to run. The
  roastery's new site is a separate question, ticketed against #209.

## 0.8.0 (2026-10-18)

### Added

- BONTÉ COFFEE (`praziarenbonte.sk`), a Nové Zámky roastery and café, is
  crawled through the WooCommerce Store API (#206). It brings 38 roasted
  coffees, every one sold as a 125 g bag at 7.90 EUR, so the whole shop stores
  one price and one weight. 24 of the 38 name their country (7 Brazil, 3
  Guatemala, 2 Colombia, 2 Ethiopia and ten more one apiece) and 2 are
  recognised as decaf. What is *not* recovered is the species split and the
  roast: all 38 products state an arabica/robusta ratio and 35 sit in the
  shop's light-roast category, and the parser stores neither, because it reads
  species only from an attribute and roast only from a label. Those are parser
  gaps shared with every other shop, not this config's to close. Only the
  coffee category (id 71) is crawled: the café's cakes, teas and gift
  boxes share the same WooCommerce install.

## 0.7.2 (2026-10-18)

### Fixed

- A WooCommerce detail page's headline price was read from the first `.price`
  element below the product wrapper, and this theme renders the
  related-products carousel *inside* that wrapper — so the number stored was a
  neighbouring coffee's. `ebenica` is the only shop on `mode = "html"` today,
  and `Guatemala Huehuetenango` was stored at `4.49 €`, the low end of
  `Colombia Felice Medellin`'s range, for a coffee whose single purchasable
  option is 220 g at `11.90 €`. The price is now taken from the first `.price`
  outside every nested `li.product` card; where the theme renders no price of
  its own at all — which is this page — the cheapest option the variation form
  states answers instead, the same headline a variable product already gets on
  the Store API path. That matters beyond one shop: `mode = "html"` is the
  fallback the other 46 WooCommerce shops drop to when `/wp-json/` stops
  answering, and a fallback that quietly reports a neighbour's price is worse
  than one that fails (#173).

## 0.7.1 (2026-10-18)

### Fixed

- A `brewing_methods` item now has to carry a letter and run to at most four
  words, so a sentence a roastery wrote about the drink is no longer stored
  beside `Espresso` as if it named a way of making the coffee (#211). Over the
  184 products the fixture corpus parses, three stored values go: a 13-word
  recommendation at `birdsong`, a 7-word one at `viemcoffee` and a 5-word one
  at `valasska`. Two of those three products keep the real methods that stood
  beside the sentence (`valasska` keeps `pákový kávovar`, `frenchpress` and
  `turek`), one is emptied because the sentence was all it had, and no real
  method is lost: the longest surviving item in the corpus is
  `mletá na zalévanou kávu`, exactly four words. 45 of the 152 live shops have
  fixtures, so this is what was measured on those; the junk is a per-shop
  idiom and the corpus does not support a projection onto the live catalogue.
  `roast_profile` is untouched — the filter runs where the list is built, not
  in `plausible`, which `parse_roast` also reads.

## 0.7.0 (2026-10-18)

### Added

- `update.sh` prints the deploy notes before it builds. The folder's rule has
  always been that a pull request needing a step on the server leaves a note
  beside the deploy script and the script reads them out; this one never did,
  so `164-crawl-start-needs-a-sudoers-line`,
  `174-the-seen-on-index-is-built-at-deploy` and `179-coverage-starts-empty`
  are all still pending on the live server and had to be read aloud from the
  repository by hand tonight. Which notes are new is decided by the commit the
  last successful run recorded in `/var/lib/coffee-aggregator/deployed`, not by
  the range this script pulled: `coffee-observability` pulls the checkout
  before it calls this script, so that range is empty every time. A server with
  no recorded deployment is shown every note, and so is one whose state
  directory it cannot write — that case warns on stderr and continues, because
  the step that prints the notes must never be the step that stops a deploy.
  Needs `/var/lib/coffee-aggregator` on the server (deploy note
  `168-deploy-notes-need-a-state-directory`).

## 0.6.0 (2026-10-18)

The crawl now records what each shop published, so a field that stops being
extracted is reported instead of being silently overwritten (migration
`0.6.0_crawl_coverage`).

### Added

- `crawl_coverage` stores one row per shop per field per crawl day: how many
  beans the night re-read, how many of them carried the field, and the
  aggregator version that measured it. Until now `coffee` was upserted in
  place with no `COALESCE`, so a rotted selector overwrote yesterday's value
  and left nothing behind saying it ever held one. On 2026-10-17, over 152
  shops and 3 773 rows, two shops had lost a field with nothing reporting it:
  `ajvencoffee` went 70% → 0% on `origin_country` over 11 rows (#176, a
  tagline that made every coffee a blend) and `ohmybean` 65% → 37% over 27.
  Row counts were up, prices were right and no page failed, so `no-products`,
  `write-drop`, `parse-gap` and `new-failures` all stayed silent, correctly.
- 24 fields are counted, each by its own definition of known. Three of them
  are the reason the table exists: `roast_level`, `process_method` and
  `roast_profile` can never be NULL, because `sinks/records.py` writes the
  string `'unknown'` for a `StrEnum` that knows nothing — 1 988, 1 802 and
  1 397 rows of the same crawl — and `variety` and its five jsonb siblings
  land as `'[]'`, 2 098 rows of it. A `count(col)/count(*)` metric reports
  100% for all of them for ever, so the four fields most likely to rot are the
  four it cannot see. `raw_attributes` is excluded and documented in the
  migration: it is a jsonb object, `jsonb_array_length` raises on it, and the
  write sits inside a handler that swallows everything, so one copied formula
  would lose a whole night's coverage without a line in the log.
- `report` emits the `coverage-drop` finding that `db/report.py` had been
  documenting as impossible since it was written. It is a shop against its own
  recent median, per field, and never a catalogue-wide share: `ajvencoffee`
  losing a field on 10 rows moves a 3 773-row catalogue by 0.19 points, under
  any threshold anybody would set. A fall of 20 percentage points or more
  reports, which is p99 of the 17-day distribution over 1 538 shop-field pairs
  (p50 0.0, p90 3.7, p95 8.3, p99 22.2) and finds 5 events over those days; 10
  points adds twelve single-digit-row wobbles and 30 would miss `ohmybean`'s
  28. Guards: at least 8 rows, because a fill rate over 8 moves 12.5 points per
  row, and a baseline the shop actually had — a field it never published is a
  ceiling, not a drop. A shop losing three or more fields is one finding, not
  three. Every finding names the aggregator version of tonight's rows and of
  the baseline, because three of the five falls measured were our own deploy
  (#97 moving grind words out of `brewing_methods`, at `grinders`,
  `bartcoffee` and `kavaoliver`) and an alert that cannot tell a release from
  a rotted selector is muted inside a month.

### Changed

- `coverage-drop` was described as catalogue-wide in `reporting/finding.py`,
  in the README's list of kinds and in the renderer fixture, all written
  before the 0.19-point measurement existed. All three now describe the
  per-shop finding that ships.
- A row is written only for a run that finished `complete` and `discovery_ok`,
  and it counts the rows the crawl re-read (`last_seen_at >= started_at`)
  rather than the rows not delisted. `mark_delisted` is skipped on a partial
  or unhealthy night, so the alternative would dilute the fill rate with rows
  nobody re-read and invent a drop belonging to the delisting that did not
  run.

## 0.5.0 (2026-10-18)

The three bespoke shops now say which roastery their coffee is from, so 172
rows that carried `roaster = NULL` get a name on the next crawl.

### Added

- `SiteAdapter.roaster` says the roastery every row of a shop is from, and is
  `None` for a shop that sells more than one. `coffeein`, `fathers` and
  `nordbeans` are each a single roastery and declare it: `Coffeein`,
  `Father’s Coffee Roastery` and `Nordbeans`. The strings are the ones the
  shops' own pages publish — `fathers` and `nordbeans` carry them in their
  JSON-LD `Brand` node, which a test now checks the declaration against, and
  `coffeein` publishes no brand node at all, so its value is declared rather
  than confirmed. The apostrophe in `Father’s` is U+2019, as the shop writes
  it; `normalize.fold` does not fold it to an ASCII `'`, so the spelling
  decides `roaster_key`.
- 172 rows at those three shops are what this fills, by the 17 October crawl's
  count. No migration and no backfill: `roaster` and `roaster_key` are both
  updatable, so the rows change when the next crawl rewrites them, and a row
  the crawl never reaches again keeps `NULL`.
- The 864 WooCommerce rows stay `NULL` on purpose (#181). A WooCommerce shop's
  name is the shop's, not a roastery's, and many of those shops resell other
  people's coffee — filling the column from a shop name would turn 864
  missing values into 864 wrong ones, and a wrong `roaster_key` merges coffees
  that are unrelated and splits ones that are not.

## 0.4.1 (2026-10-17)

The nightly report no longer reads a year of prices to find two days of them
(migration `0.4.1_price_history_seen_on`).

### Changed

- `price_history` gains an index on `(seen_on, site, external_id)`. The report
  is the only thing in the repository that reads the table, and it asks for a
  window of days — but of the five indexes the table had since `0001`, three
  led with `site`, the primary key was on `id`, and the BRIN was on `seen_at`,
  which is a different column from the generated `seen_on`. So every night's
  two-day window scanned all 1 241 000 rows. Measured on Postgres 16 over a
  generated year of crawling at the real shape: 18 126 buffers (~142 MB) and
  33 ms before, 210 buffers and 11 ms after. The index is 48 MB, and the read
  it replaces grew with every night of history — 139 MB at one year. The 210 is
  for a heap in the order the crawl writes it, a night's rows together; over a
  heap clustered by product instead it is 3 512, still well under the 6 000 the
  issue asked for.
- Nothing is dropped. `price_history_day_idx` reports `idx_scan = 0` and is
  still the arbiter of the daily upsert's `ON CONFLICT (site, external_id,
  seen_on)`, which does not increment that counter; #175, which proposes
  dropping two other indexes, is deliberately not part of this.
- The index does not exist until the migration runs on the server, and the
  report keeps scanning until it does — see
  `deploy/notes/174-the-seen-on-index-is-built-at-deploy.md`.

## 0.4.0 (2026-10-17)

Every `crawl_run` row now records the aggregator version that produced it
(migration `0.4.0_crawl_run_version`), so a field that collapses overnight can
be attributed.

### Added

- `crawl_run.version` holds what `coffee-aggregator --version` prints, beside
  the `command` that was already stored. Between the 30 September and
  17 October crawls five shops lost most of a field; three of those five were
  our own deploy — #97 moved grind words out of `brewing_methods` at
  `grinders`, `bartcoffee` and `kavaoliver` — and the other two were shops
  changing their pages. Nothing stored told them apart. Two distinct versions
  over a window of runs now say a deploy sat between the two nights.
- The column is nullable and nothing backfills it: rows written before this
  release keep `NULL`, which is honest about a version nobody recorded, and
  the stamp starts with the next crawl. `crawl_finding` is deliberately not
  stamped — `report --day <past date>` is a separate invocation and would
  record the version that summarised a run rather than the one that performed
  it.

### Fixed

- `test_every_migration_is_numbered_once_and_in_order` was still asserting the
  pre-#145 invariant, a plain lexical sort and a four-digit prefix. Both fail
  on any version-named migration, and this is the first one, so it now checks
  what is actually true: the padded names come first and are numbered 1..n
  without a gap, then the version-named ones ascend by parsed version.

## 0.3.5 (2026-10-17)

The session-start hook and its learnings now come with the repository, so an agent working in its own git worktree gets the team's trail notes too.

### Changed

- `.trail/` (the hook, its README and its ignore file) and `.claude/settings.json` are tracked. Before, they were untracked, and a worktree checkout contains only tracked files, so every worktree agent started without them.
- The `.gitignore` rule for `.claude/` now ignores only `.claude/settings.local.json` and `.claude/worktrees/`, so a worktree stays out of `git status`.

## 0.3.4 (2026-10-12)

The chocolate-covered rule stops filing a coffee that comes with a chocolate bean as `food`.

### Fixed

- `Káva pro maminku + kávové zrno v hořké čokoládě` is a coffee sold beside a chocolate-covered
  bean, not one, so it is no longer `food`. It stays undecided, as `beans` from its label.
- `Bundle Brasil Doce Samba + Zrno v mléčné čokoládě` is a bundle, and its chocolate bean comes
  after the `+`, so it is no longer `food`. Its stored `sampler` label is unchanged.

The chocolate rule still files chocolate-covered beans and bars as `food`, such as `Kávová zrna v
hořké čokoládě a kakau` and `Cuba Serrano v mléčné čokoládě`. No stored row changes until a crawl
reaches it.

## 0.3.3 (2026-10-12)

### Fixed

- `deploy/update.sh --crawl` runs as the user that owns the checkout, not as root. Only starting
  the crawl unit needs root, and it now runs through `sudo -n`, which needs the sudoers line in
  `deploy/README.md`. Without that line the script exits 1 and prints the command to run by hand,
  where it used to report a crawl that never started.

## 0.3.2 (2026-10-12)

The kind rules place three more kinds of non-coffee product. A stored row gets its kind on the
next crawl that reaches it, and no stored row changes until then.

### Fixed

- The `Kafe BOX` gift boxes, which hold coffee together with brewing equipment, are now `kit`. An
  empty `Kafe BOX` with a wooden lever is `equipment`.
- A set of coffees named `set`, such as `SUPER OCKO set` and `MEGA MAMA set`, is now `sampler`.
- A book about American football, `Manuál amerického fotbalu`, is now `merch`.

The catalogue view hides these only once `coffee-api` reads `product_kind` (coffee-api#69).

## 0.3.1 (2026-10-12)

Six `kava.cz` rows that stored no country take one on the next crawl that reaches them. No
stored row changes until then.

### Fixed

- `Indonésie`, the Czech spelling, now resolves to `ID`. Only the Slovak `Indonézia` was in the
  country table, so a Czech product name with no other country term stored `NULL`.

## 0.3.0 (2026-10-12)

No stored row carries pictures until the next crawl republishes it. The events were emitted
without the field and the stream is compacted per subject, so consumers see pictures after the
next crawl, not at deploy. A coffee that no crawl reaches keeps its earlier event until
`republish --all`, which publishes the pictures from the row.

### Added

- The `coffee.state` event carries `images`: the shop's own picture URLs, in the order the page
  lists them, from the `images` column the crawl already fills. A coffee whose page had none
  publishes `[]`, not `null`. The URLs are passed through, not downloaded or re-hosted. The
  pin moves to `coffee-contracts` `v2.5.0`, which defines the field.

## 0.2.1 (2026-10-11)

The six fields reach the stream on the next crawl that reaches a coffee. A coffee that no
crawl reaches keeps its earlier event until `republish --all`, which now publishes the same
six values the crawl does.

### Fixed

- Every crawl's `coffee.state` event carries `first_seen_at`, `decaf`, `product_kind`,
  `product_kind_source`, `arabica_pct` and `robusta_pct` from the row. They were published as
  `null` (#142), which is the gap recorded under `0.1.1`. `decaf`, `arabica_pct` and
  `robusta_pct` come from the parsed coffee. `first_seen_at`, `product_kind` and
  `product_kind_source` are read back from the database inside the crawl's transaction,
  because only the database holds them.

## 0.2.0 (2026-10-11)

This entry corrects the number of the entries below it. `0.1.1` was numbered as a
patch and understated what it carried. `0.1.2`, `0.1.3` and `0.1.4` are patches in
their own right, but they were numbered on top of that understatement. No entry's text is
changed, and the numbers are not renumbered here, because a reader may already have
seen them.

`0.1.1` describes capabilities: a product kind on every row, report findings,
`availability_raw` and the image push. Those make it a minor. It also changes what
three stored values mean, which is a major only for a reader who could observe the
change, and none could (see below). So the version is `0.2.0`, one minor on top of
`0.1.4`. The jump from `0.1.4` is this correction.

`0.1.0` was set by the project's `uv init` in March 2025, and nothing moved it
until the changelog was added on 11 October. The version did not change across the
rebuild in September 2026, and the history behind every entry is in `git log`.

### Stored meaning changed, safely

- `decaf`, `is_blend` and `specialty_grade` store `NULL` where they used to store
  `false` for "the page said nothing" (#89, #104, #116). A stored `false` had
  meant *unknown* and now asserts *caffeinated* or *single origin*. A row keeps its
  stored value until a crawl rewrites it, so until then a `false` still means
  unknown.
- No consumer could read the difference. `decaf` first reached `coffee-contracts`
  in `v2.4.0`, tagged on 11 October, the day after these merges. `is_blend` and
  `specialty_grade` have never been a contract field. No sibling repository reads
  any of the three from the aggregator's data.

### Carried from 0.1.1 to 0.1.4

- Product kind on every row, decided from the page or by a labelled seed. Report
  findings in `crawl_finding`. `availability_raw` beside `available`. The image
  pushed as `sha-<commit>` and as `main`. Decaf read from its label. Details under
  `0.1.1`.
- The migration runner orders version-named migrations by version. Details under
  `0.1.2`.
- A CI check that fails a pull request unless it moves the version, adds its
  changelog entry and raises the number. Details under `0.1.3`.
- Release tags are semantic versions, `vX.Y.Z`, and the image is named without the
  `v`. Details under `0.1.4`.

## 0.1.4 (2026-10-11)

Nothing a crawl or an operator has to do. The crawler is unchanged.

CI only. A release tag is now `vX.Y.Z`, and its image is named without the `v`: `v0.1.4`
publishes `0.1.4` and `latest`. The date form `YYYY.MM.DD` is refused, and so is any other
tag, so a tag in the wrong shape fails the image job instead of publishing nothing. Pushes
to `main` and pull requests publish as before.

## 0.1.3 (2026-10-11)

Nothing in the crawler or the database changes, and the next crawl writes the same rows.

CI only. A pull request now fails unless it moves `version` in `pyproject.toml`, adds its
entry here, or makes the version smaller than the one on `main`. Versions compare as
numbers, so `0.10.0` is after `0.9.0`.

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
