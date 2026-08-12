import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from lib.pcs_text import CONTROL_TOKEN_RE


GLOSSARY_PLACEHOLDER_RE = re.compile(r"⟦glossary-[0-9]+⟧")


class GlossaryError(ValueError):
    pass


@dataclass(frozen=True)
class GlossaryLimit:
    categories: tuple[str, ...]
    max_length: int
    length_unit: str
    use_compact_target: bool = False


@dataclass(frozen=True)
class GlossaryTerm:
    source: str
    target: str
    kind: str
    note: str = ""
    case_sensitive: bool = True
    categories: tuple[str, ...] = ()
    full_target: str | None = None
    limits: tuple[GlossaryLimit, ...] = ()

    def target_for(self, category=None):
        if self.full_target is None:
            return self.target
        if any(
            limit.use_compact_target
            and (not limit.categories or category in limit.categories)
            for limit in self.limits
        ):
            return self.target
        return self.full_target


def _term_pattern(term):
    prefix = r"(?<!\w)" if term.source[0].isalnum() else ""
    suffix = r"(?!\w)" if term.source[-1].isalnum() else ""
    flags = 0 if term.case_sensitive else re.IGNORECASE
    return re.compile(prefix + re.escape(term.source) + suffix, flags)


class TranslationGlossary:
    def __init__(self, language, terms, source_path=None):
        self.language = language
        self.terms = tuple(terms)
        self.source_path = Path(source_path) if source_path else None
        self._patterns = tuple((term, _term_pattern(term)) for term in self.terms)

    def matches(self, text, category=None):
        candidates = []
        for order, (term, pattern) in enumerate(self._patterns):
            if term.categories and category not in term.categories:
                continue
            for match in pattern.finditer(text):
                candidates.append((match.start(), match.end(), order, term))

        # Earlier text wins; at one position, longest source wins. This lets a
        # specific place such as "Tomb of Borrius" override the nested region.
        candidates.sort(key=lambda row: (row[0], -(row[1] - row[0]), row[2]))
        selected = []
        occupied_until = -1
        for start, end, _order, term in candidates:
            if start < occupied_until:
                continue
            selected.append((start, end, term))
            occupied_until = end
        return selected

    def protect(self, text, category=None):
        matches = self.matches(text, category)
        if not matches:
            return text, []

        parts = []
        replacements = []
        cursor = 0
        for index, (start, end, term) in enumerate(matches, start=1):
            placeholder = f"⟦glossary-{index}⟧"
            target = term.target_for(category)
            parts.extend((text[cursor:start], placeholder))
            replacements.append(
                {
                    "placeholder": placeholder,
                    "source": text[start:end],
                    "target": target,
                    "kind": term.kind,
                }
            )
            if term.full_target is not None:
                replacements[-1]["full_target"] = term.full_target
            cursor = end
        parts.append(text[cursor:])
        return "".join(parts), replacements

    def missing_targets(self, source_text, translated_text, category=None):
        # ROM control mnemonics may directly touch visible text, as in
        # ``\\qoAklove\\qc`` or ``\\auBorgo Magnolia``. Remove them before
        # applying word boundaries so their letters do not mask valid terms.
        normalized_translation = translated_text.replace("{B4}", "'").replace(
            "{B3}", "'"
        )
        visible_translation = re.sub(
            r"\s+", " ", CONTROL_TOKEN_RE.sub(" ", normalized_translation)
        )
        expected = Counter(
            term.target_for(category)
            for _start, _end, term in self.matches(source_text, category)
        )
        missing = []
        for target, expected_count in expected.items():
            pattern = _term_pattern(
                GlossaryTerm(target, target, "target", case_sensitive=False)
            )
            actual_count = len(pattern.findall(visible_translation))
            if actual_count < expected_count:
                missing.append((target, expected_count, actual_count))
        return missing


