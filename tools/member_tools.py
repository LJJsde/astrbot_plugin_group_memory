"""提供给大模型的函数工具（Function Tool）。

让大模型在群聊中按需查询 MySQL 里的群成员档案，
从而用真实成员信息调整自己的回复，避免把所有成员信息塞进 prompt。
"""

from __future__ import annotations

from typing import Any

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
        "当对话中需要了解某个群成员的身份、称呼、个性、爱好等信息时使用。"
        "可以通过 QQ 号精确查询，也可以用昵称关键词模糊搜索。"
        "返回的是成员的静态档案，可用于让回复更贴合该成员、更像熟悉他的真人。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "qq": {
                    "type": "integer",
                    "description": "成员的 QQ 号。若已知则优先使用它精确查询。",
                },
                "keyword": {
                    "type": "string",
                    "description": "昵称或备注关键词，用于模糊搜索成员档案。",
                },
            },
            "required": [],
        }
    )

    async def call(
        self, context: ContextWrapper[AstrAgentContext], **kwargs
    ) -> ToolExecResult:
        # 从模块级单例获取数据库实例（插件初始化时注入）。
        from ..db import get_current_db

        db = get_current_db()
        if db is None:
            return "错误：群成员记忆数据库尚未初始化。"

        qq = kwargs.get("qq")
        keyword = kwargs.get("keyword")

        try:
            if qq is not None:
                member = await db.get_by_qq(int(qq))
                if member is None:
                    return f"未找到 QQ 号为 {qq} 的成员档案。"
                return self._format_member(member)

            if keyword:
                members = await db.search_members(str(keyword), limit=10)
                if not members:
                    return f"未找到与“{keyword}”匹配的成员档案。"
                return self._format_member_list(members)

            return "请提供 qq 号或 keyword 关键词以查询成员档案。"
        except Exception as e:  # noqa: BLE001
            logger.exception("query_group_member 查询失败")
            return f"查询群成员档案时出错：{e}"

    @staticmethod
    def _format_member(member: dict[str, Any]) -> str:
        lines = [
            f"QQ: {member.get('qq')}",
            f"昵称: {member.get('nickname') or '（未填）'}",
            f"群名片: {member.get('card_name') or '（未填）'}",
            f"职业: {member.get('occupation') or '（未填）'}",
            f"地区: {member.get('location') or '（未填）'}",
            f"爱好: {member.get('hobby') or '（未填）'}",
            f"备注: {member.get('remark') or '（未填）'}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _format_member_list(members: list[dict[str, Any]]) -> str:
        if len(members) == 1:
            return QueryGroupMemberTool._format_member(members[0])
        lines = [f"找到 {len(members)} 个匹配的成员档案：", ""]
        for m in members:
            lines.append(
                f"- QQ {m.get('qq')} | {m.get('nickname') or '（未知昵称）'} "
                f"| 群名片: {m.get('card_name') or '（未填）'}"
            )
        return "\n".join(lines)
