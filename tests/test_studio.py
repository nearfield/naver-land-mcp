import unittest
from unittest.mock import Mock, patch


from naver_land import AccessRestrictedError, NaverLandClient, check_access
from studio import (
    M2_PER_PYEONG,
    evaluate_articles,
    get_studio_detail,
    normalize_article,
    search_studio,
)


def article(aid="9000000001", **overrides):
    return {
        "articleNo": aid,
        "realEstateTypeCode": "SMS",
        "tradeTypeCode": "B2",
        "area2": 17 * M2_PER_PYEONG,
        "floorInfo": "2/5",
        "rentPrc": 140,
        "dealOrWarrantPrc": "2,000",
        **overrides,
    }


class StudioTests(unittest.TestCase):
    def test_rent_strict_cap_and_deposit_unlimited(self):
        result = evaluate_articles(
            [
                article("1", rentPrc="149.9", dealOrWarrantPrc="10억"),
                article("2", rentPrc=150),
            ]
        )
        self.assertEqual(
            [x["articleNo"] for x in result["matchingAdvertisements"]], ["1"]
        )
        self.assertEqual(
            result["excludedAdvertisements"][0]["exclusionReasons"], ["월세 상한 이상"]
        )

    def test_exclusive_not_supply_area(self):
        result = evaluate_articles([article(area1=66, area2=11 * M2_PER_PYEONG)])
        self.assertFalse(result["matchingAdvertisements"])
        self.assertIn(
            "전용면적", result["excludedAdvertisements"][0]["exclusionReasons"][0]
        )

    def test_inclusive_area_edges(self):
        for area in [15, 25]:
            self.assertEqual(
                len(
                    evaluate_articles([article(area2=area * M2_PER_PYEONG)])[
                        "matchingAdvertisements"
                    ]
                ),
                1,
            )

    def test_unknown_and_ambiguous_floor_not_matching(self):
        result = evaluate_articles(
            [article("1", area2=None), article("2", floorInfo="저/4")]
        )
        self.assertEqual(len(result["needsVerification"]), 2)
        self.assertFalse(result["matchingAdvertisements"])

    def test_basement_first_floor_and_rooftop(self):
        result = evaluate_articles(
            [
                article("1", floorInfo="B2/5"),
                article("2", floorInfo="1/4"),
                article("3", floorInfo="옥탑/5"),
            ]
        )
        self.assertEqual(len(result["excludedAdvertisements"]), 2)
        self.assertEqual(len(result["needsVerification"]), 1)

    def test_age_parking_and_elevator_not_filters(self):
        result = evaluate_articles(
            [
                article(
                    parkingPossibleYN="N", elevatorYN="N", buildingUseAprvYmd="19890101"
                )
            ]
        )
        self.assertEqual(len(result["matchingAdvertisements"]), 1)
        self.assertFalse(result["matchingAdvertisements"][0]["within10YearsPreferred"])

    def test_optional_deposit_unknown(self):
        result = evaluate_articles([article(dealOrWarrantPrc=None)], deposit_max=3000)
        self.assertEqual(
            result["needsVerification"][0]["unknownFilterFields"], ["depositManwon"]
        )

    def test_only_same_ad_id_deduplicated(self):
        result = evaluate_articles([article("1"), article("1"), article("2")])
        self.assertEqual(len(result["matchingAdvertisements"]), 2)
        self.assertEqual(result["duplicateArticleIdsRemoved"], 1)

    def test_distance_before_age_rent(self):
        result = evaluate_articles(
            [
                article("1", latitude=37.50, longitude=127.05, rentPrc=70),
                article("2", latitude=37.47, longitude=127.05, rentPrc=140),
            ],
            center_lat=37.47,
            center_lon=127.05,
        )
        self.assertEqual(
            [x["articleNo"] for x in result["matchingAdvertisements"]], ["2", "1"]
        )

    def test_detail_areas_and_photo_urls_cost_scope(self):
        data = {
            "articleDetail": article(),
            "articleSpace": {"exclusiveSpace": "56.2", "supplySpace": 70},
            "articlePrice": {"rentPrice": 140, "warrantPrice": 2000},
            "articleFacility": {"buildingUseAprvYmd": "19920101"},
            "articlePhotos": [
                {"imageSrc": "/image.jpg"},
                {"imageSrc": "javascript:alert(1)"},
            ],
            "administrationCostInfo": {"amount": 170000},
        }
        item = normalize_article(data)
        self.assertEqual(item["advertisedExclusiveM2"], 56.2)
        self.assertEqual(item["monthlyRentManwon"], 140)
        self.assertEqual(
            item["photoUrls"], ["https://landthumb-phinf.pstatic.net/image.jpg"]
        )
        self.assertEqual(
            item["managementFeeRaw"]["administrationCostInfo"]["amount"], 170000
        )
        self.assertNotIn("totalMonthlyManwon", item)

    def test_search_type_pagination_and_no_supply_area_filter(self):
        client = Mock()
        client.resolve_region.return_value = {
            "cortarNo": "1168010300",
            "cortarType": "sec",
        }
        client._get.side_effect = [
            {"articleList": [article()], "isMoreData": True},
            {"articleList": [], "isMoreData": False},
        ]
        result = search_studio(client, detail_limit=0)
        self.assertEqual(result["pagesScanned"], 2)
        self.assertFalse(result["truncated"])
        params = client._get.call_args_list[0].args[1]
        self.assertEqual(params["realEstateType"], "SMS:SG")
        for key in ["areaMin", "areaMax", "tag", "priceMax"]:
            self.assertNotIn(key, params)

    def test_partial_coverage_not_empty_result(self):
        client = Mock()
        client.resolve_region.return_value = {
            "cortarNo": "1168010300",
            "cortarType": "sec",
        }
        client._get.return_value = {"articleList": [], "isMoreData": True}
        self.assertTrue(search_studio(client, max_pages=1)["truncated"])
        client._get.return_value = {}
        with self.assertRaises(RuntimeError):
            search_studio(client)

    def test_detail_invalid_id_or_schema(self):
        client = Mock()
        with self.assertRaises(ValueError):
            get_studio_detail(client, "../../x")
        client._get.assert_not_called()
        client._get.return_value = {}
        with self.assertRaises(RuntimeError):
            get_studio_detail(client, "9000000001")

    def test_invalid_conditions_no_network(self):
        client = Mock()
        for kwargs in [
            {"monthly_rent_lt": float("nan")},
            {"min_area_pyeong": 26},
            {"center_lat": 37.4},
            {"max_pages": 100},
        ]:
            with self.assertRaises(ValueError):
                search_studio(client, **kwargs)
        client.resolve_region.assert_not_called()

    def test_access_denial_and_captcha(self):
        for status in [307, 401, 403, 429]:
            with self.assertRaises(AccessRestrictedError):
                check_access(Mock(status_code=status))
        with self.assertRaises(AccessRestrictedError):
            check_access(
                Mock(
                    status_code=200,
                    headers={"Content-Type": "text/html"},
                    text="서비스 이용이 제한되었습니다 captcha",
                )
            )

    def test_access_denial_is_sticky_no_retries(self):
        client = NaverLandClient()
        client._session, client._jwt = Mock(), "test-only-placeholder"
        client._session.get.return_value = Mock(status_code=429)
        with patch.object(client, "_pause"):
            for _ in range(2):
                with self.assertRaises(AccessRestrictedError):
                    client._get("/articles")
        self.assertEqual(client._session.get.call_count, 1)
        self.assertFalse(client._session.get.call_args.kwargs["allow_redirects"])

    def test_original_apartment_formatter_still_works(self):
        from filter import filter_and_rank

        row = article(realEstateTypeCode="APT")
        item = filter_and_rank([row], 1000, 3000)[0]
        self.assertEqual(item["price"], 2000)
        self.assertEqual(item["rentPrice"], 140)


if __name__ == "__main__":
    unittest.main()
