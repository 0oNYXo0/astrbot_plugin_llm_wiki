import sys
import types
import unittest


class _CommandGroupDecorator:
    def __call__(self, func):
        return self

    def command(self, *args, **kwargs):
        return lambda func: func


class _Filter:
    def command_group(self, *args, **kwargs):
        return _CommandGroupDecorator()

    def llm_tool(self, *args, **kwargs):
        return lambda func: func

    def on_llm_request(self, *args, **kwargs):
        return lambda func: func


class _Logger:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def _install_astrbot_stubs():
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    event = types.ModuleType("astrbot.api.event")
    star = types.ModuleType("astrbot.api.star")
    core = types.ModuleType("astrbot.core")
    agent = types.ModuleType("astrbot.core.agent")
    message = types.ModuleType("astrbot.core.agent.message")
    star_filter = types.ModuleType("astrbot.core.star.filter")
    command = types.ModuleType("astrbot.core.star.filter.command")

    class GreedyStr(str):
        pass

    class TextPart:
        def __init__(self, text):
            self.text = text
            self.temporary = False

        def mark_as_temp(self):
            self.temporary = True
            return self

    class Star:
        def __init__(self, context):
            self.context = context

    class Context:
        pass

    event.filter = _Filter()
    event.AstrMessageEvent = object
    star.Context = Context
    star.Star = Star
    star.register = lambda *args, **kwargs: lambda cls: cls
    api.logger = _Logger()
    api.AstrBotConfig = dict
    message.TextPart = TextPart
    command.GreedyStr = GreedyStr

    sys.modules.update(
        {
            "astrbot": astrbot,
            "astrbot.api": api,
            "astrbot.api.event": event,
            "astrbot.api.star": star,
            "astrbot.core": core,
            "astrbot.core.agent": agent,
            "astrbot.core.agent.message": message,
            "astrbot.core.star.filter": star_filter,
            "astrbot.core.star.filter.command": command,
        }
    )


_install_astrbot_stubs()

from astrbot.core.star.filter.command import GreedyStr

from client import LlmWikiError
from main import LlmWikiPlugin


class FakeClient:
    def __init__(self):
        self.closed = False
        self.chat_calls = []
        self.search_calls = []
        self.read_calls = []

    async def health(self):
        return {
            "version": "0.6.11",
            "status": "running",
            "authRequired": False,
        }

    async def projects(self):
        return {
            "projects": [
                {"id": "a", "name": "GB_JT", "current": False},
                {"id": "b", "name": "TCP", "current": True},
            ]
        }

    async def search(self, project_id, query, top_k=5):
        self.search_calls.append((project_id, query, top_k))
        return {
            "results": [
                {
                    "title": "TCP",
                    "path": "wiki/entities/tcp.md",
                    "snippet": "Transmission Control Protocol",
                }
            ]
        }

    async def chat(self, project_id, message):
        self.chat_calls.append((project_id, message))
        return {
            "message": {"role": "assistant", "content": "LLM Wiki 生成的回答"},
            "references": [
                {
                    "title": "TCP",
                    "path": "wiki/entities/tcp.md",
                    "kind": "wiki",
                }
            ],
        }

    async def read_page(self, project_id, path):
        self.read_calls.append((project_id, path))
        return {"path": path, "content": "TCP page body"}

    async def close(self):
        self.closed = True


class FakeRequest:
    def __init__(self, prompt):
        self.prompt = prompt
        self.extra_user_content_parts = []


class FakeEvent:
    unified_msg_origin = "test:PrivateMessage:user"


class FakeContext:
    def __init__(self):
        self.activated = []
        self.deactivated = []
        self.provider_id = "provider"
        self.summary = "AstrBot 生成的摘要"
        self.llm_calls = []

    def activate_llm_tool(self, name):
        self.activated.append(name)
        return True

    def deactivate_llm_tool(self, name):
        self.deactivated.append(name)
        return True

    async def get_current_chat_provider_id(self, umo):
        return self.provider_id

    async def llm_generate(self, *, chat_provider_id, prompt):
        self.llm_calls.append((chat_provider_id, prompt))
        return types.SimpleNamespace(completion_text=self.summary)


