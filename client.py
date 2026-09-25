import json
from urllib.parse import quote, urlencode

import aiohttp


class LlmWikiError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class LlmWikiClient:
    def __init__(
        self,
        base_url: str,
        token: str = "",
        timeout: int = 15,
        session=None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.timeout = timeout
        self._session = session

    async def close(self) -> None:
        if self._session and not getattr(self._session, "closed", False):
            await self._session.close()

    async def health(self) -> dict:
        return await self._request("GET", "/health", auth=False)

    async def projects(self) -> dict:
        return await self._request("GET", "/projects")

    async def search(self, project_id: str, query: str, top_k: int = 5) -> dict:
        project = quote(project_id, safe="")
        return await self._request(
            "POST",
            f"/projects/{project}/search",
            json_body={
                "query": query,
                "topK": top_k,
                "includeContent": False,
            },
        )

    async def read_page(self, project_id: str, path: str) -> dict:
        project = quote(project_id, safe="")
        query = urlencode({"path": path})
        return await self._request("GET", f"/projects/{project}/files/content?{query}")

    async def chat(self, project_id: str, message: str) -> dict:
        project = quote(project_id, safe="")
        return await self._request(
            "POST",
            f"/projects/{project}/chat",
            json_body={
                "message": message,
                "persistSession": False,
                "tools": {"wiki": True, "web": False, "anytxt": False},
            },
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        auth: bool = True,
        json_body: dict | None = None,
    ) -> dict:
        if self._session is None:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )

        headers = {"Accept": "application/json"}
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        kwargs = {"headers": headers}
        if json_body is not None:
            kwargs["json"] = json_body

        url = f"{self.base_url}/api/v1{path}"
        try:
            async with self._session.request(method, url, **kwargs) as response:
                text = await response.text()
        except (aiohttp.ClientError, OSError, TimeoutError) as exc:
            raise LlmWikiError(f"Cannot connect to LLM Wiki: {exc}") from exc

        try:
            data = json.loads(text) if text else {}
        except json.JSONDecodeError as exc:
            raise LlmWikiError(
                f"LLM Wiki returned invalid JSON (HTTP {response.status}).",
                response.status,
            ) from exc

        if not isinstance(data, dict):
            raise LlmWikiError(
                f"LLM Wiki expected a JSON object response (HTTP {response.status}).",
                response.status,
            )

        if response.status >= 400 or data.get("ok") is False:
            raise self._http_error(response.status, data.get("error"))
        return data

    @staticmethod
    def _http_error(status: int, server_error) -> LlmWikiError:
        detail = server_error if isinstance(server_error, str) else "Request failed"
        if status == 401:
            message = "LLM Wiki rejected the API token; configure a valid token."
        elif status == 503:
            message = f"LLM Wiki is unavailable: {detail}"
        else:
            message = f"LLM Wiki API error {status}: {detail}"
        return LlmWikiError(message, status)
