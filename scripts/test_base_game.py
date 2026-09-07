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
        for item in data["entries"][1:]:
            item["translations"]["FR"]["needed"] = False
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
                         {("UI", "Missing"), ("SurvivalGuide", "New"),
                          ("UI", "ExistingBlankTarget"), ("SurvivalGuide", "Blank")})
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
            "source_file": "UI.json", "source_layer": "game", "source_format": "json"},
            {"category": "UI", "key": "ExistingBlankTarget", "english": "Do not automatically translate",
             "translations": {"DE": {"text": "", "needed": False, "review": False, "audit": "blank_target"},
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
            self.assertEqual({e["key"] for e in updated["entries"]}, {"Missing", "New", "ExistingBlankTarget"})
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
        # Workshop drafts share translation keys, but cannot carry Vanilla audits.
        for item in mod["entries"]:
            for state in item["translations"].values():
                state.pop("audit", None)
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

    def blank_state(self, data, language="DE"):
        return common.index_entries(data["entries"])[("UI", "ExistingBlankTarget")]["translations"][language]

    def test_audit_status_excludes_empty_english_missing_and_translated_targets(self):
        self.english.update(EmptyEnglish=" \t", WhitespaceTarget="English")
        self.target.update(EmptyEnglish="", WhitespaceTarget=" \n\t", TargetOnly="")
        self.write_sources()
        row = status.analyze_scan(pzgt.scan_data(), "DE")["base_game"]
        self.assertEqual({e["key"] for e in row["audit_blank"]},
                         {"ExistingBlankTarget", "WhitespaceTarget"})
        self.assertEqual({e["key"] for e in row["missing"]}, {"Missing"})
        self.assertEqual(row["blank"], [])
        self.assertEqual(row["counts"]["open"], 1)
        self.assertEqual(row["counts"]["blank_ignored"], 3)
        data = self.refresh("Project Zomboid")
        for item in data["entries"]:
            if item["key"] == "Missing":
                self.assertTrue(item["translations"]["DE"]["needed"])
            else:
                self.assertEqual(item["translations"]["DE"],
                                 {"text": "", "needed": False, "review": False, "audit": "blank_target"})
            self.assertNotIn("audit", item)

    def test_audit_schema_validates_only_the_supported_state_value(self):
        data = self.adopt()
        common.validate_draft(self.game_path, data)
        for value in (None, "", "different", True, 1, [], {}):
            with self.subTest(value=value):
                invalid = deepcopy(data)
                self.blank_state(invalid)["audit"] = value
                with self.assertRaisesRegex(ValueError, "ungültiges audit"):
                    common.validate_draft(self.game_path, invalid)
        del self.blank_state(data)["audit"]
        common.validate_draft(self.game_path, data)

    def test_audit_only_preserves_progress_work_and_runtime_bytes(self):
        import work

        game = self.adopt()
        without_audit = deepcopy(game)
        without_audit["entries"] = [e for e in without_audit["entries"]
                                    if e["translations"]["DE"].get("audit") != "blank_target"]
        self.store(self.bilingual("FR fixture"))
        mod_drafts = [(p, d) for p, d in common.load_drafts() if p != self.game_path]
        build.build(mod_drafts + [(self.game_path, without_audit)], ["DE"])
        runtime = common.read_tree(config.TRANSLATE)
        for field in ("needed", "translated", "open", "review", "unknown", "complete"):
            self.assertEqual(progress.state(self.game_path, game, "DE")[field],
                             progress.state(self.game_path, without_audit, "DE")[field])
        self.assertEqual(work.work_entries(game, "DE"), [])
        # Stored audit text or review is also inert until explicitly needed.
        self.blank_state(game).update(text="Unveröffentlichter Entwurf %1", review=True)
        build.build(mod_drafts + [(self.game_path, game)], ["DE"])
        self.assertEqual(common.read_tree(config.TRANSLATE), runtime)
        common.write_json(self.game_path, game)
        verify.run("DE")
        game["entries"][0]["translations"]["DE"]["text"] = ""
        package = work.make_work([(self.game_path, game)], "Project Zomboid", language="DE")
        self.assertEqual([e["key"] for e in package["entries"]], ["Missing"])

    def test_manual_audit_release_survives_refresh_work_apply_build_and_verify(self):
        game = self.adopt()
        self.blank_state(game)["needed"] = True
        common.write_json(self.game_path, game)
        game = self.refresh()
        self.assertEqual(self.blank_state(game),
                         {"text": "", "needed": True, "review": False, "audit": "blank_target"})
        summary = progress.state(self.game_path, game, "DE")
        self.assertEqual((summary["needed"], summary["open"]), (2, 1))
        build.run(language="DE")
        verify.run("DE")
        self.assertEqual(pzgt.main(["work", "Project Zomboid", "--language", "DE"]), 0)
        path = config.DATA / "work/__project_zomboid.DE.work.json"
        package = common.load_json(path)
        self.assertEqual([e["key"] for e in package["entries"]], ["ExistingBlankTarget"])
        package["entries"][0]["translation"] = "Manuell freigegeben"
        common.write_json(path, package)
        self.assertEqual(pzgt.main(["apply", str(path)]), 0)
        game = self.refresh()
        self.assertEqual(self.blank_state(game)["text"], "Manuell freigegeben")
        self.assertTrue(self.blank_state(game)["needed"])
        build.run(language="DE")
        runtime = json.loads((config.TRANSLATE / "DE/UI.json").read_text())
        self.assertEqual(runtime, {"Missing": "Übersetze mich", "ExistingBlankTarget": "Manuell freigegeben"})
        verify.run("DE")

    def test_audit_refresh_transitions_preserve_text_and_other_languages(self):
        original = self.adopt()
        self.blank_state(original).update(text="Eigener Text", needed=True)
        self.blank_state(original, "FR").update(text="Texte", needed=True, audit="blank_target")
        for change, expected in (("translated", False), ("missing", True),
                                 ("removed_english", False), ("empty_english", False)):
            with self.subTest(change=change):
                self.english["ExistingBlankTarget"] = "Do not automatically translate"
                self.target["ExistingBlankTarget"] = ""
                common.write_json(self.game_path, original)
                if change == "translated":
                    self.target["ExistingBlankTarget"] = "Offiziell"
                elif change == "missing":
                    del self.target["ExistingBlankTarget"]
                elif change == "removed_english":
                    del self.english["ExistingBlankTarget"]
                else:
                    self.english["ExistingBlankTarget"] = ""
                self.write_sources()
                updated = self.refresh()
                state = self.blank_state(updated)
                self.assertIs(state["needed"], expected)
                self.assertNotIn("audit", state)
                self.assertEqual(state["text"], "Eigener Text")
                if change == "empty_english":
                    self.assertTrue(state["review"])
                    self.assertEqual(self.blank_state(updated, "FR")["text"], "Texte")
                else:
                    self.assertEqual(self.blank_state(updated, "FR"), self.blank_state(original, "FR"))
                if change == "removed_english":
                    retired = common.index_entries(updated["entries"])[("UI", "ExistingBlankTarget")]
                    self.assertEqual(retired["english"], "Do not automatically translate")
                build.run(language="DE")
                if change != "empty_english":
                    verify.run("DE")

    def test_audit_english_review_keeps_first_source_and_manual_release(self):
        original = self.adopt()
        self.blank_state(original).update(text="Eigener Text", needed=True)
        self.blank_state(original, "FR").update(text="Texte", needed=False, audit="blank_target")
        common.write_json(self.game_path, original)
        for text in ("Changed", "Changed again"):
            self.english["ExistingBlankTarget"] = text
            self.write_sources()
            updated = self.refresh()
            self.assertTrue(self.blank_state(updated)["needed"])
            for language in ("DE", "FR"):
                state = self.blank_state(updated, language)
                self.assertTrue(state["review"])
                self.assertEqual(state["previous_english"], "Do not automatically translate")
                self.assertEqual(state["text"], self.blank_state(original, language)["text"])
                self.assertEqual(state["audit"], "blank_target")

    def test_audit_language_refresh_is_independent(self):
        game = self.adopt()
        self.blank_state(game).update(text="Eigener Text", needed=True)
        common.write_json(self.game_path, game)
        de_before = {common.entry_identity(e): deepcopy(e["translations"]["DE"]) for e in game["entries"]}
        fr_path = self.translate / "FR/UI.json"
        fr_path.parent.mkdir()
        fr_path.write_text(json.dumps({"ExistingBlankTarget": " \t"}))
        game = self.refresh(language="FR")
        self.assertEqual(self.blank_state(game, "FR"),
                         {"text": "", "needed": False, "review": False, "audit": "blank_target"})
        for item in game["entries"]:
            if common.entry_identity(item) in de_before:
                self.assertEqual(item["translations"]["DE"], de_before[common.entry_identity(item)])
        fr_before = {common.entry_identity(e): deepcopy(e["translations"]["FR"]) for e in game["entries"]}
        game = self.refresh(language="DE")
        self.assertTrue(self.blank_state(game)["needed"])
        for item in game["entries"]:
            self.assertEqual(item["translations"]["FR"], fr_before[common.entry_identity(item)])

    def test_verify_detects_missing_and_stale_audit_inventory(self):
        original = self.adopt()
        for change, message in (("new", "neuer Audit-Kandidat"), ("marker", "neuer Audit-Kandidat"),
                                ("translated", "veraltetes blank_target-Audit"),
                                ("missing", "veraltetes blank_target-Audit"),
                                ("removed_english", "veraltetes blank_target-Audit"),
                                ("empty_english", "veraltetes blank_target-Audit"),
                                ("required", "neuer offener Quell-Key")):
            with self.subTest(change=change):
                game = deepcopy(original)
                english, target = deepcopy(self.english), deepcopy(self.target)
                if change == "new":
                    self.target["ExistingTranslated"] = ""
                elif change == "marker":
                    del self.blank_state(game)["audit"]
                elif change == "translated":
                    self.target["ExistingBlankTarget"] = "Offiziell"
                elif change == "missing":
                    del self.target["ExistingBlankTarget"]
                elif change == "removed_english":
                    del self.english["ExistingBlankTarget"]
                elif change == "empty_english":
                    self.english["ExistingBlankTarget"] = ""
                else:
                    game["entries"][0]["translations"]["DE"]["needed"] = False
                common.write_json(self.game_path, game)
                self.write_sources()
                build.run(language="DE")
                with self.assertRaisesRegex(ValueError, message):
                    verify.run("DE")
                self.english, self.target = english, target

    def test_audit_summary_reads_only_draft_and_filters_category_and_language(self):
        self.adopt()
        (self.translate / "EN/Recorded_Media.json").write_text('{"Recorded": "English"}')
        (self.translate / "DE/Recorded_Media.json").write_text('{"Recorded": ""}')
        self.refresh()
        shutil.rmtree(self.values["game"])
        shutil.rmtree(config.DATA)
        before = common.read_tree(self.root)
        for language, category, total in (("DE", None, 2), ("DE", "Recorded_Media", 1),
                                          ("DE", "unknown", 0), ("FR", None, 0)):
            output = StringIO()
            args = ["audit", "Project Zomboid", "--language", language]
            if category is not None:
                args += ["--category", category]
            with redirect_stdout(output), patch.object(pzgt, "scan_data", side_effect=AssertionError("Source read")):
                self.assertEqual(pzgt.main(args), 0)
            self.assertIn(f"Audit-Kandidaten: {total}", output.getvalue())
            if category == "Recorded_Media":
                self.assertIn("Recorded_Media", output.getvalue())
                self.assertNotIn("  UI", output.getvalue())
        self.assertEqual(common.read_tree(self.root), before)

    def test_old_status_without_audit_cannot_silently_retire_manual_release(self):
        game = self.adopt()
        self.blank_state(game)["needed"] = True
        common.write_json(self.game_path, game)
        snapshot = common.load_json(config.DATA / "status.json")
        del snapshot["base_game"]["audit_blank"]
        common.write_json(config.DATA / "status.json", snapshot)
        before = self.game_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "Status ohne Vanilla-Auditbestand"):
            draft.run("--all")
        self.assertEqual(self.game_path.read_bytes(), before)

    def adopt_same(self):
        self.target["ExistingBlankTarget"] = self.english["ExistingBlankTarget"]
        self.write_sources()
        return self.adopt()

    def test_same_as_source_status_uses_exact_nonempty_strings_only(self):
        self.english.update(Same="Hello", Case="Hello", Spaces="Hello", ExactSpaces=" Hello ",
                            Empty="", Whitespace=" \t", EmptySource="", NonemptySource="Hello")
        self.target.update(Same="Hello", Case="hello", Spaces=" Hello ", ExactSpaces=" Hello ",
                           Empty="", Whitespace=" \t", EmptySource="Nonempty", NonemptySource=" \t")
        self.write_sources()
        scan = pzgt.scan_data()
        row = status.analyze_scan(scan, "DE")["base_game"]
        self.assertEqual({e["key"] for e in row["audit_same_as_source"]}, {"Same", "ExactSpaces"})
        self.assertEqual({e["key"] for e in row["audit_blank"]}, {"ExistingBlankTarget", "NonemptySource"})
        self.assertEqual({e["key"] for e in row["missing"]}, {"Missing"})
        self.assertEqual(row["counts"]["open"], 1)
        self.assertEqual(row["counts"]["translated"], 6)
        # Identical Workshop targets stay ordinary existing translations.
        mod = dict(scan["base_game"], workshop_id="123", directory="mod", effective_id="mod")
        del mod["source_type"]
        scan["mods"] = [mod]
        del scan["base_game"]
        row = status.analyze_scan(scan, "DE")["mods"][0]
        self.assertNotIn("audit_blank", row)
        self.assertNotIn("audit_same_as_source", row)
        self.assertEqual(row["counts"]["open"], 6)
        data = draft.merge_entries(row, [], "DE")
        self.assertTrue(all(e["translations"]["DE"]["needed"] for e in data))
        self.assertFalse(any("audit" in e["translations"]["DE"] for e in data))

    def test_new_same_audit_has_empty_text_and_independent_language_state(self):
        game = self.adopt_same()
        self.assertEqual(self.blank_state(game),
                         {"text": "", "needed": False, "review": False, "audit": "same_as_source"})
        common.validate_draft(self.game_path, game)
        self.assertNotIn("audit", self.blank_state(game, "FR"))
        self.assertNotIn("audit", game["entries"][0]["translations"]["DE"])
        self.assertTrue(game["entries"][0]["translations"]["DE"]["needed"])
        self.blank_state(game, "FR").update(text="Texte", needed=True, audit="blank_target")
        common.write_json(self.game_path, game)
        self.assertEqual(self.blank_state(self.refresh(), "FR"), self.blank_state(game, "FR"))

    def test_manual_release_and_text_survive_all_audit_type_transitions(self):
        original = self.adopt()
        for needed in (False, True):
            game = deepcopy(original)
            self.blank_state(game).update(text="Eigener Text", needed=needed)
            common.write_json(self.game_path, game)
            for audit_type in ("blank_target", "same_as_source", "same_as_source", "blank_target"):
                with self.subTest(needed=needed, audit_type=audit_type):
                    self.target["ExistingBlankTarget"] = (
                        " \t" if audit_type == "blank_target" else self.english["ExistingBlankTarget"])
                    self.write_sources()
                    game = self.refresh()
                    self.assertEqual(self.blank_state(game),
                                     {"text": "Eigener Text", "needed": needed,
                                      "review": False, "audit": audit_type})
                    build.run(language="DE")
                    verify.run("DE")
                    before = self.game_path.read_bytes()
                    self.refresh()
                    self.assertEqual(self.game_path.read_bytes(), before)

    def test_same_audit_ends_without_losing_text_or_history(self):
        original = self.adopt_same()
        self.blank_state(original).update(text="Eigener Text", needed=True)
        self.blank_state(original, "FR").update(text="Texte", needed=False, audit="same_as_source")
        for change, needed in (("translated", False), ("missing", True),
                               ("removed_english", False), ("empty_english", False)):
            with self.subTest(change=change):
                self.english["ExistingBlankTarget"] = "Do not automatically translate"
                self.target["ExistingBlankTarget"] = self.english["ExistingBlankTarget"]
                common.write_json(self.game_path, original)
                if change == "translated":
                    self.target["ExistingBlankTarget"] = "Offizielle Übersetzung"
                elif change == "missing":
                    del self.target["ExistingBlankTarget"]
                elif change == "removed_english":
                    del self.english["ExistingBlankTarget"]
                else:
                    self.english["ExistingBlankTarget"] = ""
                self.write_sources()
                updated = self.refresh()
                state = self.blank_state(updated)
                self.assertEqual(state["needed"], needed)
                self.assertEqual(state["text"], "Eigener Text")
                self.assertNotIn("audit", state)
                if change == "empty_english":
                    for language in ("DE", "FR"):
                        self.assertTrue(self.blank_state(updated, language)["review"])
                        self.assertEqual(self.blank_state(updated, language)["previous_english"],
                                         "Do not automatically translate")
                else:
                    self.assertEqual(self.blank_state(updated, "FR"), self.blank_state(original, "FR"))
                if change == "removed_english":
                    item = common.index_entries(updated["entries"])[("UI", "ExistingBlankTarget")]
                    self.assertEqual(item["english"], "Do not automatically translate")
                build.run(language="DE")
                verify.run("DE")

    def test_same_audit_source_changes_preserve_first_english_and_release(self):
        game = self.adopt_same()
        self.blank_state(game).update(text="Eigener Text", needed=True)
        self.blank_state(game, "FR").update(text="Texte", needed=False)
        common.write_json(self.game_path, game)
        for english in ("Changed", "Changed again"):
            self.english["ExistingBlankTarget"] = english
            self.target["ExistingBlankTarget"] = english
            self.write_sources()
            updated = self.refresh()
            self.assertTrue(self.blank_state(updated)["needed"])
            self.assertEqual(self.blank_state(updated)["audit"], "same_as_source")
            for language in ("DE", "FR"):
                state = self.blank_state(updated, language)
                self.assertTrue(state["review"])
                self.assertEqual(state["previous_english"], "Do not automatically translate")
                self.assertEqual(state["text"], self.blank_state(game, language)["text"])
            build.run(language="DE")
            with self.assertRaisesRegex(ValueError, "Review offen"):
                verify.run("DE")

    def test_same_audit_only_does_not_change_progress_work_or_runtime(self):
        import work

        before = self.adopt()
        self.store(self.bilingual("FR fixture"))
        build.run(language="DE")
        runtime = common.read_tree(config.TRANSLATE)
        self.english["Same"] = "Hello"
        self.target["Same"] = "Hello"
        self.write_sources()
        game = self.refresh()
        self.assertEqual(game["entries"][:-1], before["entries"])
        state = game["entries"][-1]["translations"]["DE"]
        self.assertEqual(state, {"text": "", "needed": False, "review": False, "audit": "same_as_source"})
        state.update(text="Unveröffentlichter Text %1", review=True)
        common.write_json(self.game_path, game)
        for field in ("needed", "translated", "open", "review", "unknown", "complete"):
            self.assertEqual(progress.state(self.game_path, game, "DE")[field],
                             progress.state(self.game_path, before, "DE")[field])
        self.assertEqual(work.work_entries(game, "DE"), [])
        game["entries"][0]["translations"]["DE"]["text"] = ""
        package = work.make_work([(self.game_path, game)], "Project Zomboid", language="DE")
        self.assertEqual([e["key"] for e in package["entries"]], ["Missing"])
        build.run(language="DE")
        self.assertEqual(common.read_tree(config.TRANSLATE), runtime)
        verify.run("DE")

    def test_manual_same_audit_uses_normal_work_apply_and_build(self):
        game = self.adopt_same()
        self.blank_state(game)["needed"] = True
        common.write_json(self.game_path, game)
        self.refresh()
        build.run(language="DE")
        verify.run("DE")
        self.assertEqual(pzgt.main(["work", "Project Zomboid", "--language", "DE"]), 0)
        path = config.DATA / "work/__project_zomboid.DE.work.json"
        package = common.load_json(path)
        self.assertEqual([e["key"] for e in package["entries"]], ["ExistingBlankTarget"])
        package["entries"][0]["translation"] = "Manuell übersetzt"
        common.write_json(path, package)
        self.assertEqual(pzgt.main(["apply", str(path)]), 0)
        game = self.refresh()
        self.assertEqual(self.blank_state(game), {"text": "Manuell übersetzt", "needed": True,
                                                 "review": False, "audit": "same_as_source"})
        build.run(language="DE")
        runtime = json.loads((config.TRANSLATE / "DE/UI.json").read_text())
        self.assertEqual(runtime, {"Missing": "Übersetze mich", "ExistingBlankTarget": "Manuell übersetzt"})
        verify.run("DE")

    def test_verify_requires_matching_audit_type_and_inventory(self):
        original = self.adopt_same()
        for change, message in (("marker", "neuer Audit-Kandidat"), ("entry", "neuer Audit-Kandidat"),
                                ("wrong_type", "falscher Audittyp"), ("now_blank", "falscher Audittyp"),
                                ("translated", "veraltetes same_as_source-Audit"),
                                ("missing", "veraltetes same_as_source-Audit"),
                                ("new", "neuer Audit-Kandidat")):
            with self.subTest(change=change):
                game = deepcopy(original)
                self.target["ExistingBlankTarget"] = self.english["ExistingBlankTarget"]
                self.target["ExistingTranslated"] = "Hallo"
                if change == "marker":
                    del self.blank_state(game)["audit"]
                elif change == "entry":
                    game["entries"] = game["entries"][:1]
                elif change == "wrong_type":
                    self.blank_state(game)["audit"] = "blank_target"
                elif change == "now_blank":
                    self.target["ExistingBlankTarget"] = ""
                elif change == "translated":
                    self.target["ExistingBlankTarget"] = "Offiziell"
                elif change == "missing":
                    del self.target["ExistingBlankTarget"]
                else:
                    self.target["ExistingTranslated"] = self.english["ExistingTranslated"]
                self.write_sources()
                common.write_json(self.game_path, game)
                build.run(language="DE")
                with self.assertRaisesRegex(ValueError, message):
                    verify.run("DE")

    def test_old_status_without_same_inventory_aborts_both_refresh_selectors(self):
        game = self.adopt_same()
        self.blank_state(game).update(text="Eigener Text", needed=True)
        common.write_json(self.game_path, game)
        self.store(self.bilingual("Texte"))
        snapshot = common.load_json(config.DATA / "status.json")
        del snapshot["base_game"]["audit_same_as_source"]
        common.write_json(config.DATA / "status.json", snapshot)
        before = common.read_tree(config.TRANSLATIONS)
        for selector in ("--all", "Project Zomboid"):
            with self.subTest(selector=selector), self.assertRaises(ValueError) as caught:
                draft.run(selector)
            self.assertIn("./pzgt scan", str(caught.exception))
            self.assertIn("./pzgt status --language DE", str(caught.exception))
            self.assertEqual(common.read_tree(config.TRANSLATIONS), before)
        errors = verify.source_errors(self.game_path, game, snapshot, "DE")
        self.assertTrue(any("Status ohne Vanilla-Auditbestand" in e for e in errors))

    def test_audit_cli_combines_type_category_and_language_filters_without_sources(self):
        self.adopt()
        for language, entries in (("EN", {"Same": "English", "Blank": "Blank"}),
                                  ("DE", {"Same": "English", "Blank": ""})):
            (self.translate / language / "RadioData.json").write_text(json.dumps(entries))
        self.refresh()
        shutil.rmtree(self.values["game"])
        shutil.rmtree(config.DATA)
        before = common.read_tree(self.root)
        cases = ((None, None, 3, 2, 1), ("blank_target", None, 2, 2, 0),
                 ("same_as_source", None, 1, 0, 1), (None, "RadioData", 2, 1, 1),
                 ("same_as_source", "RadioData", 1, 0, 1), ("blank_target", "RadioData", 1, 1, 0),
                 ("same_as_source", "UI", 0, 0, 0))
        for audit_type, category, total, blank, same in cases:
            with self.subTest(audit_type=audit_type, category=category):
                args = ["audit", "Project Zomboid", "--language", "DE"]
                if audit_type:
                    args += ["--type", audit_type]
                if category:
                    args += ["--category", category]
                output = StringIO()
                with redirect_stdout(output), patch.object(pzgt, "scan_data", side_effect=AssertionError("Source read")):
                    self.assertEqual(pzgt.main(args), 0)
                text = output.getvalue()
                self.assertIn(f"{blank:6}  blank_target", text)
                self.assertIn(f"{same:6}  same_as_source", text)
                self.assertIn(f"{total:6}  gesamt", text)
                self.assertIn("Nach Kategorie:", text)
                if category == "RadioData":
                    self.assertIn(f"{'RadioData':24} {blank:6} {same:6} {total:7}", text)
                    self.assertNotIn("UI ", text)
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(pzgt.main(["audit", "Project Zomboid", "--language", "FR", "--type", "same_as_source"]), 0)
        self.assertIn("Audit-Kandidaten: 0", output.getvalue())
        for value in ("", "different", "true"):
            with self.subTest(value=value), self.assertRaises(SystemExit) as caught:
                pzgt.main(["audit", "Project Zomboid", "--language", "DE", "--type", value])
            self.assertEqual(caught.exception.code, 2)
        self.assertEqual(common.read_tree(self.root), before)
