"""astrbot_plugin_group_memory 插件入口。

功能：让大模型按需查询 MySQL 中的群成员档案（member_profile 表），
避免把所有成员信息塞进 prompt。提供 function-calling 工具 + WebUI 管理页。
"""

from __future__ import annotations

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api.web import error_response, json_response, request

from .db import GroupMemoryDB, get_current_db, set_current_db
from .tools import QueryGroupMemberTool

PLUGIN_NAME = "astrbot_plugin_group_memory"


class GroupMemoryPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or AstrBotConfig({})
        self.db: GroupMemoryDB | None = None

    async def initialize(self) -> None:
        """实例化后自动调用：初始化数据库并注册工具与 Web API。"""
        await self._init_db()
        self.context.add_llm_tools(QueryGroupMemberTool())
        self._register_web_api()
        logger.info(f"[{PLUGIN_NAME}] 初始化完成，已注册工具 query_group_member。")

    async def _init_db(self) -> None:
        host = self.config.get("db_host", "mysql")
        port = int(self.config.get("db_port", 3306))
        user = self.config.get("db_user", "root")
        password = self.config.get("db_password", "")
        db_name = self.config.get("db_name", "group_memory")

        try:
            self.db = GroupMemoryDB(host, port, user, password, db_name)
            await self.db.init()
            set_current_db(self.db)
            logger.info(
                f"[{PLUGIN_NAME}] 已连接 MySQL {host}:{port}/{db_name} "
                "并完成建库建表。"
            )
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[{PLUGIN_NAME}] 初始化数据库失败：{e}")
            self.db = None
            set_current_db(None)

    # ---------------- WebUI 管理页 API ----------------

    def _register_web_api(self) -> None:
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/members", self._list_members, ["GET"], "列出成员档案"
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/members/search",
            self._search_members,
            ["GET"],
            "搜索成员档案",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/members/get",
            self._get_member,
            ["GET"],
            "按 QQ 精确查询单个成员档案",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/members/save",
            self._save_member,
            ["POST"],
            "新增或更新成员档案",
        )
        self.context.register_web_api(
            f"/{PLUGIN_NAME}/members/delete",
            self._delete_member,
            ["POST"],
            "删除成员档案",
        )

    async def _list_members(self):
        if not self.db:
            return error_response("数据库未初始化", status_code=500)
        limit = request.query.get("limit", 100, type=int)
        members = await self.db.list_all(limit=limit)
        return json_response({"members": members})

    async def _search_members(self):
        if not self.db:
            return error_response("数据库未初始化", status_code=500)
        keyword = request.query.get("keyword", "")
        if not keyword:
            return error_response("keyword 不能为空", status_code=400)
        members = await self.db.search_members(keyword)
        return json_response({"members": members})

    async def _get_member(self):
        if not self.db:
            return error_response("数据库未初始化", status_code=500)
        qq = request.query.get("qq", "")
        if not qq:
            return error_response("qq 不能为空", status_code=400)
        try:
            member = await self.db.get_by_qq(int(qq))
        except ValueError:
            return error_response("qq 必须是数字", status_code=400)
        if member is None:
            return error_response("未找到该成员", status_code=404)
        return json_response({"member": member})

    async def _save_member(self):
        if not self.db:
            return error_response("数据库未初始化", status_code=500)
        payload = await request.json(default={})
        qq = payload.get("qq")
        if qq is None:
            return error_response("缺少 qq 字段", status_code=400)
        try:
            member = await self.db.upsert(payload)
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[{PLUGIN_NAME}] 保存成员失败")
            return error_response(f"保存失败：{e}", status_code=500)
        return json_response({"member": member})

    async def _delete_member(self):
        if not self.db:
            return error_response("数据库未初始化", status_code=500)
        payload = await request.json(default={})
        qq = payload.get("qq")
        if qq is None:
            return error_response("缺少 qq 字段", status_code=400)
        ok = await self.db.delete(int(qq))
        if not ok:
            return error_response("未找到该成员", status_code=404)
        return json_response({"deleted": True})

    # ---------------- 测试指令，仅测试数据库连通 ----------------

    @filter.command("gm_show")
    async def gm_show(self, event: AstrMessageEvent, qq: str = ""):
        """测试：查看成员档案。用法 /gm_show <qq号或自然语言查询意图>"""
        if not self.db:
            yield event.plain_result("数据库未初始化，请检查插件配置。")
            return
        if not qq.strip():
            yield event.plain_result("用法：/gm_show <qq号或查询意图>")
            return
        result = await self.db.query(qq.strip())
        import json as _json

        yield event.plain_result(_json.dumps(result, ensure_ascii=False, indent=2))

    async def terminate(self) -> None:
        """插件卸载/停用时调用。"""
        if self.db:
            await self.db.close()
            self.db = None
        set_current_db(None)
        logger.info(f"[{PLUGIN_NAME}] 已清理数据库连接。")
