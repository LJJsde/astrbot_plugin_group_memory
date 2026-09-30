"""提供给大模型的函数工具（Function Tool）。

让大模型在群聊中按需查询 MySQL 里的群成员档案，
从而用真实成员信息调整自己的回复，避免把所有成员信息塞进 prompt。

返回值使用紧凑 JSON，字段明确、便于 LLM 理解。
"""

from __future__ import annotations

import json

from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot import logger
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext


@dataclass
class QueryGroupMemberTool(FunctionTool[AstrAgentContext]):
    name: str = "query_group_member"
    description: str = (
        "查询群聊天成员的档案信息（昵称、群名片、职业、地区、爱好、备注等）。"
        "当对话中需要了解某个群成员的身份、称呼、个性、爱好、职业、地区等信息时使用。"
        "Query 可以是一句自然语言描述，例如“职业是教师的人”、“谁喜欢摄影”、“找 LJJ”。"
        "返回结构化 JSON，可用于让回复更贴合该成员、更像熟悉他的真人。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "自然语言查询意图，例如“职业是教师的人”“谁喜欢摄影”"
                        "“找 QQ 号 123456789 的人”。"
                    ),
                },
            },
            "required": ["query"],
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        # 从模块级单例获取数据库实例（插件初始化时注入）。
        from ..db import get_current_db

        db = get_current_db()
        if db is None:
            return json.dumps(
                {"error": "群成员记忆数据库尚未初始化"},
                ensure_ascii=False,
            )

        query = kwargs.get("query")
        if not query:
            return json.dumps(
                {"error": "缺少 query 参数"},
                ensure_ascii=False,
            )

        try:
            result = await db.query(str(query), limit=10)
            # 紧凑 JSON，保留中文（ensure_ascii=False），无多余空白。
            return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        except Exception as e:  # noqa: BLE001
            logger.exception("query_group_member 查询失败")
            return json.dumps(
                {"error": f"查询群成员档案时出错：{e}"},
                ensure_ascii=False,
            )
