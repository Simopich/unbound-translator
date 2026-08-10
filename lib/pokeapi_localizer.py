import json
import re
import threading
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

POKEAPI_LANGUAGE = {"pt-br": "pt-BR"}

# category: (resource endpoint, localized field kind, identifier strategy)
CATEGORY_SPECS = {
    "pokemon_names": ("pokemon-species", "name", "table_index"),
    "pokedex_species": ("pokemon-species", "genus", "table_index_plus_one"),
    "pokedex_descriptions": ("pokemon-species", "flavor", "table_index_plus_one"),
    "move_names": ("move", "name", "table_index"),
    "move_descriptions": ("move", "flavor", "table_index_plus_one"),
    "item_names": ("item", "name", "table_index"),
    "item_descriptions": ("item", "flavor", "table_index"),
    "ability_names": ("ability", "name", "table_index"),
    "ability_descriptions": ("ability", "flavor", "table_index"),
    "type_names": ("type", "name", "source_slug"),
    "nature_names": ("nature", "name", "source_slug"),
    "habitat_names": ("pokemon-habitat", "habitat", "source_slug"),
}

SOURCE_SLUG_ALIASES = {
    "type_names": {"fight": "fighting"},
}

SOURCE_RESOURCE_ALIASES = {
    "item_names": {
        "aerodactite": "aerodactylite",
        "blastoisite": "blastoisinite",
        "charizitex": "charizarditex",
        "charizitey": "charizarditey",
        "houndoomite": "houndoominite",
        "kangaskhite": "kangaskhanite",
        "lumiosegale": "lumiosegalette",
        "marangberry": "marangaberry",
        "parlyzheal": "paralyzeheal",
        "weakpolicy": "weaknesspolicy",
        "whipdream": "whippeddream",
    },
    "move_names": {
        "1000waves": "thousandwaves",
        "aromamist": "aromaticmist",
        "banefulbunk": "banefulbunker",
        "breakswipe": "breakingswipe",
        "clangscales": "clangingscales",
        "clangsoul": "clangoroussoul",
        "coreenforce": "coreenforcer",
        "darklariat": "darkestlariat",
        "dazzlegleam": "dazzlinggleam",
        "dolleyes": "babydolleyes",
        "doubleiron": "doubleironbash",
        "dracohammer": "dragonhammer",
        "electerrain": "electricterrain",
        "endlessedge": "ceaselessedge",
        "expandforce": "expandingforce",
        "faintattack": "feintattack",
        "firstpress": "firstimpression",
        "geistbeam": "moongeistbeam",
        "grassterrain": "grassyterrain",
        "hijumpkick": "highjumpkick",
        "infernalrage": "infernalparade",
        "jungleheal": "junglehealing",
        "lightoruin": "lightofruin",
        "lunarbless": "lunarblessing",
        "magnetflux": "magneticflux",
        "mistterrain": "mistyterrain",
        "mistyexplode": "mistyexplosion",
        "mysticfire": "mysticalfire",
        "mysticpower": "mysticalpower",
        "paracharge": "paraboliccharge",
        "prismlaser": "prismaticlaser",
        "psycterrain": "psychicterrain",
        "psychicfang": "psychicfangs",
        "psyshieldram": "psyshieldbash",
        "reveldance": "revelationdance",
        "risingvolt": "risingvoltage",
        "scorchsands": "scorchingsands",
        "smellingsalt": "smellingsalts",
        "spacefury": "hyperspacefury",
        "spacehole": "hyperspacehole",
        "sparklearia": "sparklingaria",
        "spectthief": "spectralthief",
        "sunsteelram": "sunsteelstrike",
        "surgestrikes": "surgingstrikes",
        "tearylook": "tearfullook",
        "thunderkick": "thunderouskick",
        "trickotreat": "trickortreat",
        "woodscurse": "forestscurse",
    },
    "ability_names": {
        "neutralizegas": "neutralizinggas",
        "watercompact": "watercompaction",
    },
}


def normalized(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def compact_text(text):
    return " ".join((text or "").replace("\f", " ").replace("\n", " ").split())


def source_slug(source, category):
    alias = SOURCE_SLUG_ALIASES.get(category, {}).get(source.casefold())
    if alias:
        return alias
    source = unicodedata.normalize("NFKD", source)
    source = "".join(char for char in source if not unicodedata.combining(char))
    source = source.replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "-", source.casefold()).strip("-")


