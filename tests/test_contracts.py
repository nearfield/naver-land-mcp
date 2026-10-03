"""Regressions based on independently sanitized live response contracts."""

import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from articles import (
    floor_number,
    get_article_detail,
    normalize_article,
    number,
    photo_url,
)
from naver_land import AccessRestrictedError, NaverLandClient, ResponseSchemaError
from studio import evaluate_articles, search_studio

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class ContractTests(unittest.TestCase):
    def test_mcp_float_money_serializes_as_upstream_integer_manwon(self):
        client = Mock()
        client.resolve_region.return_value = {
            "cortarNo": "1168010300", "cortarType": "sec",
        }
        client._get.return_value = {"articleList": [], "isMoreData": False}
        search_studio(client, monthly_rent_lt=150.0, deposit_max=3000.0,
                      detail_limit=0)
        params = client._get.call_args.args[1]
        query = requests.Request("GET", "https://example.test/articles",
                                 params=params).prepare().url
        self.assertIn("rentPriceMax=150&", query)
        self.assertTrue(query.endswith("priceMax=3000&page=1"))
        self.assertNotIn("150.0", query)
        self.assertNotIn("3000.0", query)

    def test_fractional_money_caps_preserve_eligible_ads_and_exact_local_limits(self):
        client = Mock()
        client.resolve_region.return_value = {
            "cortarNo": "1168010300", "cortarType": "sec",
        }
        base = fixture("office_list")["articleList"][1]
        rows = [
            dict(base, articleNo="9000000011", rentPrc=149.5,
                 dealOrWarrantPrc="3000.5"),
            dict(base, articleNo="9000000012", rentPrc=149.9,
                 dealOrWarrantPrc="3000.5"),
            dict(base, articleNo="9000000013", rentPrc=149.5,
                 dealOrWarrantPrc="3001"),
        ]
        client._get.return_value = {"articleList": rows, "isMoreData": False}
        result = search_studio(client, monthly_rent_lt=149.9,
                               deposit_max=3000.5, detail_limit=0)
        params = client._get.call_args.args[1]
        self.assertEqual(params["rentPriceMax"], 150)
        self.assertEqual(params["priceMax"], 3001)
        self.assertEqual([x["articleNo"] for x in result["matchingAdvertisements"]],
                         ["9000000011"])
        self.assertEqual(len(result["excludedAdvertisements"]), 2)

    def test_live_detail_field_casing_and_sources(self):
        item = normalize_article(fixture("office_detail"))
        self.assertEqual(item["propertyType"], "SMS")
        self.assertEqual(item["monthlyRentManwon"], 150)
        self.assertEqual(item["advertisedExclusiveM2"], 114.75)
        self.assertEqual(item["advertisementConfirmedDate"], "20261002")
        self.assertEqual(item["managementFeeRaw"]["monthlyManagementCost"], 60000)
        self.assertEqual(item["photoStatus"], "not_published")

    def test_photo_contract_has_seven_public_urls(self):
        item = normalize_article(fixture("office_photos"))
        self.assertEqual(item["propertyType"], "SMS")
        self.assertEqual(item["photoStatus"], "available")
        self.assertEqual(len(item["photoUrls"]), 7)
        self.assertTrue(all(x.startswith("https://") for x in item["photoUrls"]))

    def test_apartment_detail_is_not_treated_as_office(self):
        item = normalize_article(fixture("apartment_detail"))
        self.assertEqual(item["propertyType"], "APT")
        self.assertEqual(item["photoStatus"], "not_published")
        result = evaluate_articles([fixture("apartment_detail")])
        self.assertIn(
            "상가·사무실 아님", result["excludedAdvertisements"][0]["exclusionReasons"]
        )

    def test_display_rounded_boundary_is_unknown_not_excluded(self):
        raw = fixture("office_list")["articleList"][0]
        raw.update(area2=49, rentPrc=100, floorInfo="2/5")
        result = evaluate_articles([raw])
        self.assertEqual(len(result["needsVerification"]), 1)
        self.assertIn(
            "advertisedExclusiveM2Precision",
            result["needsVerification"][0]["unknownFilterFields"],
        )
        self.assertFalse(result["excludedAdvertisements"])

    def test_boundary_enrichment_reclassifies_using_exact_advertised_area(self):
        raw = fixture("office_list")["articleList"][0]
        raw.update(area2=49, rentPrc=100, floorInfo="2/5")
        detail = fixture("office_detail")
        detail["articleDetail"]["articleNo"] = raw["articleNo"]
        detail["articleSpace"]["exclusiveSpace"] = 49.6
        detail["articlePrice"]["rentPrice"] = 100
        detail["articleAddition"]["floorInfo"] = "2/5"
        client = Mock()
        client.resolve_region.return_value = {
            "cortarNo": "1168010300",
            "cortarType": "sec",
        }
        client._get.side_effect = [{"articleList": [raw], "isMoreData": False}, detail]
        result = search_studio(client, detail_limit=1)
        self.assertEqual(len(result["matchingAdvertisements"]), 1)
        self.assertEqual(
            result["matchingAdvertisements"][0]["advertisedExclusiveM2"], 49.6
        )
        self.assertEqual(result["detailLookups"], 1)

    def test_basement_label_overrides_unsigned_floor_count(self):
        raw = fixture("office_detail")
        raw["articleAddition"]["floorInfo"] = "B2/5"
        raw["articleFloor"]["correspondingFloorCount"] = "2"
        self.assertEqual(normalize_article(raw)["floorNumber"], -2)

    def test_unknown_cost_units_never_become_total_monthly_cost(self):
        item = normalize_article(fixture("office_detail"))
        self.assertNotIn("totalMonthlyManwon", item)
        self.assertNotIn("maintenanceManwon", item)
        self.assertEqual(item["managementFeeRaw"]["monthlyManagementCost"], 60000)

    def test_photo_missing_and_unsafe_are_distinct_from_no_published_photos(self):
        raw = fixture("office_detail")
        del raw["articlePhotos"]
        self.assertEqual(normalize_article(raw)["photoStatus"], "unknown")
        raw["articlePhotos"] = [{"imageSrc": "http://unsafe.test/image.jpg"}]
        self.assertEqual(normalize_article(raw)["photoStatus"], "unusable")

    def test_malformed_nested_blocks_fail_loudly(self):
        for key in [
            "articleDetail",
            "articlePrice",
            "articleSpace",
            "articleFacility",
            "articleFloor",
            "articleAddition",
            "articleBuildingRegister",
        ]:
            raw = fixture("office_detail")
            raw[key] = []
            with self.subTest(key=key), self.assertRaises(ResponseSchemaError):
                normalize_article(raw)
        raw = fixture("office_detail")
        raw["articlePhotos"] = {}
        with self.assertRaises(ResponseSchemaError):
            normalize_article(raw)

    def test_detail_identity_mismatch_is_not_success(self):
        client = Mock()
        client._get.return_value = fixture("office_detail")
        with self.assertRaises(ResponseSchemaError):
            get_article_detail(client, "9000000002")
        raw = fixture("office_detail")
        del raw["articlePhotos"]
        client._get.return_value = raw
        with self.assertRaises(ResponseSchemaError):
            get_article_detail(client, "9000000001")
        raw = fixture("office_detail")
        del raw["articleDetail"]["articleNo"]
        client._get.return_value = raw
        with self.assertRaises(ResponseSchemaError):
            get_article_detail(client, "9000000001")

    def test_detail_empty_photos_is_valid_only_with_valid_contract(self):
        client = Mock()
        client._get.return_value = fixture("office_detail")
        result = get_article_detail(client, "9000000001")
        self.assertEqual(result["photoStatus"], "not_published")
        self.assertFalse(result["photoDownloadPerformed"])

    def test_duplicate_urls_and_unknown_photo_rows(self):
        raw = fixture("office_detail")
        raw["articlePhotos"] = [
            None,
            {"imageSrc": "/one.jpg"},
            {"imageSrc": "/one.jpg"},
        ]
        self.assertEqual(len(normalize_article(raw)["photoUrls"]), 1)

    def test_numeric_values_do_not_accept_ambiguous_units(self):
        for raw in [None, True, "", "6억 5천", "협의", "NaN", "-1", "Infinity"]:
            self.assertIsNone(number(raw), raw)
        self.assertEqual(number("1억 2,000"), 12000)
        self.assertEqual(number("0"), 0)
        self.assertEqual(number("-122.5", allow_negative=True), -122.5)

    def test_unsafe_urls_cannot_be_emitted(self):
        for value in [
            "javascript:x",
            "http://example.test/a",
            "https://user:pw@example.test/a",
            "https://example.test:8080/a",
            "https://[broken",
            "https://example.test/a\n",
        ]:
            # Leading/trailing whitespace is normalized, internal whitespace is rejected.
            if value.endswith("\n"):
                value = value.replace("/a\n", "/a\nb")
            self.assertIsNone(photo_url(value), value)
        self.assertEqual(photo_url("//example.test/a"), "https://example.test/a")
        self.assertEqual(photo_url("https://example.test/a"), "https://example.test/a")

    def test_zero_area_and_missing_identity_need_verification(self):
        raw = fixture("office_list")["articleList"][1]
        raw.update(area2=0, articleNo="")
        item = evaluate_articles([raw])["needsVerification"][0]
        self.assertIn("articleNo", item["unknownFilterFields"])
        self.assertIn("advertisedExclusiveM2", item["unknownFilterFields"])

    def test_invalid_and_future_approval_dates_not_fabricated(self):
        for value in ["unknown", "29990101"]:
            raw = fixture("office_detail")
            raw["articleFacility"]["buildingUseAprvYmd"] = value
            self.assertIsNone(normalize_article(raw)["ageYearsAdvertised"])

    def test_invalid_inputs_never_reach_the_network(self):
        client = Mock()
        for kwargs in [
            {"limit": True},
            {"max_pages": 2.5},
            {"detail_limit": 11},
            {"min_floor": 1},
            {"deposit_max": -1},
            {"center_lat": float("nan"), "center_lon": 127},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                search_studio(client, **kwargs)
        client.resolve_region.assert_not_called()

    def test_region_must_be_dong_level(self):
        client = Mock()
        for region in [None, {"cortarType": "city"}, {"cortarType": "dvsn"}]:
            client.resolve_region.return_value = region
            with self.assertRaises(ValueError):
                search_studio(client)
        client._get.assert_not_called()

    def test_malformed_list_row_and_detail_response_are_errors(self):
        client = Mock()
        client.resolve_region.return_value = {
            "cortarNo": "1168010300",
            "cortarType": "sec",
        }
        client._get.return_value = {"articleList": [{}], "isMoreData": False}
        with self.assertRaises(ResponseSchemaError):
            search_studio(client)
        client._get.side_effect = [
            {
                "articleList": fixture("office_list")["articleList"][1:2],
                "isMoreData": False,
            },
            {},
        ]
        with self.assertRaises(ResponseSchemaError):
            search_studio(client)

    def test_time_budget_reports_zero_pages_honestly(self):
        client = Mock()
        client.resolve_region.return_value = {
            "cortarNo": "1168010300",
            "cortarType": "sec",
        }
        with patch("studio.time.monotonic", side_effect=[0, 36, 36]):
            result = search_studio(client)
        self.assertEqual(result["pagesScanned"], 0)
        self.assertTrue(result["timeBudgetReached"])
        self.assertTrue(result["truncated"])
        client._get.assert_not_called()

    def test_total_input_and_return_caps(self):
        raw = fixture("office_list")["articleList"][1]
        with self.assertRaises(ValueError):
            evaluate_articles([raw] * 501)
        client = Mock()
        client.resolve_region.return_value = {
            "cortarNo": "1168010300",
            "cortarType": "sec",
        }
        rows = [dict(raw, articleNo=str(9000000000 + i)) for i in range(4)]
        client._get.return_value = {"articleList": rows, "isMoreData": False}
        result = search_studio(client, limit=1, detail_limit=0)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["classifiedCounts"]["matchingAdvertisements"], 4)
        self.assertEqual(len(result["matchingAdvertisements"]), 1)

    def test_floor_parsing_preserves_ground_and_basement(self):
        for text, expected in [
            ("0", 0),
            ("-2", -2),
            ("지하 2/5", -2),
            ("2층/5", 2),
            ("중/5", None),
        ]:
            self.assertEqual(floor_number(text), expected)


