from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import pytest

from coffee_aggregator import normalize, platforms, sites
from coffee_aggregator.labels import KNOWN_FIELDS, map_label
from coffee_aggregator.platforms.shoptet import DEFAULT_LABEL_MAP
from coffee_aggregator.sites import CONFIG_DIR

if TYPE_CHECKING:
    from pathlib import Path

CONFIGS = sorted(CONFIG_DIR.glob("*.toml"))
CURRENCIES = {"CZK", "EUR"}


def load(path: Path) -> dict[str, Any]:
    """Read one shop config.

    Args:
        path: The TOML file.

    Returns:
        Its contents.
    """
    return tomllib.loads(path.read_text("utf-8"))


def ids(path: Path) -> str:
    """Name a parametrised case after its shop.

    Args:
        path: The TOML file.

    Returns:
        The file's stem.
    """
    return path.stem


# Most shops are onboarded by writing one of these files and nothing else, so
# these checks are what stands between a typo and a shop that quietly collects
# nothing. They run offline: no saved page, no network.


def test_there_are_configs_to_check() -> None:
    assert CONFIGS, "no shop configs found"


@pytest.mark.parametrize("path", CONFIGS, ids=ids)
def test_the_file_name_is_the_site_id(path: Path) -> None:
    """The registry keys on site_id; a mismatch hides the shop in plain sight."""
    assert load(path)["site_id"] == path.stem


@pytest.mark.parametrize("path", CONFIGS, ids=ids)
def test_the_shop_states_what_every_platform_needs(path: Path) -> None:
    config = load(path)

    assert config["platform"] in {"shoptet", "woocommerce", "shopify"}
    assert config["name"].strip()
    assert config["country"] in {"CZ", "SK"}
    assert config["base_url"].startswith("https://")
    assert config["base_url"].endswith("/")


@pytest.mark.parametrize("path", CONFIGS, ids=ids)
def test_the_currency_is_one_we_convert(path: Path) -> None:
    """Prices are compared across shops, which needs a currency we hold a rate for."""
    currency = load(path).get("currency")

    assert currency is None or currency in CURRENCIES


@pytest.mark.parametrize("path", CONFIGS, ids=ids)
def test_category_urls_belong_to_the_shop(path: Path) -> None:
    """A category on another host would crawl someone else's catalogue into this shop."""
    config = load(path)
    base = urlsplit(config["base_url"]).netloc.removeprefix("www.")

    for url in config.get("category_urls", []):
        host = urlsplit(url).netloc.removeprefix("www.")
        assert not host or host.endswith(base) or base.endswith(host.split(".", 1)[-1]), (
            f"{path.name}: {url} is not on {base}"
        )


@pytest.mark.parametrize("path", CONFIGS, ids=ids)
def test_a_shop_can_be_reached_without_a_catalogue_guess(path: Path) -> None:
    """Every shop must say where its coffee is, by URL or by category id."""
    config = load(path)
    has_urls = bool(config.get("category_urls"))
    has_ids = bool(config.get("api_category_ids") or config.get("api_category_slugs"))
    has_collections = bool(config.get("collections"))

    assert has_urls or has_ids or has_collections, f"{path.name}: no coffee category"


@pytest.mark.parametrize("path", CONFIGS, ids=ids)
def test_every_label_map_entry_points_at_a_real_field(path: Path) -> None:
    for label, field in (load(path).get("label_map") or {}).items():
        assert field in KNOWN_FIELDS, f"{path.name}: {label!r} points at {field!r}"


@pytest.mark.parametrize("path", CONFIGS, ids=ids)
def test_no_shop_repeats_the_shared_vocabulary(path: Path) -> None:
    """Ordinary Czech or Slovak belongs in labels.py, where every shop gains it."""
    config = load(path)
    if config.get("platform") != "shoptet":
        return
    repeated = [
        label
        for label, field in (config.get("label_map") or {}).items()
        if map_label(normalize.fold(label), DEFAULT_LABEL_MAP) == field
    ]

    assert not repeated, f"{path.name}: move {repeated} into coffee_aggregator/labels.py"


@pytest.mark.parametrize("path", CONFIGS, ids=ids)
def test_the_config_builds_an_adapter(path: Path) -> None:
    """The last word on a config is whether the platform accepts it."""
    adapter = platforms.build_from_config(path)

    assert adapter.site_id == path.stem
    assert adapter.base_url.startswith("https://")


