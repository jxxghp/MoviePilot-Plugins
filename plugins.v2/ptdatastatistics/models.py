"""PT 数据统计插件专属数据库模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class PluginBase(DeclarativeBase):
    """V2 插件本地 SQLite 所使用的声明式模型基类。"""


class PTSiteHourlySnapshot(PluginBase):
    """保存 MP 每次站点刷新后的累计值，用于计算真实小时增量。"""

    __tablename__ = "site_hourly_snapshots"
    __table_args__ = (
        UniqueConstraint("domain", "captured_at", name="uq_ptstats_hourly_domain_time"),
        Index("ix_ptstats_hourly_day_domain", "updated_day", "domain"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    site_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    site_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    upload: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    download: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_day: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    updated_time: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    captured_at: Mapped[str] = mapped_column(String(32), nullable=False)
    copied_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "site_id": self.site_id,
            "domain": self.domain,
            "site_name": self.site_name,
            "upload": int(self.upload or 0),
            "download": int(self.download or 0),
            "updated_day": self.updated_day,
            "updated_time": self.updated_time,
            "source_updated_at": self.captured_at,
            "err_msg": "",
        }
