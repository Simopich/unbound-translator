#!/usr/bin/env python3

import argparse
from collections import Counter
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from queue import Empty, Queue

from lib import translation_tokens


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
MAX_API_ATTEMPTS = 3

LANGUAGE_NAMES = {
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
    "pt": "Portuguese",
    "pt-br": "Brazilian Portuguese",
    "id": "Indonesian",
}

CATEGORY_PRIORITY = {
    "menu_options": 20_000,
    "menu_pc": 20_000,
    "menu_pcoptions": 20_000,
    "menu_pokemon": 20_000,
    "menu_pokemon_options": 20_000,
    "menu_item_storage": 20_000,
    "menu_pause": 20_000,
    "trade_messages": 8_500,
    "map_names": 8_000,
    "type_names": 7_500,
    "nature_names": 7_000,
    "trainer_classes": 6_500,
    "item_names": 6_000,
    "ability_names": 6_000,
    "move_names": 6_000,
    "move_descriptions": 4_000,
    "ability_descriptions": 4_000,
    "plain_scripts": 1_500,
    "scripts": 1_000,
    "pokemon_names": 100,
}


class TranslationError(RuntimeError):
    pass


class RetryableTranslationError(TranslationError):
    pass


class OutputTokenLimitError(TranslationError):
    pass


class SkippedTranslation:
    def __init__(self, entry_id, reason):
        self.entry_id = entry_id
        self.reason = reason


class RateLimiter:
    def __init__(self, calls_per_minute, wait_callback=None):
        self.interval = 60.0 / calls_per_minute if calls_per_minute > 0 else 0.0
        self.lock = threading.Lock()
        self.next_call_at = 0.0
        self.wait_callback = wait_callback

    def wait(self):
        if self.interval <= 0:
            return

        with self.lock:
            while True:
                remaining = self.next_call_at - time.monotonic()
                if remaining <= 0:
                    break
                if self.wait_callback:
                    self.wait_callback(remaining)
                time.sleep(min(1.0, remaining))
            self.next_call_at = time.monotonic() + self.interval
            if self.wait_callback:
                self.wait_callback(None)


def iter_entries(data):
    for table in data.get("tables", []):
        for entry in table.get("entries", []):
            yield entry
    for entry in data.get("free_texts", []):
        yield entry
    for entry in data.get("entries", []):
        yield entry


def iter_entry_refs(data):
    for index, entry in enumerate(iter_entries(data)):
        yield index, entry


def strip_hma_quotes(text):
    if isinstance(text, str) and len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text or ""


def entry_key(index, entry):
    entry_id = entry.get("id")
    if isinstance(entry_id, str) and entry_id:
        return entry_id
    return f"@entry_{index}"


def has_translation(entry):
    translated = entry.get("translated")
    return isinstance(translated, str) and translated.strip() != ""


def collect_existing_translations(data):
    translations = {}
    for index, entry in iter_entry_refs(data):
        if has_translation(entry):
            translations[entry_key(index, entry)] = entry["translated"]
    return translations


def apply_existing_translations(data, existing_data):
    existing = collect_existing_translations(existing_data)
    applied = 0
    for index, entry in iter_entry_refs(data):
        key = entry_key(index, entry)
        if key in existing and not has_translation(entry):
            entry["translated"] = existing[key]
            applied += 1
    return applied


def parse_value_set(value):
    if not value:
        return set()
    return {item.strip() for item in value.replace(";", ",").split(",") if item.strip()}


def parse_category_set(value):
    return parse_value_set(value)


def split_entry_id(entry_id):
    match = None
    for index in range(len(entry_id) - 1, -1, -1):
        if not entry_id[index].isdigit():
            match = index + 1
            break
    if match is None or match >= len(entry_id):
        return None
    return entry_id[:match], int(entry_id[match:]), len(entry_id) - match


def parse_id_ranges(value):
    ranges = []
    for item in parse_value_set(value):
        separator = ":" if ":" in item else "-"
        if separator not in item:
            raise SystemExit(f"error: invalid --include-id-ranges item: {item}")
        start_id, end_id = [part.strip() for part in item.split(separator, 1)]
        start = split_entry_id(start_id)
        end = split_entry_id(end_id)
        if start is None or end is None or start[0] != end[0]:
            raise SystemExit(f"error: invalid --include-id-ranges item: {item}")
        prefix, start_number, width = start
        _end_prefix, end_number, end_width = end
        if width != end_width or start_number > end_number:
            raise SystemExit(f"error: invalid --include-id-ranges item: {item}")
        ranges.append((prefix, start_number, end_number, width))
    return ranges


def id_in_ranges(entry_id, ranges):
    split = split_entry_id(entry_id)
    if split is None:
        return False
    prefix, number, width = split
    return any(
        prefix == range_prefix
        and width == range_width
        and start <= number <= end
        for range_prefix, start, end, range_width in ranges
    )


def include_filters_active(include_ids, include_ranges, include_categories, include_prefixes):
    return bool(include_ids or include_ranges or include_categories or include_prefixes)


def entry_matches_include(entry, include_ids, include_ranges, include_categories, include_prefixes):
    entry_id = entry.get("id", "")
    category = entry.get("category", "")
    return (
        entry_id in include_ids
        or id_in_ranges(entry_id, include_ranges)
        or category in include_categories
        or any(category.startswith(prefix) for prefix in include_prefixes)
    )


