# -*- coding: utf-8 -*-
"""文本工具：剥离推理模型的 <think> 思考块、从噪声文本中提取 JSON 对象。

MiniMax-M3 属于推理型模型，返回的 content 前面会带 <think>...</think> 思考链，
直接展示给用户或直接 json.loads 都会出问题，这里统一做清洗。
"""
from __future__ import annotations

import json
import re

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)
_THINK_OPEN_RE = re.compile(r"<think>.*$", re.S | re.I)


def strip_think(text: str) -> str:
    """去掉 <think>...</think> 思考块；思考块未闭合时截掉其后的内容。"""
    if not text:
        return ""
    cleaned = _THINK_BLOCK_RE.sub("", text)
    cleaned = _THINK_OPEN_RE.sub("", cleaned)
    return cleaned.strip()


def iter_json_objects(text: str):
    """按括号配对扫描文本中所有最外层 {...} 片段并逐个 yield。"""
    if not text:
        return
    depth = 0
    start = -1
    in_str = False
    escape = False
    for i, ch in enumerate(text):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    yield text[start:i + 1]
                    start = -1
    if depth > 0 and start >= 0:
        yield text[start:]


def loads_first_json(text: str):
    """解析文本中第一个合法 JSON 对象；没有则返回 None。"""
    if not text:
        return None
    try:
        data = json.loads(text.strip())
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    for candidate in iter_json_objects(text):
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return None