from pathlib import PurePosixPath


def _truncate(text: str, max_chars: int | None) -> str:
    if max_chars is None:
        return text
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return "." * max(0, max_chars)
    return text[: max_chars - 3].rstrip() + "..."


def truncate_text(text: str, max_chars: int) -> str:
    return _truncate(text, max_chars)


def format_search_results(
    results: list[dict], include_sources: bool, max_chars: int | None
) -> str:
    if not results:
        return "未找到相关知识。"

    blocks = []
    for index, result in enumerate(results, 1):
        title = str(result.get("title") or result.get("path") or "未命名页面")
        snippet = " ".join(str(result.get("snippet") or "").split())
        lines = [f"{index}. {title}"]
        if include_sources and result.get("path"):
            lines.append(f"来源: {result['path']}")
        if snippet:
            lines.append(snippet)
        blocks.append("\n".join(lines))
    return _truncate("\n\n".join(blocks), max_chars)


def format_page(path: str, content: str, max_chars: int) -> str:
    return _truncate(f"来源: {path}\n\n{content}", max_chars)


def validate_wiki_path(path: str) -> str:
    normalized = path.strip().lstrip("/")
    pure_path = PurePosixPath(normalized)
    if (
        "\\" in normalized
        or "\x00" in normalized
        or not normalized.startswith("wiki/")
        or normalized == "wiki/"
        or ".." in pure_path.parts
    ):
        raise ValueError("页面路径必须位于 wiki/ 目录下。")
    return normalized
