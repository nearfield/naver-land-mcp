import json
import unittest
from unittest.mock import patch

from fastmcp import Client

from server import mcp
from test_contracts import fixture


class MCPContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_generic_detail_and_photos_use_real_contract_shapes(self):
        async with Client(mcp) as client:
            tools = await client.list_tools()
            self.assertEqual(len(tools), 11)
            with patch("server._client._get", return_value=fixture("office_photos")):
                for name in [
                    "get_article_detail",
                    "get_article_photos",
                    "get_studio_article",
                ]:
                    response = await client.call_tool(
                        name, {"article_no": "9000000002"}
                    )
                    payload = json.loads(
                        next(c.text for c in response.content if c.type == "text")
                    )
                    self.assertEqual(payload["propertyType"], "SMS")
                    self.assertEqual(len(payload["photoUrls"]), 7)

    async def test_apartment_empty_photo_response_has_explicit_state(self):
        async with Client(mcp) as client:
            with patch("server._client._get", return_value=fixture("apartment_detail")):
                response = await client.call_tool(
                    "get_article_photos", {"article_no": "9000000003"}
                )
                payload = json.loads(
                    next(c.text for c in response.content if c.type == "text")
                )
                self.assertEqual(payload["propertyType"], "APT")
                self.assertEqual(payload["photoStatus"], "not_published")


if __name__ == "__main__":
    unittest.main()
