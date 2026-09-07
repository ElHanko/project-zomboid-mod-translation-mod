"""Script DisplayNames supplement only missing effective English ItemNames."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import config
import draft
import pzgt
import status


class ScriptItemNameTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def write(self, layer, relative, text):
        path = self.root / layer / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def script(self, layer, text, filename="items.txt"):
        return self.write(layer, "media/scripts/" + filename, text)

    def translate(self, layer, language, filename, text):
        return self.write(layer, f"media/lua/shared/Translate/{language}/{filename}", text)

    def mod(self):
        with patch.object(config, "LANGUAGES", ["DE", "FR"]):
            layers = pzgt.discover_layers(self.root)
        effective, _ = pzgt.select_effective_layers(layers, "42.20.4")
        return {"workshop_id": "123", "directory": "fixture", "layers": layers,
                "effective_layers": [layer["name"] for layer in effective]}

    def test_missing_itemname_becomes_normal_source_and_draft_requirement(self):
        self.script("42.20", "module damnCraft { item SeatFabric { DisplayName = Seat Fabric, } }")
        scan = {"mods": [self.mod()], "languages": ["DE"], "game_version": "42.20.4"}
        row = status.analyze_scan(scan, "DE")["mods"][0]
        self.assertEqual(row["english"], [{
            "category": "ItemName", "key": "damnCraft.SeatFabric", "text": "Seat Fabric",
            "file": "media/scripts/items.txt", "layer": "42.20", "format": "script-displayname",
        }])
        self.assertEqual(row["missing"], row["english"])
        self.assertEqual(row["counts"]["translated"], 0)
        with patch.object(config, "LANGUAGES", ["DE"]):
            entries = draft.merge_entries(row, [], "DE")
        self.assertEqual(entries[0]["translations"]["DE"],
                         {"text": "", "needed": True, "review": False})

    def test_comments_whitespace_multiple_modules_and_nested_blocks(self):
        path = self.script("common", '''\ufeff
            /* module Fake { item Wrong { DisplayName = Wrong, } } */
            module\tChristmas
            {
                imports { Base, }
                item /* comment between header tokens */ ChristmasAHBare
                {
                    // DisplayName = Wrong, } {
                    DisplayName\t= American Holly,
                    component Nested { DisplayName = Wrong, }
                }
                model Decoration { DisplayName = Wrong, }
                recipe MakeSomething { item Wrong { DisplayName = Wrong, } }
                item Other { DisplayName = Placeholder, }
                item NoName { Icon = Anything, }
            }
            module Second { item Other { DisplayName = no, } }
        ''')
        self.assertEqual(status.parse_script_itemnames(path), {
            "Christmas.ChristmasAHBare": "American Holly", "Christmas.Other": "Placeholder",
            "Second.Other": "no",
        })

    def test_quoted_delimiters_and_comments_do_not_change_block_structure(self):
        path = self.script("common", '''module Base {
            item Test { DisplayName = "Fabric, {blue} // /* label */", }
            item Next { DisplayName = Next, } // trailing comment
        }''')
        self.assertEqual(status.parse_script_itemnames(path), {
            "Base.Test": "Fabric, {blue} // /* label */", "Base.Next": "Next",
        })

    def test_real_workshop_nested_comments_and_empty_separators(self):
        path = self.script("common", '''
            /* recipe Example { Ingredient=1, /* note */ Result:Example, } */
            module Base {
                /* template vehicle Disabled { /* */ } */
                /* item Hidden { /* nested */ DisplayName = Hidden, } */
                /*/
                item First { DisplayName = First, }
                /*/
                item Second { DisplayName = Second, }
                /*/
            }
        ''')
        self.assertEqual(status.parse_script_itemnames(path), {
            "Base.First": "First", "Base.Second": "Second",
        })

    def test_explicit_en_wins_in_either_layer_and_keeps_translate_semantics(self):
        for layer in ("common", "42.20"):
            self.script(layer, "module Christmas { item Tree { DisplayName = Big American Holly, } }")
        self.translate("common", "EN", "ItemName_EN.txt",
                       'ItemName_EN = {\n Christmas.Tree = "Tall American Holly",\n}\n')
        self.translate("common", "EN", "UI_EN.txt", 'UI_EN = {\n UI_Label = "Old",\n}\n')
        self.translate("42.20", "EN", "UI.json", '{"UI_Label": "Current"}')
        ident = status.identity("ItemName", "Christmas.Tree")
        collected = status.collect_language(self.mod(), "EN")
        self.assertEqual(collected["entries"][ident]["text"], "Tall American Holly")
        self.assertEqual(collected["entries"][ident]["format"], "legacy-txt")
        self.assertEqual(collected["entries"][status.identity("UI", "UI_Label")]["text"], "Current")
        self.translate("42.20", "EN", "ItemName.json", json.dumps({"Christmas.Tree": "Newest"}))
        record = status.collect_language(self.mod(), "EN")["entries"][ident]
        self.assertEqual((record["text"], record["layer"], record["format"]), ("Newest", "42.20", "json"))
        self.translate("42.20", "EN", "ItemName.json", '{"Christmas.Tree": ""}')
        self.assertEqual(status.collect_language(self.mod(), "EN")["entries"][ident]["text"], "")

    def test_only_effective_layers_and_later_script_value_wins(self):
        for layer in ("common", "42.0", "42.13", "42.20", "42.21"):
            self.script(layer, f"module Base {{ item Shared {{ DisplayName = {layer}, }} }}")
        self.script("common", "module Base { item CommonOnly { DisplayName = Common, } }", "nested/more.txt")
        self.script("42.20", "module Base { item VersionOnly { DisplayName = Version, } }", "nested/more.txt")
        self.script("42.13", "module Base { item OldOnly { DisplayName = Old, } }", "old.txt")
        self.script("", "module Base { item Legacy { DisplayName = Legacy, } }")
        self.write("", "mod.info", "id=legacy\n")
        mod = self.mod()
        self.assertEqual(mod["effective_layers"], ["common", "42.20"])
        records = status.collect_language(mod, "EN")["entries"]
        self.assertEqual({record["key"]: record["text"] for record in records.values()}, {
            "Base.Shared": "42.20", "Base.CommonOnly": "Common", "Base.VersionOnly": "Version",
        })
        self.assertEqual(records[status.identity("ItemName", "Base.Shared")]["layer"], "42.20")

    def test_target_languages_only_collect_explicit_translations(self):
        self.script("common", "module Base { item Test { DisplayName = English, } }")
        for language in ("DE", "FR"):
            with self.subTest(language=language):
                self.assertEqual(status.collect_language(self.mod(), language)["entries"], {})
                self.translate("common", language, "ItemName.json", '{"Base.Test": "Target"}')
                records = status.collect_language(self.mod(), language)["entries"]
                self.assertEqual(records[status.identity("ItemName", "Base.Test")]["text"], "Target")

    def test_malformed_script_reports_source_file_without_losing_other_files(self):
        for text in ('module Base {', '}', '/* unclosed', 'module Base { item Test { DisplayName = "open'):
            with self.subTest(text=text):
                self.script("common", text, "broken.txt")
                self.script("common", "module Base { item Test { DisplayName = Good, } }", "good.txt")
                collected = status.collect_language(self.mod(), "EN")
                self.assertEqual(len(collected["parse_errors"]), 1)
                self.assertEqual(collected["parse_errors"][0]["file"], "media/scripts/broken.txt")
                self.assertEqual(len(collected["entries"]), 1)
                self.assertEqual(status.collect_language(self.mod(), "DE")["parse_errors"], [])


if __name__ == "__main__":
    unittest.main()
