#!/usr/bin/env python3
"""Validation and execution tests for declarative Mystery Gift authoring."""

from dataclasses import FrozenInstanceError
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from frlgsim import charmap, gift_composer as gc  # noqa: E402
from frlgsim import gift_registry, mg_script, mg_server, stamp_rally, wonder_card  # noqa: E402
from test_mystery_gift_end_to_end import _run_full_stack  # noqa: E402


class ScriptVM:
    """Small model for the opcodes emitted by gift_composer."""

    BASE = 0x08000000

    def __init__(self, script, *, variables=None, flags=None, bag_space=True,
                 mon_results=(), party_size=1):
        self.script = script
        self.pc = 0
        self.vars = dict(variables or {})
        self.flags = set(flags or ())
        self.bag_space = bag_space
        self.mon_results = list(mon_results)
        self.party_size = party_size
        self.comparison = 0
        self.items = []
        self.mons = []
        self.eggs = []
        self.moves = []
        self.sprites = []
        self.battles = []
        self.messages = []
        self.ended = False

    def u16(self):
        value = int.from_bytes(self.script[self.pc:self.pc + 2], "little")
        self.pc += 2
        return value

    def u32(self):
        value = int.from_bytes(self.script[self.pc:self.pc + 4], "little")
        self.pc += 4
        return value

    def jump(self, pointer):
        self.pc = pointer - self.BASE

    def var(self, variable):
        return self.vars.get(variable, 0)

    def result(self):
        return self.mon_results.pop(0) if self.mon_results else 0

    def run(self):
        for _step in range(10000):
            op = self.script[self.pc]
            self.pc += 1
            if op == 0x02:  # end
                self.ended = True
                return self
            if op in (0x5A, 0x68, 0x6A, 0x6C, 0x66, 0x6D):
                continue
            if op == 0x09:  # callstd
                assert self.script[self.pc] == 0
                self.pc += 1
                self.items.append((self.var(0x8000), self.var(0x8001)))
                self.vars[0x800D] = 1
            elif op == 0x16:  # setvar
                variable, value = self.u16(), self.u16()
                self.vars[variable] = value
            elif op == 0x17:  # addvar
                variable, value = self.u16(), self.u16()
                self.vars[variable] = (self.var(variable) + value) & 0xFFFF
            elif op == 0x1A:  # setorcopyvar
                variable, value = self.u16(), self.u16()
                self.vars[variable] = value
            elif op == 0x21:  # compare var/value
                variable, value = self.u16(), self.u16()
                self.comparison = 1 if self.var(variable) == value else 0
            elif op == 0x28:  # delay
                self.u16()
            elif op == 0x29:  # setflag
                self.flags.add(self.u16())
            elif op == 0x2A:  # clearflag
                self.flags.discard(self.u16())
            elif op == 0x2B:  # checkflag
                self.comparison = 1 if self.u16() in self.flags else 0
            elif op == 0x42:  # getplayerxy
                x, y = self.u16(), self.u16()
                self.vars[x], self.vars[y] = 10, 20
            elif op == 0x43:  # getpartysize
                self.vars[0x800D] = self.party_size
            elif op == 0x46:  # checkitemspace
                self.u16()
                self.u16()
                if isinstance(self.bag_space, list):
                    available = self.bag_space.pop(0)
                elif isinstance(self.bag_space, tuple):
                    available = self.bag_space[0]
                    self.bag_space = self.bag_space[1:]
                else:
                    available = self.bag_space
                self.vars[0x800D] = int(available)
            elif op == 0x79:  # givemon
                species = self.u16()
                level = self.script[self.pc]
                self.pc += 1
                item = self.u16()
                self.pc += 9
                result = self.result()
                self.vars[0x800D] = result
                if result != gc.MON_CANT_GIVE:
                    self.mons.append((species, level, item))
            elif op == 0x7A:  # giveegg
                species = self.u16()
                result = self.result()
                self.vars[0x800D] = result
                if result != gc.MON_CANT_GIVE:
                    self.eggs.append(species)
            elif op == 0x7B:  # setmonmove
                party, slot, move = self.script[self.pc], self.script[self.pc + 1], \
                    int.from_bytes(self.script[self.pc + 2:self.pc + 4], "little")
                self.pc += 4
                self.moves.append((party, slot, move))
            elif op == 0xAA:  # createvobject
                graphics, sprite = self.script[self.pc], self.script[self.pc + 1]
                self.pc += 2
                x, y = self.u16(), self.u16()
                elevation, direction = self.script[self.pc], self.script[self.pc + 1]
                self.pc += 2
                self.sprites.append((graphics, sprite, self.var(x) if x >= 0x4000 else x,
                                     self.var(y) if y >= 0x4000 else y,
                                     elevation, direction))
            elif op == 0xB6:  # setwildbattle
                species = self.u16()
                level = self.script[self.pc]
                self.pc += 1
                item = self.u16()
                self.battles.append((species, level, item))
            elif op == 0xB7:  # dowildbattle
                continue
            elif op == 0xB8:  # setvaddress
                assert self.u32() == self.BASE
            elif op == 0xB9:  # vgoto
                self.jump(self.u32())
            elif op == 0xBB:  # vgoto_if
                condition, pointer = self.script[self.pc], int.from_bytes(
                    self.script[self.pc + 1:self.pc + 5], "little")
                self.pc += 5
                assert condition == 1
                if self.comparison:
                    self.jump(pointer)
            elif op == 0xBD:  # vmessage
                pointer = self.u32() - self.BASE
                end = self.script.index(0xFF, pointer)
                self.messages.append(self.script[pointer:end])
            else:
                raise AssertionError(f"unknown emitted opcode 0x{op:02x} at {self.pc - 1}")
        raise AssertionError("script did not terminate")