def _load_term(row, index):
    if not isinstance(row, dict):
        raise GlossaryError(f"glossary term {index} must be an object")
    source = row.get("source")
    target = row.get("target")
    kind = row.get("kind")
    if not isinstance(source, str) or not source.strip():
        raise GlossaryError(f"glossary term {index} has an empty source")
    if not isinstance(target, str) or not target.strip():
        raise GlossaryError(f"glossary term {index} has an empty target")
    if not isinstance(kind, str) or not kind.strip():
        raise GlossaryError(f"glossary term {index} has an empty kind")
    note = row.get("note", "")
    case_sensitive = row.get("case_sensitive", True)
    categories = row.get("categories", [])
    full_target = row.get("full_target")
    limits = row.get("limits", [])
    if not isinstance(note, str):
        raise GlossaryError(f"glossary term {index} note must be a string")
    if not isinstance(case_sensitive, bool):
        raise GlossaryError(f"glossary term {index} case_sensitive must be boolean")
    if not isinstance(categories, list) or not all(
        isinstance(category, str) and category for category in categories
    ):
        raise GlossaryError(
            f"glossary term {index} categories must be an array of non-empty strings"
        )
    if full_target is not None and (
        not isinstance(full_target, str) or not full_target.strip()
    ):
        raise GlossaryError(
            f"glossary term {index} full_target must be a non-empty string"
        )
    if not isinstance(limits, list):
        raise GlossaryError(f"glossary term {index} limits must be an array")
    parsed_limits = []
    for limit_index, limit in enumerate(limits):
        if not isinstance(limit, dict):
            raise GlossaryError(
                f"glossary term {index} limit {limit_index} must be an object"
            )
        limit_categories = limit.get("categories", [])
        max_length = limit.get("max_length")
        length_unit = limit.get("length_unit")
        use_compact_target = limit.get("use_compact_target", False)
        if not isinstance(limit_categories, list) or not all(
            isinstance(category, str) and category for category in limit_categories
        ):
            raise GlossaryError(
                f"glossary term {index} limit {limit_index} categories must be "
                "an array of non-empty strings"
            )
        if not isinstance(max_length, int) or max_length <= 0:
            raise GlossaryError(
                f"glossary term {index} limit {limit_index} max_length must be positive"
            )
        if length_unit not in {"visible_characters", "pixels", "pcs_bytes"}:
            raise GlossaryError(
                f"glossary term {index} limit {limit_index} has invalid length_unit"
            )
        if not isinstance(use_compact_target, bool):
            raise GlossaryError(
                f"glossary term {index} limit {limit_index} "
                "use_compact_target must be boolean"
            )
        parsed_limits.append(
            GlossaryLimit(
                tuple(limit_categories),
                max_length,
                length_unit,
                use_compact_target,
            )
        )
    if full_target is not None and not parsed_limits:
        raise GlossaryError(
            f"glossary term {index} full_target requires at least one limit"
        )
    return GlossaryTerm(
        source,
        target,
        kind,
        note,
        case_sensitive,
        tuple(categories),
        full_target,
        tuple(parsed_limits),
    )


def load_glossary(path, expected_language=None):
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GlossaryError(f"cannot load glossary {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise GlossaryError("glossary root must be an object")
    language = data.get("language")
    if not isinstance(language, str) or not language:
        raise GlossaryError("glossary language must be a non-empty string")
    if expected_language and language != expected_language:
        raise GlossaryError(
            f"glossary language {language!r} does not match target {expected_language!r}"
        )
    rows = data.get("terms")
    if not isinstance(rows, list):
        raise GlossaryError("glossary terms must be an array")
    terms = [_load_term(row, index) for index, row in enumerate(rows)]
    duplicates = sorted(
        source for source in {term.source for term in terms}
        if sum(other.source == source for other in terms) > 1
    )
    if duplicates:
        raise GlossaryError(f"duplicate glossary sources: {', '.join(duplicates)}")
    return TranslationGlossary(language, terms, path)


def default_glossary_path(target, root=None):
    root = Path(root) if root else Path(__file__).resolve().parents[1]
    path = root / "glossaries" / f"{target}.json"
    return path if path.is_file() else None


def restore_glossary_placeholders(text, replacements):
    expected = {row["placeholder"] for row in replacements}
    actual = GLOSSARY_PLACEHOLDER_RE.findall(text)
    counts = {placeholder: actual.count(placeholder) for placeholder in set(actual)}
    problems = []
    for placeholder in sorted(expected | set(counts)):
        expected_count = 1 if placeholder in expected else 0
        actual_count = counts.get(placeholder, 0)
        if actual_count != expected_count:
            problems.append(
                f"{placeholder!r}: expected {expected_count}, got {actual_count}"
            )
    if problems:
        raise GlossaryError("; ".join(problems))
    for row in replacements:
        text = text.replace(row["placeholder"], row["target"])
    return text