def filter_entries_by_include(entries, include_ids, include_ranges, include_categories, include_prefixes):
    return [
        entry
        for entry in entries
        if entry_matches_include(
            entry,
            include_ids,
            include_ranges,
            include_categories,
            include_prefixes,
        )
    ]


def keep_included_entries(data, include_ids, include_ranges, include_categories, include_prefixes):
    if not include_filters_active(include_ids, include_ranges, include_categories, include_prefixes):
        return 0
    removed = 0
    for table in data.get("tables", []):
        entries = table.get("entries")
        if not isinstance(entries, list):
            continue
        filtered = filter_entries_by_include(
            entries,
            include_ids,
            include_ranges,
            include_categories,
            include_prefixes,
        )
        removed += len(entries) - len(filtered)
        table["entries"] = filtered
    for key in ("free_texts", "entries"):
        entries = data.get(key)
        if not isinstance(entries, list):
            continue
        filtered = filter_entries_by_include(
            entries,
            include_ids,
            include_ranges,
            include_categories,
            include_prefixes,
        )
        removed += len(entries) - len(filtered)
        data[key] = filtered
    return removed


def filter_entries_by_category(entries, excluded_categories):
    return [
        entry
        for entry in entries
        if entry.get("category", "") not in excluded_categories
    ]


def remove_excluded_categories(data, excluded_categories):
    if not excluded_categories:
        return 0
    removed = 0
    for table in data.get("tables", []):
        entries = table.get("entries")
        if not isinstance(entries, list):
            continue
        filtered = filter_entries_by_category(entries, excluded_categories)
        removed += len(entries) - len(filtered)
        table["entries"] = filtered
    for key in ("free_texts", "entries"):
        entries = data.get(key)
        if not isinstance(entries, list):
            continue
        filtered = filter_entries_by_category(entries, excluded_categories)
        removed += len(entries) - len(filtered)
        data[key] = filtered
    return removed


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path, data):
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(f".{output_path.name}.tmp")
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(output_path)


def target_language_name(target):
    return LANGUAGE_NAMES[target.lower()]


def make_system_prompt(target):
    return (
        "You translate text extracted from Pokemon Unbound.\n"
        f"Translate every item into {target}.\n"
        "Use established official Pokemon terminology for the target language "
        "whenever it exists, especially for moves, items, abilities, types, "
        "Pokemon descriptions, battle text, menu labels, and common franchise phrases.\n"
        "If your environment has access to web pages or retrieval tools, consult "
        "reputable Pokemon references such as Bulbapedia or Pokemon Database for "
        "localized names and descriptions. If you do not have web access, rely on "
        "known official localized terminology and keep uncertain proper nouns unchanged.\n"
        "Return only valid JSON in this exact shape:\n"
        '{"translations":[{"id":"same id","translated":"translated text"}]}\n'
        "Rules:\n"
        "- Return one translation for every input item.\n"
        "- Keep the same ids. Do not invent, omit, merge, or reorder ids.\n"
        "- Preserve every placeholder listed in semantic_placeholders exactly and "
        "in the same count. These placeholders stand for protected Pokemon "
        "Unbound engine tokens.\n"
        "- Placeholder labels describe their role, such as [player-name-1], "
        "[buffer1-2], [color-red-3], [button-icon-4], [quote-open-5], or "
        "[control-code-6]. Move them only when grammar requires it.\n"
        "- Do not output the real protected token values from semantic_tokens "
        "unless the source text already contains real tokens instead of "
        "placeholders. Prefer the bracketed placeholders in the source text.\n"
        "- semantic_placeholder_counts maps each placeholder to the number of "
        "times it MUST appear in your translation: no more, no fewer, none added, "
        "none renamed.\n"
        "- Layout markers such as line breaks, \\n, \\l, \\p, and \\pn are not "
        "semantic tokens. They were removed before translation and will be "
        "recomputed later, so do not add them.\n"
        "- Do not add outer quotes unless they are part of the source text.\n"
        "- Keep Pokemon species names, move names, item names, and proper nouns "
        "unchanged when there is no natural translation.\n"
    )


def token_counts_to_dict(counts):
    return {token: counts[token] for token in sorted(counts)}


def make_user_prompt(batch, target):
    items = [
        {
            "id": item["id"],
            "category": item["category"],
            "text": item["text"],
            "semantic_placeholders": item["semantic_placeholders"],
            "semantic_placeholder_counts": token_counts_to_dict(
                item["semantic_placeholder_counts"]
            ),
            "semantic_tokens": item["semantic_tokens"],
            "semantic_token_counts": token_counts_to_dict(item["semantic_token_counts"]),
        }
        for item in batch
    ]
    return json.dumps(
        {
            "target_language": target,
            "items": items,
        },
        ensure_ascii=False,
    )


