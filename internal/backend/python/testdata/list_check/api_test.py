"""Verify generated variable-length string lists and element constraints."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

import generated as api


class StringLists(unittest.TestCase):
    def test_variable_length_lists_and_optional_absence(self) -> None:
        empty = api.Query.model_validate({"tags": []})
        self.assertEqual(empty.tags, [])
        self.assertIsNone(empty.notes)
        absent = api.Query.model_validate({})
        self.assertIsNone(absent.tags)
        self.assertIsNone(absent.notes)

        populated = api.Query.model_validate({"tags": ["alpha", "beta"], "notes": []})
        self.assertEqual(populated.tags, ["alpha", "beta"])
        self.assertEqual(populated.notes, [])

    def test_list_elements_obey_cue_constraints(self) -> None:
        for values in [[""], ["HasUpper"], ["has-dash"]]:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                api.Query.model_validate({"tags": values})

    def test_list_items_must_be_strings(self) -> None:
        with self.assertRaises(ValidationError):
            api.Query.model_validate({"tags": [1]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
