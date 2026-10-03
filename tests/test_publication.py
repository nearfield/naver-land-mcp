import json
import unittest

from publication import text_issues


class PublicationTests(unittest.TestCase):
    def test_private_path_is_rejected_without_printing_it(self):
        path = "/Users/" + "example" + "/Documents/private.md"
        self.assertEqual(text_issues(path), ["personal_absolute_path"])

    def test_synthetic_fixtures_are_distinct_from_actual_listing_ids(self):
        self.assertFalse(text_issues('{"articleNo": "9000000001"}'))
        self.assertEqual(
            text_issues(json.dumps({"articleNo": str(1234567890)})),
            ["actual_fixture_listing_id"],
        )

    def test_literal_token_is_rejected_but_regex_source_is_allowed(self):
        token = "eyJ" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12
        self.assertEqual(text_issues(token), ["jwt_literal"])
        self.assertFalse(text_issues("eyJ[A-Za-z0-9_-]+"))


if __name__ == "__main__":
    unittest.main()