def make_single_system_prompt(target):
    return (
        f"Translate one Pokemon Unbound text into {target}.\n"
        "Use established official Pokemon terminology when it exists.\n"
        "Preserve every placeholder listed in semantic_placeholders exactly and "
        "in the same count. These placeholders stand for protected game-engine "
        "tokens and have meaningful labels such as [player-name-1] or "
        "[control-code-2]. Do not add layout markers such as \\n, \\l, \\p, or "
        "\\pn.\n"
        "Return only valid JSON in this exact shape:\n"
        '{"translated":"translated text"}\n'
    )


def make_single_user_prompt(item, target):
    return json.dumps(
        {
            "target_language": target,
            "id": item["id"],
            "category": item["category"],
            "text": item["text"],
            "semantic_placeholders": item["semantic_placeholders"],
            "semantic_placeholder_counts": token_counts_to_dict(
                item["semantic_placeholder_counts"]
            ),
            "semantic_tokens": item["semantic_tokens"],
            "semantic_token_counts": token_counts_to_dict(item["semantic_token_counts"]),
        },
        ensure_ascii=False,
    )


def make_plain_single_system_prompt(target):
    return (
        f"Translate one Pokemon Unbound text into {target}.\n"
        "Use established official Pokemon terminology when it exists.\n"
        "Preserve every placeholder listed in semantic_placeholders exactly and "
        "in the same count. Do not add layout markers such as \\n, \\l, \\p, or "
        "\\pn.\n"
        "Return only the translated text. Do not return JSON. Do not explain.\n"
    )


def make_codex_batch_prompt(batch, target):
    return (
        "You are being used as a non-interactive translation engine.\n"
        "Do not inspect files, run commands, or modify the workspace.\n"
        "Translate the provided Pokemon Unbound text and return only the final JSON.\n\n"
        f"{make_system_prompt(target)}\n"
        f"Input JSON:\n{make_user_prompt(batch, target)}\n"
    )


def make_codex_single_prompt(item, target):
    return (
        "You are being used as a non-interactive translation engine.\n"
        "Do not inspect files, run commands, or modify the workspace.\n"
        "Translate the provided Pokemon Unbound text and return only the final JSON.\n\n"
        f"{make_single_system_prompt(target)}\n"
        f"Input JSON:\n{make_single_user_prompt(item, target)}\n"
    )


BATCH_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "translated": {"type": "string"},
                },
                "required": ["id", "translated"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["translations"],
    "additionalProperties": False,
}


SINGLE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "translated": {"type": "string"},
    },
    "required": ["translated"],
    "additionalProperties": False,
}


def api_endpoint(api_base):
    base = api_base.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def read_response_content(choice):
    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "".join(parts)
    return ""


def parse_model_json(content):
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for start, char in enumerate(content):
            if char not in "{[":
                continue
            try:
                parsed, _end = decoder.raw_decode(content[start:])
                return parsed
            except json.JSONDecodeError:
                continue
    raise RetryableTranslationError("API returned invalid JSON.")


def validate_translations(payload, batch):
    if isinstance(payload, dict):
        translations = payload.get("translations")
    elif isinstance(payload, list):
        translations = payload
    else:
        translations = None

    if not isinstance(translations, list):
        raise RetryableTranslationError("API response JSON does not contain a translations array.")

    if len(translations) != len(batch):
        raise TranslationError(
            f"API returned {len(translations)} translations for a batch of {len(batch)}; "
            "this is probably a partial response."
        )

    expected_ids = [item["id"] for item in batch]
    received = {}
    for row in translations:
        if not isinstance(row, dict):
            raise RetryableTranslationError("API returned a non-object item in translations.")
        row_id = row.get("id")
        translated = row.get("translated")
        if not isinstance(row_id, str) or not isinstance(translated, str):
            raise RetryableTranslationError(
                "API translation items must contain string id and translated fields."
            )
        if row_id in received:
            raise TranslationError(f"API returned duplicate translation id: {row_id}")
        received[row_id] = translated

    missing = [entry_id for entry_id in expected_ids if entry_id not in received]
    extra = [entry_id for entry_id in received if entry_id not in expected_ids]
    if missing or extra:
        detail = []
        if missing:
            detail.append(f"missing ids: {', '.join(missing[:5])}")
        if extra:
            detail.append(f"unexpected ids: {', '.join(extra[:5])}")
        raise TranslationError("API returned a mismatched batch; " + "; ".join(detail))

    return [received[entry_id] for entry_id in expected_ids]


def token_count_mismatches(expected, actual):
    mismatches = []
    for token in sorted(set(expected) | set(actual)):
        expected_count = expected.get(token, 0)
        actual_count = actual.get(token, 0)
        if expected_count != actual_count:
            mismatches.append(f"{token!r}: expected {expected_count}, got {actual_count}")
    return mismatches


def placeholder_counts(text):
    return Counter(translation_tokens.SEMANTIC_PLACEHOLDER_RE.findall(text))


def validate_placeholders(item, translated):
    expected = item["semantic_placeholder_counts"]
    if not expected:
        return []
    actual = placeholder_counts(translated)
    return token_count_mismatches(expected, actual)