def _card(title="COMPOSED GIFT", flag_id=1008):
    return gc.WonderCardSpec(
        icon_species=wonder_card.SPECIES_CELEBI,
        title=title,
        subtitle="A composed event",
        body=("Visit the deliveryman.",),
        default_flag_id=flag_id)


def _plan(*stages):
    return gc.DeliveryPlan(delivery=tuple(stages))


def _hooks(*stages):
    return gc.DeliveryPlan(pre_stages=tuple(stages))


def _gift(slug, delivery, *, card=None, repeatable=False,
          intro_message="A MYSTERY GIFT has arrived!",
          completed_message=gc.DEFAULT_COMPLETED_MESSAGE):
    return gc.WonderGift(
        slug=slug, card=card or _card(), intro_message=intro_message,
        event=gc.GiftSpec(repeatable=repeatable), delivery=delivery,
        completed_message=completed_message)


def _rally(slug, slots, completion, *, card=None,
           intro_message="Let us check your STAMPS!",
           completed_message="This STAMP RALLY is complete.",
           shared=None):
    return gc.WonderGift(
        slug=slug, card=card or _card(), intro_message=intro_message,
        event=gc.StampRallySpec(
            slots=tuple(slots), completion=completion),
        delivery=shared or gc.DeliveryPlan(),
        completed_message=completed_message)


def test_models_are_immutable_and_compile_to_the_existing_distribution_interface():
    definition = _gift(
        "composed-gift", _plan(gc.DeliveryStage(gc.Message("Hello, {PLAYER}!"))))
    try:
        definition.slug = "changed"
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("WonderGift accepted mutation")
    distribution = gc.compile_definition(definition)
    assert isinstance(distribution, stamp_rally.MysteryGiftDistribution)
    assert len(distribution.card) == 332
    assert len(distribution.ram_script) <= 995
    assert int.from_bytes(distribution.card[:2], "little") == 1008
    assert distribution.card[9] == 0
    assert gc.DeliveryStage(actions=(gc.Message("Keyword"),)).actions == \
        (gc.Message("Keyword"),)


