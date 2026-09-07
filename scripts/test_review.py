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

    def interactive(self, replies, audit_type="same_as_source", category=None, offset=None,
                    selector="Project Zomboid", language="DE"):
        args = ["review", selector, "--language", language, "--interactive"]
        args += ["--type", audit_type] if audit_type is not None else ["--review"]
        if category is not None:
            args += ["--category", category]
        if offset is not None:
            args += ["--offset", str(offset)]
        output = StringIO()
        with redirect_stdout(output), patch("builtins.input", side_effect=replies):
            result = pzgt.main(args)
        return result, output.getvalue()

    def test_interactive_cli_selection_action_and_offset_rules(self):
        prefix = ["review", "Project Zomboid", "--language", "DE"]
        invalid = (
            ["--type", "same_as_source", "--review", "--interactive"],
            ["--type", "same_as_source", "--need", "--interactive"],
            ["--type", "same_as_source", "--not-needed", "--interactive"],
            ["--review", "--need"], ["--review", "--not-needed"],
            ["--type", "same_as_source", "--need", "--offset", "0"],
            ["--type", "same_as_source", "--not-needed", "--offset", "1"],
            ["--type", "same_as_source", "--interactive", "--offset", "-1"],
            ["--review", "--interactive", "--offset", "-1"],
        )
        for args in invalid:
            with self.subTest(args=args), patch.object(config, "configure") as configured:
                with self.assertRaises(SystemExit) as caught:
                    pzgt.main(prefix + args)
                self.assertEqual(caught.exception.code, 2)
                configured.assert_not_called()
        for selection in (["--type", "blank_target"], ["--review"]):
            with patch.object(review, "run_interactive") as run:
                self.assertEqual(pzgt.main(prefix + selection + ["--interactive", "--offset", "1"]), 0)
                run.assert_called_once_with("Project Zomboid", "DE",
                                            "blank_target" if selection[0] == "--type" else None,
                                            None, offset=1)

    def test_interactive_audit_n_x_preserve_every_other_field_and_filter(self):
        for audit_type, category, replies, changes in (
                ("same_as_source", "RadioData", ["n", "x"], {0: True, 1: False}),
                ("blank_target", None, ["n", "x"], {3: True, 4: False}),
                ("same_as_source", None, ["n", "s", "x"], {0: True, 2: False})):
            with self.subTest(audit_type=audit_type, category=category):
                common.write_json(self.path, self.data)
                expected = deepcopy(self.data)
                for number, needed in changes.items():
                    expected["entries"][number]["translations"]["DE"]["needed"] = needed
                with patch.object(review, "write_json", wraps=common.write_json) as writer:
                    result, output = self.interactive(replies, audit_type, category)
                    writer.assert_called_once()
                self.assertEqual(result, 0)
                self.assertEqual(common.load_json(self.path), expected)
                self.assertIn("Offizielles DE (laut Audit):", output)
                self.assertIn("<leer>" if audit_type == "blank_target" else "English", output)
                if category == "RadioData":
                    self.assertNotIn("Recorded_Media /", output)

    def test_interactive_audit_translation_preserves_marker_and_other_language(self):
        expected = deepcopy(self.data)
        state = expected["entries"][1]["translations"]["DE"]
        state.update(text="  Eigene Übersetzung  ", needed=True, review=False)
        state.pop("previous_english")
        result, output = self.interactive(["t", "  Eigene Übersetzung  "], category="RadioData", offset=1)
        self.assertEqual(result, 0)
        self.assertIn("[2/2] RadioData / SameB", output)
        self.assertNotIn("RadioData / SameA", output)
        self.assertEqual(common.load_json(self.path), expected)
        # A previously unneeded audit becomes needed when translated directly.
        result, _ = self.interactive(["t", "Freigegeben", "q"], category="RadioData")
        self.assertEqual(result, 0)
        expected["entries"][0]["translations"]["DE"].update(text="Freigegeben", needed=True)
        self.assertEqual(common.load_json(self.path), expected)

    def test_interactive_empty_bad_placeholder_and_invalid_choice_retry_same_entry(self):
        data = deepcopy(self.data)
        data["entries"][0]["english"] = "English %1 {name}"
        common.write_json(self.path, data)
        before = self.path.read_bytes()
        with patch.object(review, "write_json", side_effect=AssertionError("Invalid input wrote draft")):
            result, output = self.interactive(["invalid", "t", " \t", "t", "Falsch %1", "q"], category="RadioData")
        self.assertEqual(result, 0)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIn("Ungültige Auswahl", output)
        self.assertIn("Übersetzung ist leer", output)
        self.assertIn("Placeholder-Abweichung", output)
        self.assertEqual(output.count("[1/2] RadioData / SameA"), 4)
        self.assertNotIn("[2/2]", output)
        result, _ = self.interactive(["t", "Gültig %1 {name}", "q"], category="RadioData")
        self.assertEqual(result, 0)
        self.assertEqual(common.load_json(self.path)["entries"][0]["translations"]["DE"]["text"],
                         "Gültig %1 {name}")

    def test_interactive_skip_immediate_quit_and_noop_leave_bytes_unchanged(self):
        for replies, audit_type, category, offset in (
                (["q"], "same_as_source", None, None),
                (["s", "s", "s"], "same_as_source", None, None),
                (["x", "n"], "same_as_source", "RadioData", None),
                (["q"], None, None, None), (["s"], None, None, None),
                (["q"], "same_as_source", None, 2)):
            with self.subTest(replies=replies, audit_type=audit_type, offset=offset):
                before = self.path.read_bytes()
                with patch.object(review, "write_json", side_effect=AssertionError("No-op wrote draft")):
                    result, output = self.interactive(replies, audit_type, category, offset)
                self.assertEqual(result, 0)
                self.assertEqual(self.path.read_bytes(), before)
                self.assertIn("Geändert: 0", output)

    def test_interactive_review_confirmation_preserves_need_and_exact_text(self):
        for source_type in ("game", "workshop"):
            for needed in (True, False, None):
                with self.subTest(source_type=source_type, needed=needed):
                    data = deepcopy(self.data)
                    data["entries"][1]["translations"]["DE"].update(needed=needed, text="  Bestätigen  ")
                    path, selector = self.path, "Project Zomboid"
                    if source_type == "workshop":
                        data.pop("source_type")
                        data.update(mod_id="mod", name="Workshop", workshop_id="123", directory="mod")
                        for item in data["entries"]:
                            item["translations"]["DE"].pop("audit", None)
                        path, _ = self.store(data)
                        selector = "mod"
                    else:
                        common.write_json(path, data)
                    expected = deepcopy(data)
                    state = expected["entries"][1]["translations"]["DE"]
                    state["review"] = False
                    state.pop("previous_english")
                    result, output = self.interactive(["a"], audit_type=None, selector=selector)
                    self.assertEqual(result, 0)
                    self.assertEqual(common.load_json(path), expected)
                    self.assertIn("[1/1] RadioData / SameB", output)
                    self.assertIn("Vorheriges EN:\nOld English", output)
                    self.assertIn("Aktuelles EN:\nEnglish", output)
                    self.assertNotIn(" / SameA", output)

    def test_interactive_review_confirm_rejects_empty_text_and_placeholder_mismatch(self):
        for text, message in ((" \t", "Übersetzung ist leer"), ("Wrong %1", "Placeholder-Abweichung")):
            with self.subTest(text=text):
                data = deepcopy(self.data)
                data["entries"][1]["translations"]["DE"]["text"] = text
                common.write_json(self.path, data)
                before = self.path.read_bytes()
                result, output = self.interactive(["a", "q"], audit_type=None)
                self.assertEqual(result, 0)
                self.assertIn(message, output)
                self.assertEqual(output.count("[1/1] RadioData / SameB"), 2)
                self.assertEqual(self.path.read_bytes(), before)

    def test_interactive_review_t_keeps_need_including_non_audit_workshop_states(self):
        for needed in (True, False, None):
            with self.subTest(needed=needed):
                workshop = self.bilingual("Texte")
                item = workshop["entries"][0]
                item["translations"]["DE"].update(needed=needed, review=True, previous_english="Old English")
                path, _ = self.store(workshop)
                expected = deepcopy(workshop)
                state = expected["entries"][0]["translations"]["DE"]
                state.update(text="Neue Übersetzung", review=False)
                state.pop("previous_english")
                result, _ = self.interactive(["t", "Neue Übersetzung"], audit_type=None, selector="mod")
                self.assertEqual(result, 0)
                self.assertEqual(common.load_json(path), expected)
        expected = deepcopy(self.data)
        expected["entries"][1]["translations"]["DE"]["needed"] = False
        common.write_json(self.path, expected)
        result, _ = self.interactive(["t", "Neu"], audit_type=None)
        self.assertEqual(result, 0)
        state = expected["entries"][1]["translations"]["DE"]
        state.update(text="Neu", review=False)
        state.pop("previous_english")
        self.assertEqual(common.load_json(self.path), expected)

    def test_interactive_review_category_language_and_missing_previous_english(self):
        data = deepcopy(self.data)
        state = data["entries"][2]["translations"]["FR"]
        state["review"] = True
        common.write_json(self.path, data)
        result, output = self.interactive(["a"], audit_type=None, category="Recorded_Media", language="FR")
        self.assertEqual(result, 0)
        self.assertIn("Vorheriges EN:\n—", output)
        self.assertIn("[1/1] Recorded_Media / SameC", output)
        self.assertNotIn("RadioData / SameB", output)
        state["review"] = False
        self.assertEqual(common.load_json(self.path), data)

    def test_interactive_review_rejects_need_keys_and_bad_translation_without_mutation(self):
        before = self.path.read_bytes()
        result, output = self.interactive(["n", "x", "t", "", "t", "Wrong %1", "q"], audit_type=None)
        self.assertEqual(result, 0)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(output.count("Ungültige Auswahl"), 2)
        self.assertIn("Übersetzung ist leer", output)
        self.assertIn("Placeholder-Abweichung", output)

    def test_interactive_q_interrupt_and_eof_save_prior_decisions_once(self):
        for ending in ("q", KeyboardInterrupt, EOFError):
            for during_translation in (False, True):
                with self.subTest(ending=ending, during_translation=during_translation):
                    if ending == "q" and during_translation:
                        continue
                    common.write_json(self.path, self.data)
                    replies = ["n"] + (["t"] if during_translation else []) + [ending]
                    with patch.object(review, "write_json", wraps=common.write_json) as writer:
                        result, output = self.interactive(replies)
                        writer.assert_called_once()
                    self.assertEqual(result, 0)
                    expected = deepcopy(self.data)
                    expected["entries"][0]["translations"]["DE"]["needed"] = True
                    self.assertEqual(common.load_json(self.path), expected)
                    self.assertIn("Zwischenstand gespeichert.", output)
                    self.assertIn("Fortsetzen mit --offset 1", output)
                    self.assertNotIn("[3/3]", output)

    def test_interactive_review_resume_offset_accounts_for_removed_confirmed_candidates(self):
        data = deepcopy(self.data)
        for item in data["entries"][:3]:
            item["translations"]["DE"].update(review=True, text="Prüfen")
        for ending in ("q", KeyboardInterrupt, EOFError):
            with self.subTest(ending=ending):
                common.write_json(self.path, data)
                result, output = self.interactive(["s", "a", ending], audit_type=None)
                self.assertEqual(result, 0)
                self.assertIn("Fortsetzen mit --offset 1", output)
                result, output = self.interactive(["q"], audit_type=None, offset=1)
                self.assertEqual(result, 0)
                self.assertIn("[2/2] Recorded_Media / SameC", output)
                self.assertNotIn("RadioData / SameA", output)
        # All prior reviews were cleared, so the new filtered offset is zero.
        common.write_json(self.path, data)
        result, output = self.interactive(["a", "q"], audit_type=None)
        self.assertEqual(result, 0)
        self.assertIn("Fortsetzen mit --offset 0", output)

    def test_interactive_out_of_range_offset_and_absent_candidates_fail_unchanged(self):
        before = self.path.read_bytes()
        for offset in (3, 999):
            result, _ = self.interactive([], offset=offset)
            self.assertEqual(result, 1)
        self.assertEqual(self.interactive([], audit_type=None, category="Recorded_Media")[0], 1)
        self.store()
        self.assertEqual(self.interactive([], audit_type="blank_target", selector="mod")[0], 1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_interactive_sessions_read_only_drafts_and_mutate_no_other_files(self):
        self.store()
        build.run(language="DE")
        self.assertFalse(config.DATA.exists())
        for audit_type, replies in (("same_as_source", ["n", "q"]), (None, ["t", "Neu"])):
            with self.subTest(audit_type=audit_type):
                common.write_json(self.path, self.data)
                before = common.read_tree(self.root)
                with patch.object(pzgt, "scan_data", side_effect=AssertionError("Live source")), \
                        patch.object(pzgt, "load_config", side_effect=AssertionError("Source config")), \
                        patch.object(status, "collect_language", side_effect=AssertionError("Source contents")), \
                        patch.object(build, "build", side_effect=AssertionError("Implicit build")), \
                        patch.object(work, "run", side_effect=AssertionError("Implicit work")), \
                        patch.object(apply, "run", side_effect=AssertionError("Implicit apply")), \
                        patch.object(draft, "run", side_effect=AssertionError("Implicit refresh")):
                    self.assertEqual(self.interactive(replies, audit_type)[0], 0)
                after = common.read_tree(self.root)
                self.assertEqual(before.keys(), after.keys())
                self.assertEqual([p for p in before if before[p] != after[p]],
                                 [Path("translations/__project_zomboid.json")])
        self.assertFalse(config.DATA.exists())

    def test_interactive_audit_translation_builds_and_review_translation_matches_apply(self):
        data = deepcopy(self.data)
        for item in data["entries"]:
            state = item["translations"]["DE"]
            state["review"] = False
            state.pop("previous_english", None)
            if state.get("audit"):
                state["needed"] = False
        common.write_json(self.path, data)
        self.assertEqual(self.interactive(["t", "Direkt übersetzt", "q"], category="RadioData")[0], 0)
        build.run(language="DE")
        import json
        runtime = json.loads((config.TRANSLATE / "DE/RadioData.json").read_text())
        self.assertEqual(runtime, {"Missing": "Fehlende Übersetzung", "SameA": "Direkt übersetzt"})
        self.assertEqual(common.load_json(self.path)["entries"][0]["translations"]["DE"]["audit"], "same_as_source")
        common.write_json(self.path, self.data)
        package = work.make_work(common.load_drafts(), "Project Zomboid", language="DE")
        self.assertEqual([e["key"] for e in package["entries"]], ["SameB"])
        package["entries"][0]["translation"] = "Geprüfter Text"
        _, expected, _ = apply.apply_work(package, common.load_drafts())
        self.assertEqual(self.interactive(["t", "Geprüfter Text"], audit_type=None)[0], 0)
        self.assertEqual(common.load_json(self.path), expected)
