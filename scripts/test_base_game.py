"""Base-game sources reuse the isolated multilingual draft workflow."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import shutil
from unittest.mock import patch

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
from test_workflow import TemporaryRepository


class BaseGameTests(TemporaryRepository):
    def setUp(self):
        super().setUp()
        self.values = {"game": self.root / "game", "workshop": self.root / "workshop",
                       "zomboid_home": self.root / "user"}
        self.values["workshop"].mkdir()
        self.values["zomboid_home"].mkdir()
        (self.values["zomboid_home"] / "console.txt").write_text("> version=42.20.4\n")
        self.translate = self.values["game"] / "projectzomboid/media/lua/shared/Translate"
        self.english = {"Missing": "Translate me", "MissingBlankEnglish": "",
                        "ExistingBlankTarget": "Do not automatically translate",
                        "ExistingTranslated": "Hello"}
        self.target = {"ExistingBlankTarget": "", "ExistingTranslated": "Hallo"}
        self.write_sources()
        self.stack.enter_context(patch.object(pzgt, "load_config", return_value=self.values))
        self.stack.enter_context(patch.object(config, "configure", return_value=self.values))
        self.game_path = config.TRANSLATIONS / "__project_zomboid.json"

    def write_sources(self):
        for language, entries in (("EN", self.english), ("DE", self.target)):
            path = self.translate / language / "UI.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(entries))

    def refresh(self, selector="--all", language="DE"):
        pzgt.cmd_scan()
        status.run(language)
        draft.run(selector)
        return common.load_json(self.game_path)

    def adopt(self, text="Übersetze mich", fr=""):
        data = self.refresh("Project Zomboid")
        data["entries"][0]["translations"]["DE"]["text"] = text
        data["entries"][0]["translations"]["FR"].update(text=fr, needed=True)
        common.write_json(self.game_path, data)
        return data

    def test_scan_inventory_and_conservative_status_read_only(self):
        (self.translate / "EN/glossary.tbx").write_text("ignored format")
        before = common.read_tree(self.values["game"])
        scan = pzgt.scan_data()
        self.assertEqual(scan["mods"], [])
        game = scan["base_game"]
        self.assertEqual(game["source_type"], "game")
        self.assertEqual(game["effective_layers"], ["game"])
        self.assertEqual(Path(game["layers"][0]["path"]), self.values["game"] / "projectzomboid")
        self.assertFalse({"workshop_id", "mod_id", "directory"} & game.keys())
        analysis = status.analyze_scan(scan, "DE")
        row = analysis["base_game"]
        self.assertEqual({e["key"] for e in row["missing"]}, {"Missing"})
        self.assertEqual(row["blank"], [])
        self.assertEqual(row["counts"], {"english": 4, "translated": 1, "missing": 1,
            "blank": 0, "open": 1, "extra_target": 0, "parse_errors": 0,
            "missing_total": 2, "empty_source_ignored": 1, "blank_ignored": 1})
        self.assertEqual(common.read_tree(self.values["game"]), before)
        # Identical files in a Workshop source retain the missing-or-blank rule.
        mod = dict(game, workshop_id="123", directory="mod", effective_id="mod")
        scan["mods"] = [mod]
        del scan["base_game"]
        workshop = status.analyze_scan(scan, "DE")
        self.assertNotIn("base_game", workshop)
        self.assertEqual(workshop["mods"][0]["counts"]["open"], 3)

    def test_missing_translate_or_english_rejected_before_scan_write(self):
        pzgt.cmd_scan()
        before = (config.DATA / "scan.json").read_bytes()
        for missing in (self.translate / "EN", self.translate, self.values["game"]):
            with self.subTest(missing=missing):
                shutil.rmtree(missing)
                output = StringIO()
                with patch("sys.stderr", output):
                    self.assertEqual(pzgt.main(["scan"]), 1)
                self.assertIn("Vanilla-Translate-Root mit EN fehlt", output.getvalue())
                self.assertIn("game-Pfad", output.getvalue())
                self.assertEqual((config.DATA / "scan.json").read_bytes(), before)
                self.write_sources()

    def test_vanilla_json_category_does_not_strip_language_like_ending(self):
        for language, entries in (("EN", {"Present": "Guide", "Blank": "Guide", "New": "Guide"}),
                                  ("DE", {"Present": "Anleitung", "Blank": ""})):
            (self.translate / language / "SurvivalGuide.json").write_text(json.dumps(entries))
        data = self.refresh("Project Zomboid")
        snapshot = common.load_json(config.DATA / "status.json")["base_game"]
        self.assertEqual(snapshot["counts"]["open"], 2)
        self.assertEqual(snapshot["counts"]["blank_ignored"], 2)
        self.assertEqual({(e["category"], e["key"]) for e in data["entries"]},
                         {("UI", "Missing"), ("SurvivalGuide", "New")})
        self.refresh(language="FR")
        self.refresh(language="DE")
        data = common.load_json(self.game_path)
        self.assertEqual({e["category"] for e in data["entries"]}, {"UI", "SurvivalGuide"})
        for item in data["entries"]:
            item["translations"]["DE"]["text"] = "Anleitung"
        expected, _, _ = build.collect_expected([(self.game_path, data)], "DE")
        self.assertIn(Path("SurvivalGuide.json"), expected)

    def test_explicit_cli_adoption_and_work_apply(self):
        before = common.read_tree(self.values["game"])
        self.assertEqual(pzgt.main(["scan"]), 0)
        self.assertEqual(pzgt.main(["status", "--language", "DE"]), 0)
        self.assertEqual(pzgt.main(["draft", "--all"]), 0)
        self.assertFalse(list(config.TRANSLATIONS.glob("*.json")))
        self.assertEqual(pzgt.main(["draft", "Project Zomboid"]), 0)
        self.assertEqual(list(config.TRANSLATIONS.glob("*.json")), [self.game_path])
        data = common.load_json(self.game_path)
        self.assertEqual(set(data), {"source_type", "name", "game_version", "entries"})
        self.assertEqual(data["game_version"], "42.20.4")
        self.assertEqual(data["entries"], [{"category": "UI", "key": "Missing",
            "english": "Translate me", "translations": {
                "DE": {"text": "", "needed": True, "review": False},
                "FR": {"text": "", "needed": None, "review": False}},
            "source_file": "UI.json", "source_layer": "game", "source_format": "json"}])
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(pzgt.main(["progress", "Project Zomboid", "--language", "DE"]), 0)
            self.assertEqual(pzgt.main(["work", "Project Zomboid", "--limit", "25", "--language", "DE"]), 0)
        self.assertIn("Project Zomboid (DE)", output.getvalue())
        self.assertNotIn("None", output.getvalue())
        package_path = config.DATA / "work/__project_zomboid.DE.work.json"
        package = common.load_json(package_path)
        self.assertEqual(package["source_type"], "game")
        self.assertEqual(package["draft_file"], self.game_path.name)
        self.assertFalse({"workshop_id", "mod_id", "directory"} & package.keys())
        package["entries"][0]["translation"] = "Übersetze mich"
        invalid = deepcopy(package)
        invalid["draft_file"] = "nonexistent.json"
        with self.assertRaisesRegex(ValueError, "draft_file"):
            apply.apply_work(invalid, common.load_drafts())
        common.write_json(package_path, package)
        self.assertEqual(pzgt.main(["apply", str(package_path)]), 0)
        translated = common.load_json(self.game_path)
        self.assertTrue(progress.state(self.game_path, translated, "DE")["complete"])
        self.assertEqual(common.read_tree(self.values["game"]), before)

    def test_refresh_retires_need_preserving_text_and_other_languages(self):
        original = self.adopt(fr="Traduire")
        self.target["Missing"] = "Offizielle Übersetzung"
        self.write_sources()
        updated = self.refresh()
        state = updated["entries"][0]["translations"]
        self.assertFalse(state["DE"]["needed"])
        self.assertEqual(state["DE"]["text"], "Übersetze mich")
        self.assertEqual(state["FR"], original["entries"][0]["translations"]["FR"])
        # A present but blank official target also retires the requirement.
        self.target["Missing"] = ""
        self.write_sources()
        self.assertFalse(self.refresh()["entries"][0]["translations"]["DE"]["needed"])
        del self.english["Missing"]
        self.write_sources()
        retired = self.refresh()
        self.assertEqual(retired, updated)

    def test_refresh_new_keys_and_english_review_preserves_first_source(self):
        original = self.adopt(fr="Traduire")
        for english in ("Changed", "Changed again"):
            self.english.update(Missing=english, New="New entry")
            self.write_sources()
            updated = self.refresh()
            self.assertEqual({e["key"] for e in updated["entries"]}, {"Missing", "New"})
            for language in ("DE", "FR"):
                state = updated["entries"][0]["translations"][language]
                self.assertTrue(state["review"])
                self.assertEqual(state["previous_english"], "Translate me")
                self.assertEqual(state["text"], original["entries"][0]["translations"][language]["text"])
        before = common.read_tree(config.TRANSLATIONS)
        self.refresh()
        self.assertEqual(common.read_tree(config.TRANSLATIONS), before)

    def test_game_refresh_requires_source_and_preserves_workshop_draft(self):
        path, _ = self.store(self.bilingual("FR fixture"))
        before = path.read_bytes()
        self.adopt()
        self.refresh()
        self.assertEqual(path.read_bytes(), before)
        snapshot = common.load_json(config.DATA / "status.json")
        del snapshot["base_game"]
        common.write_json(config.DATA / "status.json", snapshot)
        before = common.read_tree(config.TRANSLATIONS)
        with self.assertRaisesRegex(ValueError, "Basis-Spielquelle fehlt"):
            draft.run("--all")
        self.assertEqual(common.read_tree(config.TRANSLATIONS), before)

    def test_build_combines_sources_and_excludes_incomplete_game(self):
        self.store(self.bilingual("FR fixture"))
        self.adopt()
        build.run(language="DE")
        self.assertEqual(set(common.read_tree(config.TRANSLATE / "DE")),
                         {Path("UI.json"), Path("IG_UI.json")})
        before = common.read_tree(config.TRANSLATE)
        build.run(language="DE")
        self.assertEqual(common.read_tree(config.TRANSLATE), before)
        game = common.load_json(self.game_path)
        game["entries"][0]["translations"]["DE"]["text"] = ""
        common.write_json(self.game_path, game)
        plans = build.build(common.load_drafts(), ["DE"])
        self.assertIn(self.game_path, plans["DE"][2])
        self.assertEqual(set(common.read_tree(config.TRANSLATE / "DE")), {Path("IG_UI.json")})

    def test_shared_keys_use_existing_owner_and_conflict_rules(self):
        game = self.adopt()
        mod = self.bilingual("FR fixture")
        mod["entries"] = deepcopy(game["entries"])
        mod_path, mod = self.store(mod)
        drafts = [(self.game_path, game), (mod_path, mod)]
        expected, included, _ = build.collect_expected(drafts, "DE")
        self.assertEqual(len(included), 2)
        self.assertEqual(json.loads(expected[Path("UI.json")]), {"Missing": "Übersetze mich"})
        for change in ("english", "text"):
            changed = deepcopy(mod)
            if change == "english":
                changed["entries"][0]["english"] = "Different English"
            else:
                changed["entries"][0]["translations"]["DE"]["text"] = "Anders"
            with self.assertRaisesRegex(ValueError, "Konflikt"):
                build.collect_expected([(self.game_path, game), (mod_path, changed)], "DE")

    def test_verify_live_game_drift(self):
        game = self.adopt()
        build.run(language="DE")
        before = common.read_tree(config.DATA)
        with patch.object(pzgt, "scan_data", wraps=pzgt.scan_data) as scanner:
            verify.run("DE")
        scanner.assert_called_once_with(supported=set(), include_game=True)
        self.assertEqual(common.read_tree(config.DATA), before)
        original_english, original_target = deepcopy(self.english), deepcopy(self.target)
        for change, message in (("english", "Quelltext geändert"), ("new", "neuer offener Quell-Key"),
                                ("target", "nicht mehr benötigt"), ("removed", "nicht mehr benötigt"),
                                ("empty", "nicht mehr benötigt"), ("parser", "Parserfehler")):
            with self.subTest(change=change):
                self.english, self.target = deepcopy(original_english), deepcopy(original_target)
                if change == "english":
                    self.english["Missing"] = "Changed"
                elif change == "new":
                    self.english["New"] = "New entry"
                elif change == "target":
                    self.target["Missing"] = "Official"
                elif change == "removed":
                    del self.english["Missing"]
                elif change == "empty":
                    self.english["Missing"] = ""
                self.write_sources()
                if change == "parser":
                    (self.translate / "EN/UI.json").write_text("invalid JSON")
                with self.assertRaisesRegex(ValueError, message):
                    verify.run("DE")
        self.english, self.target = original_english, original_target
        self.write_sources()
        snapshot = status.analyze_scan(pzgt.scan_data(), "DE")
        self.assertIn("Status-Sprache", verify.source_errors(self.game_path, game, snapshot, "FR")[0])
        (self.values["zomboid_home"] / "console.txt").write_text("> version=42.21.0\n")
        with self.assertRaisesRegex(ValueError, "Spielversion geändert"):
            verify.run("DE")
        del snapshot["base_game"]
        self.assertIn("Basis-Spielquelle fehlt", verify.source_errors(self.game_path, game, snapshot, "DE")[0])
        shutil.rmtree(self.values["game"])
        with self.assertRaisesRegex(ValueError, "Vanilla-Translate-Root"):
            verify.run("DE")

    def test_verify_game_reviews_placeholders_and_runtime(self):
        original = self.adopt()
        for change, message in (("review", "Review offen"), ("placeholder", "Placeholder-Abweichung"),
                                ("runtime", "Runtime-Datei stimmt nicht")):
            with self.subTest(change=change):
                game = deepcopy(original)
                state = game["entries"][0]["translations"]["DE"]
                if change == "review":
                    state["review"] = True
                elif change == "placeholder":
                    state["text"] = "Extra %1"
                common.write_json(self.game_path, game)
                build.run(language="DE")
                if change == "runtime":
                    (config.TRANSLATE / "DE/UI.json").write_text("{}")
                with self.assertRaisesRegex(ValueError, message):
                    verify.run("DE")

    def test_restricted_scan_skips_game_without_draft(self):
        shutil.rmtree(self.values["game"])
        (self.values["zomboid_home"] / "console.txt").unlink()
        with patch.object(pzgt, "inspect_layer", side_effect=AssertionError("Game inspected")):
            scan = pzgt.scan_data(supported=set())
        self.assertNotIn("base_game", scan)
        self.assertIsNone(scan["game_version"])
        self.store(self.bilingual("FR fixture"))
        build.run()
        with patch.object(pzgt, "scan_data", wraps=pzgt.scan_data) as scanner:
            verify.run()
        scanner.assert_called_once_with(supported={("123", "mod")}, include_game=False)

    def test_export_counts_only_mods_and_actual_game_languages(self):
        self.store(self.bilingual("FR fixture"))
        self.adopt()
        for fr, selected, hint in (("", None, "DE"), ("", "FR", None),
                                   ("Traduire", None, "DE, FR"), ("Traduire", "DE", "DE")):
            with self.subTest(fr=fr, selected=selected):
                game = common.load_json(self.game_path)
                game["entries"][0]["translations"]["FR"]["text"] = fr
                common.write_json(self.game_path, game)
                build.run()
                with patch.object(build, "build", side_effect=AssertionError("Implicit build")):
                    export.run(selected, make_zip=True)
                    before = common.read_tree(self.root / "dist")
                    export.run(selected, make_zip=True)
                    self.assertEqual(common.read_tree(self.root / "dist"), before)
                content = before[Path(export.MOD_DIRECTORY) / "SUPPORTED-MODS.txt"].decode()
                self.assertIn("Supported mods: 1", content)
                self.assertIn("Workshop ID: 123", content)
                self.assertIn("Mod ID: mod", content)
                if hint:
                    self.assertIn(f"Base game translations: included ({hint})", content)
                else:
                    self.assertNotIn("Base game translations:", content)
