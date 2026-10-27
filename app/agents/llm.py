# -*- coding: utf-8 -*-
"""模型工厂：统一封装 MiniMax（等 OpenAI 兼容端点）为 LangChain ChatModel。"""
from __future__ import annotations

from langchain_openai import ChatOpenAI

from ..config import settings


def get_llm(temperature: float = 0.1) -> ChatOpenAI:
    """返回绑定 MiniMax 的 ChatModel。

    工具调用/编排场景用低温度（默认 0.1）保证稳定；闲聊场景可调用方覆盖。
    max_tokens 给足（MiniMax-M3 会先输出 <think> 思考链，额度太小会把回答截断）。
    """
    return ChatOpenAI(
        model=settings.minimax_model,
        base_url=settings.minimax_base_url,
        api_key=settings.minimax_api_key,
        temperature=temperature,
        max_tokens=settings.minimax_max_tokens,
    )