def test_ordinary_cursor_resumes_failed_stage_without_repeating_prior_reward():
    definition = _gift(
        "resume-gift", _plan(
            gc.DeliveryStage(gc.Message("First"), gc.GiveItem(1)),
            gc.DeliveryStage(gc.Message("Second"), gc.GivePokemon(25, 10)),
        ))
    script = gc.compile_definition(definition).ram_script
    first = ScriptVM(script, mon_results=(gc.MON_CANT_GIVE,)).run()
    assert first.items == [(1, 1)]
    assert first.mons == []
    assert first.vars[gc.VAR_MYSTERY_GIFT_1] == 1
    assert gc.FLAG_MYSTERY_GIFT_DONE not in first.flags

    second = ScriptVM(
        script, variables=first.vars, flags=first.flags, mon_results=(0,)).run()
    assert second.items == []
    assert second.mons == [(25, 10, 0)]
    assert second.vars[gc.VAR_MYSTERY_GIFT_1] == 2
    assert gc.FLAG_MYSTERY_GIFT_DONE in second.flags
    assert wonder_card.flag_for_flag_id(1008) in second.flags

    revisit = ScriptVM(script, variables=second.vars, flags=second.flags).run()
    assert revisit.items == revisit.mons == []
    assert revisit.messages


def test_item_preflight_and_custom_move_party_preflight_do_not_advance_cursor():
    item_def = _gift(
        "item-gift", _plan(gc.DeliveryStage(gc.GiveItem(1, 5))))
    item_run = ScriptVM(
        gc.compile_definition(item_def).ram_script, bag_space=False).run()
    assert item_run.items == []
    assert item_run.vars.get(gc.VAR_MYSTERY_GIFT_1, 0) == 0

    mon_def = _gift(
        "moves-gift", _plan(gc.DeliveryStage(
            gc.GivePokemon(251, 50, moves=(73, 105, 215, 219)))))
    full = ScriptVM(gc.compile_definition(mon_def).ram_script, party_size=6).run()
    assert full.mons == full.moves == []
    assert full.vars.get(gc.VAR_MYSTERY_GIFT_1, 0) == 0
    room = ScriptVM(gc.compile_definition(mon_def).ram_script, party_size=5).run()
    assert room.mons == [(251, 50, 0)]
    assert room.moves == [(7, 0, 73), (7, 1, 105), (7, 2, 215), (7, 3, 219)]


def test_egg_sprite_and_terminal_battle_execute_in_order_and_checkpoint_first():
    definition = _gift(
        "encounter-gift", _plan(
            gc.DeliveryStage(gc.GiveEgg(172)),
            gc.DeliveryStage(
                gc.ShowSprite(143, gc.RelativeToPlayer(dx=1), delay_frames=30),
                gc.Message("Prepare yourself!"),
                gc.BattlePokemon(243, 65, held_item=1)),
        ))
    run = ScriptVM(gc.compile_definition(definition).ram_script).run()
    assert run.eggs == [172]
    assert run.sprites == [(143, 0, 11, 20, 3, 3)]
    assert run.battles == [(243, 65, 1)]
    assert run.vars[gc.VAR_MYSTERY_GIFT_1] == 2
    assert gc.FLAG_MYSTERY_GIFT_DONE in run.flags


def test_repeatable_plan_resets_its_cursor_after_each_complete_run():
    definition = _gift(
        "repeat-gift", _plan(gc.DeliveryStage(gc.GiveItem(1))), repeatable=True)
    script = gc.compile_definition(definition).ram_script
    first = ScriptVM(script).run()
    assert first.items == [(1, 1)]
    assert first.vars[gc.VAR_MYSTERY_GIFT_1] == 0
    assert gc.FLAG_MYSTERY_GIFT_DONE not in first.flags
    second = ScriptVM(script, variables=first.vars, flags=first.flags).run()
    assert second.items == [(1, 1)]


def test_more_than_fifteen_stages_use_one_integer_cursor():
    definition = _gift(
        "long-gift", _plan(*(
            gc.DeliveryStage(gc.Message(str(index))) for index in range(16))))
    run = ScriptVM(gc.compile_definition(definition).ram_script).run()
    assert run.vars[gc.VAR_MYSTERY_GIFT_1] == 16
    assert len(run.flags & set(range(0x3D9, 0x3E8))) == 0


