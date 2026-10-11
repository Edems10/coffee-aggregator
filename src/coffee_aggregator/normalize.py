from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

from coffee_aggregator.models import Processing, ProcessMethod, RoastLevel, RoastProfile

_DASHES = "‐‑‒–—―−"
_SEPARATORS = f"-_/{_DASHES}"
_TRANSLATION = {ord(ch): " " for ch in _SEPARATORS}
_DASH_TRANSLATION: dict[int, str] = {ord(ch): "-" for ch in _DASHES} | {0x00A0: " "}
_WHITESPACE_RE = re.compile(r"\s+")
_PLUS_RE = re.compile(r"\s*\+")
_NUMBER_RE = re.compile(r"\d[\d\s .,]*")
# A comma or a slash between two digits is part of one number, not a separator.
# Shops write "0,25 kg" for a weight and "75/25" for a blend ratio; splitting
# either produced a fragment that then read as a different number entirely —
# a 250 g bag as 25 kg, and "Blend 75/25 250 g" as 25250 g at 11 CZK/kg.
_LIST_SPLIT_RE = re.compile(r"(?:[;|•·∙‧\n\r]|(?<!\d)[,/]|[,/](?!\d))+")
_MAX_PERCENT = 100
_MIN_ALTITUDE_M = 100
_MAX_ALTITUDE_M = 4000
_DECIMAL_DIGITS = 2
_ISO_YEAR_MIN = 1900
_ISO_YEAR_MAX = 2100