def validate_and_restore_semantic_tokens(batch, translations):
    restored_translations = []
    for item, translated in zip(batch, translations):
        placeholder_mismatches = validate_placeholders(item, translated)
        if placeholder_mismatches:
            fallback_actual = translation_tokens.semantic_token_counts(translated)
            fallback_mismatches = token_count_mismatches(
                item["semantic_token_counts"],
                fallback_actual,
            )
            if fallback_mismatches:
                detail = "; ".join(placeholder_mismatches[:8])
                if len(placeholder_mismatches) > 8:
                    detail += f"; +{len(placeholder_mismatches) - 8} more"
                print(
                    f"warning: semantic placeholder mismatch for {item['id']}: "
                    f"{detail}; retrying",
                    file=sys.stderr,
                )
                raise RetryableTranslationError(
                    "semantic/control placeholder mismatch in model output."
                )
            restored = translated
        else:
            restored = translation_tokens.restore_semantic_token_placeholders(
                translated,
                item["semantic_token_placeholders"],
            )
        leftover_placeholders = placeholder_counts(restored)
        if leftover_placeholders:
            detail = "; ".join(
                f"{token!r}: unresolved placeholder {count} time(s)"
                for token, count in sorted(leftover_placeholders.items())[:8]
            )
            print(
                f"warning: unresolved semantic placeholder for {item['id']}: "
                f"{detail}; retrying",
                file=sys.stderr,
            )
            raise RetryableTranslationError(
                "unresolved semantic/control placeholder in model output."
            )
        restored_translations.append(restored)

    return validate_semantic_tokens(batch, restored_translations)


def validate_semantic_tokens(batch, translations):
    for item, translated in zip(batch, translations):
        expected = item["semantic_token_counts"]
        actual = translation_tokens.semantic_token_counts(translated)
        mismatches = token_count_mismatches(expected, actual)
        layout = translation_tokens.layout_token_counts(translated)
        for token in sorted(layout):
            mismatches.append(f"{token!r}: layout token added {layout[token]} time(s)")

        if mismatches:
            detail = "; ".join(mismatches[:8])
            if len(mismatches) > 8:
                detail += f"; +{len(mismatches) - 8} more"
            print(
                f"warning: semantic/control token mismatch for {item['id']}: {detail}; retrying",
                file=sys.stderr,
            )
            raise RetryableTranslationError("semantic/control token mismatch in model output.")

    return translations


def validate_single_translation(payload):
    if not isinstance(payload, dict):
        raise RetryableTranslationError("API single-item response is not a JSON object.")
    translated = payload.get("translated")
    if not isinstance(translated, str):
        raise RetryableTranslationError("API single-item response does not contain translated text.")
    return translated


def clean_plain_translation(content):
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, dict) and isinstance(parsed.get("translated"), str):
        return parsed["translated"]
    if isinstance(parsed, str):
        return parsed
    if not text:
        raise RetryableTranslationError("API returned an empty plain translation.")
    return text


def compact_error_detail(text, limit=1000):
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def warn_single_prompt(item, mode="single-item"):
    print(
        f"warning: {item['id']} is using the {mode} prompt without full batch context; "
        "translation accuracy may be lower",
        file=sys.stderr,
    )


