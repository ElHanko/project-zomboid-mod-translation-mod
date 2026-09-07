"""Regression coverage using isolated drafts, runtime trees and Workshop fixtures."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

import apply
import build
import common
import config
import draft
import export
import progress
import pzgt
import status
import verify
import work
from test_shared_keys import entry, draft as fixture_draft


class ConfigTests(unittest.TestCase):
    def test_default_and_explicit_languages(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            values = {key: "/example" for key in ("game", "workshop", "zomboid_home")}
            for languages in (None, ["DE"], ["DE", "FR"], ["PT-BR"]):
                if languages is not None:
                    values["languages"] = languages
                path.write_text(json.dumps(values))
                self.assertEqual(config.load_config(path)["languages"], languages or ["DE"])

    def test_invalid_languages(self):
        for languages in ([], None, "DE", [1], [""], [" "], [" DE"], ["."], [".."],
                          ["../FR"], ["FR/DE"], ["FR\\DE"], ["C:DE"], ["DE\0"],
                          ["DE\n"], ["DE\x7f"], ["DE\x85"], ["DE", "de"]):
            with self.subTest(languages=languages), self.assertRaises(ValueError):
                config.validate_languages(languages)

    def test_language_selection(self):
        with patch.object(config, "LANGUAGES", ["DE"]):
            self.assertEqual(config.select_language(), "DE")
        with patch.object(config, "LANGUAGES", ["DE", "FR"]):
            with self.assertRaisesRegex(ValueError, "Mehrere Zielsprachen"):
                config.select_language()
            self.assertEqual(config.selected_languages(), ["DE", "FR"])
            self.assertEqual(config.select_language("FR"), "FR")
            with self.assertRaises(ValueError):
                config.select_language("ES")


class MigrationTests(unittest.TestCase):
    def legacy(self):
        return {"entries": [{"category": "UI", "key": "UI_Key", "english": "New",
                             "german": "  Übersetzung\n%1  ", "needed": False, "review": True,
                             "previous_english": "Old"}]}

    def test_lossless_and_idempotent(self):
        old = self.legacy()
        original = deepcopy(old)
        migrated = common.migrate_draft(old)
        self.assertEqual(old, original)
        state = migrated["entries"][0]["translations"]["DE"]
        self.assertEqual(state, {"text": old["entries"][0]["german"], "needed": False,
                                 "review": True, "previous_english": "Old"})
        common.validate_draft(Path("test.json"), migrated)
        self.assertEqual(common.migrate_draft(migrated), migrated)
        self.assertFalse(set(common.LEGACY_FIELDS) & migrated["entries"][0].keys())

    def test_mixed_and_ambiguous_states_rejected(self):
        cases = []
        mixed = self.legacy()
        mixed["entries"][0]["translations"] = {"DE": {"text": "conflict"}}
        cases.append(mixed)
        mixed = self.legacy()
        mixed["entries"].append(entry())
        cases.append(mixed)
        for field in ("german", "needed", "review"):
            malformed = self.legacy()
            malformed["entries"][0].pop(field)
            cases.append(malformed)
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                common.migrate_draft(case)

    def test_legacy_rejected_outside_migration(self):
        with self.assertRaisesRegex(ValueError, "draft --all"):
            common.validate_draft(Path("test.json"), self.legacy())

    def test_malformed_generic_states_rejected(self):
        for field, value in (("text", 3), ("needed", 1), ("review", None), ("previous_english", [])):
            e = entry()
            e["translations"]["DE"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                common.validate_draft(Path("test.json"), {"entries": [e]})


class TemporaryRepository(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(TemporaryDirectory()))
        self.stack.enter_context(redirect_stdout(StringIO()))
        self.stack.enter_context(redirect_stderr(StringIO()))
        for name, value in {"ROOT": self.root, "DATA": self.root / "data",
                            "TRANSLATIONS": self.root / "translations",
                            "TRANSLATE": self.root / "common/media/lua/shared/Translate",
                            "LANGUAGES": ["DE", "FR"]}.items():
            self.stack.enter_context(patch.object(config, name, value))
        (self.root / "LICENSE").write_text("Fixture license\n")

    def store(self, data=None, name="123__mod.json"):
        data = data or fixture_draft("mod", [entry()])[1]
        path = config.TRANSLATIONS / name
        common.write_json(path, data)
        return path, data

    def bilingual(self, fr="", needed=True):
        e = entry()
        e["translations"]["FR"] = {"text": fr, "needed": needed, "review": False}
        return fixture_draft("mod", [e])[1]

    def source_mod(self, english="Roofrack", needed=True):
        source = {"category": "IG_UI", "key": "IGUI_VehiclePartGM85Roofrack", "text": english,
                  "file": "IG_UI.json", "layer": "common", "format": "json"}
        return {"workshop_id": "123", "mod_id": "mod", "directory": "mod", "name": "Mod",
                "effective_layers": ["common"], "english": [source], "missing": [source] if needed else [],
                "blank": [], "counts": {"open": int(needed), "parse_errors": 0}}

    def save_status(self, mod=None, language="DE"):
        common.write_json(config.DATA / "status.json", {"language": language, "game_version": "42.20.4",
                                                       "mods": [mod or self.source_mod()]})


class RefreshTests(TemporaryRepository):
    def test_new_language_unknown_and_refresh_independent(self):
        before = [entry()]
        updated = draft.merge_entries(self.source_mod(), before, "DE")
        self.assertIsNone(updated[0]["translations"]["FR"]["needed"])
        self.assertEqual(updated[0]["translations"]["DE"], before[0]["translations"]["DE"])
        final = draft.merge_entries(self.source_mod(needed=False), updated, "FR")
        self.assertFalse(final[0]["translations"]["FR"]["needed"])
        self.assertEqual(final[0]["translations"]["DE"], before[0]["translations"]["DE"])

    def test_changes_review_all_languages_and_preserve_first_source(self):
        before = self.bilingual("Fixture FR")["entries"]
        updated = draft.merge_entries(self.source_mod("New", needed=False), before, "DE")
        for language in ("DE", "FR"):
            state = updated[0]["translations"][language]
            self.assertTrue(state["review"])
            self.assertEqual(state["previous_english"], "Roofrack")
            self.assertEqual(state["text"], before[0]["translations"][language]["text"])
        twice = draft.merge_entries(self.source_mod("Newest"), updated, "FR")
        self.assertEqual(twice[0]["translations"]["DE"]["previous_english"], "Roofrack")
        self.assertFalse(twice[0]["translations"]["DE"]["needed"])

    def test_retired_and_removed_language_states_preserved(self):
        before = self.bilingual("Fixture FR")["entries"]
        before[0]["translations"]["ES"] = {"text": "Fixture ES", "needed": True, "review": False}
        mod = self.source_mod()
        mod.update(english=[], missing=[])
        after = draft.merge_entries(mod, before, "DE")
        self.assertEqual(after[0]["english"], before[0]["english"])
        self.assertFalse(after[0]["translations"]["DE"]["needed"])
        for language in ("FR", "ES"):
            self.assertEqual(after[0]["translations"][language], before[0]["translations"][language])

    def test_draft_workflow_migrates_and_uses_status_language(self):
        legacy = fixture_draft("mod", [entry()])[1]
        e = legacy["entries"][0]
        e.pop("translations")
        e.update(german="Erhalten", needed=True, review=False)
        path, _ = self.store(legacy)
        self.save_status(language="FR")
        draft.run("--all")
        after = common.load_json(path)
        self.assertEqual(after["entries"][0]["translations"]["DE"]["text"], "Erhalten")
        self.assertTrue(after["entries"][0]["translations"]["DE"]["needed"])
        self.assertTrue(after["entries"][0]["translations"]["FR"]["needed"])

    def test_missing_language_and_parser_error_abort_without_write(self):
        path, _ = self.store()
        original = path.read_bytes()
        self.save_status(language=None)
        with self.assertRaises(ValueError):
            draft.run("--all")
        mod = self.source_mod()
        mod["counts"]["parse_errors"] = 1
        self.save_status(mod)
        with self.assertRaises(ValueError):
            draft.run("--all")
        self.assertEqual(path.read_bytes(), original)

    def test_all_prevalidated_before_any_draft_write(self):
        path, _ = self.store()
        broken, _ = self.store(name="999__broken.json")
        data = common.load_json(broken)
        data["entries"][0]["german"] = "conflict"
        common.write_json(broken, data)
        original = path.read_bytes()
        self.save_status()
        with self.assertRaises(ValueError):
            draft.run("--all")
        self.assertEqual(path.read_bytes(), original)

    def test_missing_mod_migrates_without_retiring_known_need(self):
        path, data = self.store()
        common.write_json(config.DATA / "status.json", {"language": "FR", "game_version": "42", "mods": []})
        draft.run("--all")
        after = common.load_json(path)["entries"][0]["translations"]
        self.assertEqual(after["DE"], data["entries"][0]["translations"]["DE"])
        self.assertIsNone(after["FR"]["needed"])


class CatalogueTests(TemporaryRepository):
    def test_refresh_all_only_updates_known_drafts(self):
        path, data = self.store(self.bilingual("FR fixture"))
        unknown = self.source_mod()
        unknown.update(workshop_id="456", mod_id="unknown", directory="unknown")
        unknown["counts"]["parse_errors"] = 1
        common.write_json(config.DATA / "status.json", {"language": "DE", "game_version": "42.20.4",
                                                       "mods": [unknown]})
        draft.run("--all")
        self.assertEqual(common.load_json(path), data)
        self.assertEqual(list(config.TRANSLATIONS.glob("*.json")), [path])

    def test_unknown_filename_collision_cannot_refresh_known_draft(self):
        path, data = self.store(self.bilingual("FR fixture"))
        unknown = self.source_mod("Changed by unrelated mod")
        unknown["directory"] = "different_mod_with_same_id"
        self.save_status(unknown)
        draft.run("--all")
        self.assertEqual(common.load_json(path), data)
        with self.assertRaisesRegex(ValueError, "Mehrdeutiger Draft-Dateiname"):
            draft.run("different_mod_with_same_id")
        self.assertEqual(common.load_json(path), data)

    def test_explicit_adoption_is_required(self):
        self.save_status()
        draft.run("--all")
        self.assertFalse(list(config.TRANSLATIONS.glob("*.json")))
        draft.run("mod")
        drafts = common.load_drafts()
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0][1]["mod_id"], "mod")
        self.assertTrue(drafts[0][1]["entries"][0]["translations"]["DE"]["needed"])

    def fixture_workshop(self):
        values = {"workshop": self.root / "workshop", "game": self.root / "game",
                  "zomboid_home": self.root / "user"}
        values["zomboid_home"].mkdir()
        (values["game"] / "projectzomboid/media/lua/shared/Translate/EN").mkdir(parents=True)
        (values["zomboid_home"] / "console.txt").write_text("> version=42.20.4\n")
        self.stack.enter_context(patch.object(pzgt, "load_config", return_value=values))
        for name in ("A", "B", "C"):
            data = self.bilingual("FR " + name)
            data.update(mod_id=name, directory=name, name=name,
                        game_version="42.20.4", effective_layers=["common"])
            data["entries"][0]["key"] = "Key_" + name
            self.store(data, "123__" + name + ".json")
            if name != "B":
                base = values["workshop"] / "123/mods" / name / "common"
                translate = base / "media/lua/shared/Translate/EN"
                translate.mkdir(parents=True)
                (base / "mod.info").write_text(f"id={name}\nname={name}\n")
                (translate / "IG_UI.json").write_text(json.dumps({"Key_" + name: "Roofrack"}))
        unknown = values["workshop"] / "456/mods/unknown/common/media/lua/shared/Translate/EN"
        unknown.mkdir(parents=True)
        (unknown / "IG_UI.json").write_text("invalid JSON from unsupported mod")
        return values

    def test_abc_catalogue_keeps_absent_b_in_both_languages(self):
        values = self.fixture_workshop()
        before = common.read_tree(config.TRANSLATIONS)
        build.run()
        expected = common.read_tree(config.TRANSLATE)
        output = StringIO()
        with redirect_stdout(output):
            verify.run()
        for language in ("DE", "FR"):
            self.assertIn(f"Source-Sync {language}: geprüft: 2 | Quelle nicht lokal: 1 | Abweichend: 0", output.getvalue())
            runtime = json.loads(expected[Path(language) / "IG_UI.json"])
            self.assertEqual(set(runtime), {"Key_A", "Key_B", "Key_C"})
        export.run(make_zip=True)
        distribution = common.read_tree(self.root / "dist" / export.MOD_DIRECTORY)
        supported = distribution[Path("SUPPORTED-MODS.txt")].decode("utf-8")
        for mod_id in ("A", "B", "C"):
            self.assertIn(f"Mod ID: {mod_id}", supported)
        self.assertEqual(supported.count("  Languages: DE, FR"), 3)

        for language in ("DE", "FR"):
            rel = Path("common/media/lua/shared/Translate") / language / "IG_UI.json"
            self.assertEqual(distribution[rel], expected[Path(language) / "IG_UI.json"])
        pzgt.cmd_scan()
        for language in ("DE", "FR"):
            status.run(language)
            draft.run("--all")
        self.assertEqual((config.TRANSLATIONS / "123__B.json").read_bytes(), before[Path("123__B.json")])
        self.assertEqual(len(common.load_drafts()), 3)
        build.run()
        self.assertEqual(common.read_tree(config.TRANSLATE), expected)
        verify.run()
        # Returning supported sources are checked immediately, including changed English.
        base = values["workshop"] / "123/mods/B/common"
        translate = base / "media/lua/shared/Translate/EN"
        translate.mkdir(parents=True)
        (base / "mod.info").write_text("id=B\nname=B\n")
        source = translate / "IG_UI.json"
        source.write_text('{"Key_B": "Changed English"}')
        with self.assertRaisesRegex(ValueError, "englischer Quelltext geändert"):
            verify.run()
        source.write_text('{"Key_B": "Roofrack"}')
        verify.run()
        self.assertEqual(common.read_tree(config.TRANSLATE), expected)

    def test_no_local_sources_needs_no_game_log(self):
        values = self.fixture_workshop()
        shutil.rmtree(values["workshop"])
        (values["zomboid_home"] / "console.txt").unlink()
        build.run()
        output = StringIO()
        with redirect_stdout(output):
            verify.run()
        self.assertIn("geprüft: 0 | Quelle nicht lokal: 3 | Abweichend: 0", output.getvalue())
        export.run()
        # An unrelated installed mod also does not require a source check/game log.
        (values["workshop"] / "999/mods/unrelated").mkdir(parents=True)
        with patch.object(pzgt, "discover_layers", side_effect=AssertionError("Unknown source inspected")):
            verify.run()

    def test_absent_source_still_requires_valid_placeholders_and_runtime(self):
        values = self.fixture_workshop()
        shutil.rmtree(values["workshop"])
        build.run()
        (config.TRANSLATE / "DE/IG_UI.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "Runtime-Datei stimmt nicht"):
            verify.run()
        data = common.load_json(config.TRANSLATIONS / "123__B.json")
        data["entries"][0]["translations"]["FR"]["text"] = "Invalid %1"
        common.write_json(config.TRANSLATIONS / "123__B.json", data)
        build.run()
        with self.assertRaisesRegex(ValueError, "Placeholder-Abweichung"):
            verify.run()

    def test_ambiguous_installed_source_remains_error(self):
        path, data = self.store(self.bilingual("FR fixture"))
        snapshot = {"language": "DE", "mods": [self.source_mod(), self.source_mod()]}
        self.assertIn("nicht eindeutig", verify.source_errors(path, data, snapshot, "DE")[0])
        self.assertIsNone(verify.source_errors(path, data, {"language": "DE", "mods": []}, "DE"))


class WorkApplyTests(TemporaryRepository):
    def test_next_ranks_open_entries_in_selected_category(self):
        drafts = [
            fixture_draft("few_total", [entry("ItemName", f"Base.Item{i}", text="")
                                       for i in range(2)]),
            fixture_draft("few_itemnames", [entry("ItemName", "Base.SeatFabric", text="")]
                          + [entry("UI", f"UI_Test{i}", text="") for i in range(4)]),
            fixture_draft("other_category", [entry("UI", "UI_Other", text="")]),
        ]
        package = work.make_work(drafts, language="DE", category="ItemName")
        self.assertEqual(package["mod_id"], "few_itemnames")
        self.assertEqual(package["category"], "ItemName")
        self.assertEqual(package["open_total"], 1)
        self.assertEqual([e["key"] for e in package["entries"]], ["Base.SeatFabric"])
        self.assertEqual(work.make_work(drafts[:2], language="DE")["mod_id"], "few_total")

    def test_language_filenames_and_original_translation(self):
        data = self.bilingual("Fixture FR")
        for state in data["entries"][0]["translations"].values():
            state["review"] = True
        self.store(data)
        for language in ("DE", "FR"):
            work.run(language=language)
            path = config.DATA / "work" / f"123__mod.{language}.work.json"
            payload = common.load_json(path)
            self.assertEqual(payload["language"], language)
            item = payload["entries"][0]
            self.assertEqual(item["original_translation"], item["translation"])
            self.assertNotIn("german", item)
            self.assertNotIn("translations", item)

    def test_apply_updates_only_selected_language(self):
        data = self.bilingual()
        state = data["entries"][0]["translations"]["FR"]
        state.update(review=True, previous_english="Old")
        path, _ = self.store(data)
        package = work.make_work([(path, data)], language="FR")
        package["entries"][0]["translation"] = "Fixture translation"
        _, after, count = apply.apply_work(package, [(path, data)])
        self.assertEqual(count, 1)
        self.assertEqual(after["entries"][0]["translations"]["DE"], data["entries"][0]["translations"]["DE"])
        self.assertEqual(after["entries"][0]["translations"]["FR"],
                         {"text": "Fixture translation", "needed": True, "review": False})
        self.assertEqual(data["entries"][0]["translations"]["FR"], state)

    def test_unknown_need_blocks_work_and_build(self):
        for data in (self.bilingual(needed=None), fixture_draft("mod", [entry()])[1]):
            path, _ = self.store(data)
            for action in (lambda: work.make_work([(path, data)], language="FR"),
                           lambda: build.collect_expected([(path, data)], "FR")):
                with self.assertRaisesRegex(ValueError, "status --language FR"):
                    action()
        summary = progress.state(path, data, "FR")
        self.assertEqual(summary["unknown"], 1)
        self.assertFalse(summary["complete"])

    def test_stale_work_language_identity_source_and_type_validation(self):
        path, data = self.store(self.bilingual())
        package = work.make_work([(path, data)], language="FR")
        cases = []
        for field, value in (("language", "ES"), ("language", None), ("draft_file", "../123__mod.json"),
                             ("mod_id", "wrong"), ("workshop_id", "456"), ("directory", "wrong")):
            bad = deepcopy(package)
            bad[field] = value
            cases.append(bad)
        for field, value in (("key", "missing"), ("english", "changed"), ("original_translation", "changed"),
                             ("translation", None), ("translation", 5)):
            bad = deepcopy(package)
            bad["entries"][0][field] = value
            cases.append(bad)
        bad = deepcopy(package)
        bad["entries"].append(deepcopy(bad["entries"][0]))
        cases.append(bad)
        for bad in cases:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                apply.apply_work(bad, [(path, data)])
        changed = deepcopy(data)
        changed["entries"][0]["translations"]["FR"]["text"] = "Concurrent edit"
        with self.assertRaisesRegex(ValueError, "Zielübersetzung"):
            apply.apply_work(package, [(path, changed)])

    def test_unneeded_unknown_and_missing_states_reject_apply(self):
        path, data = self.store(self.bilingual())
        package = work.make_work([(path, data)], language="FR")
        for needed in (False, None, "missing"):
            changed = deepcopy(data)
            if needed == "missing":
                del changed["entries"][0]["translations"]["FR"]
            else:
                changed["entries"][0]["translations"]["FR"]["needed"] = needed
            with self.subTest(needed=needed), self.assertRaises(ValueError):
                apply.apply_work(package, [(path, changed)])

    def test_placeholder_error_never_partially_writes(self):
        data = self.bilingual()
        second = deepcopy(data["entries"][0])
        second.update(key="Second", english="Hello %1")
        data["entries"].append(second)
        path, _ = self.store(data)
        package = work.make_work([(path, data)], language="FR")
        package["entries"][0]["translation"] = "Valid fixture"
        package["entries"][1]["translation"] = "Missing placeholder"
        original = path.read_bytes()
        work_file = config.DATA / "work.json"
        common.write_json(work_file, package)
        with self.assertRaisesRegex(ValueError, "Placeholder"):
            apply.run(str(work_file))
        self.assertEqual(path.read_bytes(), original)

    def test_empty_translation_is_skipped(self):
        path, data = self.store(self.bilingual())
        package = work.make_work([(path, data)], language="FR")
        _, after, count = apply.apply_work(package, [(path, data)])
        self.assertEqual(count, 0)
        self.assertEqual(after, data)

    def test_progress_is_language_specific(self):
        path, data = self.store(self.bilingual())
        de, fr = (progress.state(path, data, lang) for lang in ("DE", "FR"))
        self.assertTrue(de["complete"])
        self.assertFalse(fr["complete"])
        self.assertEqual((de["translated"], fr["translated"], fr["open"]), (1, 0, 1))


class BuildVerifyExportTests(TemporaryRepository):
    def test_partial_drafts_keep_finished_entries_per_language(self):
        data = self.bilingual()
        other = entry("ItemName", "Base.Other", text="")
        other["translations"]["FR"] = {"text": "Autre", "needed": True, "review": False}
        data["entries"].append(other)
        path, _ = self.store(data)
        original = path.read_bytes()
        plans = build.build([(path, data)], ["DE", "FR"])
        for language in ("DE", "FR"):
            summary = progress.state(path, data, language)
            self.assertFalse(summary["complete"])
            self.assertEqual((summary["needed"], summary["translated"], summary["open"]), (2, 1, 1))
            self.assertEqual(plans[language][1:], ([], [path]))
        self.assertEqual(json.loads((config.TRANSLATE / "DE/IG_UI.json").read_text()),
                         {"IGUI_VehiclePartGM85Roofrack": "Dachgepäckträger"})
        self.assertEqual(json.loads((config.TRANSLATE / "FR/ItemName.json").read_text()),
                         {"Base.Other": "Autre"})
        self.assertFalse((config.TRANSLATE / "DE/ItemName.json").exists())
        self.assertFalse((config.TRANSLATE / "FR/IG_UI.json").exists())
        self.assertEqual(path.read_bytes(), original)

    def test_partial_draft_skips_excluded_review_and_invalid_entries(self):
        entries = [entry("UI", "Good", text="Hallo"),
                   entry("UI", "Empty", text=" \t\n"),
                   entry("UI", "Excluded", text="Irgendein Text"),
                   entry("UI", "Review", text="Prüfen"),
                   entry("UI", "Placeholder", english="Hello %1", text="Hallo"),
                   entry("__plain__", "Book/title.txt", text="Titel  \n"),
                   entry("__plain__", "Book/description.txt", text="")]
        entries[2]["translations"]["DE"]["needed"] = False
        entries[3]["translations"]["DE"]["review"] = True
        expected, complete, incomplete = build.collect_expected([fixture_draft("partial", entries)], "DE")
        self.assertEqual(set(expected), {Path("UI.json"), Path("Book/title.txt")})
        self.assertEqual(json.loads(expected[Path("UI.json")]), {"Good": "Hallo"})
        self.assertEqual(expected[Path("Book/title.txt")], b"Titel\n")
        self.assertEqual((complete, incomplete), ([], [Path("partial.json")]))

    def test_verify_accepts_finished_runtime_entries_from_partial_draft(self):
        data = self.bilingual("FR fixture")
        data.update(game_version="42.20.4", effective_layers=["common"])
        data["entries"].append(entry("ItemName", "Base.Open", english="Open", text=""))
        path, _ = self.store(data)
        build.run(language="DE")
        self.assertEqual(common.read_tree(config.TRANSLATE / "DE"), {
            Path("IG_UI.json"): b'{\n    "IGUI_VehiclePartGM85Roofrack": "Dachgep\xc3\xa4cktr\xc3\xa4ger"\n}\n',
        })
        source = self.source_mod()
        opened = {"category": "ItemName", "key": "Base.Open", "text": "Open"}
        source["english"].append(opened)
        source["missing"].append(opened)
        snapshot = {"language": "DE", "game_version": "42.20.4", "mods": [source]}
        output = StringIO()
        with patch.object(pzgt, "scan_data", return_value={"game_version": "42.20.4"}), \
                patch.object(status, "analyze_scan", return_value=snapshot), redirect_stdout(output):
            verify.run("DE")
        self.assertIn("Runtime DE: 1 erwartet | 1 vorhanden | 0 Abweichungen", output.getvalue())
        self.assertIn("Unvollständig: 1 | Benötigt: 2 | Übersetzt: 1 | Offen: 1", output.getvalue())
        self.assertIn("Ergebnis: OK", output.getvalue())
        self.assertFalse(progress.state(path, data, "DE")["complete"])

    def test_build_inclusion_per_language_and_empty_language(self):
        path, data = self.store(self.bilingual())
        plans = build.build([(path, data)], ["DE", "FR"])
        self.assertEqual(plans["DE"][1], [path])
        self.assertEqual(plans["FR"][2], [path])
        self.assertEqual(common.read_tree(config.TRANSLATE / "FR"), {})
        self.assertTrue(common.read_tree(config.TRANSLATE / "DE"))

    def test_no_partial_multi_language_output_on_invalid_language(self):
        path, data = self.store(self.bilingual(needed=None))
        old_file = config.TRANSLATE / "DE/old.txt"
        old_file.parent.mkdir(parents=True)
        old_file.write_bytes(b"Old runtime")
        original = common.read_tree(config.TRANSLATE)
        with self.assertRaises(ValueError):
            build.build([(path, data)], ["DE", "FR"])
        self.assertEqual(common.read_tree(config.TRANSLATE), original)
        self.assertFalse((self.root / "42/mod.info").exists())

    def test_conflicts_in_second_language_prevent_all_output(self):
        data = self.bilingual("First")
        other = deepcopy(data)
        other["mod_id"] = "other"
        other["entries"][0]["translations"]["FR"]["text"] = "Different"
        path, _ = self.store(data)
        old = config.TRANSLATE / "DE/old.txt"
        old.parent.mkdir(parents=True)
        old.write_text("Old")
        before = common.read_tree(config.TRANSLATE)
        with self.assertRaises(ValueError):
            build.build([(path, data), (Path("other.json"), other)], ["DE", "FR"])
        self.assertEqual(common.read_tree(config.TRANSLATE), before)

    def test_build_rollback_on_metadata_install_failure(self):
        path, data = self.store(self.bilingual("FR fixture"))
        build.build([(path, data)], ["DE", "FR"])
        original = common.read_tree(config.TRANSLATE)
        info = self.root / "42/mod.info"
        info.write_bytes(b"old metadata")
        data["entries"][0]["translations"]["DE"]["text"] = "Changed"
        rename = Path.rename
        def fail(source, target):
            if source.name == "1" and ".pzgt-stage-" in source.parent.name:
                raise OSError("simulated exchange failure")
            return rename(source, target)
        with patch.object(Path, "rename", fail), self.assertRaises(OSError):
            build.build([(path, data)], ["DE", "FR"])
        self.assertEqual(common.read_tree(config.TRANSLATE), original)
        self.assertEqual(info.read_bytes(), b"old metadata")

    def test_selected_build_preserves_other_language_and_removes_stale(self):
        path, data = self.store(self.bilingual("FR fixture"))
        build.build([(path, data)], ["DE", "FR"])
        fr = common.read_tree(config.TRANSLATE / "FR")
        (config.TRANSLATE / "DE/stale.txt").write_text("Stale")
        build.build([(path, data)], ["DE"])
        self.assertEqual(common.read_tree(config.TRANSLATE / "FR"), fr)
        self.assertFalse((config.TRANSLATE / "DE/stale.txt").exists())

    def test_safe_paths_and_file_directory_collisions(self):
        for category, key in (("../escape", "key"), ("/escape", "key"),
                              ("__plain__", "../title.txt"), ("__plain__", "C:\\title.txt"),
                              ("__plain__", "/title.txt"), ("__plain__", "x/./title.txt")):
            with self.subTest(category=category, key=key), self.assertRaises(ValueError):
                build.collect_expected([fixture_draft("mod", [entry(category, key)])], "DE")
        for entries in ([entry("UI"), entry("__plain__", "UI.json")],
                        [entry("UI"), entry("__plain__", "UI.json/title.txt")],
                        [entry("UI"), entry("ui", "Other")]):
            with self.assertRaises(ValueError):
                build.collect_expected([fixture_draft("mod", entries)], "DE")

    def test_symlink_ancestor_and_tree_rejected(self):
        path, data = self.store(self.bilingual("FR fixture"))
        outside = self.root / "source"
        outside.mkdir()
        (outside / "untouched").write_text("Original")
        (self.root / "common").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            build.build([(path, data)], ["DE"])
        self.assertEqual((outside / "untouched").read_text(), "Original")
        (self.root / "common").unlink()
        build.build([(path, data)], ["DE"])
        (config.TRANSLATE / "DE/link").symlink_to(outside)
        with self.assertRaises(ValueError):
            build.build([(path, data)], ["DE"])

    def test_runtime_missing_stale_changed_and_exact_bytes(self):
        path, data = self.store(self.bilingual())
        build.build([(path, data)], ["DE"])
        expected = build.collect_expected([(path, data)], "DE")[0]
        directory = config.TRANSLATE / "DE"
        self.assertEqual(verify.runtime_errors(expected, directory), [])
        runtime = directory / "IG_UI.json"
        runtime.unlink()
        self.assertIn("fehlt", verify.runtime_errors(expected, directory)[0])
        runtime.write_bytes(expected[Path("IG_UI.json")].replace(b"\n", b"\r\n"))
        self.assertIn("stimmt nicht", verify.runtime_errors(expected, directory)[0])
        (directory / "unexpected.txt").write_text("Stale")
        self.assertTrue(any("unerwartete" in e for e in verify.runtime_errors(expected, directory)))

    def test_source_sync_language_english_needed_layers(self):
        path, data = self.store(self.bilingual())
        data.update(game_version="42.20.4", effective_layers=["common"])
        snapshot = {"language": "DE", "game_version": "42.20.4", "mods": [self.source_mod()]}
        self.assertEqual(verify.source_errors(path, data, snapshot, "DE"), [])
        self.assertTrue(verify.source_errors(path, data, snapshot, "FR"))
        snapshot["mods"][0]["english"][0]["text"] = "Changed"
        self.assertTrue(any("Quelltext geändert" in e for e in verify.source_errors(path, data, snapshot, "DE")))
        snapshot["mods"][0] = self.source_mod(needed=False)
        self.assertTrue(any("nicht mehr benötigt" in e for e in verify.source_errors(path, data, snapshot, "DE")))
        snapshot["mods"][0]["effective_layers"] = ["42"]
        self.assertTrue(any("Schichten" in e for e in verify.source_errors(path, data, snapshot, "DE")))

    def test_export_single_multi_zip_and_allowlist(self):
        self.store(self.bilingual("FR fixture"))
        build.run()
        for language, expected_languages in (("DE", {"DE"}), (None, {"DE", "FR"})):
            export.run(language, make_zip=True)
            destination = self.root / "dist" / export.MOD_DIRECTORY
            tree = common.read_tree(destination)
            self.assertEqual({p.parts[5] for p in tree if p.parts[:5] == ("common", "media", "lua", "shared", "Translate")}, expected_languages)
            self.assertEqual(
                {p for p in tree if p.parts[0] not in ("common", "42")},
                {Path("LICENSE"), Path("SUPPORTED-MODS.txt")},
            )
            self.assertEqual(len(tree), 4 + len(expected_languages))
            supported = tree[Path("SUPPORTED-MODS.txt")].decode("utf-8")
            self.assertIn("Workshop ID: 123", supported)
            self.assertIn("Mod ID: mod", supported)
            self.assertIn(
                "Languages: " + ", ".join(sorted(expected_languages)),
                supported,
            )
            with zipfile.ZipFile(destination.with_suffix(".zip")) as archive:
                zipped = {Path(name).relative_to(export.MOD_DIRECTORY): archive.read(name) for name in archive.namelist()}
            self.assertEqual(zipped, tree)

    def test_supported_mods_lists_only_complete_exported_languages(self):
        first = self.bilingual("FR first")
        first.update(
            workshop_id="111",
            mod_id="first",
            directory="first",
            name="First Mod",
        )
        self.store(first, "111__first.json")

        second = self.bilingual()
        second.update(
            workshop_id="222",
            mod_id="second",
            directory="second",
            name="Second Mod",
        )
        self.store(second, "222__second.json")

        build.run()
        export.run()

        supported = (
            self.root
            / "dist"
            / export.MOD_DIRECTORY
            / "SUPPORTED-MODS.txt"
        ).read_text(encoding="utf-8")

        self.assertIn("Languages: DE, FR", supported)
        self.assertIn("Supported mods: 2", supported)

        self.assertIn("First Mod", supported)
        self.assertIn("Workshop ID: 111", supported)
        self.assertIn("Mod ID: first", supported)
        self.assertIn(
            "https://steamcommunity.com/sharedfiles/filedetails/?id=111",
            supported,
        )
        self.assertIn("Languages: DE, FR", supported)

        self.assertIn("Second Mod", supported)
        self.assertIn("Workshop ID: 222", supported)
        self.assertIn("Mod ID: second", supported)

        second_block = supported.split("Second Mod", 1)[1]
        self.assertIn("Languages: DE", second_block)
        self.assertNotIn("Languages: DE, FR", second_block)

    def test_stale_runtime_blocks_export_without_build_or_dist_changes(self):
        self.store(self.bilingual("FR fixture"))
        build.run()
        export.run("DE")
        before = common.read_tree(self.root / "dist")
        runtime = config.TRANSLATE / "DE/IG_UI.json"
        for change in ("modified", "missing", "stale"):
            build.run()
            if change == "modified":
                runtime.write_text("{}")
            elif change == "missing":
                runtime.unlink()
            else:
                (runtime.parent / "extra.txt").write_text("Extra")
            current = common.read_tree(config.TRANSLATE)
            with patch.object(build, "build", side_effect=AssertionError("Implicit build")):
                with self.assertRaisesRegex(ValueError, "./pzgt build"):
                    export.run("DE")
            self.assertEqual(common.read_tree(config.TRANSLATE), current)
            self.assertEqual(common.read_tree(self.root / "dist"), before)

    def test_export_rolls_back_directory_and_archive_together(self):
        self.store(self.bilingual("FR fixture"))
        build.run()
        export.run("DE", make_zip=True)
        before = common.read_tree(self.root / "dist")
        rename = Path.rename
        def fail(source, target):
            if source.name == "1" and ".pzgt-stage-" in source.parent.name:
                raise OSError("simulated ZIP exchange failure")
            return rename(source, target)
        with patch.object(Path, "rename", fail), self.assertRaises(OSError):
            export.run(make_zip=True)
        self.assertEqual(common.read_tree(self.root / "dist"), before)

    def test_export_rejects_symlink_without_touching_destination(self):
        self.store(self.bilingual("FR fixture"))
        build.run()
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "unchanged").write_text("Original")
        (self.root / "dist").symlink_to(outside)
        with self.assertRaises(ValueError):
            export.run("DE")
        self.assertEqual(common.read_tree(outside), {Path("unchanged"): b"Original"})

    def test_duplicate_json_fields_are_not_silently_lost(self):
        path = self.root / "duplicate.json"
        path.write_text('{"german": "Original", "german": "Lost"}')
        with self.assertRaisesRegex(ValueError, "Doppeltes JSON-Feld"):
            common.load_json(path)

    def test_verify_rejects_reviews_and_placeholder_mismatch(self):
        path, data = self.store(self.bilingual("FR fixture"))
        data.update(game_version="42.20.4", effective_layers=["common"])
        state = data["entries"][0]["translations"]["DE"]
        scan = {"game_version": "42.20.4"}
        snapshot = {"language": "DE", "game_version": "42.20.4", "mods": [self.source_mod()]}
        for field, value, message in (("review", True, "Review offen"),
                                      ("text", "Bad %1", "Placeholder-Abweichung")):
            with self.subTest(field=field):
                state.update(text="Dachgepäckträger", review=False)
                state[field] = value
                common.write_json(path, data)
                build.run(language="DE")
                with patch.object(pzgt, "scan_data", return_value=scan), patch.object(status, "analyze_scan", return_value=snapshot):
                    with self.assertRaisesRegex(ValueError, message):
                        verify.run("DE")



class InstallTests(TemporaryRepository):
    def test_install_new_correct_wrong_and_real_directory(self):
        mods = self.root / "user/mods"
        link = mods / "ElHanko-German-Translations"
        with patch.object(pzgt, "ROOT", self.root), patch.object(pzgt, "LOCAL_MODS", mods), patch.object(pzgt, "LOCAL_LINK", link):
            pzgt.cmd_install()
            self.assertEqual(link.resolve(), self.root)
            pzgt.cmd_install()
            link.unlink()
            link.symlink_to(self.root / "elsewhere")
            with self.assertRaises(SystemExit):
                pzgt.cmd_install()
            self.assertTrue(link.is_symlink())
            link.unlink()
            link.mkdir()
            with self.assertRaises(SystemExit):
                pzgt.cmd_install()
            self.assertTrue(link.is_dir())


class CLITests(unittest.TestCase):
    def test_complete_multilingual_workflow_and_live_verify(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = Path(__file__).parent
            shutil.copytree(scripts, root / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
            (root / "LICENSE").write_text("Test license")
            workshop = root / "workshop"
            (root / "game/projectzomboid/media/lua/shared/Translate/EN").mkdir(parents=True)
            mod = workshop / "123/mods/mod"
            translate = Path("media/lua/shared/Translate")
            for layer in ("common", "42", "42.21"):
                base = mod / layer
                (base / translate / "EN").mkdir(parents=True)
                (base / "mod.info").write_text("id=mod\nname=Fixture Mod\n")
                text = "Hello %1" if layer == "42" else "Old %1"
                (base / translate / "EN/UI.json").write_text(json.dumps({"UI_Hello": text}))
            (mod / "common" / translate / "DE").mkdir()
            (mod / "common" / translate / "DE/UI.json").write_text('{"UI_Hello": "Official %1"}')
            (mod / "42" / translate / "EN/Recipes_EN.txt").write_text('RecipesEN {\n Recipe_Test = "Craft",\n}\n')
            (mod / "42" / translate / "EN/Book").mkdir()
            (mod / "42" / translate / "EN/Book/title.txt").write_text("Book")
            user = root / "user"
            user.mkdir()
            (user / "console.txt").write_text("> version=42.20.4\n")
            (root / "pzgt.local.json").write_text(json.dumps({"game": str(root / "game"),
                "workshop": str(workshop), "zomboid_home": str(user), "languages": ["DE", "FR"]}))
            source_before = {p.relative_to(workshop): p.read_bytes() for p in workshop.rglob("*") if p.is_file()}
            def cli(*args, success=True):
                result = subprocess.run([sys.executable, str(root / "scripts/pzgt.py"), *args],
                                        cwd=root, text=True, capture_output=True)
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
                return result.stdout + result.stderr
            cli("scan")
            scan = json.loads((root / "data/scan.json").read_text())
            self.assertEqual(scan["mods"][0]["effective_layers"], ["common", "42"])
            self.assertEqual(set(scan["mods"][0]["layers"][0]["translations"]), {"EN", "DE", "FR"})
            for command in ("status", "progress", "work"):
                self.assertIn("Mehrere Zielsprachen", cli(command, success=False))
            cli("status", "--language", "DE")
            cli("draft", "--all")
            self.assertFalse(list((root / "translations").glob("*.json")))
            cli("draft", "mod")
            cli("build", "--language", "FR", success=False)
            cli("status", "--language", "FR")
            cli("draft", "--all")
            data = json.loads((root / "translations/123__mod.json").read_text())
            hello = next(e for e in data["entries"] if e["key"] == "UI_Hello")
            self.assertEqual(hello["english"], "Hello %1")
            self.assertIsNone(hello["translations"]["DE"]["needed"])
            # FR introduced a source DE had never needed; classify it with DE status.
            cli("status", "--language", "DE")
            cli("draft", "--all")
            for language in ("DE", "FR"):
                cli("work", "--next", "--language", language)
                work_file = root / "data/work" / f"123__mod.{language}.work.json"
                package = json.loads(work_file.read_text())
                for item in package["entries"]:
                    item["translation"] = "Fixture " + item["english"]
                work_file.write_text(json.dumps(package))
                cli("apply", str(work_file))
                cli("progress", "mod", "--language", language)
            cli("build")
            cli("verify")
            cli("export", "--zip")
            for language in ("DE", "FR"):
                cli("verify", "--language", language)
            self.assertEqual(source_before, {p.relative_to(workshop): p.read_bytes() for p in workshop.rglob("*") if p.is_file()})
            # Verify rereads source files, including new files absent from saved scan.
            (mod / "42" / translate / "EN/new.json").write_text('{"New": "New source"}')
            self.assertIn("Quell-Key", cli("verify", "--language", "DE", success=False))


if __name__ == "__main__":
    unittest.main()