def test_every_config_is_registered_and_unique() -> None:
    sites.load_all()
    registered = {site.site_id for site in sites.all_sites()}
    # A `disabled` config is skipped on purpose and is not a load error; every
    # other one has to be there.
    live = {
        path.stem for path in CONFIGS if not tomllib.loads(path.read_text("utf-8")).get("disabled")
    }

    assert not sites.load_errors, sites.load_errors
    assert live <= registered
    assert registered.isdisjoint({path.stem for path in CONFIGS} - live)


@pytest.mark.parametrize(
    ("site_id", "listing"),
    [
        ("ciernaperla", "BIALETTI Mokka kávovar"),
        ("penerini", "Plátěná taška PENERINI s kávovým motivem"),
        ("penerini", "White labeling - káva pod vlastní značkou"),
        ("theminers", "Aeropress Paper Filter (350pcs)"),
        ("theminers", "Hario V60-02 Filters (100pcs)"),
        ("theminers", "Moccamaster Paper Filters (100pcs)"),
        ("theminers", "Solo Filter Daily (50pcs)"),
        ("theminers", "The Miners Espresso Cup by Mindset"),
        ("zlatezrnko", "Zlaté Zrnko – Papierový pohár 110ml na espresso 50ks"),
        ("zlatezrnko", "Zlaté Zrnko – Linda pistáciová – kokosové tyčinky s pistáciami 40g – 5ks"),
    ],
)
def test_a_shop_marker_catches_the_listing_it_was_measured_against(
    site_id: str,
    listing: str,
) -> None:
    """A per-shop marker is only ever added for a listing seen in the catalogue;
    this pins the listing so a later edit cannot quietly stop matching it."""
    assert platforms.build_from_config(CONFIG_DIR / f"{site_id}.toml").is_ignored(listing)


@pytest.mark.parametrize(
    ("site_id", "listing"),
    [
        ("ciernaperla", "DARČEKOVÉ BALENIE  CUBA Venchi cigara, 250g pražená káva 100% ARABIKA"),
        ("theminers", "Ethiopia Kello Siko #3"),
        ("theminers", "Office Blend"),
        ("zlatezrnko", "Káva Zlaté Zrnko – Káva na filter Tanzánia 250g"),
        ("zlatezrnko", "Káva Zlaté Zrnko – Peru – “Kakao a gaštan”"),
    ],
)
def test_a_shop_marker_spares_that_shop_s_coffee(site_id: str, listing: str) -> None:
    """A marker that also matches coffee does not hide it: the run stops seeing
    the product, the delisting pass stamps it, and it leaves the catalogue."""
    assert not platforms.build_from_config(CONFIG_DIR / f"{site_id}.toml").is_ignored(listing)


def shop_key(base_url: str) -> tuple[str, str]:
    """Reduce a base URL to what identifies the shop behind it.

    Scheme, a ``www.`` prefix and a trailing slash are spellings of one
    address, so they are dropped. The path is kept: every shipped config today
    owns a whole host, and the day one shop lives under another's path this
    must not call the two the same shop.

    Args:
        base_url: A config's ``base_url``.

    Returns:
        The host without ``www.`` and the path without its trailing slash.
    """
    parts = urlsplit(base_url.lower())
    return parts.netloc.removeprefix("www."), parts.path.rstrip("/")


def test_no_two_live_configs_crawl_one_shop() -> None:
    """Two ids on one base_url crawl the same catalogue into two sites.

    This happened: `valasska`/`valasskaprazirna` and `coffeeport`/
    `lighthousecoffee` were each one shop configured twice, and the 2026-09-30
    snapshot counted 24 and 20 of their products a second time. A `disabled`
    config is exempt because it is absent from the registry and crawls
    nothing — that is how the loser of such a pair is retired while its saved
    pages keep testing the adapter.
    """
    seen: dict[tuple[str, str], list[str]] = {}
    for path in CONFIGS:
        config = load(path)
        if config.get("disabled"):
            continue
        seen.setdefault(shop_key(config["base_url"]), []).append(path.stem)
    shared = {host: shops for host, shops in seen.items() if len(shops) > 1}

    assert not shared, f"one shop, several live configs: {shared}"