def test_rally_slot_cursors_are_independent_and_completion_resumes():
    rally = _rally(
        "composed-rally", (
            gc.StampSlot("alpha-stamp", 349, 1, _hooks(
                gc.DeliveryStage(gc.GiveItem(1)),
                gc.DeliveryStage(gc.Message("Alpha complete")))),
            gc.StampSlot("beta-stamp", 348, 2, _hooks(
                gc.DeliveryStage(gc.GiveEgg(172)))),
        ), _hooks(gc.DeliveryStage(gc.GivePokemon(251, 50))),
        card=_card("COMPOSED RALLY", flag_id=1009))
    distributions = gc.compile_definition(rally)
    assert tuple(distributions) == ("alpha-stamp", "beta-stamp")
    assert distributions["alpha-stamp"].card == distributions["beta-stamp"].card
    assert distributions["alpha-stamp"].card[9] == 2
    assert distributions["alpha-stamp"].stamp == bytes.fromhex("5d010100")
    assert bytes.fromhex("16b7400100") in distributions["alpha-stamp"].activation_script
    assert bytes.fromhex("2ab00216b7400100") in \
        distributions["alpha-stamp"].install_activation_script
    assert bytes.fromhex("16b8400100") in distributions["beta-stamp"].activation_script

    script = distributions["alpha-stamp"].ram_script
    alpha = ScriptVM(script, variables={gc.VAR_MYSTERY_GIFT_2: 1}).run()
    assert alpha.items == [(1, 1)]
    assert alpha.vars[gc.VAR_MYSTERY_GIFT_2] == 3
    assert alpha.vars.get(gc.VAR_MYSTERY_GIFT_1, 0) == 0

    beta = ScriptVM(
        script, variables={**alpha.vars, gc.VAR_MYSTERY_GIFT_2 + 1: 1},
        flags=alpha.flags, mon_results=(0, gc.MON_CANT_GIVE)).run()
    assert beta.items == []
    assert beta.eggs == [172]
    assert beta.vars[gc.VAR_MYSTERY_GIFT_2] == 3
    assert beta.vars[gc.VAR_MYSTERY_GIFT_2 + 1] == 2
    assert beta.vars.get(gc.VAR_MYSTERY_GIFT_1, 0) == 0
    assert gc.FLAG_MYSTERY_GIFT_DONE not in beta.flags

    complete = ScriptVM(
        script, variables=beta.vars, flags=beta.flags, mon_results=(0,)).run()
    assert complete.mons == [(251, 50, 0)]
    assert complete.vars[gc.VAR_MYSTERY_GIFT_1] == 1
    assert gc.FLAG_MYSTERY_GIFT_DONE in complete.flags


def test_wonder_gift_composes_rally_hooks_around_shared_delivery_in_order():
    rally = _rally(
        "ordered-rally",
        (gc.StampSlot(
            "ordered-stamp", 349, 1,
            gc.DeliveryPlan(
                pre_stages=(gc.DeliveryStage(gc.Message("SLOT PRE")),),
                post_stages=(gc.DeliveryStage(gc.Message("SLOT POST")),))),),
        gc.DeliveryPlan(
            pre_stages=(gc.DeliveryStage(gc.Message("COMP PRE")),),
            post_stages=(gc.DeliveryStage(gc.Message("COMP POST")),)),
        intro_message="INTRO",
        completed_message="COMPLETED",
        shared=gc.DeliveryPlan(delivery=(
            gc.DeliveryStage(gc.Message("MIDDLE")),)))
    script = gc.compile_definition(rally)["ordered-stamp"].ram_script
    run = ScriptVM(
        script, variables={gc.VAR_MYSTERY_GIFT_2: 1}).run()
    assert [charmap.decode(message) for message in run.messages] == [
        "INTRO", "SLOT PRE", "MIDDLE", "SLOT POST",
        "COMP PRE", "MIDDLE", "COMP POST",
    ]
    assert run.vars[gc.VAR_MYSTERY_GIFT_2] == 4
    assert run.vars[gc.VAR_MYSTERY_GIFT_1] == 3
    assert gc.FLAG_MYSTERY_GIFT_DONE in run.flags

    revisit = ScriptVM(script, variables=run.vars, flags=run.flags).run()
    assert [charmap.decode(message) for message in revisit.messages] == ["COMPLETED"]


