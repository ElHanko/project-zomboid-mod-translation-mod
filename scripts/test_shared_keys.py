from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import build
import verify


class SharedKeyTests(unittest.TestCase):
    def drafts(self, english="Roofrack", german="Dachgepäckträger", owner="buick"):
        return [
            (Path(mod + ".json"), {
                "mod_id": mod,
                "entries": [{
                    "category": "IG_UI",
                    "key": "IGUI_VehiclePartGM85Roofrack",
                    "english": source,
                    "german": target,
                }],
            })
            for mod, source, target in [
                ("pontiac", "Roofrack", "Dachgepäckträger"),
                (owner, english, german),
            ]
        ]

    def test_identical_shared_key_builds_once(self):
        drafts = self.drafts()
        errors = []
        states = {path: {"complete": True} for path, _ in drafts}
        expected, _ = verify.collect_expected(drafts, states, errors)
        self.assertEqual(errors, [])
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(build, "DE_ROOT", root), patch.object(build, "write_mod_info"), redirect_stdout(StringIO()):
                build.build(drafts)
            actual = (root / "IG_UI.json").read_text()
            self.assertEqual(json.loads(actual), {"IGUI_VehiclePartGM85Roofrack": "Dachgepäckträger"})
            self.assertEqual(actual, expected[Path("IG_UI.json")])

    def test_conflicts_and_same_mod_duplicates_fail(self):
        for kwargs in ({"english": "Other"}, {"german": "Andere"}, {"owner": "pontiac"}):
            with self.subTest(kwargs=kwargs):
                drafts = self.drafts(**kwargs)
                errors = []
                states = {path: {"complete": True} for path, _ in drafts}
                verify.collect_expected(drafts, states, errors)
                self.assertTrue(errors)
                with (
                    redirect_stdout(StringIO()),
                    redirect_stderr(StringIO()),
                    self.assertRaises(SystemExit),
            ):
                    build.build(drafts)

    def test_identical_shared_plain_target_builds_once(self):
        drafts = [
            (
                Path("first.json"),
                {
                    "mod_id": "first",
                    "entries": [{
                        "category": "__plain__",
                        "key": "Shared/description.txt",
                        "english": "First English description",
                        "german": "Gemeinsame Beschreibung   ",
                    }],
                },
            ),
            (
                Path("second.json"),
                {
                    "mod_id": "second",
                    "entries": [{
                        "category": "__plain__",
                        "key": "Shared/description.txt",
                        "english": "Different English description",
                        "german": "Gemeinsame Beschreibung",
                    }],
                },
            ),
        ]

        errors = []
        states = {path: {"complete": True} for path, _ in drafts}

        expected, _ = verify.collect_expected(drafts, states, errors)
        self.assertEqual(errors, [])

        with TemporaryDirectory() as directory:
            root = Path(directory)

            with (
                patch.object(build, "DE_ROOT", root),
                patch.object(build, "write_mod_info"),
                redirect_stdout(StringIO()),
            ):
                build.build(drafts)

            actual = (root / "Shared" / "description.txt").read_text()

            self.assertEqual(actual, "Gemeinsame Beschreibung\n")
            self.assertEqual(
                actual,
                expected[Path("Shared/description.txt")],
            )

if __name__ == "__main__":
    unittest.main()
