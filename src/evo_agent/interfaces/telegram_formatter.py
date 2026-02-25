"""Преобразование markdown-подобного ответа LLM в телеграм-friendly plain text."""

from __future__ import annotations

import re


_FENCED_CODE_RE = re.compile(r"```(?:[a-zA-Z0-9_+-]+)?\n?(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_BOLD_ALT_RE = re.compile(r"__(.+?)__")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
_TABLE_DIVIDER_RE = re.compile(r"^\s*\|?[\s:-]+\|[\s|:-]*\s*$")
_LIST_RE = re.compile(r"^\s*[-*]\s+")


def normalize_for_telegram(text: str) -> str:
    """Сделать ответ читаемым в Telegram без markdown-артефактов."""
    if not text:
        return text

    result = text.replace("\r\n", "\n").replace("\r", "\n")
    result = result.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    result = result.replace("&nbsp;", " ")
    result = _convert_tables(result)
    result = _normalize_code_blocks(result)
    result = _LINK_RE.sub(r"\1 (\2)", result)
    result = _BOLD_RE.sub(r"\1", result)
    result = _BOLD_ALT_RE.sub(r"\1", result)
    result = _ITALIC_RE.sub(r"\1", result)
    result = _INLINE_CODE_RE.sub(r"\1", result)

    lines: list[str] = []
    for line in result.split("\n"):
        heading = _HEADING_RE.match(line)
        if heading:
            lines.append(heading.group(1).strip())
            continue
        if _LIST_RE.match(line):
            lines.append(_LIST_RE.sub("• ", line))
            continue
        lines.append(line)

    # Схлопываем длинные пустые блоки
    compact = "\n".join(lines)
    compact = re.sub(r"\n{3,}", "\n\n", compact).strip()
    return compact


def _normalize_code_blocks(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        body = match.group(1).strip("\n")
        # plain text для Telegram: без markdown, но читаемо.
        return f"Код:\n{body}"

    return _FENCED_CODE_RE.sub(repl, text)


def _convert_tables(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if "|" not in line:
            out.append(line)
            i += 1
            continue

        # Ищем markdown-таблицу вида header + divider + rows
        if i + 1 >= len(lines) or not _TABLE_DIVIDER_RE.match(lines[i + 1]):
            out.append(line)
            i += 1
            continue

        header = _split_table_row(lines[i])
        i += 2  # пропускаем divider
        rows: list[list[str]] = []
        while i < len(lines) and "|" in lines[i] and lines[i].strip():
            rows.append(_split_table_row(lines[i]))
            i += 1

        out.append("Таблица:")
        for idx_row, row in enumerate(rows, start=1):
            pairs: list[str] = []
            for idx, value in enumerate(row):
                key = header[idx] if idx < len(header) and header[idx] else f"col{idx + 1}"
                pairs.append(f"{key}: {value}")
            out.append(f"• Запись {idx_row}:")
            for pair in pairs:
                out.append(f"  - {pair}")

    return "\n".join(out)


def _split_table_row(line: str) -> list[str]:
    parts = [p.strip() for p in line.strip().strip("|").split("|")]
    return parts

