# -*- coding: utf-8 -*-
"""3.0 多 Agent 助手包：LangGraph Supervisor + 业务子 Agent。

架构原则：LLM 只负责理解意图、编排与自然语言交互，
确定性业务逻辑（高德路径/贪心 TSP/OCR 审核/余额补偿）继续复用 2.0 的 service 层，以 Tools 形式暴露给 Agent。
"""