from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Protocol, cast

from coffee_aggregator import normalize
from coffee_aggregator.labels import KNOWN_FIELDS
from coffee_aggregator.sites.base import DEFAULT_IGNORED, SiteAdapter

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

__all__ = [
    "CommonFields",
    "ConfiguredSite",
    "PlatformConfig",
    "PlatformConfigError",
    "check_label_map",
    "common_fields",
]

#: The keys no platform can invent a value for.
_REQUIRED: tuple[str, ...] = ("site_id", "name", "country", "base_url")
#: The two markets the catalogue covers; a config naming another one is wrong
#: rather than merely unsupported, because every price is read in one of them.
_MARKETS: frozenset[str] = frozenset({"CZ", "SK"})


class PlatformConfigError(ValueError):
    """Raised when a shop TOML is missing a key its adapter cannot invent.

    One error for all three platforms: the caller never distinguishes them, and
    three identical classes meant three places to change the message.
    """

    def __init__(self, path: Path, problem: str) -> None:
        """Build the error.

        Args:
            path: The configuration file that is wrong.
            problem: What is wrong with it.
        """
        super().__init__(f"{path}: {problem}")
        self.path = path


def check_label_map(folded: dict[str, str], written: dict[str, Any], path: Path) -> None:
    """Refuse a ``label_map`` that points a label at a field nobody reads.

    Every platform maps onto the same ``KNOWN_FIELDS`` so one sink schema
    serves them all, which is why one check serves them all too.

    Args:
        folded: The folded label -> field mapping the TOML asked for.
        written: The same mapping with the labels as the file spells them.
        path: The configuration file, for the error message.

    Raises:
        PlatformConfigError: When a value is not one of :data:`KNOWN_FIELDS`.
    """
    spellings = {normalize.fold(label): str(label) for label in written}
    for label, field_name in folded.items():
        if field_name in KNOWN_FIELDS:
            continue
        valid = ", ".join(sorted(name for name in KNOWN_FIELDS if name))
        raise PlatformConfigError(
            path,
            f"label_map[{spellings.get(label, label)!r}] = {field_name!r} is not a field; "
            f"valid fields are: {valid}",
        )


@dataclass(slots=True, frozen=True)
class CommonFields:
    """The values every platform reads the same way out of its shop TOML.

    Attributes:
        site_id: Registry id.
        name: Human-readable shop name.
        country: Which market the shop sells in.
        base_url: Shop root, with a trailing slash. A platform that resolves
            its listing URLs against the root does so against the *written*
            value instead, because a slash changes what ``urljoin`` keeps of a
            base URL that has a path.
        currency: The currency the TOML pins, when it pins one.
        label_map: Folded label -> field, already checked.
        ignore: Folded non-coffee markers.
        max_pages: Hard cap on listing pages.
    """

    site_id: str
    name: str
    country: Literal["CZ", "SK"]
    base_url: str
    currency: str | None
    label_map: dict[str, str]
    ignore: list[str]
    max_pages: int


def common_fields(
    config: dict[str, Any],
    path: Path,
    *,
    default_max_pages: int,
    also_required: Sequence[str] = (),
) -> CommonFields:
    """Validate the head every platform's ``from_mapping`` used to repeat.

    Args:
        config: The mapping ``tomllib`` produced.
        path: Where it came from, for error messages.
        default_max_pages: The platform's own page cap, which differs because
            a JSON page holds a hundred products and an HTML one holds twelve.
        also_required: Keys this platform needs beyond the shared four.

    Returns:
        The shared values, validated.

    Raises:
        PlatformConfigError: When a required key is missing or malformed.
    """
    missing = [key for key in (*_REQUIRED, *also_required) if not config.get(key)]
    if missing:
        raise PlatformConfigError(path, f"missing required key(s): {', '.join(missing)}")
    country = str(config["country"]).upper()
    if country not in _MARKETS:
        raise PlatformConfigError(path, f"country must be CZ or SK, not {country!r}")
    base_url = str(config["base_url"])
    label_map = {
        normalize.fold(key): str(value) for key, value in config.get("label_map", {}).items()
    }
    check_label_map(label_map, config.get("label_map", {}), path)
    return CommonFields(
        site_id=str(config["site_id"]),
        name=str(config["name"]),
        country=cast("Literal['CZ', 'SK']", country),
        base_url=base_url if base_url.endswith("/") else f"{base_url}/",
        currency=str(config["currency"]) if config.get("currency") else None,
        label_map=label_map,
        ignore=[normalize.fold(marker) for marker in config.get("ignore", [])],
        max_pages=int(config.get("max_pages", default_max_pages)),
    )


class PlatformConfig(Protocol):
    """What :class:`ConfiguredSite` needs of a config, whatever else it holds."""

    site_id: str
    name: str
    country: Literal["CZ", "SK"]
    base_url: str
    label_map: dict[str, str]
    ignore: list[str]
    max_pages: int


class ConfiguredSite[ConfigT: PlatformConfig](SiteAdapter):
    """One shop of a platform, parameterised entirely by its config.

    Attributes:
        default_label_map: The platform's own vocabulary, which the shop's own
            ``label_map`` is merged over.
    """

    default_label_map: ClassVar[dict[str, str]] = {}

    def __init__(self, config: ConfigT) -> None:
        """Build the adapter.

        Args:
            config: The shop's validated configuration.
        """
        self.config = config
        self.site_id = config.site_id
        self.name = config.name
        self.country = config.country
        self.base_url = config.base_url
        self.max_pages = config.max_pages
        self.label_map = {**self.default_label_map, **config.label_map}

    def ignored_names(self) -> tuple[str, ...]:
        """Return the folded markers of products that are not coffee beans.

        Returns:
            The shared defaults plus whatever the shop's TOML added.
        """
        return (*DEFAULT_IGNORED, *self.config.ignore)
