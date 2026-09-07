"""Explicit Workshop exclusions survive refresh without hiding source changes."""
from copy import deepcopy
from unittest.mock import patch

import build
import common
import draft
import verify
from test_workflow import TemporaryRepository


class ModExclusionTests(TemporaryRepository):
    def setUp(self):
        super().setUp()
        self.data = self.bilingual("Texte conservé")
        self.data.update(game_version="42.20.4", effective_layers=["common"])
        self.state = self.data["entries"][0]["translations"]["DE"]
        self.state.update(needed=False, reviewed=1)
        self.path, _ = self.store(self.data)
        self.snapshot = {"language": "DE", "game_version": "42.20.4",
                         "mods": [self.source_mod()]}

    def test_new_key_and_unreviewed_false_state_become_needed(self):
        fresh = draft.merge_entries(self.source_mod(), [], "DE")
        self.assertTrue(fresh[0]["translations"]["DE"]["needed"])
        for reviewed in (None, 0):
            with self.subTest(reviewed=reviewed):
                self.state.pop("reviewed", None)
                if reviewed is not None:
                    self.state["reviewed"] = reviewed
                merged = draft.merge_entries(self.source_mod(), self.data["entries"], "DE")
                self.assertTrue(merged[0]["translations"]["DE"]["needed"])

    def test_draft_all_preserves_exclusion_and_other_language(self):
        self.save_status()
        draft.run("--all")
        after = common.load_json(self.path)
        self.assertEqual(after["entries"][0]["translations"], self.data["entries"][0]["translations"])
        first = self.path.read_bytes()
        draft.run("--all")
        self.assertEqual(self.path.read_bytes(), first)
        merged = draft.merge_entries(self.source_mod(), after["entries"], "FR")
        self.assertTrue(merged[0]["translations"]["FR"]["needed"])
        self.assertEqual(merged[0]["translations"]["DE"], self.state)

    def test_verify_accepts_exclusion_and_runtime_omits_saved_text(self):
        self.assertEqual(verify.source_errors(self.path, self.data, self.snapshot, "DE"), [])
        expected, _, _ = build.collect_expected([(self.path, self.data)], "DE")
        self.assertEqual(expected, {})
        build.run(language="DE")
        with patch("pzgt.scan_data", return_value={}), \
                patch("status.analyze_scan", return_value=self.snapshot):
            verify.run("DE")

    def test_verify_still_rejects_missing_and_unreviewed_exclusions(self):
        for entries in ([], self.data["entries"]):
            for reviewed in (None, 0):
                with self.subTest(entries=bool(entries), reviewed=reviewed):
                    data = deepcopy(self.data)
                    data["entries"] = deepcopy(entries)
                    if entries:
                        state = data["entries"][0]["translations"]["DE"]
                        state.pop("reviewed", None)
                        if reviewed is not None:
                            state["reviewed"] = reviewed
                    errors = verify.source_errors(self.path, data, self.snapshot, "DE")
                    self.assertTrue(any("neuer offener Quell-Key fehlt im Draft" in e for e in errors))

    def test_changed_source_invalidates_exclusion_and_requires_review(self):
        changed = self.source_mod("Changed source")
        snapshot = dict(self.snapshot, mods=[changed])
        errors = verify.source_errors(self.path, self.data, snapshot, "DE")
        self.assertTrue(any("englischer Quelltext geändert" in e for e in errors))
        after = draft.merge_entries(changed, self.data["entries"], "DE")
        for language in ("DE", "FR"):
            state = after[0]["translations"][language]
            self.assertTrue(state["review"])
            self.assertNotIn("reviewed", state)
            self.assertEqual(state["previous_english"], "Roofrack")
            self.assertEqual(state["text"], self.data["entries"][0]["translations"][language]["text"])
        self.assertTrue(after[0]["translations"]["DE"]["needed"])
        after = draft.merge_entries(changed, after, "DE")
        self.assertTrue(after[0]["translations"]["DE"]["needed"])
        updated = dict(self.data, entries=after)
        common.write_json(self.path, updated)
        build.run(language="DE")
        with patch("pzgt.scan_data", return_value={}), \
                patch("status.analyze_scan", return_value=snapshot), \
                self.assertRaisesRegex(ValueError, "Review offen"):
            verify.run("DE")

    def test_automatic_retirement_does_not_become_manual_exclusion(self):
        self.state["needed"] = True
        retired = draft.merge_entries(self.source_mod(needed=False), self.data["entries"], "DE")
        self.assertFalse(retired[0]["translations"]["DE"]["needed"])
        self.assertNotIn("reviewed", retired[0]["translations"]["DE"])
        returned = draft.merge_entries(self.source_mod(), retired, "DE")
        self.assertTrue(returned[0]["translations"]["DE"]["needed"])

    def test_exclusion_survives_upstream_translation_and_disappearance(self):
        for source in (self.source_mod(needed=False), dict(self.source_mod(), english=[], missing=[])):
            with self.subTest(source=source):
                after = draft.merge_entries(source, self.data["entries"], "DE")
                self.assertEqual(after[0]["translations"]["DE"], self.state)
                self.assertEqual(verify.source_errors(self.path, dict(self.data, entries=after),
                                 dict(self.snapshot, mods=[source]), "DE"), [])
                returned = draft.merge_entries(self.source_mod(), after, "DE")
                self.assertEqual(returned[0]["translations"]["DE"], self.state)

    def test_workshop_exclusion_does_not_apply_to_vanilla_missing_keys(self):
        source = dict(self.source_mod(), source_type="game", audit_blank=[], audit_same_as_source=[])
        game = dict(self.data, source_type="game")
        snapshot = dict(self.snapshot, mods=[], base_game=source)
        errors = verify.source_errors(self.path, game, snapshot, "DE")
        self.assertTrue(any("neuer offener Quell-Key fehlt im Draft" in e for e in errors))
        after = draft.merge_entries(source, game["entries"], "DE")
        self.assertTrue(after[0]["translations"]["DE"]["needed"])