def fold(text: str | None) -> str:
    """Lower-case, de-accent and flatten separators so tables can match.

    Args:
        text: Arbitrary shop text.

    Returns:
        A folded ASCII-ish string, or an empty string for ``None``.
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    flattened = stripped.lower().translate(_TRANSLATION)
    flattened = _PLUS_RE.sub(" +", flattened)
    return _WHITESPACE_RE.sub(" ", flattened).strip()


# A product's kind was decided from its name, so the name is what to fingerprint.
# It is folded, so a shop re-typesetting a title (case, accents, separators,
# spacing) does not send a settled product back to review: the matchers in this
# module already read names through fold, so that is the same name by the codebase's
# own definition. SHA-256 rather than hash(), which is salted per process and would
# change from one run to the next. A Unicode release that changes a decomposition
# turns a match into a miss, which costs a review and never a wrong kind.
def product_name_hash(name: str) -> str:
    """Fingerprint a product name for the kind that was decided from it.

    Args:
        name: The product name as the shop wrote it.

    Returns:
        The SHA-256 hex digest of the folded name.
    """
    return hashlib.sha256(fold(name).encode("utf-8")).hexdigest()


def dash_fold(text: str | None) -> str:
    """Lower-case and de-accent while keeping dashes, so ranges stay readable.

    Args:
        text: Arbitrary shop text.

    Returns:
        A folded string in which every kind of dash became an ASCII hyphen.
    """
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    hyphenated = stripped.lower().translate(_DASH_TRANSLATION)
    return _WHITESPACE_RE.sub(" ", hyphenated).strip()


def _first_match(folded: str, table: tuple[tuple[str, str], ...]) -> str | None:
    for needle, value in table:
        if needle in folded:
            return value
    return None


def _to_float(raw: str) -> float | None:
    """Turn a localised number such as ``1 249,50`` into a float."""
    cleaned = raw.replace(" ", "").replace(" ", "").strip(".,")
    if not cleaned:
        return None
    last_comma = cleaned.rfind(",")
    last_dot = cleaned.rfind(".")
    decimal_at = max(last_comma, last_dot)
    if decimal_at == -1:
        integer, fraction = cleaned, ""
    elif len(cleaned) - decimal_at - 1 <= _DECIMAL_DIGITS:
        integer, fraction = cleaned[:decimal_at], cleaned[decimal_at + 1 :]
    else:
        integer, fraction = cleaned, ""
    digits = re.sub(r"\D", "", integer)
    if not digits and not fraction:
        return None
    try:
        value = float(f"{digits or '0'}.{fraction or '0'}")
    except ValueError:  # pragma: no cover - defensive, regex guarantees digits
        return None
    # A few hundred digits — a mangled EAN, a leaked blob — overflow to inf, and
    # every round() downstream then raises OverflowError on that one product.
    return value if math.isfinite(value) else None


# The digit group admits spaces so "1 000 g" reads as one number, and a comma so
# "0,25 kg" does. The space after a comma is what tells the two apart: a decimal
# comma is written with no gap, a separator is written with one, so the comma in
# "10, 450g" must end the number and "450g" is the weight. Spaces also glued two
# numbers together: "75/25 250 g" became 25250 g and the coffee was the cheapest
# in the catalogue at 11 CZK/kg. A thousands separator is never preceded by a
# digit, a slash or a dash, and a second number always is.
_WEIGHT_RE = re.compile(
    r"(?<![\d/-])(\d(?:[\d\s .]|,(?!\s))*)\s*(kg|kilogram\w*|kilo|gram\w*|gr|g)\b",
    re.IGNORECASE,
)


# One multiplication only, never a sum. "1x250g + 1x500g" is an honest 750 g,
# but of 3678 products exactly two names are shaped that way and both belong to
# one shop, while 12 of the 14 names stating two sizes are that same shop's
# size axis ("250g – 500g") whose headline price is the smaller bag. Summing
# would have to overrule the guard that keeps those 12 and the grinder bundles
# right, and a wrong per-kilogram price costs more than two missing rows (#58).
_PACK_RE = re.compile(
    r"(\d{1,3})\s*[x\u00d7]\s*(\d[\d\s.,]*)\s*(kg|kilogram\w*|kilo|gram\w*|gr|g)\b",
    re.IGNORECASE,
)


#: A pack written as a count rather than a multiplication: "250g 12ks", or
#: just "36 ks" with the bag size stated elsewhere on the page.
_COUNT_RE = re.compile(r"(?<![\d.,])(\d{1,3})\s*(?:ks|kus\w*|pcs|pack)\b", re.IGNORECASE)


def parse_pack_count(text: str | None) -> int | None:
    """Parse how many packages a name says the price buys.

    ``"Illy Intenso 36 ks"`` is thirty-six tins, and the page states the size
    of one of them somewhere else. Without the count the price of the whole
    case is divided by a single tin: that read 23 196 CZK/kg against a true
    644 CZK/kg.

    Args:
        text: The product name.

    Returns:
        The count, or None when the name states none or states one.
    """
    if not text:
        return None
    match = _COUNT_RE.search(text)
    if match is None:
        return None
    count = int(match.group(1))
    return count if count > 1 else None


def parse_pack_grams(text: str | None) -> int | None:
    """Parse the total weight a package name states, multiplier included.

    ``"Six pack AMERIKA (6 x 100 g)"`` is 600 g of coffee, not 100 g, and the
    price on that page buys all six. Reading only the second number is how a
    four-pack came to be ranked as the dearest coffee in the catalogue.

    Args:
        text: Text such as ``"6 x 100 g"``, ``"12x250g"`` or plain ``"250 g"``.

    Returns:
        The total weight in grams, or None when the text states none.
    """
    if not text:
        return None
    if _PACK_RE.search(text) is None:
        return parse_weight_grams(text)
    multiplied = parse_multiplied_pack_grams(text)
    return None if multiplied is None else multiplied[1]


def parse_multiplied_pack_grams(text: str | None) -> tuple[int, int] | None:
    """Parse a spelt-out multiplication into one package and the whole pack.

    Both halves matter to a reader that has to tell a carton from a bundle:
    ``"BANUA Café 5 kg (20x250g)"`` names two sizes that are one article,
    because 20 x 250 g is the 5 kg the same name states (#70).

    Args:
        text: Text such as ``"6 x 100 g"`` or ``"20x250g"``.

    Returns:
        The weight of one package and of all of them, in grams, or None when
        the text spells no usable multiplication.
    """
    if not text:
        return None
    match = _PACK_RE.search(text)
    if match is None:
        return None
    count = int(match.group(1))
    each = _to_float(match.group(2))
    if each is None or each <= 0 or count <= 0:
        return None
    unit = match.group(3).lower()
    grams = each * 1000 if unit.startswith(("kg", "kilo")) else each
    total = count * grams
    if not math.isfinite(total):
        return None
    return round(grams), round(total)


def parse_weight_grams(text: str | None) -> int | None:
    """Parse a package weight into grams.

    Args:
        text: Text such as ``"200 g"``, ``"1 kg"``, ``"0,25 kg"`` or ``"250g"``.

    Returns:
        The weight in grams, or None when no weight is present.
    """
    if not text:
        return None
    match = _WEIGHT_RE.search(text)
    return None if match is None else _match_grams(match)


def parse_weights_grams(text: str | None) -> list[int]:
    """Parse every weight a text states, in the order it states them.

    Args:
        text: Text such as ``"Mlýnek 1 kg + káva 250 g"``.

    Returns:
        The weights in grams, empty when the text states none.
    """
    if not text:
        return []
    return [
        grams for match in _WEIGHT_RE.finditer(text) if (grams := _match_grams(match)) is not None
    ]


def _match_grams(match: re.Match[str]) -> int | None:
    """Convert one ``_WEIGHT_RE`` match into grams.

    Args:
        match: A match of ``_WEIGHT_RE``, whose groups are the number and unit.

    Returns:
        The weight in grams, or None when the number is not a usable one.
    """
    value = _to_float(match.group(1))
    if value is None or value <= 0:
        return None
    unit = match.group(2).lower()
    grams = value * 1000 if unit.startswith(("kg", "kilo")) else value
    if not math.isfinite(grams):
        return None
    return round(grams)


# The same guard as _WEIGHT_RE, for the same reason: a number glued to the one
# before it is not a volume of its own.
_VOLUME_RE = re.compile(
    r"(?<![\d/-])(\d[\d\s .,]*)\s*(ml|mililitr\w*|cl|dl|l|litr\w*|liter\w*)\b",
    re.IGNORECASE,
)

#: Millilitres in one of the two-letter units ``_VOLUME_RE`` admits; the spelt
#: out ones are decided by their prefix.
_ML_PER_UNIT = {"ml": 1.0, "cl": 10.0, "dl": 100.0, "l": 1000.0}


def parse_volume_ml(text: str | None) -> int | None:
    """Parse the package volume a text states, in millilitres.

    Args:
        text: Text such as ``"330ml"``, ``"0,5 l"`` or ``"5x200 ml"``. A
            multiplier is not applied: this reads the size of one container.

    Returns:
        The volume in millilitres, or None when the text states none.
    """
    if not text:
        return None
    match = _VOLUME_RE.search(text)
    if match is None:
        return None
    value = _to_float(match.group(1))
    if value is None or value <= 0:
        return None
    unit = match.group(2).lower()
    factor = _ML_PER_UNIT.get(unit, 1.0 if unit.startswith("mili") else 1000.0)
    millilitres = value * factor
    if not math.isfinite(millilitres):
        return None
    return round(millilitres)


def states_volume(text: str | None) -> bool:
    """Say whether a name sells a volume of liquid rather than a weight of beans.

    A litre of cold brew is not a kilogram of coffee, and no density may be
    invented to pretend otherwise, so the package is only comparable by what the
    page itself states. Two measurements decide where the unit is believed. It
    is read from the product name alone, because a volume *label* means
    something else: 13 simplecoffee bags of beans carry "OBJEM ESPRESSA
    35 - 45 ml" as brewing advice, and one 250 g gift box states "OBJEM 0,18L"
    for the mug inside it. And it yields to a weight in the same name, which
    costs nothing measured — of 3678 products not one name states both — but
    keeps a future "250 g + hrnek 330 ml" set weighed by its coffee.

    Over the whole catalogue 12 names state a volume and none of them is beans:
    three cold brews in cans, a body scrub, a descaler and paper cups. The name
    markers refused in #24 ("cold brew", "nitro") each delist real coffee.

    Args:
        text: The product name.

    Returns:
        True when the name states a volume and no weight.
    """
    return parse_volume_ml(text) is not None and parse_weight_grams(text) is None


_CURRENCIES: tuple[tuple[str, str], ...] = (
    ("eur", "EUR"),
    ("€", "EUR"),
    ("czk", "CZK"),
    ("kc", "CZK"),
    ("usd", "USD"),
    ("$", "USD"),
    ("gbp", "GBP"),
    ("pln", "PLN"),
)


def detect_currency(text: str | None) -> str | None:
    """Detect the currency a price is quoted in.

    Args:
        text: Text such as ``"9,99 EUR"`` or ``"249 Kc"``.

    Returns:
        An ISO 4217 code, or None when no currency marker is present.
    """
    if not text:
        return None
    lowered = fold(text)
    for needle, code in _CURRENCIES:
        if needle in lowered:
            return code
    return None


def parse_amount(text: str | None) -> float | None:
    """Parse the first localised number in the text into a float.

    Args:
        text: Text such as ``"9,99"``, ``"1 299"`` or ``"249,-"``.

    Returns:
        The number, or None when the text holds no digits.
    """
    if not text:
        return None
    match = _NUMBER_RE.search(text.replace("\u00a0", " ").replace("\u202f", " "))
    if match is None:
        return None
    return _to_float(match.group(0))


def parse_price(text: str | None) -> tuple[float | None, str | None]:
    """Parse a localised price together with the currency it is quoted in.

    Args:
        text: Text such as ``"9,99 EUR"``, ``"249 Kc"``, ``"1 299 Kc"``,
            ``"249,-"`` or ``"9.99"``.

    Returns:
        An ``(amount, currency)`` tuple; either member is None when absent.
    """
    return (parse_amount(text), detect_currency(text))


_ALTITUDE_RE = re.compile(
    r"(\d[\d\s .,]*)(?:\s*(?:az|do|to|\+)?\s*[-]\s*|\s+az\s+|\s+do\s+|\s+to\s+)"
    r"(\d[\d\s .,]*)"
)
#: A number immediately followed by a metre marker — the only reliable way to
#: tell an altitude from the harvest year that so often shares the same cell.
_ALTITUDE_UNIT_RE = re.compile(
    r"(\d[\d\s]*\d|\d)\s*(?:m\s*\.?\s*n\.?\s*m|masl|metrov|metru|metrech|metres|meters|m)\b",
    re.IGNORECASE,
)
#: A bare number; spaces group thousands, but a comma or a dot ends it, so
#: "2024, 1800" is two candidates rather than one unparsable blob.
_ALTITUDE_SINGLE_RE = re.compile(r"(\d[\d\s]*\d|\d)")


def _altitude_value(raw: str) -> int | None:
    value = _to_float(raw)
    if value is None:
        return None
    metres = round(value)
    if not _MIN_ALTITUDE_M <= metres <= _MAX_ALTITUDE_M:
        return None
    return metres


def parse_altitude(text: str | None) -> tuple[int | None, int | None]:
    """Parse an altitude statement into a metre range.

    Args:
        text: Text such as ``"1500 - 1700 m n. m."`` or ``"1 200 m.n.m."``.

    Returns:
        A ``(minimum, maximum)`` tuple; both members are None when unparsable
        and both are equal when a single altitude is given.
    """
    folded = dash_fold(text)
    if not folded:
        return (None, None)
    ranged = _ALTITUDE_RE.search(folded)
    if ranged is not None:
        low = _altitude_value(ranged.group(1))
        high = _altitude_value(ranged.group(2))
        if low is not None and high is not None:
            return (min(low, high), max(low, high))
    # A number carrying a metre marker wins over a bare one: "zber 2024, 1800 m
    # n.m." states a harvest year first, and a year is a plausible altitude.
    for candidate in (_ALTITUDE_UNIT_RE, _ALTITUDE_SINGLE_RE):
        for match in candidate.finditer(folded):
            value = _altitude_value(match.group(1))
            if value is not None:
                return (value, value)
    return (None, None)


_PROCESS_TABLE: tuple[tuple[str, str], ...] = (
    ("carbonic maceration", ProcessMethod.EXPERIMENTAL),
    ("karbonicka maceracia", ProcessMethod.EXPERIMENTAL),
    ("karbonicka macerace", ProcessMethod.EXPERIMENTAL),
    ("experiment", ProcessMethod.EXPERIMENTAL),
    ("anaerob", ProcessMethod.ANAEROBIC),
    ("wet hulled", ProcessMethod.WET_HULLED),
    ("wet hulling", ProcessMethod.WET_HULLED),
    ("giling basah", ProcessMethod.WET_HULLED),
    ("pulped natural", ProcessMethod.PULPED_NATURAL),
    ("poloprana", ProcessMethod.PULPED_NATURAL),
    ("honey", ProcessMethod.HONEY),
    ("medova", ProcessMethod.HONEY),
    ("medove", ProcessMethod.HONEY),
    ("medovy", ProcessMethod.HONEY),
    ("washed", ProcessMethod.WASHED),
    ("wet process", ProcessMethod.WASHED),
    ("prana", ProcessMethod.WASHED),
    ("prane", ProcessMethod.WASHED),
    ("prany", ProcessMethod.WASHED),
    ("myta", ProcessMethod.WASHED),
    ("myte", ProcessMethod.WASHED),
    ("mokra metoda", ProcessMethod.WASHED),
    ("mokrou metodou", ProcessMethod.WASHED),
    ("mokra cesta", ProcessMethod.WASHED),
    ("mokr", ProcessMethod.WASHED),  # mokré / mokro spracovaná — SK/CZ for "wet"
    ("natural", ProcessMethod.NATURAL),
    ("dry process", ProcessMethod.NATURAL),
    ("sucha metoda", ProcessMethod.NATURAL),
    ("suchou metodou", ProcessMethod.NATURAL),
    ("sucha", ProcessMethod.NATURAL),
    ("suche", ProcessMethod.NATURAL),
    ("susena", ProcessMethod.NATURAL),
    ("susene", ProcessMethod.NATURAL),
    ("prirodni", ProcessMethod.NATURAL),
    ("prirodna", ProcessMethod.NATURAL),
)


#: How many words a chunk may have and still be read as a method name of its own.
_MAX_METHOD_WORDS = 2
#: Members that carry no information about how the cherry was processed.
_UNSPECIFIC_METHODS = (ProcessMethod.OTHER, ProcessMethod.UNKNOWN, ProcessMethod.MIXED)


def normalize_process(text: str | None) -> ProcessMethod:
    """Map a free-form processing description onto :class:`ProcessMethod`.

    Args:
        text: Text such as ``"prana"``, ``"natural"`` or ``"giling basah"``.

    Returns:
        The matching member, ``OTHER`` for unrecognised non-empty text and
        ``UNKNOWN`` for empty input.
    """
    folded = fold(text)
    if not folded:
        return ProcessMethod.UNKNOWN
    matched = _first_match(folded, _PROCESS_TABLE)
    return ProcessMethod(matched) if matched is not None else ProcessMethod.OTHER


def parse_processing(text: str | None) -> Processing:
    """Read a processing statement that may name more than one method.

    A blend, or a lot marked ``"Washed · Natural"``, really was processed in
    several ways; collapsing that to one method loses the fact. Every recognised
    method is kept, and ``method`` becomes :attr:`ProcessMethod.MIXED` when there
    is more than one.

    Args:
        text: Text such as ``"Washed · Natural"`` or ``"natural / ruční sběr"``.

    Returns:
        The processing block, with ``raw`` untouched.
    """
    methods: list[ProcessMethod] = []
    for item in split_list(text):
        # An enumeration names methods ("Washed · Natural"); a description names
        # the stages of one ("mokré, sušené na slnku" is a washed coffee that was
        # sun dried). Only a bare name is read as a separate method.
        if len(item.split()) > _MAX_METHOD_WORDS:
            continue
        method = normalize_process(item)
        if method in _UNSPECIFIC_METHODS or method in methods:
            continue
        methods.append(method)
    if len(methods) == 1:
        return Processing(method=methods[0], raw=text, methods=methods)
    if len(methods) > 1:
        return Processing(method=ProcessMethod.MIXED, raw=text, methods=methods)
    # Nothing recognised: keep the single-value verdict, which is OTHER for text
    # that says *something* and UNKNOWN for text that says nothing at all.
    return Processing(method=normalize_process(text), raw=text, methods=[])


_ROAST_TABLE: tuple[tuple[str, str], ...] = (
    ("full city +", RoastLevel.DARK),
    ("full city plus", RoastLevel.DARK),
    ("full city", RoastLevel.MEDIUM_DARK),
    ("city +", RoastLevel.MEDIUM),
    ("city plus", RoastLevel.MEDIUM),
    ("cinnamon", RoastLevel.LIGHT),
    ("svetlo stredn", RoastLevel.MEDIUM_LIGHT),
    ("svetle stredn", RoastLevel.MEDIUM_LIGHT),
    ("stredne svetl", RoastLevel.MEDIUM_LIGHT),
    ("light medium", RoastLevel.MEDIUM_LIGHT),
    ("medium light", RoastLevel.MEDIUM_LIGHT),
    ("stredne tmav", RoastLevel.MEDIUM_DARK),
    ("stredni tmav", RoastLevel.MEDIUM_DARK),
    ("medium dark", RoastLevel.MEDIUM_DARK),
    ("viedensk", RoastLevel.MEDIUM_DARK),
    ("vieden", RoastLevel.MEDIUM_DARK),
    ("french", RoastLevel.DARK),
    ("italian", RoastLevel.DARK),
    ("taliansk", RoastLevel.DARK),
    ("francuzsk", RoastLevel.DARK),
    ("tmav", RoastLevel.DARK),
    ("dark", RoastLevel.DARK),
    ("svetl", RoastLevel.LIGHT),
    ("light", RoastLevel.LIGHT),
    ("city", RoastLevel.LIGHT),
    ("stredn", RoastLevel.MEDIUM),
    ("medium", RoastLevel.MEDIUM),
)


#: Words that prove the text is talking about roasting rather than about the cup.
_ROAST_CONTEXT_RE = re.compile(r"praz|roast|pecen")
#: Colour words that are just as often cup notes: "tmavá čokoláda" is a tasting
#: note on a light roast, not a dark roast.
_AMBIGUOUS_ROAST_NEEDLES = frozenset({"tmav", "dark", "svetl", "light"})
#: Nouns a colour word qualifies when it is a cup note rather than a roast level.
_CUP_NOTE_NOUNS = (
    "berr",
    "bobul",
    "cocoa",
    "cokolad",
    "chocolate",
    "cukor",
    "cukr",
    "fruit",
    "kakao",
    "karamel",
    "caramel",
    "nuts",
    "nutty",
    "orech",
    "oriesk",
    "orisk",
    "ovoc",
    "sugar",
    "tabak",
    "tobacco",
)
#: How many words a text may have and still be read as a parameter value rather
#: than prose — a bare "tmavé" in a roast cell needs no roasting word to be real.
_MAX_ROAST_WORDS = 3


def _roast_colour_is_real(folded: str, needle: str) -> bool:
    """Decide whether a colour word names the roast or describes the cup.

    Args:
        folded: The folded text the needle matched in.
        needle: The matched colour needle, such as ``"tmav"``.

    Returns:
        True when some occurrence of the colour word names the roast level.
    """
    words = _WORD_RE.findall(folded)
    cup_notes = any(word.startswith(_CUP_NOTE_NOUNS) for word in words)
    prose = len(words) > _MAX_ROAST_WORDS or cup_notes
    roasting = _ROAST_CONTEXT_RE.search(folded) is not None
    for index, word in enumerate(words):
        if needle not in word:
            continue
        following = words[index + 1] if index + 1 < len(words) else ""
        # "tmavé ovoce", "dark chocolate": the colour belongs to the noun.
        if following.startswith(_CUP_NOTE_NOUNS):
            continue
        if roasting or not prose:
            return True
    return False


def normalize_roast_level(text: str | None) -> RoastLevel:
    """Map a free-form roast description onto :class:`RoastLevel`.

    A bare colour word is trusted in a short parameter value ("tmavé"), and in
    prose only next to a roasting word ("tmavé praženie"); a colour sitting on a
    food noun ("tmavá čokoláda") is a cup note and is skipped, so the table goes
    on looking for a real roast word further down.

    Args:
        text: Text such as ``"Full City +"``, ``"svetle prazena"`` or ``"dark"``.

    Returns:
        The matching member, or ``UNKNOWN`` when nothing matches.
    """
    folded = fold(text)
    if not folded:
        return RoastLevel.UNKNOWN
    for needle, value in _ROAST_TABLE:
        if needle not in folded:
            continue
        if needle in _AMBIGUOUS_ROAST_NEEDLES and not _roast_colour_is_real(folded, needle):
            continue
        return RoastLevel(value)
    return RoastLevel.UNKNOWN


_ESPRESSO_MARKERS = ("espresso", "espreso", "moka", "kavovar", "pakova")
_FILTER_MARKERS = (
    "filter",
    "filtr",
    "prekvapkav",
    "prekapav",
    "preliv",
    "v60",
    "chemex",
    "aeropress",
    "french press",
    "dripper",
)
_OMNI_MARKERS = ("omni", "univerzal", "vsestrann")


def normalize_roast_profile(text: str | None) -> RoastProfile:
    """Decide whether a roast targets espresso, filter or both.

    Args:
        text: Text such as ``"Kava na espresso"`` or ``"filter / espresso"``.

    Returns:
        The matching member, or ``UNKNOWN`` when nothing matches.
    """
    folded = fold(text)
    if not folded:
        return RoastProfile.UNKNOWN
    if any(marker in folded for marker in _OMNI_MARKERS):
        return RoastProfile.OMNI
    espresso = any(marker in folded for marker in _ESPRESSO_MARKERS)
    filtered = any(marker in folded for marker in _FILTER_MARKERS)
    if espresso and filtered:
        return RoastProfile.OMNI
    if espresso:
        return RoastProfile.ESPRESSO
    if filtered:
        return RoastProfile.FILTER
    return RoastProfile.UNKNOWN


_COUNTRY_TERMS: dict[str, tuple[str, ...]] = {
    "BR": ("brazilia", "brazilie", "brazil", "brasil", "brazilska", "brazilian"),
    "CO": ("kolumbia", "kolumbie", "colombia", "kolumbijska", "colombian"),
    "ET": ("etiopia", "etiopie", "ethiopia", "ethiopie", "etiopska", "ethiopian", "abesinia"),
    "KE": ("kena", "kenya", "kenska", "kenyan"),
    "VN": ("vietnam", "vietnamska", "vietnamese"),
    "ID": ("indonezia", "indonezie", "indonesia", "indonezska", "sumatra", "sulawesi", "flores"),
    "HN": ("honduras", "honduraska", "honduran"),
    "UG": ("uganda", "ugandska", "ugandan"),
    "PE": ("peru", "peruanska", "peruvian"),
    "IN": ("india", "indie", "indicka", "indian"),
    "GT": ("guatemala", "guatemalska", "guatemalan"),
    "NI": ("nikaragua", "nicaragua", "nikaragujska", "nicaraguan"),
    "CR": ("kostarika", "costa rica", "kostaricka", "costa rican"),
    "MX": ("mexiko", "mexico", "mexicka", "mexican"),
    "TZ": ("tanzania", "tanzanie", "tanzanska", "tanzanian", "kilimandzaro"),
    "SV": ("el salvador", "salvador", "salvadorska", "salvadoran"),
    "CN": ("cina", "china", "cinska", "chinese", "yunnan"),
    "CI": ("pobrezie slonoviny", "pobrezi slonoviny", "ivory coast"),
    "PG": ("papua nova guinea", "papua new guinea", "papua"),
    "EC": ("ekvador", "ecuador", "ekvadorska", "ecuadorian"),
    "LA": ("laos", "laoska", "laotian"),
    "TH": ("thajsko", "thailand", "thajska", "thai"),
    "VE": ("venezuela", "venezuelska", "venezuelan"),
    "DO": ("dominikanska republika", "dominican republic", "dominikanska"),
    "HT": ("haiti", "haitska", "haitian"),
    "CD": ("kongo", "congo", "konzska", "congolese"),
    "RW": ("rwanda", "rwandska", "rwandan"),
    "BI": ("burundi", "burundska", "burundian"),
    "YE": ("jemen", "yemen", "jemenska", "yemeni"),
    "PA": ("panama", "panamska", "panamanian"),
    "BO": ("bolivia", "bolivie", "bolivijska", "bolivian"),
    "CU": ("kuba", "cuba", "kubanska", "cuban"),
    "JM": ("jamajka", "jamaica", "jamajska", "jamaican", "blue mountain"),
    "MW": ("malawi", "malawijska", "malawian"),
    "ZM": ("zambia", "zambie", "zambijska", "zambian"),
    "ZW": ("zimbabwe", "zimbabwianska"),
    "CM": ("kamerun", "cameroon", "kamerunska", "cameroonian"),
    "MG": ("madagaskar", "madagascar", "madagaskarska"),
    "MM": ("mjanmarsko", "myanmar", "barma", "burma"),
    "PH": ("filipiny", "philippines", "filipinska", "philippine"),
    "TL": ("vychodny timor", "vychodni timor", "east timor", "timor leste", "timor"),
    "NP": ("nepal", "nepalska", "nepalese"),
    "AO": ("angola", "angolska", "angolan"),
    "PR": ("portoriko", "puerto rico"),
    "US": ("havaj", "hawaii", "hawaiian"),
    "GH": ("ghana", "ghanska", "ghanaian"),
    "CV": ("kapverdy", "cape verde"),
}

_COUNTRY_BY_TERM: dict[str, str] = {
    fold(term): code for code, terms in _COUNTRY_TERMS.items() for term in terms
}
_COUNTRY_RE = re.compile(
    r"\b(?:"
    + "|".join(re.escape(term) for term in sorted(_COUNTRY_BY_TERM, key=lambda t: (-len(t), t)))
    + r")\b"
)


def detect_country(text: str | None) -> str | None:
    """Detect a coffee-producing country mentioned anywhere in the text.

    Args:
        text: Product name, description or keyword list in SK, CZ or EN.

    Returns:
        An ISO 3166-1 alpha-2 code, or None when no country is recognised.
    """
    folded = fold(text)
    if not folded:
        return None
    match = _COUNTRY_RE.search(folded)
    if match is None:
        return None
    return _COUNTRY_BY_TERM[match.group(0)]


def countries_in(text: str | None) -> frozenset[str]:
    """List every coffee-producing country a text names, not just the first.

    Args:
        text: An origin value such as ``"Brazílie, Keňa"`` or ``"Kolumbia · Cauca"``.

    Returns:
        The distinct ISO 3166-1 alpha-2 codes, empty when the text names none.
    """
    folded = fold(text)
    if not folded:
        return frozenset()
    return frozenset(_COUNTRY_BY_TERM[match.group(0)] for match in _COUNTRY_RE.finditer(folded))


_SPECIES_RE = re.compile(
    r"(?:(?P<pct_first>\d{1,3})\s*%\s*(?P<name_last>arabi\w*|robus\w*)"
    r"|(?P<name_first>arabi\w*|robus\w*)\s*[:\-]?\s*(?P<pct_last>\d{1,3})\s*%)",
    re.IGNORECASE,
)


def parse_species(text: str | None) -> tuple[int | None, int | None]:
    """Parse an arabica/robusta split.

    Args:
        text: Text such as ``"90 % Arabika, 10 % Robusta"`` or ``"100% arabica"``.

    Returns:
        A ``(arabica_pct, robusta_pct)`` tuple; members are None when unknown.
        When only one species is stated the other is inferred as the remainder.
    """
    folded = fold(text)
    if not folded:
        return (None, None)
    arabica: int | None = None
    robusta: int | None = None
    for match in _SPECIES_RE.finditer(folded):
        name = match.group("name_last") or match.group("name_first") or ""
        raw_pct = match.group("pct_first") or match.group("pct_last")
        if raw_pct is None:
            continue
        pct = int(raw_pct)
        if pct > _MAX_PERCENT:
            continue
        if name.startswith("arabi") and arabica is None:
            arabica = pct
        elif name.startswith("robus") and robusta is None:
            robusta = pct
    if arabica is not None and robusta is None:
        robusta = _MAX_PERCENT - arabica
    elif robusta is not None and arabica is None:
        arabica = _MAX_PERCENT - robusta
    return (arabica, robusta)


_BLEND_MARKERS = ("blend", "zmes", "smes", "smesi", "zmesi", "mix", "espresso blend")


def detect_blend(text: str | None, arabica_pct: int | None, robusta_pct: int | None) -> bool | None:
    """Read what one name or species split states about blending.

    A single-species split is reported as False, but that is only a statement
    about species: a blend of one species from several origins looks the same.
    Callers weigh it against the rest of the page rather than trust it alone.

    Args:
        text: Product name or description.
        arabica_pct: Arabica share, when known.
        robusta_pct: Robusta share, when known.

    Returns:
        True when the text says blend or the split mixes two species, False when
        the split names one species alone, and None when neither is stated. An
        unstated value is None, never False: False would assert single origin.
    """
    folded = fold(text)
    if any(marker in folded for marker in _BLEND_MARKERS):
        return True
    known = [pct for pct in (arabica_pct, robusta_pct) if pct is not None]
    if not known:
        return None
    return not any(pct == _MAX_PERCENT for pct in known)


def split_list(text: str | None) -> list[str]:
    """Split a human-written enumeration into trimmed, de-duplicated items.

    Args:
        text: Text such as ``"kakao, karamel / tabakove listy"``.

    Returns:
        The individual items in their original order and spelling.
    """
    if not text:
        return []
    items: list[str] = []
    seen: set[str] = set()
    for chunk in _LIST_SPLIT_RE.split(text):
        cleaned = _WHITESPACE_RE.sub(" ", chunk).strip(" \t.-")
        key = fold(cleaned)
        if not cleaned or key in seen:
            continue
        seen.add(key)
        items.append(cleaned)
    return items


_DATE_RE = re.compile(r"(\d{1,2})\s*[./-]\s*(\d{1,2})\s*[./-]\s*(\d{4})")
_ISO_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def parse_date_dmy(text: str | None) -> date | None:
    """Parse a day-first date such as ``"11.09.2026"``.

    Also accepts ISO ``YYYY-MM-DD`` because shops mix both in microdata.

    Args:
        text: Text containing a date.

    Returns:
        The parsed date, or None when no valid date is present.
    """
    if not text:
        return None
    iso = _ISO_DATE_RE.search(text)
    if iso is not None:
        return _safe_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    match = _DATE_RE.search(text)
    if match is None:
        return None
    return _safe_date(int(match.group(3)), int(match.group(2)), int(match.group(1)))


def _safe_date(year: int, month: int, day: int) -> date | None:
    if not _ISO_YEAR_MIN <= year <= _ISO_YEAR_MAX:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_int(text: str | None) -> int | None:
    """Parse the first integer in the text.

    Args:
        text: Text such as ``"51 hodnoteni"`` or ``"Uprazene a vypite: 24339x"``.

    Returns:
        The integer, or None when the text holds no digits.
    """
    if not text:
        return None
    match = re.search(r"\d[\d\s ]*", text)
    if match is None:
        return None
    digits = re.sub(r"\D", "", match.group(0))
    return int(digits) if digits else None


def parse_float(text: str | None) -> float | None:
    """Parse the first decimal number in the text.

    Args:
        text: Text such as ``"4,8 / 5"``.

    Returns:
        The number, or None when the text holds no digits.
    """
    return parse_amount(text)


#: Folded SK/CZ/EN intensity word -> its place on the 1-5 scale. Longer phrases
#: come first so "velmi vysoka" is never read as a plain "vysoka".
_INTENSITY_TABLE: tuple[tuple[str, int], ...] = (
    ("velmi vysoka", 5),
    ("velmi vysoke", 5),
    ("very high", 5),
    ("intenzivna", 5),
    ("intenzivni", 5),
    ("ziadna", 1),
    ("zadna", 1),
    ("none", 1),
    ("nizka", 2),
    ("nizke", 2),
    ("low", 2),
    ("jemna", 2),
    ("jemne", 2),
    ("stredna", 3),
    ("stredni", 3),
    ("stredne", 3),
    ("medium", 3),
    ("vysoka", 4),
    ("vysoke", 4),
    ("high", 4),
    ("plna", 4),
    ("plne", 4),
    ("plnej", 4),
    ("full", 4),
    ("vyrazna", 4),
    ("vyrazne", 4),
)
_MIN_INTENSITY = 1
_MAX_INTENSITY = 5
_WORD_RE = re.compile(r"[a-z0-9]+")


def parse_intensity(text: str | None) -> int | None:
    """Map an intensity word onto the same 1-5 scale the sensory bars use.

    Shops that draw no bars still describe body, acidity, bitterness and
    sweetness in words; putting both on one scale is what makes the two
    comparable across shops.

    Args:
        text: Text such as ``"vysok\u00e1"``, ``"st\u0159edn\u00ed"`` or ``"3"``.

    Returns:
        A value between 1 and 5, or None when the text names no intensity.
    """
    folded = fold(text)
    if not folded:
        return None
    # Whole words only: "príjemná" contains "jemná" and means pleasant, not weak.
    words = _WORD_RE.findall(folded)
    for needle, value in _INTENSITY_TABLE:
        wanted = needle.split()
        if any(
            words[start : start + len(wanted)] == wanted
            for start in range(len(words) - len(wanted) + 1)
        ):
            return value
    number = parse_int(folded)
    if number is not None and _MIN_INTENSITY <= number <= _MAX_INTENSITY:
        return number
    return None


#: Species names that introduce a variety rather than being one.
_SPECIES_PREFIX_RE = re.compile(
    r"^(?:arabica|arabika|arabic|robusta|canephora|liberica)\b[\s\-:.]*",
    re.IGNORECASE,
)
_VARIETY_SPLIT_RE = re.compile(r"[,/\u00b7\u2022\u2219\u2027;|]+")


def clean_variety(items: Iterable[str] | None) -> list[str]:
    """Turn shop variety text into plain cultivar names.

    ``"Arabica \u2013 Lempira"`` names one cultivar, not two, and
    ``"Castillo / Caturra"`` names two; both spellings are common enough that
    grouping by variety needs them flattened the same way.

    Args:
        items: The variety strings a shop stated, in any spelling.

    Returns:
        The cultivar names, de-duplicated, in their original order.
    """
    if items is None:
        return []
    cleaned: list[str] = []
    for item in items:
        for chunk in _VARIETY_SPLIT_RE.split(dash_fold_keep(item)):
            name = _SPECIES_PREFIX_RE.sub("", chunk).strip(" \t-\u2013\u2014.:")
            if name:
                cleaned.append(_WHITESPACE_RE.sub(" ", name))
    return _unique_preserving(cleaned)


def dash_fold_keep(text: str | None) -> str:
    """Collapse whitespace without touching case or diacritics.

    Args:
        text: Arbitrary shop text.

    Returns:
        The same text with runs of whitespace reduced to one space.
    """
    if not text:
        return ""
    return _WHITESPACE_RE.sub(" ", text.replace("\u00a0", " ")).strip()


def _unique_preserving(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = fold(value)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