class TransportTests(unittest.TestCase):
    def test_all_apartment_lookups_failing_cannot_return_zero_results(self):
        from naver_land import crawl_district

        with (
            patch(
                "naver_land.resolve_region",
                return_value={
                    "cortarNo": "1168010300",
                    "cortarType": "sec",
                    "cortarName": "개포동",
                },
            ),
            patch(
                "naver_land._client.get_complexes",
                return_value=[{"complexNo": "12345", "rentCount": 20}],
            ),
            patch(
                "naver_land._client.get_articles",
                side_effect=RuntimeError("upstream error"),
            ),
            patch("naver_land.time.sleep"),
        ):
            with self.assertRaises(RuntimeError):
                crawl_district("개포동", 0, 999999, trade_type="B2", limit=1)

    def test_apartment_schema_change_is_not_an_empty_search(self):
        client = NaverLandClient()
        with patch.object(client, "_get", return_value={}):
            with self.assertRaises(ResponseSchemaError):
                client.get_articles("12345", max_pages=1)

    def test_apartment_requested_limit_does_not_scan_an_extra_page(self):
        from naver_land import crawl_district

        row = fixture("apartment_detail")["articleAddition"]
        with (
            patch(
                "naver_land.resolve_region",
                return_value={
                    "cortarNo": "1168010300",
                    "cortarType": "sec",
                    "cortarName": "개포동",
                },
            ),
            patch(
                "naver_land._client.get_complexes",
                return_value=[{"complexNo": "12345", "rentCount": 20}],
            ),
            patch("naver_land._client.get_articles", return_value=[row]) as articles,
            patch("naver_land.time.sleep"),
        ):
            result, _ = crawl_district("개포동", 0, 999999, trade_type="B2", limit=1)
        self.assertEqual(len(result), 1)
        self.assertEqual(articles.call_args.kwargs["max_pages"], 1)

    def client_with_response(self, response):
        client = NaverLandClient()
        client._session = Mock()
        client._jwt = "synthetic-test-token"
        client._session.get.return_value = response
        client._pause = Mock()
        return client

    def test_json_error_and_non_object_contract(self):
        for raw in [[], "not-object"]:
            response = Mock(
                status_code=200, headers={"Content-Type": "application/json"}
            )
            response.json.return_value = raw
            with self.assertRaises(ResponseSchemaError):
                self.client_with_response(response)._get("/articles")
        response.json.side_effect = ValueError("bad body")
        with self.assertRaises(ResponseSchemaError):
            self.client_with_response(response)._get("/articles")

    def test_200_access_denial_is_sticky(self):
        response = Mock(status_code=200, headers={"Content-Type": "application/json"})
        response.json.return_value = {
            "error": {"code": "CAPTCHA", "message": "do not log"}
        }
        client = self.client_with_response(response)
        for _ in range(2):
            with self.assertRaises(AccessRestrictedError):
                client._get("/articles")
        self.assertEqual(client._session.get.call_count, 1)

    def test_generic_api_and_network_errors_not_empty_data(self):
        response = Mock(status_code=200, headers={"Content-Type": "application/json"})
        response.json.return_value = {"error": "upstream failure"}
        with self.assertRaises(RuntimeError):
            self.client_with_response(response)._get("/articles")
        client = self.client_with_response(response)
        client._session.get.side_effect = requests.Timeout("secret-must-not-appear")
        with self.assertRaises(RuntimeError) as exc:
            client._get("/articles")
        self.assertNotIn("secret-must-not-appear", str(exc.exception))

    def test_close_does_not_clear_access_denial(self):
        client = self.client_with_response(Mock())
        client._access_restricted = True
        session = client._session
        client.close()
        session.close.assert_called_once()
        self.assertIsNone(client._jwt)
        with self.assertRaises(AccessRestrictedError):
            client._get("/articles")


if __name__ == "__main__":
    unittest.main()
