"""Read the decompilation's C sources the way the compiler did: definition order, and CALL order.

This is the offline half of bs84's method. A dump gives a body's `bl` targets in address order
(`thumb.bl_targets`); the decomp gives the same function's calls in the order agbcc has to emit
them; zipping the two names every worker behind a table entry without spending a run. bs111, bs112
and bs121 did exactly that by eye - "the decomp's call order names each bl" - and every name it
produced held up. What is here is that reading, mechanised, so it can be run over all 500-odd
bodies this project holds instead of the handful a session has time for.

THREE THINGS DECIDE WHETHER THE ZIP IS EVIDENCE OR A GUESS.

1. EVALUATION ORDER, NOT TOKEN ORDER. `VarGet(ScriptReadHalfword(ctx))` compiles to
   `bl ScriptReadHalfword` then `bl VarGet`: the argument is computed before the call that consumes
   it. So the call list is built POST-ORDER - an inner call is emitted before the one it feeds.
   Reading left to right instead would misalign nearly every ScrCmd body, because that is their
   shape.

2. THE RIGHT BUILD. The Switch release is `firered_switch`: GAME_VERSION=FIRERED,
   GAME_REVISION=10, MODERN=0 [decomp:Makefile:227], so `#if REVISION >= 0xA` is LIVE code and
   `#if defined(LEAFGREEN)` is not. Reading both branches of 203 conditionals would add calls no
   `bl` corresponds to. `NDEBUG` is a MEASUREMENT rather than a build flag: ScrCmd_special's body
   on the cartridge makes exactly two calls (bs121), and the assert branch would add a third, so
   the asserts compile to nothing.

3. A LENGTH MATCH IS THE ALIGNMENT PROOF, and anything else is rejected. agbcc inlines, emits
   `__divsi3` and friends for arithmetic the source does not name, and expands macros this parser
   reads as calls. Every one of those changes the COUNT, so a body whose two lists are the same
   length is one where none of it happened; a body where they differ is dropped rather than guessed
   at. `scripts/gen_worker_names.py` adds the checks on top - a name already measured must land
   back on its own address, two callers of the same address must agree, and a file's names must
   come back in the order the file defines them.

The parser is deliberately small and syntactic: no types, no scope, and only the preprocessor it
takes to pick the right branch. It only has to be right about which identifiers are called and in
what order, and it says so by refusing to guess - an indirect call through a table becomes
`INDIRECT` (a `bl` to a veneer on this ROM, so it holds a slot) rather than being dropped, which
keeps the count honest.
"""
import re

# A call through a pointer - `gSpecials[index]()`, or `(*specialPtr)()`. agbcc turns it into `bl` a
# veneer (0x081E2224 on this cartridge, `CALL_VIA_R0`), so it occupies one slot in the measured
# list; what it does not do is name anything, and the caller skips that slot.
INDIRECT = "*indirect*"

# The `firered_switch` build [decomp:Makefile:227]. An identifier not in here is 0, which is what C
# does with an undefined name in `#if`. LIBRFU_VERSION only gates librfu, which no table reaches.
BUILD = {
    "REVISION": 0xA,
    "FIRERED": 1,
    "MODERN": 0,
    "NDEBUG": 1,
    "LIBRFU_VERSION": 1026,
    "__STDC_VERSION__": 199409,
}

# Macros that emit no call at all, so whatever a body appended from inside their parentheses is
# dropped with them. The asserts expand to NOTHING in this build [decomp:include/gba/isagbprint.h:
# 53-57 under NDEBUG]; NELEMS and ARRAY_COUNT expand to a pair of `sizeof`s, which does not evaluate
# its argument either.
EMPTY_MACROS = frozenset({"AGB_ASSERT", "AGB_WARNING", "AGB_ASSERT_EX", "AGB_WARNING_EX",
                          "NELEMS", "ARRAY_COUNT"})

# Macros that look like a call and expand to arithmetic, so they emit no `bl` - but whatever is
# inside their parentheses IS evaluated and keeps its slot. `ScriptReadByte` is the one that
# mattered: `#define ScriptReadByte(ctx) (*(ctx->scriptPtr++))` [decomp:include/script.h:24], and
# reading it as a call put a phantom `bl` in 151 bodies, nearly half of everything that failed to
# align.
NO_CALL_MACROS = frozenset({"ScriptReadByte", "MAP_GROUP", "MAP_NUM", "BG_PLTT_ID", "OBJ_PLTT_ID",
                            "PLTT_SIZEOF"})

# Macros that dispatch on their argument COUNT to functions that are one symbol in the ROM:
# `#define GetMonData(...) CAT(GetMonData, NARG_8(__VA_ARGS__))(__VA_ARGS__)`
# [decomp:include/pokemon.h:343], and GetMonData2 is `__attribute__((alias("GetMonData3")))`
# [decomp:src/pokemon.c:2970] - one address, two names, and the source calls it by a third.
ALIASES = {"GetMonData": "GetMonData3", "GetBoxMonData": "GetBoxMonData3"}