class OpenAICompatibleClient:
    def __init__(
        self,
        api_base,
        api_key,
        model,
        max_tokens,
        temperature,
        timeout,
        user_agent,
        rate_limiter,
    ):
        self.endpoint = api_endpoint(api_base)
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self.user_agent = user_agent
        self.rate_limiter = rate_limiter

    def translate_batch(self, batch, target):
        try:
            return self.translate_batch_with_retries(batch, target)
        except OutputTokenLimitError:
            if len(batch) > 1:
                translations = []
                for item in batch:
                    translations.append(self.translate_single_or_skip(item, target))
                return translations
            return [self.translate_single_or_skip(batch[0], target)]

    def translate_single_or_skip(self, item, target):
        try:
            return self.translate_single_item(item, target)
        except OutputTokenLimitError as exc:
            return SkippedTranslation(item["id"], str(exc))

    def translate_batch_with_retries(self, batch, target):
        last_error = None
        for attempt in range(1, MAX_API_ATTEMPTS + 1):
            try:
                return self.translate_batch_once(batch, target)
            except RetryableTranslationError as exc:
                last_error = exc
                if attempt == MAX_API_ATTEMPTS:
                    break
                time.sleep(min(2 ** (attempt - 1), 8))

        raise TranslationError(
            f"API request failed after {MAX_API_ATTEMPTS} attempts: {last_error}"
        ) from last_error

    def translate_batch_once(self, batch, target):
        content = self.chat(
            [
                {"role": "system", "content": make_system_prompt(target)},
                {"role": "user", "content": make_user_prompt(batch, target)},
            ],
            self.max_tokens,
        )
        parsed = parse_model_json(content)
        translations = validate_translations(parsed, batch)
        return validate_and_restore_semantic_tokens(batch, translations)

    def translate_single_item(self, item, target):
        try:
            return self.translate_single_item_with_retries(item, target)
        except OutputTokenLimitError:
            return self.translate_single_item_plain(item, target)

    def translate_single_item_with_retries(self, item, target):
        warn_single_prompt(item)
        last_error = None
        for attempt in range(1, MAX_API_ATTEMPTS + 1):
            try:
                return self.translate_single_item_once(item, target)
            except RetryableTranslationError as exc:
                last_error = exc
                if attempt == MAX_API_ATTEMPTS:
                    break
                time.sleep(min(2 ** (attempt - 1), 8))

        raise TranslationError(
            f"API single-item request failed after {MAX_API_ATTEMPTS} attempts: {last_error}"
        ) from last_error

    def translate_single_item_once(self, item, target):
        content = self.chat(
            [
                {"role": "system", "content": make_single_system_prompt(target)},
                {"role": "user", "content": make_single_user_prompt(item, target)},
            ],
            self.single_item_max_tokens(),
        )
        parsed = parse_model_json(content)
        translated = validate_single_translation(parsed)
        return validate_and_restore_semantic_tokens([item], [translated])[0]

    def translate_single_item_plain(self, item, target):
        warn_single_prompt(item, "plain single-item")
        last_error = None
        for attempt in range(1, MAX_API_ATTEMPTS + 1):
            try:
                content = self.chat(
                    [
                        {"role": "system", "content": make_plain_single_system_prompt(target)},
                        {"role": "user", "content": make_single_user_prompt(item, target)},
                    ],
                    self.single_item_max_tokens(),
                )
                translated = clean_plain_translation(content)
                return validate_and_restore_semantic_tokens([item], [translated])[0]
            except OutputTokenLimitError:
                raise
            except RetryableTranslationError as exc:
                last_error = exc
                if attempt == MAX_API_ATTEMPTS:
                    break
                time.sleep(min(2 ** (attempt - 1), 8))

        raise TranslationError(
            f"API plain single-item request failed after {MAX_API_ATTEMPTS} attempts: {last_error}"
        ) from last_error

    def single_item_max_tokens(self):
        return max(self.max_tokens + 1024, self.max_tokens * 2)

    def chat(self, messages, max_tokens):
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            },
            method="POST",
        )

        self.rate_limiter.wait()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            message = f"API HTTP {exc.code}: {detail[:1000]}"
            if exc.code in {401, 403, 429} or 400 <= exc.code < 500:
                raise TranslationError(message) from exc
            raise RetryableTranslationError(message) from exc
        except urllib.error.URLError as exc:
            raise RetryableTranslationError(f"API request failed: {exc}") from exc

        try:
            response_data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RetryableTranslationError("API returned a non-JSON HTTP response.") from exc

        choices = response_data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RetryableTranslationError("API response does not contain choices.")

        choice = choices[0]
        finish_reason = choice.get("finish_reason")
        if finish_reason and finish_reason != "stop":
            if finish_reason == "length":
                raise OutputTokenLimitError("API response hit the output token limit.")
            raise TranslationError(f"API response finished with reason {finish_reason!r}.")

        content = read_response_content(choice)
        if not content.strip():
            raise RetryableTranslationError("API returned an empty message.")

        return content


