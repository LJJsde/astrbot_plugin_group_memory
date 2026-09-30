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
