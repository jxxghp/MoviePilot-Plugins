"""PT 数据统计插件专属数据库访问层。"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from sqlalchemy import delete, select, tuple_

from .core import as_text, compute_daily_delta
from .models import PTSiteHourlySnapshot


class SnapshotRepository:
    """查询 MP 日级快照，并在插件本地库读写小时快照。"""

    _DAILY_DEFAULTS = {
        "site_id": None,
        "domain": "",
        "site_name": "",
        "is_active": False,
        "username": "",
        "userid": "",
        "join_at": "",
        "user_level": "",
        "upload": 0,
        "download": 0,
        "ratio": None,
        "bonus": None,
        "seeding": 0,
        "seeding_size": 0,
        "leeching": 0,
        "leeching_size": 0,
        "updated_day": "",
        "updated_time": "",
        "err_msg": "",
        "source_updated_at": "",
    }

    def __init__(
        self,
        database_handle,
        daily_snapshots: Iterable[dict[str, Any]] | None = None,
    ) -> None:
        self._database = database_handle
        self._daily_snapshots = [
            {**self._DAILY_DEFAULTS, **item} for item in (daily_snapshots or [])
        ]

    def count(self) -> int:
        """返回当前日级数据源中的快照数量。"""

        return len(self._daily_snapshots)

    def upsert(self, snapshots: Iterable[dict[str, Any]]) -> int:
        """更新日级数据视图；仅供隔离测试和兼容调用使用。"""

        items = [item for item in snapshots if item.get("domain") and item.get("updated_day")]
        if not items:
            return 0
        by_key = {
            (str(item["domain"]), str(item["updated_day"])): item
            for item in self._daily_snapshots
        }
        for item in items:
            key = (str(item["domain"]), str(item["updated_day"]))
            by_key[key] = {
                **self._DAILY_DEFAULTS,
                **by_key.get(key, {}),
                **item,
            }
        self._daily_snapshots = list(by_key.values())
        return len(items)

    def capture_hourly(
        self,
        snapshots: Iterable[dict[str, Any]],
        *,
        captured_at: str | None = None,
    ) -> int:
        """按站点和插件收到刷新结果的时间保存累计值，重复时点不会重复写入。"""

        items = []
        for item in snapshots:
            domain = as_text(item.get("domain"))
            day = as_text(item.get("updated_day"))[:10]
            capture_time = as_text(captured_at or item.get("source_updated_at")).strip()
            if not domain or not day or not capture_time or as_text(item.get("err_msg")).strip():
                continue
            items.append({**item, "domain": domain, "updated_day": day, "captured_at": capture_time})
        if not items:
            return 0

        keys = {(item["domain"], item["captured_at"]) for item in items}
        with self._database.session() as session:
            try:
                existing = set(
                    session.execute(
                        select(PTSiteHourlySnapshot.domain, PTSiteHourlySnapshot.captured_at).where(
                            tuple_(PTSiteHourlySnapshot.domain, PTSiteHourlySnapshot.captured_at).in_(keys)
                        )
                    ).all()
                )
                inserted = 0
                for item in items:
                    key = (item["domain"], item["captured_at"])
                    if key in existing:
                        continue
                    session.add(
                        PTSiteHourlySnapshot(
                            site_id=item.get("site_id"),
                            domain=item["domain"],
                            site_name=as_text(item.get("site_name")),
                            upload=max(int(item.get("upload") or 0), 0),
                            download=max(int(item.get("download") or 0), 0),
                            updated_day=item["updated_day"],
                            updated_time=as_text(item.get("updated_time"))[:16],
                            captured_at=item["captured_at"],
                        )
                    )
                    existing.add(key)
                    inserted += 1
                session.commit()
                return inserted
            except Exception:
                session.rollback()
                raise

    def hourly_for_day(self, day: str, site_id: int | None = None) -> list[dict[str, Any]]:
        """返回指定服务器日期的插件小时快照。"""

        conditions = [PTSiteHourlySnapshot.updated_day == day]
        if site_id is not None:
            conditions.append(PTSiteHourlySnapshot.site_id == site_id)
        statement = (
            select(PTSiteHourlySnapshot)
            .where(*conditions)
            .order_by(PTSiteHourlySnapshot.captured_at, PTSiteHourlySnapshot.domain)
        )
        with self._database.session() as session:
            return [row.to_dict() for row in session.execute(statement).scalars().all()]

    def mark_active_domains(self, active_domains: Iterable[str]) -> None:
        """把站点当前启用状态投影到所有已保存历史行。"""

        domains = {domain for domain in active_domains if domain}
        for item in self._daily_snapshots:
            item["is_active"] = item.get("domain") in domains

    def latest(
        self,
        *,
        active_only: bool = True,
        valid_only: bool = True,
    ) -> list[dict[str, Any]]:
        """返回每个站点最近一条快照，可选择是否排除失败记录。"""

        latest_by_domain: dict[str, dict[str, Any]] = {}
        for item in self._daily_snapshots:
            if active_only and not item.get("is_active"):
                continue
            if valid_only and as_text(item.get("err_msg")).strip():
                continue
            domain = as_text(item.get("domain"))
            current = latest_by_domain.get(domain)
            if current is None or as_text(item.get("updated_day")) > as_text(
                current.get("updated_day")
            ):
                latest_by_domain[domain] = dict(item)
        return sorted(
            latest_by_domain.values(),
            key=lambda item: (-int(item.get("upload") or 0), as_text(item.get("site_name"))),
        )

    def records_for_days(
        self,
        days: Iterable[str],
        *,
        active_only: bool = False,
    ) -> list[dict[str, Any]]:
        """返回指定服务器日期内的成功快照。"""

        day_values = {day for day in days if day}
        if not day_values:
            return []
        return sorted(
            [
                dict(item)
                for item in self._daily_snapshots
                if item.get("updated_day") in day_values
                and not as_text(item.get("err_msg")).strip()
                and (not active_only or item.get("is_active"))
            ],
            key=lambda item: (as_text(item.get("updated_day")), as_text(item.get("site_name"))),
        )

    def previous_successful(
        self,
        latest_rows: Iterable[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """返回每个最新快照之前最近的一条成功每日快照。"""

        latest_days = {
            str(row.get("domain") or ""): str(row.get("updated_day") or "")
            for row in latest_rows
            if row.get("domain") and row.get("updated_day")
        }
        if not latest_days:
            return {}
        previous: dict[str, dict[str, Any]] = {}
        for item in self._daily_snapshots:
            domain = as_text(item.get("domain"))
            day = as_text(item.get("updated_day"))
            if (
                domain not in latest_days
                or day >= latest_days[domain]
                or as_text(item.get("err_msg")).strip()
            ):
                continue
            current = previous.get(domain)
            if current is None or day > as_text(current.get("updated_day")):
                previous[domain] = dict(item)
        return previous

    def history(
        self,
        *,
        start_day: str,
        end_day: str,
        site_ids: Iterable[int] | None = None,
        include_archived: bool = True,
        limit: int | None = 10000,
    ) -> list[dict[str, Any]]:
        """查询历史，并为每行附加严格相邻日增量。"""

        site_id_values = {int(value) for value in (site_ids or ()) if value}
        valid_rows = [
            dict(item)
            for item in self._daily_snapshots
            if start_day <= as_text(item.get("updated_day")) <= end_day
            and not as_text(item.get("err_msg")).strip()
            and (not site_id_values or item.get("site_id") in site_id_values)
            and (include_archived or item.get("is_active"))
        ]
        valid_rows.sort(
            key=lambda item: (as_text(item.get("updated_day")), as_text(item.get("domain"))),
            reverse=True,
        )
        if limit is not None:
            valid_rows = valid_rows[: max(1, min(limit, 50000))]
        all_valid = {
            (as_text(item.get("domain")), as_text(item.get("updated_day"))): item
            for item in self._daily_snapshots
            if not as_text(item.get("err_msg")).strip()
        }
        results = []
        for row in valid_rows:
            try:
                previous_day = (
                    date.fromisoformat(row["updated_day"]) - timedelta(days=1)
                ).isoformat()
            except (KeyError, ValueError):
                previous_day = ""
            delta = compute_daily_delta(
                row,
                all_valid.get((as_text(row.get("domain")), previous_day)),
            )
            results.append({**row, **delta})
        results.sort(
            key=lambda item: (item["updated_day"], item["site_name"]),
            reverse=True,
        )
        return results

    def cleanup(self, *, retention_days: int, server_day: str) -> int:
        """删除超过保留期的插件小时快照。"""

        if retention_days <= 0:
            return 0
        try:
            cutoff = (date.fromisoformat(server_day) - timedelta(days=retention_days - 1)).isoformat()
        except ValueError:
            return 0
        with self._database.session() as session:
            try:
                hourly_result = session.execute(
                    delete(PTSiteHourlySnapshot).where(PTSiteHourlySnapshot.updated_day < cutoff)
                )
                session.commit()
                return int(getattr(hourly_result, "rowcount", 0) or 0)
            except Exception:
                session.rollback()
                raise

    def date_bounds(self) -> tuple[str, str]:
        """返回 MP 日级历史的最早和最晚日期。"""

        days = sorted(
            as_text(item.get("updated_day"))
            for item in self._daily_snapshots
            if item.get("updated_day")
        )
        return (days[0], days[-1]) if days else ("", "")
