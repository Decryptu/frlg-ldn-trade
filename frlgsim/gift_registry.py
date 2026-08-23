"""Capability-aware catalog for legacy and composed Mystery Gifts."""

import argparse
from dataclasses import dataclass

from . import stamp_rally, wonder_card, wonder_card_events
from .gift_composer import (
    GiftSpec, StampRallySpec, WonderGift, compile_definition, validate_definition,
)


@dataclass(frozen=True)
class GiftCatalogEntry:
    slug: str
    default_flag_id: int
    live: bool
    static: bool
    description: str
    builder: object

    def build_distribution(self, *, flag_id=None):
        selected_flag = self.default_flag_id if flag_id is None else flag_id
        return self.builder(selected_flag)


class _FlagIdAction(argparse.Action):
    """Keep the legacy visible default while recording an explicit override."""

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)
        setattr(namespace, "_flag_id_explicit", True)


def add_flag_id_argument(parser):
    parser.add_argument(
        "--flag-id", type=int, action=_FlagIdAction,
        default=1003, metavar="ID",
        help=("Wonder Card flagId, 1000..1019; without this option, the "
              "selected gift's registered default shown below is used"))


def resolve_flag_id(args, registry=None):
    registry = GIFT_REGISTRY if registry is None else registry
    return (args.flag_id if getattr(args, "_flag_id_explicit", False)
            else registry.default_flag_id(args.gift))


class GiftRegistry:
    """Registry whose entries declare where a gift can be distributed."""

    def __init__(self):
        self._entries = {}

    def register(self, entry):
        if not isinstance(entry, GiftCatalogEntry):
            raise TypeError("entry must be a GiftCatalogEntry")
        if entry.slug in self._entries:
            raise ValueError(f"duplicate Mystery Gift slug {entry.slug!r}")
        self._entries[entry.slug] = entry
        return entry

    def register_legacy(self, slug, builder, *, default_flag_id=1003,
                        live=True, static=True, description="legacy Mystery Gift"):
        def build(flag_id):
            value = builder(flag_id=flag_id)
            if isinstance(value, stamp_rally.MysteryGiftDistribution):
                return value
            card, ram_script = value
            return stamp_rally.MysteryGiftDistribution(card, ram_script)

        return self.register(GiftCatalogEntry(
            slug=slug, default_flag_id=default_flag_id,
            live=live, static=static, description=description,
            builder=build))

    def register_definition(self, definition):
        """Validate and register one ordinary definition or all rally slots."""
        validate_definition(definition)
        # Compile once at registration so size and relocation errors fail before
        # the definition can appear in a CLI choice list.
        compiled = compile_definition(definition)
        if not isinstance(definition, WonderGift):
            raise TypeError("definition must be a WonderGift")
        if isinstance(definition.event, GiftSpec):
            candidates = (GiftCatalogEntry(
                slug=definition.slug,
                default_flag_id=definition.card.default_flag_id,
                live=True, static=True,
                description=f"composed gift {definition.card.title!r}",
                builder=lambda flag_id, definition=definition:
                    compile_definition(definition, flag_id=flag_id)),)
        else:
            rally = definition.event
            assert isinstance(rally, StampRallySpec)
            candidates = tuple(
                GiftCatalogEntry(
                    slug=slot.slug,
                    default_flag_id=definition.card.default_flag_id,
                    live=True, static=False,
                    description=(f"{slot.stamp_species} stamp for "
                                 f"{definition.card.title!r}"),
                    builder=lambda flag_id, definition=definition, slug=slot.slug:
                        compile_definition(definition, flag_id=flag_id)[slug])
                for slot in rally.slots)
            # Touch the registration-time result so every advertised slug is
            # guaranteed to have been produced by the rally compiler.
            for candidate in candidates:
                compiled[candidate.slug]

        # Registration is atomic: a collision in a later rally slot cannot
        # leave earlier slots partially visible in the catalog.
        for candidate in candidates:
            if candidate.slug in self._entries:
                raise ValueError(f"duplicate Mystery Gift slug {candidate.slug!r}")
        for candidate in candidates:
            self._entries[candidate.slug] = candidate
        return candidates

    def entry(self, slug):
        try:
            return self._entries[slug]
        except KeyError as exc:
            choices = ", ".join(self.live_choices)
            raise ValueError(f"unknown Mystery Gift {slug!r}; choose from {choices}") from exc

    @property
    def live_choices(self):
        return tuple(entry.slug for entry in self._entries.values() if entry.live)

    @property
    def static_choices(self):
        return tuple(entry.slug for entry in self._entries.values() if entry.static)

    def default_flag_id(self, slug):
        return self.entry(slug).default_flag_id

    def build_distribution(self, slug, *, flag_id=None):
        entry = self.entry(slug)
        if not entry.live:
            raise ValueError(f"Mystery Gift {slug!r} is not available to the live host")
        return entry.build_distribution(flag_id=flag_id)

    def build_static(self, slug, *, flag_id=None):
        entry = self.entry(slug)
        if not entry.static:
            raise ValueError(f"Mystery Gift {slug!r} is live-host-only")
        distribution = entry.build_distribution(flag_id=flag_id)
        return distribution.card, distribution.ram_script

    def describe(self, slug):
        return self.entry(slug).description

    def format_live_gift_help(self):
        """Return the live catalog in a formatter-friendly CLI help block."""
        entries = tuple(entry for entry in self._entries.values() if entry.live)
        width = max(len(entry.slug) for entry in entries)
        lines = [
            "gift payload to distribute; without --flag-id, uses the registered default.",
            "Available gifts:",
        ]
        lines.extend(
            f"  {entry.slug:<{width}}  flag ID {entry.default_flag_id}: "
            f"{entry.description}"
            for entry in entries)
        return "\n".join(lines)


def build_default_registry():
    registry = GiftRegistry()
    registry.register_legacy(
        wonder_card.GIFT_BEAST_CUTSCENE,
        wonder_card.build_legendary_beast_cutscene_gift,
        description=(f"level-{wonder_card.LEGENDARY_BEAST_LEVEL} starter-dependent "
                     "legendary-beast encounter; Lansat Berry, Liechi Berry, and Master Ball"))
    registry.register_legacy(
        wonder_card.GIFT_CELEBI, wonder_card.build_default_gift,
        description="level-50 Celebi; no item")
    registry.register_legacy(
        stamp_rally.GIFT_SOLROCK_STAMP,
        stamp_rally.build_solrock_stamp_event,
        default_flag_id=stamp_rally.STAMP_RALLY_FLAG_ID,
        static=False,
        description=("Solrock stamp; shared two-slot Claydol card; level-30 stamp "
                     "rewards and level-50 Celebi grand prize"))
    registry.register_legacy(
        stamp_rally.GIFT_LUNATONE_STAMP,
        stamp_rally.build_lunatone_stamp_event,
        default_flag_id=stamp_rally.STAMP_RALLY_FLAG_ID,
        static=False,
        description=("Lunatone stamp; shared two-slot Claydol card; level-30 stamp "
                     "rewards and level-50 Celebi grand prize"))
    registry.register_definition(wonder_card_events.PORYGON_TM_GIFT)
    return registry


GIFT_REGISTRY = build_default_registry()


__all__ = [
    "GIFT_REGISTRY", "GiftCatalogEntry", "GiftRegistry",
    "add_flag_id_argument", "build_default_registry", "resolve_flag_id",
]
