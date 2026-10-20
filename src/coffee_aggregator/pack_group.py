from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final
from urllib.parse import urlsplit

from coffee_aggregator.normalize import _COUNT_RE, _PACK_RE, _WEIGHT_RE, dash_fold, fold

if TYPE_CHECKING:
    from collections.abc import Iterable
    from re import Match

#: The version of the rule that built a key. Two keys are comparable only when
#: they carry the same source.
PACK_GROUP_KEY_SOURCE: Final = "name:v1"

_ESPRESSO: Final = "espresso"
_FILTER: Final = "filter"
#: Roast words, folded, and the canonical kind each one stands for.
_ROAST_KINDS: Final = {
    "espresso": _ESPRESSO,
    "espreso": _ESPRESSO,
    "esko": _ESPRESSO,
    "filtr": _FILTER,
    "filter": _FILTER,
}
_TOKEN_RE: Final = re.compile(r"[^\W_]+")
_NON_ALNUM_RE: Final = re.compile(r"[\W_]+")
#: Bean, ground and bare-coffee words, matched on folded text. Decaf words
#: (``decaf``, ``dekaf``, ``bez kofeinu``, ``bezkofeinova``) are not in this
#: list and must never be.
_FORM_RE: Final = re.compile(
    r"\b(?:whole\s+beans?|beans?|ground|coffee|zrnkov(?:a|e|y|ou)|zrnka|zrnko|zrna|zrno"
    r"|mlet(?:a|e|y|ou|ie)|kav(?:a|y|u|ou))\b"
    r"|(?:\bv\s+)?\b(?:doz(?:a|y|u|ou|e)|plechov(?:ka|ky|ku|kou|ce|ke))\b"
)
_NUMBER_TAIL_RE: Final = re.compile(r"\d+(?:[.,]\d+)?[\s.]*$")
#: A pack written as a number of portions, such as ``7 porcí``.
_PORTION_RE: Final = re.compile(r"(?<![\d.,])\d{1,3}\s*porc(?:i|e|ie|ii)\b")
_SPACE: Final = " "


def _drop_weight(match: Match[str]) -> str:
    """Replace a weight by a space, keeping every number before the weight's own.

    ``_WEIGHT_RE`` lets a number contain spaces so that ``1 000 g`` reads as
    one figure, which also lets it swallow the ``4`` of ``n°4 250 g``. Only
    the last number is the weight, so a ``1 000 g`` is read as ``000 g`` and
    leaves its ``1`` behind: a pack that is not grouped is a miss, and
    swallowing a digit that tells two coffees apart is a false merge.

    Args:
        match: A match of ``_WEIGHT_RE``.

    Returns:
        The text that stays where the weight was.
    """
    number = match.group(1)
    tail = _NUMBER_TAIL_RE.search(number)
    return f"{number[: tail.start()]} " if tail else _SPACE


def _strip_sizes(text: str) -> str:
    without_packs = _PACK_RE.sub(_SPACE, text)
    without_weights = _WEIGHT_RE.sub(_drop_weight, without_packs)
    without_counts = _COUNT_RE.sub(_SPACE, without_weights)
    return _PORTION_RE.sub(_SPACE, without_counts)


def _collapse(text: str) -> str:
    return _NON_ALNUM_RE.sub(_SPACE, text).strip()


def _roast_kinds(words: Iterable[str]) -> set[str]:
    return {_ROAST_KINDS[word] for word in words if word in _ROAST_KINDS}


def _path(url: str | None) -> str:
    if not url:
        return ""
    try:
        return urlsplit(url).path
    except ValueError:
        return ""


def _url_roast(url: str | None) -> str | None:
    kinds = _roast_kinds(_TOKEN_RE.findall(fold(_path(url))))
    return next(iter(kinds)) if len(kinds) == 1 else None


def _url_slug(url: str | None) -> str:
    segments = [segment for segment in _path(url).split("/") if segment]
    return _collapse(_strip_sizes(fold(segments[-1]))) if segments else ""


def pack_group_key(site: str, name: str, url: str | None) -> str | None:
    """Build the key that two listings of one coffee in one shop share.

    Two listings get the same key exactly when they are the same coffee from
    the same shop in another pack. The name is folded and then stripped of
    pack-size, weight and count tokens (``250 g``, ``1kg``, ``3x250g``,
    ``12 ks``, ``7 porcí``), of packaging words (``dóza``, ``plechovka``), of
    bean and ground words (``zrnková``, ``mletá``, ``beans``, ``ground``) and
    of the bare words for coffee (``káva``, ``coffee``), and what remains is
    collapsed to lower-case alphanumerics. So a bundle, a carton or a tin is
    the same coffee as the single bag, and the ground version is the same
    coffee as the beans.

    Decaf is a different coffee: decaf words stay in the name and are never
    removed. An espresso and a filter roast of one origin are different
    coffees: a roast word in the name stays, and where the name states none,
    the roast kind that the URL path states is appended as ``~espresso`` or
    ``~filter``. A URL that states both kinds or neither adds nothing, and an
    unparseable URL counts as no URL.

    A name with nothing left but roast words, or nothing at all, does not say
    which coffee it is (``filtr`` names four coffees at one shop), so the last
    segment of the URL path, folded and stripped of sizes, stands in for it.
    Without a usable URL the folded name is kept as it is, unless nothing is
    left of it.

    Sizes are removed before the separators are flattened, because a slash
    between digits is part of a blend ratio (``Blend 75/25 250 g``) and
    flattening it first would let it merge with the weight. Only the last
    number before a unit is the weight, so ``n°4 250 g`` keeps its ``4``.

    The key is opaque and is compared for equality only. It is never parsed,
    ordered or matched across shops, and it is valid only against the rule
    version in ``PACK_GROUP_KEY_SOURCE``. The suffix is introduced by ``~``,
    which survives a URL query string where ``#`` would be cut off.

    Args:
        site: The shop's site slug; it is part of the key.
        name: The product name as the shop wrote it.
        url: The product page URL, or None. Only its path is read.

    Returns:
        ``"<site>/<normalised name>"``, followed by ``"~espresso"`` or
        ``"~filter"`` when the rule adds a roast. None when nothing is left
        of the name and the URL gives no slug either: a key with nothing
        after the slash would put every such listing of the shop in one
        group.
    """
    folded_name = fold(name)
    normalised = _collapse(_FORM_RE.sub(_SPACE, fold(_strip_sizes(dash_fold(name)))))
    if all(token in _ROAST_KINDS for token in _TOKEN_RE.findall(normalised)):
        normalised = _url_slug(url) or normalised or _collapse(folded_name)
    if not normalised:
        return None
    key = f"{site}/{normalised}"
    if _roast_kinds(_TOKEN_RE.findall(normalised)):
        return key
    roast = _url_roast(url)
    return key if roast is None else f"{key}~{roast}"