class CodexExecClient:
    def __init__(
        self,
        codex_command,
        model,
        profile,
        timeout,
        rate_limiter,
    ):
        self.codex_command = codex_command
        self.model = model
        self.profile = profile
        self.timeout = timeout
        self.rate_limiter = rate_limiter

    def translate_batch(self, batch, target):
        try:
            return self.translate_batch_with_retries(batch, target)
        except RetryableTranslationError:
            if len(batch) <= 1:
                raise
            translations = []
            for item in batch:
                translations.append(self.translate_single_item(item, target))
            return translations

    def translate_batch_with_retries(self, batch, target):
        last_error = None
        for attempt in range(1, MAX_API_ATTEMPTS + 1):
            try:
                return self.translate_batch_once(batch, target)
            except RetryableTranslationError as exc:
                last_error = exc
                if attempt == MAX_API_ATTEMPTS:
                    break
                time.sleep(min(2 ** (attempt - 1), 8))

        raise TranslationError(
            f"Codex request failed after {MAX_API_ATTEMPTS} attempts: {last_error}"
        ) from last_error

    def translate_batch_once(self, batch, target):
        parsed = self.run_codex_json(
            make_codex_batch_prompt(batch, target),
            BATCH_OUTPUT_SCHEMA,
        )
        translations = validate_translations(parsed, batch)
        return validate_and_restore_semantic_tokens(batch, translations)

    def translate_single_item(self, item, target):
        warn_single_prompt(item)
        last_error = None
        for attempt in range(1, MAX_API_ATTEMPTS + 1):
            try:
                parsed = self.run_codex_json(
                    make_codex_single_prompt(item, target),
                    SINGLE_OUTPUT_SCHEMA,
                )
                translated = validate_single_translation(parsed)
                return validate_and_restore_semantic_tokens([item], [translated])[0]
            except RetryableTranslationError as exc:
                last_error = exc
                if attempt == MAX_API_ATTEMPTS:
                    break
                time.sleep(min(2 ** (attempt - 1), 8))

        raise TranslationError(
            f"Codex single-item request failed after {MAX_API_ATTEMPTS} attempts: {last_error}"
        ) from last_error

    def run_codex_json(self, prompt, schema):
        with tempfile.TemporaryDirectory(prefix="llm-translate-codex-") as tmpdir:
            schema_path = Path(tmpdir) / "schema.json"
            schema_path.write_text(json.dumps(schema), encoding="utf-8")

            command = [
                self.codex_command,
                "exec",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--ephemeral",
                "--cd",
                tmpdir,
                "--output-schema",
                str(schema_path),
            ]
            if self.model:
                command.extend(["--model", self.model])
            if self.profile:
                command.extend(["--profile", self.profile])
            command.append("-")

            self.rate_limiter.wait()
            try:
                result = subprocess.run(
                    command,
                    input=prompt,
                    text=True,
                    capture_output=True,
                    timeout=self.timeout,
                    cwd=tmpdir,
                    check=False,
                )
            except FileNotFoundError as exc:
                raise TranslationError(
                    f"Codex command not found: {self.codex_command!r}. "
                    "Install Codex CLI or pass --codex-command."
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise RetryableTranslationError(
                    f"codex exec timed out after {self.timeout:g}s"
                ) from exc

        if result.returncode != 0:
            detail = compact_error_detail(result.stderr or result.stdout)
            lower_detail = detail.lower()
            message = f"codex exec failed with exit code {result.returncode}: {detail}"
            if any(
                token in lower_detail
                for token in (
                    "auth",
                    "login",
                    "log in",
                    "unauthorized",
                    "forbidden",
                    "invalid api key",
                    "no valid session",
                )
            ):
                raise TranslationError(message)
            raise RetryableTranslationError(message)

        content = result.stdout.strip()
        if not content:
            raise RetryableTranslationError("codex exec returned an empty final message.")
        return parse_model_json(content)


def build_work_items(data):
    work = []
    skipped_empty = 0
    already_translated = 0

    for index, entry in iter_entry_refs(data):
        if has_translation(entry):
            already_translated += 1
            continue

        prepared_source = entry.get("translation_source")
        if isinstance(prepared_source, str):
            text = strip_hma_quotes(prepared_source)
        else:
            original = strip_hma_quotes(entry.get("original", ""))
            text, _layout = translation_tokens.remove_layout_tokens(original)

        if not text:
            skipped_empty += 1
            continue

        semantic_token_placeholders = entry.get("semantic_token_placeholders")
        if not isinstance(semantic_token_placeholders, list):
            semantic_token_placeholders = []

        if semantic_token_placeholders:
            protected_tokens = [
                item["token"]
                for item in semantic_token_placeholders
                if isinstance(item, dict) and isinstance(item.get("token"), str)
            ]
            protected_token_counts = Counter(protected_tokens)
            semantic_placeholders = [
                item["placeholder"]
                for item in semantic_token_placeholders
                if isinstance(item, dict) and isinstance(item.get("placeholder"), str)
            ]
            semantic_placeholder_counts = translation_tokens.semantic_placeholder_counts(
                semantic_token_placeholders
            )
        else:
            protected_tokens = translation_tokens.semantic_tokens(text)
            protected_token_counts = translation_tokens.semantic_token_counts(text)
            semantic_placeholders = []
            semantic_placeholder_counts = Counter()

        work.append(
            {
                "id": entry_key(index, entry),
                "category": entry.get("category", ""),
                "text": text,
                "semantic_placeholders": semantic_placeholders,
                "semantic_placeholder_counts": semantic_placeholder_counts,
                "semantic_token_placeholders": semantic_token_placeholders,
                "semantic_tokens": protected_tokens,
                "semantic_token_counts": protected_token_counts,
                "entry": entry,
            }
        )

    return work, already_translated, skipped_empty


def short_text_bonus(length):
    if length <= 8:
        return 100
    if length <= 16:
        return 75
    if length <= 32:
        return 50
    if length <= 64:
        return 25
    return 0


def huge_text_penalty(length):
    if length >= 1024:
        return 150
    if length >= 512:
        return 75
    if length >= 256:
        return 25
    return 0


def pointer_source_count(entry):
    sources = entry.get("pointer_sources") or entry.get("pointer_addresses") or []
    return len(sources) if isinstance(sources, list) else 0


def translation_priority(item, duplicate_originals, duplicate_sources):
    entry = item["entry"]
    category = item["category"]
    length = len(item["text"])
    duplicate_original_count = min(duplicate_originals.get(strip_hma_quotes(entry.get("original", "")), 1), 10)
    duplicate_source_count = min(duplicate_sources.get(item["text"], 1), 10)
    return (
        CATEGORY_PRIORITY.get(category, 0)
        + pointer_source_count(entry) * 50
        + duplicate_original_count * 25
        + duplicate_source_count * 25
        + short_text_bonus(length)
        - huge_text_penalty(length)
    )


def sort_work_by_priority(work):
    duplicate_originals = {}
    duplicate_sources = {}
    for item in work:
        original = strip_hma_quotes(item["entry"].get("original", ""))
        duplicate_originals[original] = duplicate_originals.get(original, 0) + 1
        duplicate_sources[item["text"]] = duplicate_sources.get(item["text"], 0) + 1

    for item in work:
        item["priority"] = translation_priority(item, duplicate_originals, duplicate_sources)

    work.sort(
        key=lambda item: (
            item["priority"],
            -len(item["text"]),
            item["id"],
        ),
        reverse=True,
    )
    return work


def chunked(items, size):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def progress_bar(completed, total, width=36):
    if total <= 0:
        percent = 100.0
        filled = width
    else:
        percent = completed / total * 100
        filled = round(width * completed / total)
    empty = width - filled
    return f"[{'#' * filled}{'.' * empty}] {percent:6.2f}% ({completed}/{total})"


def render_progress(completed, total, status=None):
    text = progress_bar(completed, total)
    if status:
        text = f"{text} | {status}"
    sys.stdout.write("\r" + text + "\x1b[K")
    sys.stdout.flush()


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Translate extracted Pokemon Unbound text with an OpenAI-compatible API "
            "or a local Codex ChatGPT login."
        )
    )
    parser.add_argument("input", help="Extracted JSON file to translate.")
    parser.add_argument(
        "-o",
        "--output",
        help="Output JSON path. Defaults to <input-stem>-<target>.json.",
    )
    parser.add_argument(
        "--target",
        required=True,
        choices=sorted(LANGUAGE_NAMES),
        help="Target Latin-script language code. Supported: %(choices)s.",
    )
    parser.add_argument(
        "--auth",
        choices=("api-key", "chatgpt"),
        default=os.environ.get("LLM_TRANSLATE_AUTH", "api-key"),
        help=(
            "Authentication backend. Use api-key for an OpenAI-compatible "
            "chat completions API, or chatgpt to reuse Codex CLI ChatGPT login. "
            "Defaults to LLM_TRANSLATE_AUTH or api-key."
        ),
    )
    parser.add_argument(
        "--api-base",
        default=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        help=(
            "OpenAI-compatible API base URL for --auth api-key. "
            "Defaults to OPENAI_BASE_URL or OpenAI v1."
        ),
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("OPENAI_API_KEY"),
        help="API key for --auth api-key. Defaults to OPENAI_API_KEY.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENAI_MODEL"),
        help=(
            "Model name. Required for --auth api-key; optional Codex model "
            "override for --auth chatgpt. Defaults to OPENAI_MODEL."
        ),
    )
    parser.add_argument(
        "--codex-command",
        default=os.environ.get("CODEX_COMMAND", "codex"),
        help=(
            "Codex CLI executable for --auth chatgpt. Defaults to CODEX_COMMAND "
            "or codex."
        ),
    )
    parser.add_argument(
        "--codex-profile",
        default=os.environ.get("CODEX_PROFILE"),
        help="Optional Codex config profile for --auth chatgpt. Defaults to CODEX_PROFILE.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel API workers. Default: 1.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Sentences per API call. Default: 20.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=4096,
        help="Maximum output tokens per API call. Default: 4096.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="Sampling temperature. Default: 0.2.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="HTTP timeout in seconds. Default: 120.",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="HTTP User-Agent header. Some gateways reject Python's default client.",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=0.0,
        help="Maximum API calls per minute across all workers. Use 0 to disable. Default: 0.",
    )
    parser.add_argument(
        "--exclude-categories",
        default="",
        help=(
            "Comma-separated categories to omit from the output JSON before translation. "
            "Useful for debugging smaller builds."
        ),
    )
    parser.add_argument(
        "--include-ids",
        default="",
        help="Comma- or semicolon-separated entry ids to keep in the output JSON.",
    )
    parser.add_argument(
        "--include-id-ranges",
        default="",
        help=(
            "Comma- or semicolon-separated id ranges to keep, such as "
            "scr_09023-scr_09114."
        ),
    )
    parser.add_argument(
        "--include-categories",
        default="",
        help="Comma- or semicolon-separated exact categories to keep.",
    )
    parser.add_argument(
        "--include-category-prefixes",
        default="",
        help="Comma- or semicolon-separated category prefixes to keep, such as menu_.",
    )
    parser.add_argument(
        "--priority-order",
        action="store_true",
        help="Translate missing entries in priority order instead of JSON order.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Translate at most this many missing entries after filtering/sorting. Use 0 for all.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from an existing output JSON and translate only missing entries.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing output JSON instead of resuming from it.",
    )
    return parser.parse_args()


