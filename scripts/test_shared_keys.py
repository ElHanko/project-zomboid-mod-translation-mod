from copy import deepcopy
import json
from pathlib import Path
import unittest

import build


def entry(category="IG_UI", key="IGUI_VehiclePartGM85Roofrack", english="Roofrack", text="Dachgepäckträger"):
    return {"category": category, "key": key, "english": english,
            "translations": {"DE": {"text": text, "needed": True, "review": False}}}


def draft(mod, entries):
    return Path(mod + ".json"), {"workshop_id": "123", "directory": mod, "mod_id": mod, "entries": entries}


class SharedKeyTests(unittest.TestCase):
    def drafts(self, english="Roofrack", text="Dachgepäckträger", owner="buick"):
        return [draft("pontiac", [entry()]), draft(owner, [entry(english=english, text=text)])]

    def test_identical_shared_key_builds_once(self):
        expected, included, _ = build.collect_expected(self.drafts(), "DE")
        self.assertEqual(json.loads(expected[Path("IG_UI.json")]),
                         {"IGUI_VehiclePartGM85Roofrack": "Dachgepäckträger"})
        self.assertEqual(len(included), 2)

    def test_conflicts_and_same_mod_duplicates_fail(self):
        for kwargs in ({"english": "Other"}, {"text": "Andere"}, {"owner": "pontiac"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build.collect_expected(self.drafts(**kwargs), "DE")

    def test_identical_shared_plain_target_builds_once(self):
        drafts = [draft("first", [entry("__plain__", "Shared/description.txt", "First English", "Gemeinsam   ")]),
                  draft("second", [entry("__plain__", "Shared/description.txt", "Different English", "Gemeinsam")])]
        expected, included, _ = build.collect_expected(drafts, "DE")
        self.assertEqual(expected, {Path("Shared/description.txt"): b"Gemeinsam\n"})
        self.assertEqual(len(included), 2)

    def test_plain_conflicts_and_same_owner_fail(self):
        for text, owner in (("Anders", "second"), ("Gemeinsam", "first")):
            drafts = [draft("first", [entry("__plain__", "title.txt", text="Gemeinsam")]),
                      draft(owner, [entry("__plain__", "title.txt", text=text)])]
            with self.subTest(text=text, owner=owner), self.assertRaises(ValueError):
                build.collect_expected(drafts, "DE")

    def test_later_duplicate_of_second_owner_fails(self):
        drafts = self.drafts()
        drafts.append(deepcopy(drafts[1]))
        with self.assertRaises(ValueError):
            build.collect_expected(drafts, "DE")

    def test_duplicate_inside_incomplete_owner_fails(self):
        with self.assertRaises(ValueError):
            build.collect_expected([draft("one", [entry(text=""), entry(text="")])], "DE")

    def test_plain_identity_does_not_collide_with_json_category_named_plain(self):
        drafts = [draft("mod", [entry("__plain__", "title.txt"), entry("plain", "title.txt")])]
        expected, _, _ = build.collect_expected(drafts, "DE")
        self.assertEqual(set(expected), {Path("title.txt"), Path("plain.json")})

    def test_conflict_only_in_other_language(self):
        drafts = self.drafts()
        for i, (_, data) in enumerate(drafts):
            data["entries"][0]["translations"]["FR"] = {"text": str(i), "needed": True, "review": False}
        build.collect_expected(drafts, "DE")
        with self.assertRaises(ValueError):
            build.collect_expected(drafts, "FR")


if __name__ == "__main__":
    unittest.main()