def test_six_slot_rally_uses_vars_two_through_seven():
    slots = tuple(
        gc.StampSlot(
            f"slot-{index}-stamp", index + 1, index + 1,
            _hooks(gc.DeliveryStage(gc.Message("Stamp"))))
        for index in range(6))
    rally = _rally(
        "six-slot-rally", slots,
        _hooks(gc.DeliveryStage(gc.Message("Complete"))),
        card=_card("SIX SLOT RALLY"))
    distributions = gc.compile_definition(rally)
    script = next(iter(distributions.values())).ram_script
    variables = {gc.VAR_MYSTERY_GIFT_2 + index: 1 for index in range(6)}
    run = ScriptVM(script, variables=variables).run()
    assert [run.vars[gc.VAR_MYSTERY_GIFT_2 + index] for index in range(6)] == [2] * 6
    assert run.vars[gc.VAR_MYSTERY_GIFT_1] == 1
    assert gc.FLAG_MYSTERY_GIFT_DONE in run.flags


def test_composed_stamp_distribution_survives_impaired_reliable_rfu_stack():
    rally = _rally(
        "radio-rally", (
            gc.StampSlot(
                "radio-stamp", 25, 7,
                _hooks(gc.DeliveryStage(gc.Message("Radio reward")))),),
        _hooks(gc.DeliveryStage(gc.Message("Rally complete"))),
        card=_card("RADIO RALLY"))
    distribution = gc.compile_definition(rally)["radio-stamp"]
    run = _run_full_stack(payload=distribution, max_ms=9000)
    assert run.engine.result == mg_server.SVR_MSG_STAMP_SENT
    assert run.console.result == mg_script.CLI_MSG_STAMP_RECEIVED
    assert run.console.stamps == [(25, 7)]
    assert run.console.vars[gc.VAR_MYSTERY_GIFT_2] == 1
    assert run.console.dropped_inits == run.console.dropped_fragments == 0
    assert run.radio.dropped and run.radio.duplicated


def _assert_invalid(definition, fragment):
    try:
        gc.validate_definition(definition)
    except gc.GiftValidationError as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError(f"definition unexpectedly valid: {definition}")


def test_validation_reports_precise_paths_and_execution_hazards():
    _assert_invalid(_gift(
        "bad-rewards", _plan(gc.DeliveryStage(
            gc.GiveItem(1), gc.GivePokemon(1, 5)))),
        "bad-rewards.delivery.delivery[0]")
    _assert_invalid(_gift(
        "bad-battle", _plan(
            gc.DeliveryStage(gc.BattlePokemon(1, 5)),
            gc.DeliveryStage(gc.Message("Too late")))),
        "battle must be the last action")
    _assert_invalid(_gift(
        "bad-moves", _plan(gc.DeliveryStage(
            gc.GivePokemon(1, 5, moves=(1, 2, 3, 4, 5))))),
        "bad-moves.delivery.delivery[0].actions[0].moves")
    _assert_invalid(_gift(
        "bad-empty", gc.DeliveryPlan()),
        "composed delivery path must contain at least one stage")

    _assert_invalid(gc.WonderGift(
        slug="bad-top-hooks", card=_card(), intro_message="Intro",
        event=gc.GiftSpec(),
        delivery=gc.DeliveryPlan(
            pre_stages=(gc.DeliveryStage(gc.Message("Wrong lane")),),
            delivery=(gc.DeliveryStage(gc.Message("Gift")),)),
        completed_message="Done"),
        "top-level delivery uses only the delivery section")

    wrong_slot_lane = _rally(
        "bad-slot-lane", (gc.StampSlot(
            "bad-slot-stamp", 1, 1,
            gc.DeliveryPlan(delivery=(
                gc.DeliveryStage(gc.Message("Wrong lane")),))),),
        _hooks(gc.DeliveryStage(gc.Message("Done"))))
    _assert_invalid(
        wrong_slot_lane, "stamp slots use only pre_stages and post_stages")