# Keywords that take a parenthesised group without being a call. `sizeof` is the one that would
# otherwise produce a plausible-looking name.
NOT_CALLS = frozenset("""
if else while for switch return sizeof do case break continue goto default typedef struct union
enum static const volatile unsigned signed void register extern inline __attribute__ asm
""".split())

# Enough of the decomp's type vocabulary to tell a cast and a function-pointer declarator from a
# call: `(u8)(x)` and `u16 (*const *p)(void)` both put a `(` where a call through a pointer does.
TYPE_WORDS = frozenset("""
void bool8 bool16 bool32 char short int long float double signed unsigned
u8 u16 u32 u64 s8 s16 s32 s64 vu8 vu16 vu32 vs8 vs16 vs32 size_t
struct union enum const volatile
""".split())

_TOKEN = re.compile(r"[A-Za-z_]\w*|0[xX][0-9a-fA-F]+|\d+|->|\+\+|--|\S")

# A definition in this decomp is a signature at column 0 with its brace on the next line or the same
# one, which is what separates it from a call, a declaration (`;`) and an initialiser (`= {`). The
# same-line form is rare and is how `sloopsvc.c` - the Switch build's own hypercalls - is written.
_DEFINITION = re.compile(
    r"(?m)^(?P<sig>[A-Za-z_][A-Za-z0-9_ \t*]*?)(?P<name>[A-Za-z_]\w*)[ \t]*"
    r"\((?P<args>[^;{}]*)\)[ \t]*\n?\{",
)

_DIRECTIVE = re.compile(r"^[ \t]*#[ \t]*(\w+)[ \t]*(.*)$")


def strip_comments(text):
    """-> the source with comments and string/char literals blanked, newlines preserved.

    Blanked rather than deleted so a definition's line number survives: a name reported at the wrong
    line is a citation nobody can check."""
    out, i, n = [], 0, len(text)
    while i < n:
        two = text[i:i + 2]
        if two == "/*":
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            out.append("".join(c if c == "\n" else " " for c in text[i:end]))
            i = end
        elif two == "//":
            end = text.find("\n", i)
            end = n if end < 0 else end
            out.append(" " * (end - i))
            i = end
        elif text[i] in "\"'":
            quote, j = text[i], i + 1
            while j < n and text[j] != quote:
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
            out.append("".join(c if c == "\n" else " " for c in text[i:j]))
            i = j
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def evaluate(expression, build=None):
    """-> the truth of one `#if` expression under `build`, C's rules for an undefined name.

    Small on purpose: `defined`, the comparisons, `&&`, `||`, `!`, and integer literals. That covers
    every conditional in the decomp's C sources - `REVISION >= 0xA`, `defined(FIRERED)`,
    `!defined(NDEBUG) || REVISION >= 0xA`, `LOG_HANDLER == LOG_HANDLER_MGBA_PRINT`."""
    values = BUILD if build is None else build
    text = re.sub(r"defined\s*\(\s*(\w+)\s*\)", lambda m: str(int(m.group(1) in values)), expression)
    text = re.sub(r"defined\s+(\w+)", lambda m: str(int(m.group(1) in values)), text)
    text = re.sub(r"\b(0[xX][0-9a-fA-F]+|\d+)[uUlL]*\b", r"\1", text)
    text = re.sub(r"\w+", lambda m: (m.group(0) if re.fullmatch(r"0[xX][0-9a-fA-F]+|\d+", m.group(0))
                                     else str(values.get(m.group(0), 0))), text)
    text = text.replace("&&", " and ").replace("||", " or ").replace("!=", " __ne__ ")
    text = text.replace("!", " not ").replace(" __ne__ ", " != ")
    try:
        return bool(eval(text, {"__builtins__": {}}, {}))  # noqa: S307 - digits and operators only
    except Exception:
        return False


def preprocess(text, build=None):
    """-> the source with the branches this build does NOT compile blanked, line count preserved.

    203 `#if REVISION >= 0xA` blocks in the decomp's C sources are LIVE on the Switch cartridge and
    the `#else` beside them is not; reading both is how a call list ends up longer than the body it
    is meant to describe."""
    out, stack = [], []          # stack of [active here, some branch already taken]
    continuing = False
    for line in text.split("\n"):
        if continuing:
            continuing = line.rstrip().endswith("\\")
            out.append("")
            continue
        match = _DIRECTIVE.match(line)
        if not match:
            out.append(line if all(active for active, _taken in stack) else "")
            continue
        keyword, rest = match.group(1), match.group(2)
        outer = all(active for active, _taken in stack)
        if keyword in ("if", "ifdef", "ifndef"):
            if keyword == "ifdef":
                value = evaluate(f"defined({rest.split()[0]})" if rest.split() else "0", build)
            elif keyword == "ifndef":
                value = not evaluate(f"defined({rest.split()[0]})" if rest.split() else "0", build)
            else:
                value = evaluate(rest, build)
            stack.append([outer and value, value])
        elif keyword == "elif" and stack:
            taken = stack[-1][1]
            value = (not taken) and evaluate(rest, build)
            stack[-1] = [outer_of(stack) and value, taken or value]
        elif keyword == "else" and stack:
            taken = stack[-1][1]
            stack[-1] = [outer_of(stack) and not taken, True]
        elif keyword == "endif" and stack:
            stack.pop()
        continuing = line.rstrip().endswith("\\")
        out.append("")
    return "\n".join(out)