def same_genus(source, english_genus):
    source_key = normalized(source)
    genus_key = normalized(english_genus)
    return source_key == genus_key or genus_key == source_key + "pokemon"


def same_name(source, english_name, category):
    expected = SOURCE_SLUG_ALIASES.get(category, {}).get(source.casefold(), source)
    expected_key = normalized(expected)
    expected_key = SOURCE_RESOURCE_ALIASES.get(category, {}).get(expected_key, expected_key)
    return normalized(english_name) == expected_key


def language_value(items, language, field):
    wanted = POKEAPI_LANGUAGE.get(language, language).casefold()
    for item in items or []:
        item_language = item.get("language", {}).get("name", "").casefold()
        value = item.get(field)
        if item_language == wanted and isinstance(value, str) and value.strip():
            return compact_text(value)
    return None


def paired_flavor_value(items, source, language):
    source_key = normalized(source)
    if not source_key:
        return None

    version_keys = ("version", "version_group")
    matching_contexts = []
    for item in items or []:
        if item.get("language", {}).get("name") != "en":
            continue
        if normalized(item.get("flavor_text", "")) != source_key:
            continue
        for key in version_keys:
            context = item.get(key, {}).get("name")
            if context:
                matching_contexts.append((key, context))

    wanted = POKEAPI_LANGUAGE.get(language, language).casefold()
    for key, context in matching_contexts:
        for item in items or []:
            if (
                    item.get("language", {}).get("name", "").casefold() == wanted
                    and item.get(key, {}).get("name") == context
            ):
                value = compact_text(item.get("flavor_text", ""))
                if value:
                    return value
    return None


