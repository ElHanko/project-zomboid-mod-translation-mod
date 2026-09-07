"""Audit decisions mutate only the chosen draft states, using isolated fixtures."""
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import apply
import build
import common
import config
import draft
import progress
import pzgt
import review
import status
import work
from test_shared_keys import entry
from test_workflow import TemporaryRepository


class ReviewTests(TemporaryRepository):
    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(config, "configure"))
        self.data = {"source_type": "game", "name": "Project Zomboid", "game_version": "42.20.4",
                     "entries": [
                         self.candidate("RadioData", "SameA", "same_as_source"),
                         self.candidate("RadioData", "SameB", "same_as_source", True, "Eigener Text"),
                         self.candidate("Recorded_Media", "SameC", "same_as_source"),
                         self.candidate("RadioData", "BlankA", "blank_target"),
                         self.candidate("Recorded_Media", "BlankB", "blank_target", True, "Leerwert-Entwurf"),
                         self.candidate("RadioData", "Missing", None, True, "Fehlende Übersetzung"),
                     ]}
        self.data["entries"][1]["translations"]["DE"].update(review=True, previous_english="Old English")
        self.path, _ = self.store(self.data, "__project_zomboid.json")

    def candidate(self, category, key, audit_type, needed=False, text=""):
        item = entry(category, key, english="English", text=text)
        item["translations"]["DE"].update(needed=needed, future={"notes": ["Preserve me"]})
        if audit_type:
            item["translations"]["DE"]["audit"] = audit_type
        item["translations"]["FR"] = {"text": "Texte", "needed": False, "review": False}
        return item

    def cli(self, audit_type="same_as_source", category=None, needed=True, language="DE", selector="Project Zomboid"):
        args = ["review", selector, "--language", language, "--type", audit_type,
                "--need" if needed else "--not-needed"]
        if category is not None:
            args += ["--category", category]
        output = StringIO()
        with redirect_stdout(output):
            result = pzgt.main(args)
        return result, output.getvalue()

    def test_cli_command_and_required_arguments(self):
        output = StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as caught:
            pzgt.main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("review", output.getvalue())
        prefix = ["review", "Project Zomboid", "--language", "DE"]
        for args in (["review"], prefix + ["--need"], prefix + ["--type", "blank_target"],
                     prefix + ["--type", "blank_target", "--need", "--not-needed"],
                     prefix + ["--type", "different", "--need"]):
            with self.subTest(args=args), patch.object(config, "configure") as configured:
                with self.assertRaises(SystemExit) as caught:
                    pzgt.main(args)
                self.assertEqual(caught.exception.code, 2)
                configured.assert_not_called()

    def test_need_filters_preserve_every_other_field_and_language(self):
        for audit_type, category, keys in (
                ("same_as_source", None, {"SameA", "SameB", "SameC"}),
                ("blank_target", None, {"BlankA", "BlankB"}),
                ("same_as_source", "RadioData", {"SameA", "SameB"}),
                ("blank_target", "RadioData", {"BlankA"})):
            with self.subTest(audit_type=audit_type, category=category):
                common.write_json(self.path, self.data)
                expected = deepcopy(self.data)
                already = 0
                for item in expected["entries"]:
                    if item["key"] in keys:
                        already += item["translations"]["DE"]["needed"] is True
                        item["translations"]["DE"]["needed"] = True
                result, output = self.cli(audit_type, category)
                self.assertEqual(result, 0)
                self.assertEqual(common.load_json(self.path), expected)
                self.assertIn(f"{'Passend:':24}{len(keys):6}", output)
                self.assertIn(f"{'Bereits benötigt:':24}{already:6}", output)
                self.assertIn(f"{'Geändert:':24}{len(keys) - already:6}", output)
                self.assertIn(f"Kategorie: {category or 'alle'}", output)

    def test_not_needed_preserves_missing_keys_text_audit_and_history(self):
        for audit_type, category, keys in (
                ("same_as_source", None, {"SameA", "SameB", "SameC"}),
                ("blank_target", None, {"BlankA", "BlankB"}),
                ("same_as_source", "RadioData", {"SameA", "SameB"})):
            with self.subTest(audit_type=audit_type, category=category):
                common.write_json(self.path, self.data)
                expected = deepcopy(self.data)
                already = 0
                for item in expected["entries"]:
                    if item["key"] in keys:
                        already += item["translations"]["DE"]["needed"] is False
                        item["translations"]["DE"]["needed"] = False
                result, output = self.cli(audit_type, category, needed=False)
                self.assertEqual(result, 0)
                self.assertEqual(common.load_json(self.path), expected)
                self.assertIn("Entscheidung: nicht benötigt", output)
                self.assertIn(f"{'Bereits nicht benötigt:':24}{already:6}", output)
                self.assertTrue(common.load_json(self.path)["entries"][-1]["translations"]["DE"]["needed"])

    def test_selected_language_is_the_only_modified_language(self):
        expected = deepcopy(self.data)
        for item in expected["entries"][:2]:
            item["translations"]["FR"]["audit"] = "blank_target"
        common.write_json(self.path, expected)
        for item in expected["entries"][:2]:
            item["translations"]["FR"]["needed"] = True
        result, _ = self.cli("blank_target", "RadioData", language="FR")
        self.assertEqual(result, 0)
        self.assertEqual(common.load_json(self.path), expected)
        with patch.object(config, "LANGUAGES", ["DE"]):
            review.run("Project Zomboid", None, "blank_target", needed=True)
        self.assertTrue(common.load_json(self.path)["entries"][3]["translations"]["DE"]["needed"])

    def test_noop_does_not_write_or_change_bytes(self):
        for needed in (True, False):
            with self.subTest(needed=needed):
                self.assertEqual(self.cli(needed=needed)[0], 0)
                before, modified = self.path.read_bytes(), self.path.stat().st_mtime_ns
                with patch.object(review, "write_json", side_effect=AssertionError("No-op wrote draft")):
                    result, output = self.cli(needed=needed)
                self.assertEqual(result, 0)
                self.assertIn(f"{'Geändert:':24}{0:6}", output)
                self.assertEqual(self.path.read_bytes(), before)
                self.assertEqual(self.path.stat().st_mtime_ns, modified)

    def test_no_matching_candidate_is_error_without_changes(self):
        before = common.read_tree(config.TRANSLATIONS)
        for category, language in (("Typo", "DE"), ("", "DE"), (None, "FR")):
            with self.subTest(category=category, language=language):
                with self.assertRaisesRegex(ValueError, "Keine passenden Audit-Kandidaten"):
                    review.run("Project Zomboid", language, "same_as_source", category, needed=True)
        self.assertEqual(common.read_tree(config.TRANSLATIONS), before)

    def test_workshop_draft_is_rejected_unchanged(self):
        self.store()
        before = common.read_tree(config.TRANSLATIONS)
        with self.assertRaisesRegex(ValueError, "nur für Basis-Spiel-Audit-Einträge"):
            review.run("mod", "DE", "blank_target", needed=True)
        self.assertEqual(common.read_tree(config.TRANSLATIONS), before)

    def test_review_needs_only_drafts_and_never_changes_runtime_or_work(self):
        self.assertFalse(config.DATA.exists())
        self.assertFalse((self.root / "game").exists())
        self.assertFalse((self.root / "workshop").exists())
        self.store()
        build.run(language="DE")
        before = common.read_tree(self.root)
        with patch.object(pzgt, "scan_data", side_effect=AssertionError("Live source")), \
                patch.object(pzgt, "load_config", side_effect=AssertionError("Source config")), \
                patch.object(pzgt, "discover_mods", side_effect=AssertionError("Workshop source")), \
                patch.object(status, "collect_language", side_effect=AssertionError("Source contents")), \
                patch.object(build, "build", side_effect=AssertionError("Implicit build")), \
                patch.object(work, "run", side_effect=AssertionError("Implicit work")):
            self.assertEqual(self.cli(category="RadioData")[0], 0)
        after = common.read_tree(self.root)
        self.assertEqual(before.keys(), after.keys())
        self.assertEqual([p for p in before if before[p] != after[p]],
                         [Path("translations/__project_zomboid.json")])
        self.assertFalse(config.DATA.exists())

    def test_decision_progress_work_apply_refresh_and_build_workflow(self):
        data = deepcopy(self.data)
        for item in data["entries"]:
            state = item["translations"]["DE"]
            state["review"] = False
            state.pop("previous_english", None)
            if state.get("audit"):
                state.update(needed=False, text="")
        common.write_json(self.path, data)
        build.run(language="DE")
        before = common.read_tree(config.TRANSLATE)
        summary = progress.state(self.path, data, "DE")
        self.assertEqual((summary["needed"], summary["open"]), (1, 0))
        self.assertEqual(self.cli(category="RadioData")[0], 0)
        data = common.load_json(self.path)
        summary = progress.state(self.path, data, "DE")
        self.assertEqual((summary["needed"], summary["open"]), (3, 2))
        package = work.make_work(common.load_drafts(), "Project Zomboid", language="DE")
        self.assertEqual({item["key"] for item in package["entries"]}, {"SameA", "SameB"})
        self.assertEqual(self.cli(category="RadioData", needed=False)[0], 0)
        self.assertEqual(work.work_entries(common.load_json(self.path), "DE"), [])
        self.assertEqual(self.cli(category="RadioData")[0], 0)
        for item in package["entries"]:
            item["translation"] = "Übersetzt"
        work_path = config.DATA / "work/__project_zomboid.DE.work.json"
        common.write_json(work_path, package)
        apply.run(str(work_path))
        data = common.load_json(self.path)
        source = {"source_type": "game", "english": [], "missing": [], "blank": [],
                  "audit_blank": [], "audit_same_as_source": []}
        for item in data["entries"]:
            record = {"category": item["category"], "key": item["key"], "text": item["english"],
                      "file": item["category"] + ".json", "layer": "game", "format": "json"}
            source["english"].append(record)
            kind = item["translations"]["DE"].get("audit")
            target = {"blank_target": "audit_blank", "same_as_source": "audit_same_as_source"}.get(kind, "missing")
            source[target].append(record)
        refreshed = draft.merge_entries(source, data["entries"], "DE")
        for item in refreshed:
            self.assertEqual(item["translations"], common.index_entries(data["entries"])[common.entry_identity(item)]["translations"])
        build.run(language="DE")
        import json
        runtime = json.loads((config.TRANSLATE / "DE/RadioData.json").read_text())
        self.assertEqual(runtime, {"Missing": "Fehlende Übersetzung", "SameA": "Übersetzt", "SameB": "Übersetzt"})
        self.assertEqual(self.cli(category="RadioData", needed=False)[0], 0)
        data = common.load_json(self.path)
        self.assertEqual(data["entries"][0]["translations"]["DE"]["text"], "Übersetzt")
        self.assertEqual(data["entries"][0]["translations"]["DE"]["audit"], "same_as_source")
        build.run(language="DE")
        self.assertEqual(common.read_tree(config.TRANSLATE), before)

    def test_overlapping_source_audits_are_rejected_before_draft_write(self):
        record = {"category": "RadioData", "key": "SameA", "text": "English"}
        source = {"source_type": "game", "english": [record], "missing": [], "blank": [],
                  "audit_blank": [record], "audit_same_as_source": [deepcopy(record)]}
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "überschneidet sich"):
            common.index_audits(source, "DE")
        with self.assertRaisesRegex(ValueError, "überschneidet sich"):
            draft.merge_entries(source, self.data["entries"], "DE")
        self.assertEqual(self.path.read_bytes(), before)

    def test_audit_markers_are_valid_only_in_game_drafts(self):
        path, workshop = self.store()
        for audit_type in common.AUDIT_TYPES:
            with self.subTest(audit_type=audit_type):
                workshop["entries"][0]["translations"]["DE"]["audit"] = audit_type
                with self.assertRaisesRegex(ValueError, "nur für Basis-Spiel-Drafts"):
                    common.validate_draft(path, workshop)
                game = deepcopy(workshop)
                game["source_type"] = "game"
                common.validate_draft(self.path, game)
