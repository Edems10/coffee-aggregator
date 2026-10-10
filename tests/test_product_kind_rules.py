from __future__ import annotations

import pytest

from coffee_aggregator import product_kind, product_kind_rules

KIND_CASES = [
    ("Zlaté Zrnko – Papierový pohár 110ml na espresso 50ks", "144569", "equipment", "paper-cup"),
    ("Aeropress Paper Filter (350pcs)", "687", "equipment", "paper-filter"),
    ("Sandwich Pack (750pcs)", "2163", "equipment", "piece-count"),
    ("Mokka kávovar", "7447", "equipment", "machine-or-cleaner"),
    ("Urnex Rinza - 1000ml", "699", "equipment", "machine-or-cleaner"),
    ("The Miners T-Shirt", "1601", "merch", "clothing"),
    ("Elephants kšiltovka", "3271", "merch", "clothing"),
    ("Sada nálepek: filtr", "25150", "merch", "sticker"),
    ("Plátěná taška PENERINI s kávovým motivem", "7455", "merch", "bag"),
    ("Dárkový poukaz Pražírna Ignác", "1377", "merch", "voucher"),
    ("Předplatné na 6 měsíců", "848", "merch", "subscription"),
    ("Kávová zrna v hořké čokoládě a kakau", "19342", "food", "chocolate-covered"),
    ("Porcovaný cukr 4 kg", "2990", "food", "sugar"),
    ("Zlaté Zrnko – Linda pistáciová – kokosové tyčinky s pistáciami 40g", "142817", "food", "bar"),
    ("Výběrová instantní káva BLÆK NØ.1 – Blonde Roast (60 g)", "17244", "instant", "instant"),
    ("Kávové kapsle DEAD OR ALIVE 50ks - kompatibilní s Nespresso®", "43", "capsules", "capsule"),
    ("Cold Brew Burundi 330ml", "16619", "ready_to_drink", "bottled-drink"),
    (
        "Nitro Flat White: Káva s ovesným mlékem a dusíkem (5x200 ml)",
        "17123",
        "ready_to_drink",
        "bottled-drink",
    ),
    ("Zákazkové praženie kávy", "4613", "service", "custom-roast"),
    ("Baristický kurz – u Vás doma", "757", "service", "course"),
    ("White labeling - káva pod vlastní značkou", "9303", "service", "white-label"),
    ("Káva s vlastním logem", "1192", "service", "white-label"),
    ("TEST Product", "159451", "test", "shop-test-product"),
    ("Kávové scrub mýdlo Penerini x Naturinka", "8754", "cosmetics", "scrub-or-soap"),
    ("Rooibos espresso 50 g", "366", "other_drink", "rooibos"),
    ("Spirit PLUS", "spirit-plus", "not_a_product", "slug-id"),
]

COFFEE_NAMES = [
    ("Donella 250g", "147"),
    ("Terra 100g", "159"),
    ("Caprice STILE 500g", "255"),
    ("Moravský TUREK", "2199"),
    ("Káva Káva!", "1950"),
    ("KPZ Blend", "14844537995609"),
    ("Zrnko na usmířenou 100g", "2954"),
    ("Orca", "6722752774312"),
    ("Gentoo", "6722764898472"),
    ("King", "6722782134440"),
    ("AUTUMN GLOW", "119"),
    ("LEGATO", "131"),
    ("FORTE", "134"),
    ("Illy Classico zrnková káva 250g 12ks", "20398"),
    ("Bezkofeinová káva - Decaf Honduras 250g", "91"),
    ("COLD BREW", "416"),
    ("Vortex melon nitro - káva 100% Arabica", "1540"),
    ("Colombia Finca Milán Nitro Fermented 250 g", "1423"),
    ("Brasil do Chocolate", "91"),
    ("Čokoládová Kolumbie na espresso", "116"),
    ("Excelso Sugar Cane Decaf", "2078"),
    ("Moka Kolumbie Sierra Nevada", "1129"),
    ("Brazil Cerrado Dulce NY17/18 Fine Cup, zrnková káva", "390"),
    ("Mexico Emmanuel Rincon Finca La Esperanza Cup Of Excellence Farm", "5426"),
    ("Lily Ethiopia Filter 200g, FiftyBeans", "5377"),
    ("DARČEKOVÉ BALENIE, pražená káva, 100% ARABIKA, 2x250g", "4509"),
]


@pytest.mark.parametrize(("name", "external_id", "kind", "rule"), KIND_CASES)
def test_a_non_coffee_name_is_decided(name: str, external_id: str, kind: str, rule: str) -> None:
    decision = product_kind_rules.decide(name, external_id)
    assert decision is not None
    assert decision.kind == kind
    assert decision.source == f"rule:{rule}"
    assert decision.kind in product_kind.PRODUCT_KINDS


@pytest.mark.parametrize(("name", "external_id"), COFFEE_NAMES)
def test_a_coffee_name_is_left_undecided(name: str, external_id: str) -> None:
    assert product_kind_rules.decide(name, external_id) is None


def test_a_numeric_or_uuid_id_is_not_a_slug() -> None:
    uuid = "0cbecbe1-31a0-43b6-87a5-d0a7d38e8598"
    assert product_kind_rules.decide("Kolumbie - Chapata", uuid) is None
    assert product_kind_rules.decide("Kolumbie - Chapata", "384") is None


def test_an_empty_name_and_id_are_undecided() -> None:
    assert product_kind_rules.decide("", "") is None