class PokeAPILocalizer:
    def __init__(
            self,
            target_language,
            cache_dir,
            base_url="https://pokeapi.co/api/v2",
            timeout=30.0,
            user_agent="unbound-translator/1.0",
            opener=None,
    ):
        self.target_language = target_language
        self.cache_dir = Path(cache_dir)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.user_agent = user_agent
        self.opener = opener or urllib.request.urlopen
        self.memory_cache = {}
        self.cache_lock = threading.Lock()
        self.inflight = {}
        self.resource_slugs = {}
        self.resource_slug_inflight = {}

    def _get(self, endpoint, identifier):
        key = f"{endpoint}/{identifier}"
        with self.cache_lock:
            if key in self.memory_cache:
                return self.memory_cache[key]
            waiting_for = self.inflight.get(key)
            if waiting_for is None:
                waiting_for = threading.Event()
                self.inflight[key] = waiting_for
                is_request_owner = True
            else:
                is_request_owner = False

        if not is_request_owner:
            waiting_for.wait()
            with self.cache_lock:
                return self.memory_cache.get(key)

        try:
            cache_path = self.cache_dir / endpoint / f"{identifier}.json"
            if cache_path.exists():
                try:
                    payload = json.loads(cache_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    payload = None
            else:
                payload = None

            if payload is None:
                url = f"{self.base_url}/{endpoint}/{urllib.parse.quote(str(identifier))}/"
                request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
                try:
                    with self.opener(request, timeout=self.timeout) as response:
                        payload = json.load(response)
                except (OSError, ValueError, urllib.error.HTTPError, urllib.error.URLError):
                    payload = None

            if payload is not None:
                try:
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(
                        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
                    )
                except OSError:
                    pass
        finally:
            with self.cache_lock:
                self.memory_cache[key] = payload if "payload" in locals() else None
                self.inflight.pop(key).set()

        payload = self.memory_cache[key]
        return payload

    def _resource_slugs(self, endpoint):
        with self.cache_lock:
            if endpoint in self.resource_slugs:
                return self.resource_slugs[endpoint]
            waiting_for = self.resource_slug_inflight.get(endpoint)
            if waiting_for is None:
                waiting_for = threading.Event()
                self.resource_slug_inflight[endpoint] = waiting_for
                is_request_owner = True
            else:
                is_request_owner = False

        if not is_request_owner:
            waiting_for.wait()
            with self.cache_lock:
                return self.resource_slugs.get(endpoint, {})

        slugs = {}
        try:
            cache_path = self.cache_dir / "_lists" / f"{endpoint}.json"
            if cache_path.exists():
                try:
                    payload = json.loads(cache_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    payload = None
            else:
                payload = None

            if payload is None:
                url = f"{self.base_url}/{endpoint}/?limit=10000"
                request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
                try:
                    with self.opener(request, timeout=self.timeout) as response:
                        payload = json.load(response)
                except (OSError, ValueError, urllib.error.HTTPError, urllib.error.URLError):
                    payload = None

            if isinstance(payload, dict):
                for item in payload.get("results", []):
                    name = item.get("name") if isinstance(item, dict) else None
                    if isinstance(name, str) and name:
                        slugs.setdefault(normalized(name), name)
                if slugs:
                    try:
                        cache_path.parent.mkdir(parents=True, exist_ok=True)
                        cache_path.write_text(
                            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
                        )
                    except OSError:
                        pass
        finally:
            with self.cache_lock:
                self.resource_slugs[endpoint] = slugs
                self.resource_slug_inflight.pop(endpoint).set()
        return slugs

    def _localized_value(self, payload, kind, source, category):
        if not payload:
            return None
        if kind == "name":
            english = language_value(payload.get("names"), "en", "name")
            if not same_name(source, english, category):
                return None
            return language_value(payload.get("names"), self.target_language, "name")
        if kind == "genus":
            english = language_value(payload.get("genera"), "en", "genus")
            if not same_genus(source, english):
                return None
            return language_value(payload.get("genera"), self.target_language, "genus")
        if kind == "habitat":
            english = language_value(payload.get("names"), "en", "name")
            if normalized(english) not in normalized(source):
                return None
            return language_value(payload.get("names"), self.target_language, "name")
        if kind == "flavor":
            return paired_flavor_value(
                payload.get("flavor_text_entries"), source, self.target_language
            )
        return None

    def translate_entry(self, entry):
        spec = CATEGORY_SPECS.get(entry.get("category"))
        source = entry.get("translation_source")
        if not isinstance(source, str) or not source.strip():
            return None
        if entry.get("semantic_token_placeholders"):
            return None

        endpoint, kind, strategy = spec if spec else (None, None, None)
        if endpoint is None:
            return None

        if strategy == "source_slug":
            slug_source = re.sub(r"\s+pok[eé]mon$", "", source, flags=re.IGNORECASE)
            identifier = source_slug(slug_source, entry.get("category", ""))
        elif strategy in {"table_index", "table_index_plus_one"}:
            table_index = entry.get("table_index")
            if not isinstance(table_index, int):
                return None
            identifier = table_index + (1 if strategy == "table_index_plus_one" else 0)
            if identifier < 1:
                return None
        else:
            return None

        category = entry.get("category", "")
        localized = self._localized_value(self._get(endpoint, identifier), kind, source, category)
        if localized:
            return localized

        if kind != "name" or strategy not in {"table_index", "table_index_plus_one"}:
            return None

        source_key = normalized(source)
        source_key = SOURCE_RESOURCE_ALIASES.get(category, {}).get(source_key, source_key)
        slug = self._resource_slugs(endpoint).get(source_key)
        if slug is None or slug == str(identifier):
            return None
        return self._localized_value(self._get(endpoint, slug), kind, source, category)


def apply_pokeapi_translations(entries, localizer, progress_callback=None, workers=1):
    translated = 0
    candidates = 0
    candidates_entries = [
        entry
        for entry in entries
        if entry.get("category") in CATEGORY_SPECS
           and not (isinstance(entry.get("translated"), str) and entry["translated"].strip())
    ]
    total = len(candidates_entries)
    candidates = total
    if workers < 1:
        raise ValueError("PokeAPI workers must be at least 1")

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pokeapi") as executor:
        future_to_entry = {
            executor.submit(localizer.translate_entry, entry): entry
            for entry in candidates_entries
        }
        for completed, future in enumerate(as_completed(future_to_entry), start=1):
            localized = future.result()
            if localized:
                future_to_entry[future]["translated"] = localized
                translated += 1
            if progress_callback:
                progress_callback(completed, total, translated)
    return translated, candidates
