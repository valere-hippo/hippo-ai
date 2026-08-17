from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

from tier_ai.rules import get_rule, load_species_rules, set_rule_source


class RuleLoaderTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_rule_source(None)

    def test_loads_default_rules(self) -> None:
        rules = load_species_rules()

        self.assertGreaterEqual(len(rules), 110)
        self.assertIn("amsel", rules)
        self.assertEqual(rules["amsel"].species, "Amsel")
        self.assertIn("zwergfledermaus", rules)
        self.assertEqual(rules["zwergfledermaus"].min_contacts_for_reproduction, 3)
        self.assertEqual(rules["zwergfledermaus"].priority_if_breeding, "hoch")
        self.assertEqual(rules["amsel"].priority_default, "niedrig")
        self.assertIn("wasserfledermaus", rules)
        self.assertEqual(rules["wasserfledermaus"].taxon_group, "bat")

    def test_loads_custom_rule_file(self) -> None:
        payload = {
            "rotmilan": {
                "species": "Rotmilan",
                "breeding_months": [4, 5, 6],
                "habitat_keywords": ["offen", "feld"],
                "min_contacts_for_reproduction": 3,
                "priority_if_breeding": "sehr hoch",
                "priority_default": "mittel",
                "notes": "Greifvogelregel",
            }
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "rules.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            set_rule_source(path)

            rule = get_rule("Rotmilan")

        self.assertIsNotNone(rule)
        self.assertEqual(rule.species, "Rotmilan")
        self.assertEqual(rule.min_contacts_for_reproduction, 3)
        self.assertEqual(rule.priority_if_breeding, "sehr hoch")
        self.assertEqual(rule.priority_default, "mittel")


if __name__ == "__main__":
    unittest.main()
