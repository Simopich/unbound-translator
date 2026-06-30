"""Pokemon Gen III PCS text codec used by the local extract/inject tools."""

from __future__ import annotations

from dataclasses import dataclass
import re


TERMINATOR = 0xFF
NEWLINE = 0xFE
LINE_SCROLL = 0xFA
PARAGRAPH = 0xFB
CONTROL_CODE_PREFIX = 0xFC
ESCAPE_PREFIX = 0xFD
F7_PREFIX = 0xF7
BUTTON_PREFIX = 0xF8
F9_PREFIX = 0xF9


PCS_CHAR_TABLE: dict[int, str] = {}

_CHAR_RANGES = [
    (0x00, " ÀÁÂÇÈÉÊËÌ"),
    (0x0B, "ÎÏÒÓÔ"),
    (0x10, "ŒÙÚÛÑßàá"),
    (0x19, "çèéêëì"),
    (0x20, "îïòóôœùúûñºª"),
    (0x5A, "Í%()"),
    (0xA1, "0123456789"),
    (0xAB, "!?.-‧"),
    (0xB7, "$,*/"),
    (0xBB, "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    (0xD5, "abcdefghijklmnopqrstuvwxyz"),
    (0xF0, ":ÄÖÜäöü"),
]

for _start, _chars in _CHAR_RANGES:
    for _index, _char in enumerate(_chars):
        PCS_CHAR_TABLE[_start + _index] = _char

PCS_CHAR_TABLE.update(
    {
        0x2C: "\\e",
        0x2D: "&",
        0x2E: "\\+",
        0x34: "\\Lv",
        0x35: "=",
        0x36: ";",
        0x48: "\\r",
        0x51: "¿",
        0x52: "¡",
        0x53: "\\pk",
        0x54: "\\mn",
        0x55: "\\Po",
        0x56: "\\Ke",
        0x57: "\\Bl",
        0x58: "\\Lo",
        0x59: "\\Ck",
        0x68: "â",
        0x6F: "í",
        0x79: "\\au",
        0x7A: "\\ad",
        0x7B: "\\al",
        0x7C: "\\ar",
        0x84: "\\d",
        0x85: "\\<",
        0x86: "\\>",
        0xB0: "\\.",
        0xB1: "\\qo",
        0xB2: "\\qc",
        0xB3: "‘",
        0xB4: "’",
        0xB5: "\\sm",
        0xB6: "\\sf",
    }
)

CHAR_TO_BYTE = {char: value for value, char in PCS_CHAR_TABLE.items()}
CHAR_TO_BYTE["'"] = 0xB4


FC_ARG_COUNTS: dict[int, int] = {
    0x04: 3,
    0x09: 0,
    0x0A: 0,
    0x0B: 2,
    0x10: 2,
}


def fc_arg_count(command: int) -> int:
    if command in FC_ARG_COUNTS:
        return FC_ARG_COUNTS[command]
    return 0 if command > 0x14 else 1


def build_cc_token_pattern() -> str:
    by_digits: dict[int, list[str]] = {}
    for cmd in range(256):
        argc = fc_arg_count(cmd)
        hex_digits = 2 + 2 * argc
        cmd_hex = f"{cmd:02X}"
        by_digits.setdefault(hex_digits, []).append(cmd_hex)

    parts = []
    for hex_digits in sorted(by_digits.keys(), reverse=True):
        cmds = by_digits[hex_digits]
        args_digits = hex_digits - 2
        cmd_patterns = []
        for c in cmds:
            pattern_c = "".join(f"[{ch.upper()}{ch.lower()}]" if ch.isalpha() else ch for ch in c)
            cmd_patterns.append(pattern_c)
        cmd_group = "(?:" + "|".join(cmd_patterns) + ")"
        if args_digits > 0:
            parts.append(f"\\\\CC{cmd_group}[0-9A-Fa-f]{{{args_digits}}}")
        else:
            parts.append(f"\\\\CC{cmd_group}")
    return "(?:" + "|".join(parts) + ")"


CC_TOKEN_PATTERN = build_cc_token_pattern()



FD_MACROS: dict[int, str] = {
    0x01: "[player]",
    0x02: "[buffer1]",
    0x03: "[buffer2]",
    0x04: "[buffer3]",
    0x05: "[kun]",
    0x06: "[rival]",
}

F9_MACROS: dict[int, str] = {
    0x00: "[up]",
    0x01: "[down]",
    0x02: "[left]",
    0x03: "[right]",
    0x04: "[plus]",
    0x05: "[LV]",
    0x06: "[PP]",
    0x07: "[ID]",
    0x08: "[No]",
    0x09: "[_]",
    0x0A: "[1]",
    0x0B: "[2]",
    0x0C: "[3]",
    0x0D: "[4]",
    0x0E: "[5]",
    0x0F: "[6]",
    0x10: "[7]",
    0x11: "[8]",
    0x12: "[9]",
    0x13: "[left_parenthesis]",
    0x14: "[right_parenthesis]",
    0x15: "[super_effective]",
    0x16: "[not_very_effective]",
    0x17: "[not_effective]",
    0xD0: "[down_bar]",
    0xD1: "[vertical_bar]",
    0xD2: "[up_bar]",
    0xD3: "[tilde]",
    0xD4: "[left_parenthesis_bold]",
    0xD5: "[right_parenthesis_bold]",
    0xD6: "[subset_of]",
    0xD7: "[greater_than_short]",
    0xD8: "[left_eye]",
    0xD9: "[right_eye]",
    0xDA: "[commercial_at]",
    0xDB: "[semicolon]",
    0xDC: "[bold_plus_1]",
    0xDD: "[bold_minus]",
    0xDE: "[bold_equals]",
    0xDF: "[dazed]",
    0xE0: "[tongue]",
    0xE1: "[delta]",
    0xE2: "[acute]",
    0xE3: "[grave]",
    0xE4: "[circle]",
    0xE5: "[triangle]",
    0xE6: "[square]",
    0xE7: "[heart]",
    0xE8: "[moon]",
    0xE9: "[eighth_note]",
    0xEA: "[half_circle]",
    0xEB: "[thunderbolt]",
    0xEC: "[leaf]",
    0xED: "[fire]",
    0xEE: "[teardrop]",
    0xEF: "[left_wing]",
    0xF0: "[right_wing]",
    0xF1: "[rose]",
    0xF2: "[unknown_F2]",
    0xF3: "[unknown_F3]",
    0xF4: "[frustration_mark]",
    0xF5: "[sad]",
    0xF6: "[happy]",
    0xF7: "[angry]",
    0xF8: "[excited]",
    0xF9: "[joyful]",
    0xFA: "[maliciously_happy]",
    0xFB: "[upset]",
    0xFC: "[straight_face]",
    0xFD: "[surprised]",
    0xFE: "[outraged]",
}

FC_MACROS: dict[int, str] = {
    0x07: "[resetfont]",
    0x09: "[pause]",
    0x0A: "[wait_sound]",
    0x0C: "[escape]",
    0x0D: "[shift_right]",
    0x0E: "[shift_down]",
    0x0F: "[fill_window]",
    0x12: "[skip]",
    0x15: "[japanese]",
    0x16: "[latin]",
    0x17: "[pause_music]",
    0x18: "[resume_music]",
}

COLOR_NAMES: dict[int, str] = {
    0x00: "white",
    0x01: "white2",
    0x02: "black",
    0x03: "grey",
    0x04: "red",
    0x05: "orange",
    0x06: "green",
    0x07: "lightgreen",
    0x08: "blue",
    0x09: "lightblue",
    0x0A: "white3",
    0x0B: "lightblue2",
    0x0C: "cyan",
    0x0D: "lightblue3",
    0x0E: "navyblue",
    0x0F: "darknavyblue",
}

COLOR_VALUES = {name: value for value, name in COLOR_NAMES.items()}
COLOR_VALUES["gray"] = 0x03

BACKSLASH_CODES: list[tuple[str, bytes]] = [
    ("\\pn", bytes([PARAGRAPH])),
    ("\\pk", bytes([0x53])),
    ("\\mn", bytes([0x54])),
    ("\\Po", bytes([0x55])),
    ("\\Ke", bytes([0x56])),
    ("\\Bl", bytes([0x57])),
    ("\\Lo", bytes([0x58])),
    ("\\Ck", bytes([0x59])),
    ("\\Lv", bytes([0x34])),
    ("\\qo", bytes([0xB1])),
    ("\\qc", bytes([0xB2])),
    ("\\sm", bytes([0xB5])),
    ("\\sf", bytes([0xB6])),
    ("\\au", bytes([0x79])),
    ("\\ad", bytes([0x7A])),
    ("\\al", bytes([0x7B])),
    ("\\ar", bytes([0x7C])),
    ("\\n", bytes([NEWLINE])),
    ("\\l", bytes([LINE_SCROLL])),
    ("\\p", bytes([PARAGRAPH])),
    ("\\e", bytes([0x2C])),
    ("\\d", bytes([0x84])),
    ("\\.", bytes([0xB0])),
    ("\\<", bytes([0x85])),
    ("\\>", bytes([0x86])),
    ("\\+", bytes([0x2E])),
    ("\\r", bytes([0x48])),
]

BRACKET_MACROS: dict[str, bytes] = {}
for _value, _name in FD_MACROS.items():
    BRACKET_MACROS[_name] = bytes([ESCAPE_PREFIX, _value])
for _value, _name in F9_MACROS.items():
    BRACKET_MACROS[_name] = bytes([F9_PREFIX, _value])
for _value, _name in FC_MACROS.items():
    BRACKET_MACROS[_name] = bytes([CONTROL_CODE_PREFIX, _value])
for _value, _name in COLOR_NAMES.items():
    BRACKET_MACROS[f"[{_name}]"] = bytes([CONTROL_CODE_PREFIX, 0x01, _value])
BRACKET_MACROS["[gray]"] = bytes([CONTROL_CODE_PREFIX, 0x01, 0x03])


@dataclass(frozen=True)
class DecodeResult:
    text: str
    byte_length: int
    terminated: bool
    raw_count: int = 0
    control_count: int = 0


def _is_hex_pair(text: str) -> bool:
    return len(text) == 2 and all(ch in "0123456789ABCDEFabcdef" for ch in text)


def _raw_byte(byte: int) -> str:
    return f"\\!{byte:02X}"


def decode_pcs(data: bytes | bytearray, offset: int = 0, max_length: int = 2048) -> DecodeResult:
    pieces: list[str] = []
    index = offset
    end = min(len(data), offset + max_length)
    raw_count = 0
    control_count = 0

    while index < end:
        byte = data[index]
        index += 1

        if byte == TERMINATOR:
            return DecodeResult("".join(pieces), index - offset, True, raw_count, control_count)
        if byte == NEWLINE:
            pieces.append("\n")
            control_count += 1
            continue
        if byte == LINE_SCROLL:
            pieces.append("\\l")
            control_count += 1
            continue
        if byte == PARAGRAPH:
            pieces.append("\n\n")
            control_count += 1
            continue
        if byte == CONTROL_CODE_PREFIX:
            if index >= end:
                pieces.append(_raw_byte(byte))
                raw_count += 1
                break
            command = data[index]
            index += 1
            argc = fc_arg_count(command)
            args = bytes(data[index : min(end, index + argc)])
            index += len(args)
            control_count += 1

            if command == 0x01 and len(args) == 1 and args[0] in COLOR_NAMES:
                pieces.append(f"[{COLOR_NAMES[args[0]]}]")
            elif argc == 0 and command in FC_MACROS:
                pieces.append(FC_MACROS[command])
            else:
                pieces.append("\\CC" + f"{command:02X}" + "".join(f"{arg:02X}" for arg in args))
                if len(args) != argc:
                    raw_count += 1
            continue
        if byte == ESCAPE_PREFIX:
            if index >= end:
                pieces.append(_raw_byte(byte))
                raw_count += 1
                break
            arg = data[index]
            index += 1
            control_count += 1
            pieces.append(FD_MACROS.get(arg, f"\\\\{arg:02X}"))
            continue
        if byte == F7_PREFIX:
            if index >= end:
                pieces.append(_raw_byte(byte))
                raw_count += 1
                break
            arg = data[index]
            index += 1
            control_count += 1
            pieces.append(f"\\?{arg:02X}")
            continue
        if byte == BUTTON_PREFIX:
            if index >= end:
                pieces.append(_raw_byte(byte))
                raw_count += 1
                break
            arg = data[index]
            index += 1
            control_count += 1
            pieces.append(f"\\btn{arg:02X}")
            continue
        if byte == F9_PREFIX:
            if index >= end:
                pieces.append(_raw_byte(byte))
                raw_count += 1
                break
            arg = data[index]
            index += 1
            control_count += 1
            pieces.append(F9_MACROS.get(arg, f"\\9{arg:02X}"))
            continue

        char = PCS_CHAR_TABLE.get(byte)
        if char is None:
            pieces.append(_raw_byte(byte))
            raw_count += 1
        else:
            pieces.append(char)

    return DecodeResult("".join(pieces), index - offset, False, raw_count, control_count)


class Charmap:
    """Small compatibility wrapper with the methods used by the injectors."""

    _FULLWIDTH_MAP = str.maketrans(
        "０１２３４５６７８９"
        "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
        "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
        "（）～",
        "0123456789"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
        "()~",
    )

    _CHAR_REPLACEMENTS = {
        "\u2014": "-",
        "\u2013": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201C": '"',
        "\u201D": '"',
        "\u300A": '"',
        "\u300B": '"',
        "\u3001": ",",
        "\uFF5E": "~",
        "\u00B7": ".",
    }

    def __init__(self, target_lang: str = "it", **_kwargs):
        self.target_lang = target_lang
        self.char_to_bytes = {char: bytes([byte]) for char, byte in CHAR_TO_BYTE.items()}
        self.bytes_to_char = dict(PCS_CHAR_TABLE)

    def encode_char(self, char: str) -> bytes | None:
        byte = CHAR_TO_BYTE.get(char)
        if byte is None:
            return None
        return bytes([byte])

    def supported_chars(self) -> set[str]:
        return set(self.char_to_bytes)

    def can_encode(self, text: str) -> tuple[bool, list[str]]:
        bad = [char for char in text if self.encode_char(char) is None]
        return not bad, bad

    def byte_length(self, text: str) -> int:
        return len(self.encode(text)) - 1

    def _sanitize(self, text: str) -> str:
        text = text.translate(self._FULLWIDTH_MAP)
        for old, new in self._CHAR_REPLACEMENTS.items():
            text = text.replace(old, new)
        return text

    def encode(self, text: str) -> bytes:
        text = self._sanitize(text)
        result = bytearray()
        index = 0

        while index < len(text):
            char = text[index]

            if char == "\n":
                if index + 1 < len(text) and text[index + 1] == "\n":
                    result.append(PARAGRAPH)
                    index += 2
                else:
                    result.append(NEWLINE)
                    index += 1
                continue

            if char == "\r":
                index += 1
                continue

            if char == "[":
                end = text.find("]", index)
                if end != -1:
                    token = text[index : end + 1]
                    macro = BRACKET_MACROS.get(token)
                    if macro is not None:
                        result.extend(macro)
                        index = end + 1
                        continue

            if char == "{" and index + 3 < len(text) and text[index + 3] == "}":
                hex_text = text[index + 1 : index + 3]
                if _is_hex_pair(hex_text):
                    result.append(int(hex_text, 16))
                    index += 4
                    continue

            if char == "\\":
                matched = False
                for token, encoded in BACKSLASH_CODES:
                    if text.startswith(token, index):
                        result.extend(encoded)
                        index += len(token)
                        matched = True
                        break
                if matched:
                    continue

                if text.startswith("\\CC", index) and index + 5 <= len(text):
                    cmd_hex = text[index + 3 : index + 5]
                    if _is_hex_pair(cmd_hex):
                        cmd = int(cmd_hex, 16)
                        req_args = 1 + fc_arg_count(cmd)
                        cursor = index + 3
                        args = []
                        while len(args) < req_args and cursor + 1 < len(text) and _is_hex_pair(text[cursor : cursor + 2]):
                            args.append(int(text[cursor : cursor + 2], 16))
                            cursor += 2
                        if len(args) == req_args:
                            result.append(CONTROL_CODE_PREFIX)
                            result.extend(args)
                            index = cursor
                            continue

                if text.startswith("\\btn", index) and _is_hex_pair(text[index + 4 : index + 6]):
                    result.extend((BUTTON_PREFIX, int(text[index + 4 : index + 6], 16)))
                    index += 6
                    continue

                if text.startswith("\\?", index) and _is_hex_pair(text[index + 2 : index + 4]):
                    result.extend((F7_PREFIX, int(text[index + 2 : index + 4], 16)))
                    index += 4
                    continue

                if text.startswith("\\9", index) and _is_hex_pair(text[index + 2 : index + 4]):
                    result.extend((F9_PREFIX, int(text[index + 2 : index + 4], 16)))
                    index += 4
                    continue

                if text.startswith("\\\\", index) and _is_hex_pair(text[index + 2 : index + 4]):
                    result.extend((ESCAPE_PREFIX, int(text[index + 2 : index + 4], 16)))
                    index += 4
                    continue

                if text.startswith("\\F", index) and index + 2 < len(text):
                    nibble = text[index + 2]
                    if nibble in "0123456789ABCDEFabcdef":
                        result.append(int("F" + nibble, 16))
                        index += 3
                        continue

                if text.startswith("\\!", index):
                    cursor = index + 2
                    values = []
                    while cursor < len(text):
                        while cursor < len(text) and text[cursor].isspace():
                            cursor += 1
                        if not _is_hex_pair(text[cursor : cursor + 2]):
                            break
                        values.append(int(text[cursor : cursor + 2], 16))
                        cursor += 2
                    if values:
                        result.extend(values)
                        index = cursor
                        continue

            encoded = self.encode_char(char)
            if encoded is not None:
                result.extend(encoded)
            index += 1

        result.append(TERMINATOR)
        return bytes(result)


CONTROL_TOKEN_RE = re.compile(
    CC_TOKEN_PATTERN
    + r"|\\btn[0-9A-Fa-f]{2}"
    r"|\\![0-9A-Fa-f\s]+"
    r"|\\\\[0-9A-Fa-f]{2}"
    r"|\\\?[0-9A-Fa-f]{2}"
    r"|\\9[0-9A-Fa-f]{2}"
    r"|\\F[0-9A-Fa-f]"
    r"|\\(?:pk|mn|Po|Ke|Bl|Lo|Ck|Lv|qo|qc|sm|sf|au|ad|al|ar|pn|n|l|p|e|d|\.|<|>|\+|r)"
    r"|\[[A-Za-z0-9_]+\]"
)


def strip_control_tokens(text: str) -> str:
    return CONTROL_TOKEN_RE.sub("", text)


def hma_quote(text: str) -> str:
    return f'"{text}"'