def test_validation_uses_actual_frlg_ranges_and_forbids_slot_battles():
    bad_values = (
        (gc.GiveItem(375), "item must be an integer from 1 through 374"),
        (gc.GivePokemon(412, 5), "species must be an integer from 1 through 411"),
        (gc.GiveEgg(1, failure_message="Bad {TOKEN}"),
         "only supported message token is {PLAYER}"),
        (gc.ShowSprite(152, gc.MapPosition(1, 1)),
         "graphics ID must be an integer from 0 through 151"),
        (gc.ShowSprite(1, gc.MapPosition(0x4000, 1)),
         "map x must be an integer from 0 through 16383"),
    )
    for index, (action, fragment) in enumerate(bad_values):
        _assert_invalid(_gift(
            f"bad-value-{index}",
            _plan(gc.DeliveryStage(action))), fragment)

    slot_battle = _rally(
        "battle-rally", (
            gc.StampSlot(
                "battle-stamp", 1, 1,
                _hooks(gc.DeliveryStage(gc.BattlePokemon(1, 5)))),),
        _hooks(gc.DeliveryStage(gc.Message("Done"))))
    _assert_invalid(slot_battle, "battles are not allowed in stamp-slot delivery plans")

    invalid_flag = _gift(
        "flag-gift", _plan(gc.DeliveryStage(gc.Message("Gift"))))
    try:
        gc.compile_definition(invalid_flag, flag_id=1020)
    except gc.GiftValidationError as exc:
        assert "flagId" in str(exc)
    else:
        raise AssertionError("runtime flag override 1020 was accepted")


def test_validation_rejects_seven_slots_duplicates_and_oversized_scripts():
    seven = tuple(gc.StampSlot(
        f"stamp-{index}", index + 1, index + 1,
        _hooks(gc.DeliveryStage(gc.Message("x")))) for index in range(7))
    _assert_invalid(_rally(
        "seven-rally", seven,
        _hooks(gc.DeliveryStage(gc.Message("done")))), "1 through 6 slots")
    duplicate = _rally(
        "duplicate-rally", (
            gc.StampSlot("one-stamp", 1, 1, _hooks(gc.DeliveryStage(gc.Message("x")))),
            gc.StampSlot("two-stamp", 1, 2, _hooks(gc.DeliveryStage(gc.Message("y")))),
        ), _hooks(gc.DeliveryStage(gc.Message("done"))))
    _assert_invalid(duplicate, "stamp species must be unique")

    huge = _gift(
        "huge-gift", _plan(gc.DeliveryStage(gc.Message("A" * 900))))
    try:
        gc.compile_definition(huge)
    except gc.GiftValidationError as exc:
        assert "compiled RAM script" in str(exc) and "maximum is 995" in str(exc)
        assert "messages=" in str(exc)
    else:
        raise AssertionError("oversized RAM script compiled")


def test_registry_supports_composed_static_gifts_and_live_only_rally_slots():
    registry = gift_registry.GiftRegistry()
    ordinary = _gift(
        "registry-gift", _plan(gc.DeliveryStage(gc.Message("Registered"))))
    registry.register_definition(ordinary)
    assert registry.live_choices == registry.static_choices == ("registry-gift",)
    card, script = registry.build_static("registry-gift")
    assert len(card) == 332 and script

    rally = _rally(
        "registry-rally", (
            gc.StampSlot("registry-stamp", 1, 1,
                         _hooks(gc.DeliveryStage(gc.Message("Stamp")))),),
        _hooks(gc.DeliveryStage(gc.Message("Done"))))
    registry.register_definition(rally)
    assert "registry-stamp" in registry.live_choices
    assert "registry-stamp" not in registry.static_choices
    try:
        registry.build_static("registry-stamp")
    except ValueError as exc:
        assert "live-host-only" in str(exc)
    else:
        raise AssertionError("stamp exported as a static gift")

    collision = _rally(
        "collision-rally", (
            gc.StampSlot("new-stamp", 2, 2,
                         _hooks(gc.DeliveryStage(gc.Message("New")))),
            gc.StampSlot("registry-stamp", 3, 3,
                         _hooks(gc.DeliveryStage(gc.Message("Collision")))),
        ), _hooks(gc.DeliveryStage(gc.Message("Done"))))
    before = registry.live_choices
    try:
        registry.register_definition(collision)
    except ValueError as exc:
        assert "duplicate Mystery Gift slug" in str(exc)
    else:
        raise AssertionError("registry accepted a duplicate slug")
    assert registry.live_choices == before


if __name__ == "__main__":
    tests = [(name, value) for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    for name, test in tests:
        test()
        print("ok   ", name)
    print(f"\n{len(tests)}/{len(tests)} passed")