def validate_args(args, output_path):
    if args.auth not in {"api-key", "chatgpt"}:
        raise SystemExit("error: --auth must be either api-key or chatgpt")
    if args.auth == "api-key" and not args.api_key:
        raise SystemExit(
            "error: --api-key is required or OPENAI_API_KEY must be set when --auth api-key"
        )
    if args.auth == "api-key" and not args.model:
        raise SystemExit(
            "error: --model is required or OPENAI_MODEL must be set when --auth api-key"
        )
    if args.auth == "chatgpt" and not args.codex_command:
        raise SystemExit("error: --codex-command must not be empty when --auth chatgpt")
    if args.workers < 1:
        raise SystemExit("error: --workers must be >= 1")
    if args.batch_size < 1:
        raise SystemExit("error: --batch-size must be >= 1")
    if args.max_tokens < 1:
        raise SystemExit("error: --max-tokens must be >= 1")
    if args.timeout <= 0:
        raise SystemExit("error: --timeout must be > 0")
    if args.rate_limit < 0:
        raise SystemExit("error: --rate-limit must be >= 0")
    if args.limit < 0:
        raise SystemExit("error: --limit must be >= 0")
    if output_path.exists() and not args.resume and not args.overwrite:
        raise SystemExit(
            f"error: {output_path} already exists; use --resume to continue or --overwrite to replace it"
        )
    if args.resume and args.overwrite:
        raise SystemExit("error: --resume and --overwrite cannot be used together")


