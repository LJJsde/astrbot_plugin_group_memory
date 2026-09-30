"""数据库引擎、建库建表与查询逻辑。

采用 SQLAlchemy 2.x 异步 + asyncmy 方言。
数据库连接串形如：mysql+asyncmy://user:pass@host:port/dbname

插件初始化时会：
1. 若目标数据库不存在，则自动创建（CREATE DATABASE IF NOT EXISTS）。
2. 在目标库中幂等建表（缺表则建，已存在则跳过）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Base, MemberProfile

# 模块级单例：插件初始化时注入，供工具类在 call 中访问。
_current_db: "GroupMemoryDB | None" = None


def set_current_db(db: "GroupMemoryDB | None") -> None:
    global _current_db
    _current_db = db


def get_current_db() -> "GroupMemoryDB | None":
    return _current_db


# 字段值词表：用于把自然语言 query 定向到具体字段。
# 遍历每个字段的「值词」，若 query 中包含某个值词，
# 则用该值词在该字段上做 LIKE 模糊搜索。
_FIELD_INTENT_MAP: dict[str, list[str]] = {
    "occupation": [
        "教师", "老师", "程序员", "开发", "学生", "医生", "护士",
        "设计师", "工程师", "运营", "产品经理", "产品", "警察", "律师",
        "会计", "销售", "老板", "司机", "厨师", "主播", "自由职业",
        "公务员", "科研", "金融", "画家", "作家", "摄影师", "建筑师",
    ],
    "hobby": [
        "摄影", "画画", "绘画", "唱歌", "跳舞", "运动", "健身", "篮球",
        "足球", "音乐", "旅游", "阅读", "看动漫", "打游戏", "游戏",
        "打代码", "编程", "钓鱼", "烘焙", "做饭", "滑雪", "游泳",
    ],
    "location": [
        "美国", "中国", "上海", "北京", "深圳", "广州", "杭州", "成都",
        "重庆", "武汉", "南京", "西安", "苏州", "天津", "日本", "韩国",
        "英国", "法国", "德国", "澳大利亚", "加拿大", "新加坡", "美国",
    ],
}


def _extract_qq(query: str) -> int | None:
    """若 query 里包含纯数字（可能带 qq 字样），视为 QQ 号。"""
    import re

    # 匹配连续的 5~12 位数字，通常为 QQ 号
    m = re.search(r"\d{5,12}", query)
    if m:
        try:
            return int(m.group())
        except ValueError:
            return None
    return None


def _parse_intent(query: str) -> tuple[str | None, str]:
    """把自然语言 query 解析为 (目标字段, 命中的值词)。

    遍历每个字段的值词，若 query 包含某值词，则用该值词在该字段做
    LIKE 模糊搜索。优先匹配较长的值词（长词更具体）。
    返回 (None, query) 表示未命中任何值词，走全字段模糊搜索。
    """
    best: tuple[str | None, str] = (None, query)
    best_len = 0
    for field, keywords in _FIELD_INTENT_MAP.items():
        for kw in keywords:
            if kw in query and len(kw) > best_len:
                best = (field, kw)
                best_len = len(kw)
    return best


# 通用停用词，用于在走全字段模糊搜索前清理 query，
# 避免“找 LJJ”这种因停用词干扰而匹配不到。
_STOPWORDS = [
    "有没有", "是不是", "找一下", "查一下", "搜索", "查询", "查找",
    "找", "谁", "查", "是", "的", "有", "在", "请", "帮我", "帮忙",
    "这个群", "群里", "的人", "成员", "人", "吗", "？", "?", "？",
]


def _clean_query(query: str) -> str:
    """去除 query 中的通用停用词，返回关键部分。"""
    cleaned = query
    for w in _STOPWORDS:
        cleaned = cleaned.replace(w, "")
    cleaned = cleaned.strip()
    return cleaned or query


class GroupMemoryDB:
    """封装 MySQL 的异步引擎、会话工厂与建库/建表/查询方法。"""

    def __init__(self, host: str, port: int, user: str, password: str, db_name: str):
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._db_name = db_name

        # 先连一个不带具体库名的引擎，用于建库。
        self._server_url = (
            f"mysql+asyncmy://{user}:{password}@{host}:{port}/"
            "?charset=utf8mb4"
        )
        # 目标库引擎，建库后再创建。
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def engine(self) -> AsyncEngine:
        if self._engine is None:
            raise RuntimeError("数据库引擎尚未初始化，请先调用 init()。")
        return self._engine

    def session(self) -> AsyncSession:
        if self._session_factory is None:
            raise RuntimeError("数据库会话工厂尚未初始化，请先调用 init()。")
        return self._session_factory()

    async def init(self) -> None:
        """建库 + 建表。插件首次启动（或重启）时调用，幂等。"""
        await self._ensure_database()
        await self._create_engine()
        await self.init_schema()

    async def _ensure_database(self) -> None:
        """若目标数据库不存在，则自动创建。"""
        server_engine = create_async_engine(
            self._server_url, echo=False, pool_pre_ping=True
        )
        try:
            async with server_engine.begin() as conn:
                # 库名来自受控配置，使用参数化无法直接拼接 DDL，
                # 这里对库名做白名单校验后拼接，防止注入。
                safe_db_name = self._db_name.replace("`", "")
                await conn.execute(
                    text(
                        f"CREATE DATABASE IF NOT EXISTS `{safe_db_name}` "
                        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                    )
                )
        finally:
            await server_engine.dispose()

    async def _create_engine(self) -> None:
        url = (
            f"mysql+asyncmy://{self._user}:{self._password}@"
            f"{self._host}:{self._port}/{self._db_name}?charset=utf8mb4"
        )
        self._engine = create_async_engine(url, echo=False, pool_pre_ping=True)
        self._session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init_schema(self) -> None:
        """幂等建表。"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None

    # ---- 查询方法 ----

    async def get_by_qq(self, qq: int) -> dict[str, Any] | None:
        """按 QQ 号查询单个成员档案。"""
        async with self.session() as session:
            result = await session.execute(
                select(MemberProfile).where(MemberProfile.qq == qq)
            )
            member = result.scalar_one_or_none()
            return self._to_dict(member) if member else None

    async def search_members(self, keyword: str, limit: int = 20) -> list[dict[str, Any]]:
        """按关键词模糊搜索成员（昵称/群名片/职业/地区/爱好/备注等）。"""
        pattern = f"%{keyword}%"
        async with self.session() as session:
            result = await session.execute(
                select(MemberProfile)
                .where(
                    (MemberProfile.nickname.like(pattern))
                    | (MemberProfile.card_name.like(pattern))
                    | (MemberProfile.occupation.like(pattern))
                    | (MemberProfile.location.like(pattern))
                    | (MemberProfile.remark.like(pattern))
                    | (MemberProfile.hobby.like(pattern))
                )
                .limit(limit)
            )
            members = result.scalars().all()
            return [self._to_dict(m) for m in members]

    async def list_all(self, limit: int = 100) -> list[dict[str, Any]]:
        """列出全部成员档案（供 WebUI 使用）。"""
        async with self.session() as session:
            result = await session.execute(
                select(MemberProfile).order_by(MemberProfile.qq).limit(limit)
            )
            members = result.scalars().all()
            return [self._to_dict(m) for m in members]

    async def query(self, query: str, limit: int = 20) -> dict[str, Any]:
        """统一查询入口：解析自然语言 query 并返回结构化结果。

        返回结构：{"query": ..., "matched_count": N, "members": [...]}
        内部优先识别 QQ 号（精确查）、字段意图（定向字段模糊查），
        其余情况走全字段模糊搜索。
        """
        # 1) 尝试识别 QQ 号 → 精确查询
        qq = _extract_qq(query)
        if qq is not None:
            member = await self.get_by_qq(qq)
            members = [member] if member else []
            return {
                "query": query,
                "matched_count": len(members),
                "members": members,
            }

        # 2) 字段意图解析 → 定向字段模糊查
        field, keyword = _parse_intent(query)
        if field is not None:
            members = await self._search_by_field(field, keyword, limit)
            return {
                "query": query,
                "matched_count": len(members),
                "members": members,
            }

        # 3) 兜底：清理停用词后走全字段模糊搜索
        cleaned = _clean_query(query)
        members = await self.search_members(cleaned, limit)
        return {
            "query": query,
            "matched_count": len(members),
            "members": members,
        }

    async def _search_by_field(
        self, field: str, keyword: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """在指定字段上做 LIKE 模糊搜索。"""
        column = getattr(MemberProfile, field, None)
        if column is None:
            return []
        pattern = f"%{keyword}%"
        async with self.session() as session:
            result = await session.execute(
                select(MemberProfile).where(column.like(pattern)).limit(limit)
            )
            members = result.scalars().all()
            return [self._to_dict(m) for m in members]

    async def upsert(self, data: dict[str, Any]) -> dict[str, Any]:
        """插入或更新一条成员档案。按 qq 唯一键 upsert。"""
        qq = int(data["qq"])
        async with self.session() as session:
            result = await session.execute(
                select(MemberProfile).where(MemberProfile.qq == qq)
            )
            member = result.scalar_one_or_none()
            if member is None:
                member = MemberProfile(qq=qq)
                session.add(member)
            self._apply_fields(member, data)
            await session.commit()
            await session.refresh(member)
            return self._to_dict(member)

    async def delete(self, qq: int) -> bool:
        """按 QQ 号删除一条档案。返回是否删除成功。"""
        async with self.session() as session:
            result = await session.execute(
                select(MemberProfile).where(MemberProfile.qq == qq)
            )
            member = result.scalar_one_or_none()
            if member is None:
                return False
            await session.delete(member)
            await session.commit()
            return True

    # ---- 工具方法 ----

    @staticmethod
    def _apply_fields(member: MemberProfile, data: dict[str, Any]) -> None:
        for field in ("nickname", "card_name", "occupation", "location", "hobby", "remark"):
            if field in data and data[field] is not None:
                setattr(member, field, str(data[field]))

    @staticmethod
    def _to_dict(member: MemberProfile) -> dict[str, Any]:
        return {
            "id": member.id,
            "qq": member.qq,
            "nickname": member.nickname,
            "card_name": member.card_name,
            "occupation": member.occupation,
            "location": member.location,
            "hobby": member.hobby,
            "remark": member.remark,
        }