def outer_of(stack):
    """-> whether everything ENCLOSING the innermost conditional is active."""
    return all(active for active, _taken in stack[:-1])


def _is_type_list(tokens, open_index, close_index):
    """-> True if the parentheses hold a type rather than an expression.

    `(u8)(x)` is a cast and `u16 (*const *p)(void)` is a declarator; both put `(` after `)` the way
    a call through a pointer does, and only what is INSIDE tells them apart."""
    inside = tokens[open_index + 1:close_index]
    if not inside:
        return False
    words = [t for t in inside if t.isidentifier()]
    stars = [t for t in inside if t == "*"]
    if not words or len(words) + len(stars) != len(inside):
        return False
    return words[0] in TYPE_WORDS or (words[0].endswith("_t") and len(words) == 1)


def _is_indirect_call(tokens, open_index):
    """-> True if the `(` at open_index calls through what the group before it evaluated to.

    Three things put a `(` straight after a `)`, and only one of them is a call:
    `(*fn)()` is, `(u8)(x)` is a cast, `u16 (*p)(void)` is a declarator, and
    `if (a < b)\\n    f();` is a CONDITION with a statement after it - which is the one that cost a
    spurious slot in ScrCmd_special until the keyword before the group was checked."""
    if tokens[open_index - 1] == "]":
        return True
    if tokens[open_index - 1] != ")":
        return False
    depth, index = 0, open_index - 1
    while index >= 0:
        if tokens[index] == ")":
            depth += 1
        elif tokens[index] == "(":
            depth -= 1
            if depth == 0:
                before = tokens[index - 1] if index else ""
                if before in NOT_CALLS:
                    return False
                return not _is_type_list(tokens, index, open_index - 1)
        index -= 1
    return False


def call_sequence(body):
    """-> [called name] in the order agbcc has to emit the `bl`s, INDIRECT for a call by pointer.

    Post-order: a call is appended when its closing parenthesis is reached, so every call in its
    arguments is already in the list. That is evaluation order, and it is what the measured `bl`
    order is. An `EMPTY_MACROS` call takes whatever was appended inside it back out again, because
    the compiler never saw any of it."""
    tokens = _TOKEN.findall(body)
    calls, stack = [], []
    for index, token in enumerate(tokens):
        if token == "(":
            previous = tokens[index - 1] if index else ""
            if previous.isidentifier() and previous not in NOT_CALLS and previous not in TYPE_WORDS:
                stack.append((previous, len(calls)))
            elif previous in (")", "]") and _is_indirect_call(tokens, index):
                stack.append((INDIRECT, len(calls)))
            else:
                stack.append((None, len(calls)))
        elif token == ")" and stack:
            name, mark = stack.pop()
            if name in EMPTY_MACROS:
                del calls[mark:]
            elif name in NO_CALL_MACROS:
                pass
            elif name is not None:
                calls.append(ALIASES.get(name, name))
    return calls


def functions(text, build=None):
    """-> [(name, line, body)] for the definitions in one C source, IN DEFINITION ORDER.

    The order is a check on every name this method proposes: agbcc emits a translation unit's
    functions in the order they are written, so two names proposed out of the same file must come
    back with addresses in the same order. That is how `VarSet` was checked without a run -
    event_data.c defines GetVarPointer, VarGet, VarSet and the three addresses ascend."""
    source = preprocess(strip_comments(text), build)
    out = []
    for match in _DEFINITION.finditer(source):
        if match.group("name") in NOT_CALLS or match.group("sig").strip().endswith("="):
            continue
        start = match.end() - 1
        end = source.find("\n}", start)
        if end < 0:
            continue
        out.append((match.group("name"), source.count("\n", 0, match.start()) + 1,
                    source[start:end + 2]))
    return out


def read_tree(paths, build=None):
    """-> ({name: [calls]}, {name: (file, index in file)}) over a list of C sources.

    A name defined in two translation units (the decomp has a few) is dropped from both maps: which
    one a `bl` reached is exactly what this method cannot tell from the source."""
    calls, where, duplicates = {}, {}, set()
    for path in paths:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for index, (name, _line, body) in enumerate(functions(text, build)):
            if name in calls:
                duplicates.add(name)
                continue
            calls[name] = call_sequence(body)
            where[name] = (path.name, index)
    for name in duplicates:
        calls.pop(name, None)
        where.pop(name, None)
    return calls, where