class PluginCommandTests(unittest.IsolatedAsyncioTestCase):
    def make_plugin(self, config=None):
        plugin = LlmWikiPlugin(object(), config or {})
        plugin.client = FakeClient()
        return plugin

    def test_configuration_uses_safe_defaults_and_bounds(self):
        plugin = LlmWikiPlugin(
            object(),
            {
                "base_url": " http://wiki.local/ ",
                "project_id": " project-a ",
                "top_k": 999,
                "request_timeout": 0,
                "summary_threshold": 10,
            },
        )

        self.assertEqual(plugin.base_url, "http://wiki.local")
        self.assertEqual(plugin.project_id, "project-a")
        self.assertEqual(plugin.top_k, 20)
        self.assertEqual(plugin.request_timeout, 1)
        self.assertTrue(plugin.chat_enabled)
        self.assertEqual(plugin.summary_threshold, 100)

    def test_default_base_url_does_not_expose_deployment_details(self):
        plugin = LlmWikiPlugin(object(), {})

        self.assertEqual(plugin.base_url, "http://127.0.0.1:19828")

    async def test_status_text_reports_server_and_project(self):
        plugin = self.make_plugin({"project_id": "fixed-project"})

        text = await plugin._status_text()

        self.assertIn("0.6.11", text)
        self.assertIn("running", text)
        self.assertIn("fixed-project", text)

    async def test_projects_text_marks_current_project(self):
        plugin = self.make_plugin()

        text = await plugin._projects_text()

        self.assertIn("GB_JT (a)", text)
        self.assertIn("TCP (b) [当前]", text)

    async def test_search_text_uses_fixed_project_and_shows_source(self):
        plugin = self.make_plugin({"project_id": "fixed-project", "top_k": 3})

        text = await plugin._search_text("TCP")

        self.assertIn("wiki/entities/tcp.md", text)
        self.assertEqual(plugin.client.search_calls, [("fixed-project", "TCP", 3)])

    async def test_manual_search_prefers_llm_wiki_chat_with_references(self):
        context = FakeContext()
        plugin = LlmWikiPlugin(context, {"project_id": "fixed-project"})
        plugin.client = FakeClient()

        text = await plugin._manual_search_text(FakeEvent(), "TCP")

        self.assertIn("LLM Wiki 生成的回答", text)
        self.assertIn("wiki/entities/tcp.md", text)
        self.assertEqual(plugin.client.chat_calls, [("fixed-project", "TCP")])
        self.assertEqual(plugin.client.search_calls, [])
        self.assertEqual(context.llm_calls, [])

    async def test_manual_search_summarizes_long_fallback_with_astrbot_llm(self):
        context = FakeContext()
        plugin = LlmWikiPlugin(
            context,
            {"project_id": "fixed-project", "summary_threshold": 100},
        )
        plugin.client = FakeClient()

        async def fail_chat(project_id, message):
            raise LlmWikiError("chat unavailable")

        async def long_search(project_id, query, top_k=5):
            return {
                "results": [
                    {
                        "title": "TCP",
                        "path": "wiki/entities/tcp.md",
                        "snippet": "x" * 300,
                    }
                ]
            }

        plugin.client.chat = fail_chat
        plugin.client.search = long_search

        text = await plugin._manual_search_text(FakeEvent(), "TCP")

        self.assertIn("AstrBot 生成的摘要", text)
        self.assertIn("wiki/entities/tcp.md", text)
        self.assertEqual(len(context.llm_calls), 1)
        self.assertIn("x" * 100, context.llm_calls[0][1])

    async def test_manual_search_returns_raw_when_astrbot_model_is_unavailable(self):
        context = FakeContext()
        context.provider_id = ""
        plugin = LlmWikiPlugin(context, {"summary_threshold": 100})
        plugin.client = FakeClient()

        async def fail_chat(project_id, message):
            raise LlmWikiError("chat unavailable")

        async def long_search(project_id, query, top_k=5):
            return {
                "results": [
                    {
                        "title": "TCP",
                        "path": "wiki/entities/tcp.md",
                        "snippet": "raw content " * 30,
                    }
                ]
            }

        plugin.client.chat = fail_chat
        plugin.client.search = long_search

        text = await plugin._manual_search_text(FakeEvent(), "TCP")

        self.assertIn("raw content", text)
        self.assertIn("wiki/entities/tcp.md", text)
        self.assertEqual(context.llm_calls, [])

    async def test_manual_search_returns_raw_when_astrbot_summary_fails(self):
        context = FakeContext()
        plugin = LlmWikiPlugin(context, {"summary_threshold": 100})
        plugin.client = FakeClient()

        async def fail_chat(project_id, message):
            raise LlmWikiError("chat unavailable")

        async def long_search(project_id, query, top_k=5):
            return {
                "results": [
                    {
                        "title": "TCP",
                        "path": "wiki/entities/tcp.md",
                        "snippet": "raw content " * 30,
                    }
                ]
            }

        async def fail_generate(**kwargs):
            raise RuntimeError("provider unavailable")

        plugin.client.chat = fail_chat
        plugin.client.search = long_search
        context.llm_generate = fail_generate

        text = await plugin._manual_search_text(FakeEvent(), "TCP")

        self.assertIn("raw content", text)
        self.assertIn("wiki/entities/tcp.md", text)

    async def test_manual_search_checks_full_length_but_limits_raw_fallback(self):
        context = FakeContext()
        plugin = LlmWikiPlugin(
            context,
            {"summary_threshold": 200, "max_page_chars": 100},
        )
        plugin.client = FakeClient()

        async def fail_chat(project_id, message):
            raise LlmWikiError("chat unavailable")

        long_snippet = "complete raw content " * 30

        async def long_search(project_id, query, top_k=5):
            return {
                "results": [
                    {
                        "title": "TCP",
                        "path": "wiki/entities/tcp.md",
                        "snippet": long_snippet,
                    }
                ]
            }

        async def fail_generate(**kwargs):
            context.llm_calls.append((kwargs["chat_provider_id"], kwargs["prompt"]))
            raise RuntimeError("provider unavailable")

        plugin.client.chat = fail_chat
        plugin.client.search = long_search
        context.llm_generate = fail_generate

        text = await plugin._manual_search_text(FakeEvent(), "TCP")

        self.assertEqual(len(context.llm_calls), 1)
        self.assertLessEqual(len(text), 100)
        self.assertTrue(text.endswith("..."))

    async def test_manual_search_empty_chat_content_falls_back_to_search(self):
        plugin = self.make_plugin({"summary_threshold": 1000})

        async def empty_chat(project_id, message):
            return {"message": {"role": "assistant", "content": ""}}

        plugin.client.chat = empty_chat

        text = await plugin._manual_search_text(FakeEvent(), "TCP")

        self.assertIn("Transmission Control Protocol", text)
        self.assertEqual(len(plugin.client.search_calls), 1)

    async def test_manual_search_tolerates_null_chat_references(self):
        plugin = self.make_plugin()

        async def chat_without_references(project_id, message):
            return {
                "message": {"role": "assistant", "content": "Chat answer"},
                "references": None,
            }

        plugin.client.chat = chat_without_references

        text = await plugin._manual_search_text(FakeEvent(), "TCP")

        self.assertEqual(text, "Chat answer")

    async def test_manual_search_limits_chat_answer_length(self):
        plugin = self.make_plugin({"max_page_chars": 100})

        async def long_chat(project_id, message):
            return {
                "message": {"role": "assistant", "content": "c" * 300},
                "references": [],
            }

        plugin.client.chat = long_chat

        text = await plugin._manual_search_text(FakeEvent(), "TCP")

        self.assertLessEqual(len(text), 100)
        self.assertTrue(text.endswith("..."))

    async def test_manual_search_limits_astrbot_summary_length(self):
        context = FakeContext()
        context.summary = "s" * 300
        plugin = LlmWikiPlugin(
            context,
            {"summary_threshold": 100, "max_page_chars": 100},
        )
        plugin.client = FakeClient()

        async def fail_chat(project_id, message):
            raise LlmWikiError("chat unavailable")

        async def long_search(project_id, query, top_k=5):
            return {
                "results": [
                    {
                        "title": "TCP",
                        "path": "wiki/entities/tcp.md",
                        "snippet": "x" * 300,
                    }
                ]
            }

        plugin.client.chat = fail_chat
        plugin.client.search = long_search

        text = await plugin._manual_search_text(FakeEvent(), "TCP")

        self.assertLessEqual(len(text), 100)
        self.assertTrue(text.endswith("..."))

    async def test_manual_search_skips_astrbot_summary_for_short_fallback(self):
        context = FakeContext()
        plugin = LlmWikiPlugin(context, {"summary_threshold": 1000})
        plugin.client = FakeClient()

        async def fail_chat(project_id, message):
            raise LlmWikiError("chat unavailable")

        plugin.client.chat = fail_chat

        text = await plugin._manual_search_text(FakeEvent(), "TCP")

        self.assertIn("Transmission Control Protocol", text)
        self.assertEqual(context.llm_calls, [])

    async def test_manual_search_skips_chat_when_disabled(self):
        plugin = self.make_plugin({"chat_enabled": False, "summary_threshold": 1000})

        text = await plugin._manual_search_text(FakeEvent(), "TCP")

        self.assertEqual(plugin.client.chat_calls, [])
        self.assertEqual(len(plugin.client.search_calls), 1)
        self.assertIn("Transmission Control Protocol", text)

    async def test_manual_search_returns_limited_raw_when_summary_is_empty(self):
        context = FakeContext()
        context.summary = ""
        plugin = LlmWikiPlugin(
            context,
            {"summary_threshold": 100, "max_page_chars": 100},
        )
        plugin.client = FakeClient()

        async def fail_chat(project_id, message):
            raise LlmWikiError("chat unavailable")

        async def long_search(project_id, query, top_k=5):
            return {
                "results": [
                    {
                        "title": "TCP",
                        "path": "wiki/entities/tcp.md",
                        "snippet": "raw content " * 30,
                    }
                ]
            }

        plugin.client.chat = fail_chat
        plugin.client.search = long_search

        text = await plugin._manual_search_text(FakeEvent(), "TCP")

        self.assertLessEqual(len(text), 100)
        self.assertIn("raw content", text)
        self.assertTrue(text.endswith("..."))

    async def test_read_text_validates_path_and_formats_page(self):
        plugin = self.make_plugin({"project_id": "fixed-project"})

        text = await plugin._read_text("/wiki/entities/tcp.md")

        self.assertIn("TCP page body", text)
        self.assertEqual(
            plugin.client.read_calls,
            [("fixed-project", "wiki/entities/tcp.md")],
        )

    async def test_command_helpers_return_api_error_instead_of_raising(self):
        plugin = self.make_plugin()

        async def fail():
            raise LlmWikiError("Cannot connect to LLM Wiki")

        plugin.client.health = fail

        text = await plugin._status_text()

        self.assertEqual(text, "LLM Wiki 错误: Cannot connect to LLM Wiki")

    async def test_terminate_closes_client(self):
        plugin = self.make_plugin()

        await plugin.terminate()

        self.assertTrue(plugin.client.closed)

    async def test_auto_retrieval_skips_disabled_empty_command_and_short_prompts(self):
        cases = [
            ({"auto_retrieval": False}, "TCP congestion control"),
            ({}, ""),
            ({}, "/wiki search TCP"),
            ({}, "hi"),
        ]
        for config, prompt in cases:
            with self.subTest(config=config, prompt=prompt):
                plugin = self.make_plugin(config)
                request = FakeRequest(prompt)

                await plugin.on_llm_request(object(), request)

                self.assertEqual(request.extra_user_content_parts, [])
                self.assertEqual(plugin.client.search_calls, [])

    async def test_auto_retrieval_appends_temporary_bounded_context(self):
        plugin = self.make_plugin(
            {
                "project_id": "fixed-project",
                "top_k": 3,
                "max_context_chars": 100,
            }
        )
        request = FakeRequest("TCP congestion control")

        await plugin.on_llm_request(object(), request)

        self.assertEqual(
            plugin.client.search_calls,
            [("fixed-project", "TCP congestion control", 3)],
        )
        self.assertEqual(len(request.extra_user_content_parts), 1)
        part = request.extra_user_content_parts[0]
        self.assertTrue(part.temporary)
        self.assertIn("<llm_wiki_context>", part.text)
        self.assertIn("Transmission Control Protocol", part.text)
        self.assertNotIn("wiki/entities/tcp.md", part.text)
        self.assertLessEqual(len(part.text), 100)

    async def test_auto_retrieval_does_not_append_empty_results(self):
        plugin = self.make_plugin()

        async def empty_search(project_id, query, top_k=5):
            return {"results": []}

        plugin.client.search = empty_search
        request = FakeRequest("unmatched knowledge question")

        await plugin.on_llm_request(object(), request)

        self.assertEqual(request.extra_user_content_parts, [])

    async def test_auto_retrieval_fails_open_on_api_error(self):
        plugin = self.make_plugin()

        async def fail_search(project_id, query, top_k=5):
            raise LlmWikiError("offline")

        plugin.client.search = fail_search
        request = FakeRequest("TCP congestion control")

        await plugin.on_llm_request(object(), request)

        self.assertEqual(request.extra_user_content_parts, [])

    async def test_tool_helpers_obey_enable_flag_and_show_sources(self):
        disabled = self.make_plugin({"enable_llm_tools": False})
        enabled = self.make_plugin({"enable_llm_tools": True})

        self.assertIn("已禁用", await disabled._tool_search_text("TCP"))
        search_text = await enabled._tool_search_text("TCP")

        self.assertIn("wiki/entities/tcp.md", search_text)

    async def test_tool_read_rejects_path_outside_wiki(self):
        plugin = self.make_plugin()

        text = await plugin._tool_read_text("raw/source.txt")

        self.assertIn("wiki/", text)
        self.assertEqual(plugin.client.read_calls, [])

    async def test_llm_tools_return_text_to_the_model(self):
        plugin = self.make_plugin()

        search_result = await plugin.search_llm_wiki(object(), "TCP")
        read_result = await plugin.read_llm_wiki_page(object(), "wiki/entities/tcp.md")

        self.assertIsInstance(search_result, str)
        self.assertIn("wiki/entities/tcp.md", search_result)
        self.assertIsInstance(read_result, str)
        self.assertIn("TCP page body", read_result)

    def test_search_command_consumes_the_complete_query(self):
        self.assertIs(LlmWikiPlugin.wiki_search.__annotations__["query"], GreedyStr)

    def test_read_command_consumes_paths_with_spaces(self):
        self.assertIs(LlmWikiPlugin.wiki_read.__annotations__["path"], GreedyStr)

    async def test_auto_retrieval_fails_open_on_malformed_results(self):
        plugin = self.make_plugin()

        async def malformed_search(project_id, query, top_k=5):
            return {"results": None}

        plugin.client.search = malformed_search
        request = FakeRequest("TCP congestion control")

        await plugin.on_llm_request(object(), request)

        self.assertEqual(request.extra_user_content_parts, [])

    async def test_auto_retrieval_fails_open_on_malformed_result_item(self):
        plugin = self.make_plugin()

        async def malformed_search(project_id, query, top_k=5):
            return {"results": ["not an object"]}

        plugin.client.search = malformed_search
        request = FakeRequest("TCP congestion control")

        await plugin.on_llm_request(object(), request)

        self.assertEqual(request.extra_user_content_parts, [])

    async def test_initialize_applies_llm_tool_enablement(self):
        enabled_context = FakeContext()
        disabled_context = FakeContext()
        enabled = LlmWikiPlugin(enabled_context, {"enable_llm_tools": True})
        disabled = LlmWikiPlugin(disabled_context, {"enable_llm_tools": False})

        await enabled.initialize()
        await disabled.initialize()

        self.assertEqual(
            enabled_context.activated,
            ["search_llm_wiki", "read_llm_wiki_page"],
        )
        self.assertEqual(
            disabled_context.deactivated,
            ["search_llm_wiki", "read_llm_wiki_page"],
        )


if __name__ == "__main__":
    unittest.main()