def main():
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path.with_name(
        f"{input_path.stem}-{args.target}.json"
    )
    validate_args(args, output_path)

    data = load_json(input_path)
    include_ids = parse_value_set(args.include_ids)
    include_ranges = parse_id_ranges(args.include_id_ranges)
    include_categories = parse_category_set(args.include_categories)
    include_prefixes = parse_value_set(args.include_category_prefixes)
    removed_not_included = keep_included_entries(
        data,
        include_ids,
        include_ranges,
        include_categories,
        include_prefixes,
    )
    if removed_not_included:
        print(f"include filters: removed {removed_not_included} non-whitelisted entries")

    excluded_categories = parse_category_set(args.exclude_categories)
    removed_excluded = remove_excluded_categories(data, excluded_categories)
    if removed_excluded:
        print(
            "excluded categories: "
            f"removed {removed_excluded} entries ({', '.join(sorted(excluded_categories))})"
        )

    if args.resume and output_path.exists():
        existing_data = load_json(output_path)
        keep_included_entries(
            existing_data,
            include_ids,
            include_ranges,
            include_categories,
            include_prefixes,
        )
        remove_excluded_categories(existing_data, excluded_categories)
        applied = apply_existing_translations(data, existing_data)
        print(f"resume: restored {applied} completed translations from {output_path}")
    elif args.resume:
        print(f"resume: {output_path} does not exist yet; starting from input JSON")

    work, already_translated, skipped_empty = build_work_items(data)
    total_missing_before_limit = len(work)
    if args.priority_order:
        sort_work_by_priority(work)
    if args.limit:
        work = work[: args.limit]

    total_entries = sum(1 for _index, _entry in iter_entry_refs(data))
    total_translatable = already_translated + len(work)

    print(f"entries: {total_entries}")
    print(f"translatable entries: {total_translatable}")
    print(f"already translated: {already_translated}")
    print(f"missing translations: {len(work)}")
    if args.limit:
        print(f"missing before limit: {total_missing_before_limit}")
        print(f"translation limit: {args.limit}")
    print(f"priority order: {'enabled' if args.priority_order else 'disabled'}")
    print(f"skipped empty translation sources: {skipped_empty}")
    print(f"auth backend: {args.auth}")

    if not work:
        save_json(output_path, data)
        render_progress(total_translatable, total_translatable)
        print()
        print(f"output: {output_path}")
        return 0

    target = target_language_name(args.target)
    batches = list(enumerate(chunked(work, args.batch_size), start=1))
    batch_queue = Queue()
    for batch_number, batch in batches:
        batch_queue.put((batch_number, batch))

    lock = threading.Lock()
    stop_event = threading.Event()
    errors = []
    translated_this_run = 0
    skipped_token_limit = 0
    completed_total = already_translated

    def show_rate_limit_wait(wait_seconds):
        status = None
        if wait_seconds is not None:
            status = f"waiting for rate limit reset ({wait_seconds:.1f}s)"
        with lock:
            render_progress(completed_total, total_translatable, status)

    rate_limiter = RateLimiter(args.rate_limit, show_rate_limit_wait)
    if args.auth == "chatgpt":
        client = CodexExecClient(
            args.codex_command,
            args.model,
            args.codex_profile,
            args.timeout,
            rate_limiter,
        )
    else:
        client = OpenAICompatibleClient(
            args.api_base,
            args.api_key,
            args.model,
            args.max_tokens,
            args.temperature,
            args.timeout,
            args.user_agent,
            rate_limiter,
        )

    render_progress(completed_total, total_translatable)

    def worker():
        nonlocal completed_total, skipped_token_limit, translated_this_run
        while not stop_event.is_set():
            try:
                _batch_number, batch = batch_queue.get_nowait()
            except Empty:
                return

            try:
                translations = client.translate_batch(batch, target)
                if stop_event.is_set():
                    return

                with lock:
                    batch_translated = 0
                    for item, translated in zip(batch, translations):
                        if isinstance(translated, SkippedTranslation):
                            skipped_token_limit += 1
                            sys.stdout.write("\n")
                            print(
                                f"warning: skipped {translated.entry_id} due to output token limit"
                            )
                            continue
                        item["entry"]["translated"] = translated
                        batch_translated += 1
                    translated_this_run += batch_translated
                    completed_total += batch_translated
                    save_json(output_path, data)
                    render_progress(completed_total, total_translatable)
            except Exception as exc:
                with lock:
                    if not errors:
                        errors.append(exc)
                    stop_event.set()
                return
            finally:
                batch_queue.task_done()

    threads = [
        threading.Thread(target=worker, name=f"translator-{index + 1}")
        for index in range(min(args.workers, len(batches)))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    print()
    if errors:
        print(f"error: {errors[0]}", file=sys.stderr)
        print(
            "stopped: completed batches were saved; rerun with --resume after fixing the issue",
            file=sys.stderr,
        )
        return 1

    print(f"translated this run: {translated_this_run}")
    if skipped_token_limit:
        print(f"skipped due to output token limit: {skipped_token_limit}")
    print(f"output: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
