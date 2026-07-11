import io
import json
import tempfile
import unittest

from lib.pokeapi_localizer import PokeAPILocalizer, apply_pokeapi_translations


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class FakeOpener:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def __call__(self, request, timeout):
        self.calls.append((request.full_url, timeout))
        payload = self.payloads[request.full_url]
        return FakeResponse(json.dumps(payload).encode("utf-8"))


def localized(language, name=None, flavor_text=None, version_group=None):
    value = {"language": {"name": language}}
    if name is not None:
        value["name"] = name
    if flavor_text is not None:
        value["flavor_text"] = flavor_text
    if version_group is not None:
        value["version_group"] = {"name": version_group}
    return value


class PokeAPILocalizerTests(unittest.TestCase):
    def make_localizer(self, payloads, cache_dir):
        opener = FakeOpener(payloads)
        localizer = PokeAPILocalizer(
            "it", cache_dir, base_url="https://example.test/api/v2", opener=opener
        )
        return localizer, opener

    def test_validated_name_is_localized_and_cached(self):
        url = "https://example.test/api/v2/move/85/"
        payload = {
            "names": [localized("en", name="Thunderbolt"), localized("it", name="Fulmine")]
        }
        with tempfile.TemporaryDirectory() as cache_dir:
            localizer, opener = self.make_localizer({url: payload}, cache_dir)
            entry = {
                "category": "move_names",
                "table_index": 85,
                "translation_source": "Thunderbolt",
            }
            self.assertEqual(localizer.translate_entry(entry), "Fulmine")
            self.assertEqual(localizer.translate_entry(entry), "Fulmine")
            self.assertEqual(len(opener.calls), 1)

    def test_name_mismatch_falls_back(self):
        url = "https://example.test/api/v2/item/1/"
        list_url = "https://example.test/api/v2/item/?limit=10000"
        payload = {
            "names": [localized("en", name="Master Ball"), localized("it", name="Master Ball")]
        }
        with tempfile.TemporaryDirectory() as cache_dir:
            localizer, _opener = self.make_localizer(
                {url: payload, list_url: {"results": []}}, cache_dir
            )
            entry = {
                "category": "item_names",
                "table_index": 1,
                "translation_source": "Custom Ball",
            }
            self.assertIsNone(localizer.translate_entry(entry))

    def test_flavor_text_uses_matching_version_group(self):
        url = "https://example.test/api/v2/move/1/"
        payload = {
            "flavor_text_entries": [
                localized("en", flavor_text="Old text.", version_group="red-blue"),
                localized("it", flavor_text="Testo vecchio.", version_group="red-blue"),
                localized("en", flavor_text="Hits the target.", version_group="firered-leafgreen"),
                localized("it", flavor_text="Colpisce il bersaglio.", version_group="firered-leafgreen"),
            ]
        }
        with tempfile.TemporaryDirectory() as cache_dir:
            localizer, _opener = self.make_localizer({url: payload}, cache_dir)
            entry = {
                "category": "move_descriptions",
                "table_index": 0,
                "translation_source": "Hits the target.",
            }
            self.assertEqual(localizer.translate_entry(entry), "Colpisce il bersaglio.")

    def test_apply_skips_existing_and_protected_entries(self):
        entries = [
            {"category": "move_names", "translated": "Manuale"},
            {
                "category": "move_names",
                "translation_source": "[buffer1-1]",
                "semantic_token_placeholders": [{"placeholder": "[buffer1-1]"}],
            },
            {"category": "scripts", "translation_source": "Hello"},
        ]
        with tempfile.TemporaryDirectory() as cache_dir:
            localizer, opener = self.make_localizer({}, cache_dir)
            translated, candidates = apply_pokeapi_translations(
                iter(entries), localizer
            )
            self.assertEqual((translated, candidates), (0, 1))
            self.assertEqual(opener.calls, [])

    def test_apply_reports_progress_for_every_eligible_entry(self):
        entries = [
            {
                "category": "move_names",
                "translation_source": "[buffer1-1]",
                "semantic_token_placeholders": [{"placeholder": "[buffer1-1]"}],
            },
            {"category": "scripts", "translation_source": "Hello"},
        ]
        with tempfile.TemporaryDirectory() as cache_dir:
            localizer, _opener = self.make_localizer({}, cache_dir)
            progress = []
            apply_pokeapi_translations(
                iter(entries), localizer, lambda *values: progress.append(values)
            )
            self.assertEqual(progress, [(1, 1, 0)])

    def test_apply_uses_parallel_workers(self):
        payloads = {
            "https://example.test/api/v2/move/85/": {
                "names": [localized("en", name="Thunderbolt"), localized("it", name="Fulmine")]
            },
            "https://example.test/api/v2/move/86/": {
                "names": [localized("en", name="Thunder"), localized("it", name="Tuono")]
            },
        }
        entries = [
            {"category": "move_names", "table_index": 85, "translation_source": "Thunderbolt"},
            {"category": "move_names", "table_index": 86, "translation_source": "Thunder"},
        ]
        with tempfile.TemporaryDirectory() as cache_dir:
            localizer, opener = self.make_localizer(payloads, cache_dir)
            translated, candidates = apply_pokeapi_translations(entries, localizer, workers=2)
            self.assertEqual((translated, candidates), (2, 2))
            self.assertEqual(len(opener.calls), 2)

    def test_parallel_entries_share_one_resource_request(self):
        url = "https://example.test/api/v2/move/85/"
        payload = {
            "names": [localized("en", name="Thunderbolt"), localized("it", name="Fulmine")],
            "flavor_text_entries": [
                localized("en", flavor_text="Hits the target.", version_group="firered-leafgreen"),
                localized("it", flavor_text="Colpisce il bersaglio.", version_group="firered-leafgreen"),
            ],
        }
        entries = [
            {"category": "move_names", "table_index": 85, "translation_source": "Thunderbolt"},
            {"category": "move_descriptions", "table_index": 84, "translation_source": "Hits the target."},
        ]
        with tempfile.TemporaryDirectory() as cache_dir:
            localizer, opener = self.make_localizer({url: payload}, cache_dir)
            translated, candidates = apply_pokeapi_translations(entries, localizer, workers=2)
            self.assertEqual((translated, candidates), (2, 2))
            self.assertEqual(len(opener.calls), 1)

    def test_type_alias_uses_pokeapi_slug(self):
        url = "https://example.test/api/v2/type/fighting/"
        payload = {
            "names": [localized("en", name="Fighting"), localized("it", name="Lotta")]
        }
        with tempfile.TemporaryDirectory() as cache_dir:
            localizer, _opener = self.make_localizer({url: payload}, cache_dir)
            entry = {"category": "type_names", "translation_source": "Fight"}
            self.assertEqual(localizer.translate_entry(entry), "Lotta")

    def test_genus_accepts_rom_label_without_pokemon(self):
        url = "https://example.test/api/v2/pokemon-species/1/"
        payload = {
            "genera": [
                {"language": {"name": "en"}, "genus": "Seed Pokémon"},
                {"language": {"name": "it"}, "genus": "Pokémon Seme"},
            ]
        }
        with tempfile.TemporaryDirectory() as cache_dir:
            localizer, _opener = self.make_localizer({url: payload}, cache_dir)
            entry = {"category": "pokedex_species", "table_index": 0, "translation_source": "Seed"}
            self.assertEqual(localizer.translate_entry(entry), "Pokémon Seme")

    def test_name_falls_back_to_pokeapi_resource_slug(self):
        numeric_url = "https://example.test/api/v2/item/13/"
        list_url = "https://example.test/api/v2/item/?limit=10000"
        potion_url = "https://example.test/api/v2/item/potion/"
        payloads = {
            numeric_url: {"names": [localized("en", name="Old Item")]},
            list_url: {"results": [{"name": "potion"}]},
            potion_url: {
                "names": [localized("en", name="Potion"), localized("it", name="Pozione")]
            },
        }
        with tempfile.TemporaryDirectory() as cache_dir:
            localizer, opener = self.make_localizer(payloads, cache_dir)
            entry = {"category": "item_names", "table_index": 13, "translation_source": "Potion"}
            self.assertEqual(localizer.translate_entry(entry), "Pozione")
            self.assertEqual(len(opener.calls), 3)


if __name__ == "__main__":
    unittest.main()
