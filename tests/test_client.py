import json
import unittest

from client import LlmWikiClient, LlmWikiError


class FakeResponse:
    def __init__(self, status=200, payload=None, text=None):
        self.status = status
        self._text = text if text is not None else json.dumps(payload or {})

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def text(self):
        return self._text


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.closed = False

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def close(self):
        self.closed = True


class LlmWikiClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_sends_expected_request_and_auth_header(self):
        session = FakeSession(
            FakeResponse(
                payload={
                    "ok": True,
                    "mode": "hybrid",
                    "results": [{"path": "wiki/tcp.md", "title": "TCP"}],
                }
            )
        )
        client = LlmWikiClient(
            "http://wiki.local/", token="test-token-not-secret", session=session
        )

        result = await client.search("project id", "TCP congestion", top_k=3)

        self.assertEqual(result["results"][0]["path"], "wiki/tcp.md")
        method, url, kwargs = session.requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "http://wiki.local/api/v1/projects/project%20id/search")
        self.assertEqual(
            kwargs["json"],
            {"query": "TCP congestion", "topK": 3, "includeContent": False},
        )
        self.assertEqual(
            kwargs["headers"]["Authorization"], "Bearer test-token-not-secret"
        )

    async def test_health_does_not_send_auth_header(self):
        session = FakeSession(FakeResponse(payload={"ok": True, "status": "running"}))
        client = LlmWikiClient(
            "http://wiki.local", token="test-token-not-secret", session=session
        )

        await client.health()

        _, _, kwargs = session.requests[0]
        self.assertNotIn("Authorization", kwargs["headers"])

    async def test_read_page_url_encodes_path_query(self):
        session = FakeSession(
            FakeResponse(payload={"ok": True, "path": "wiki/a b.md", "content": "x"})
        )
        client = LlmWikiClient("http://wiki.local", session=session)

        result = await client.read_page("current", "wiki/a b.md")

        self.assertEqual(result["content"], "x")
        _, url, _ = session.requests[0]
        self.assertEqual(
            url,
            "http://wiki.local/api/v1/projects/current/files/content?path=wiki%2Fa+b.md",
        )

    async def test_chat_sends_wiki_only_non_persistent_request(self):
        session = FakeSession(
            FakeResponse(
                payload={
                    "ok": True,
                    "message": {"role": "assistant", "content": "TCP 摘要"},
                    "references": [
                        {
                            "title": "TCP",
                            "path": "wiki/entities/tcp.md",
                            "kind": "wiki",
                        }
                    ],
                }
            )
        )
        client = LlmWikiClient("http://wiki.local", session=session)

        result = await client.chat("project id", "总结 TCP")

        self.assertEqual(result["message"]["content"], "TCP 摘要")
        method, url, kwargs = session.requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "http://wiki.local/api/v1/projects/project%20id/chat")
        self.assertEqual(
            kwargs["json"],
            {
                "message": "总结 TCP",
                "persistSession": False,
                "tools": {"wiki": True, "web": False, "anytxt": False},
            },
        )

    async def test_unauthorized_response_has_actionable_error(self):
        session = FakeSession(
            FakeResponse(status=401, payload={"ok": False, "error": "Unauthorized"})
        )
        client = LlmWikiClient("http://wiki.local", session=session)

        with self.assertRaisesRegex(LlmWikiError, "API token") as caught:
            await client.projects()

        self.assertEqual(caught.exception.status, 401)

    async def test_missing_page_preserves_server_error(self):
        session = FakeSession(
            FakeResponse(status=404, payload={"ok": False, "error": "File not found"})
        )
        client = LlmWikiClient("http://wiki.local", session=session)

        with self.assertRaisesRegex(LlmWikiError, "File not found") as caught:
            await client.read_page("current", "wiki/missing.md")

        self.assertEqual(caught.exception.status, 404)

    async def test_service_unavailable_has_actionable_error(self):
        session = FakeSession(
            FakeResponse(status=503, payload={"ok": False, "error": "API disabled"})
        )
        client = LlmWikiClient("http://wiki.local", session=session)

        with self.assertRaisesRegex(LlmWikiError, "unavailable") as caught:
            await client.projects()

        self.assertEqual(caught.exception.status, 503)

    async def test_non_json_response_is_rejected(self):
        session = FakeSession(FakeResponse(text="not json"))
        client = LlmWikiClient("http://wiki.local", session=session)

        with self.assertRaisesRegex(LlmWikiError, "invalid JSON"):
            await client.projects()

    async def test_non_object_json_response_is_rejected(self):
        session = FakeSession(FakeResponse(text="[]"))
        client = LlmWikiClient("http://wiki.local", session=session)

        with self.assertRaisesRegex(LlmWikiError, "JSON object"):
            await client.projects()

    async def test_transport_error_is_wrapped(self):
        session = FakeSession(OSError("network unreachable"))
        client = LlmWikiClient("http://wiki.local", session=session)

        with self.assertRaisesRegex(LlmWikiError, "Cannot connect"):
            await client.projects()

    async def test_close_closes_injected_session(self):
        session = FakeSession()
        client = LlmWikiClient("http://wiki.local", session=session)

        await client.close()

        self.assertTrue(session.closed)


if __name__ == "__main__":
    unittest.main()
