"""转写版本落库领域服务：把转写结果冻结成带父版本号的版本记录，产出版本记录数据集供字幕包引用与纠错回路消费。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.services.revision_ledger import revision_ledger
from app.store import store


class TranscriptVersionService(BaseModuleService):
    MODULE = "transcript_version"
    ENTITY = "版本记录"
    OPERATION_TERM = "落库"
    LIST_FIELDS = ["版本编号", "关联任务", "版本号", "父版本号", "变更行数", "变更摘要", "生效时间", "被引用次数"]
    REQUIRED_FIELDS = ["版本编号", "关联任务", "版本号"]
    STATUS_ORDER = ["草稿", "过渡中", "已生效", "已废止"]
    ACTION_RULES = {"启动过渡": "过渡中", "生效版本": "已生效", "废止版本": "已废止"}
    NEGATIVE_ACTIONS = ["废止版本"]

    def create_version(
        self, version_id: str, task_id: str, version_no: str,
        parent: str, change_lines: int, summary: str,
    ) -> tuple[dict[str, Any] | None, str]:
        """创建新转写版本。"""
        rows = store.rows(self.MODULE)
        for r in rows:
            if r.get("版本编号") == version_id:
                return None, f"版本编号 {version_id} 已存在"
        entry = {
            "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
            "版本编号": version_id, "关联任务": task_id,
            "版本号": version_no, "父版本号": parent,
            "变更行数": str(change_lines), "变更摘要": summary,
            "生效时间": "-", "被引用次数": "0",
            "status": "草稿", "pending": True, "abnormal": False,
        }
        rows.append(entry)
        return entry, f"版本 {version_id} 已创建"

    def get_effective_version(self, task_id: str) -> dict[str, Any] | None:
        """获取指定任务的当前生效版本。"""
        rows = store.rows(self.MODULE)
        for r in rows:
            if r.get("关联任务") == task_id and r.get("status") == "已生效":
                return r
        return None

    def is_referenced(self, version_id: str) -> bool:
        """检查版本是否被字幕包引用。"""
        rows = store.rows(self.MODULE)
        for r in rows:
            if r.get("版本编号") == version_id:
                return int(r.get("被引用次数", "0")) > 0
        return False

    def increment_ref_count(self, version_id: str) -> tuple[bool, str]:
        """增加版本的被引用次数。"""
        rows = store.rows(self.MODULE)
        for r in rows:
            if r.get("版本编号") == version_id:
                current = int(r.get("被引用次数", "0"))
                r["被引用次数"] = str(current + 1)
                return True, f"版本 {version_id} 引用次数: {current + 1}"
        return False, f"版本 {version_id} 不存在"

    def get_versions_by_task(self, task_id: str) -> list[dict[str, Any]]:
        """获取指定任务的全部版本记录，按版本号排序。"""
        rows = store.rows(self.MODULE)
        vers = [r for r in rows if r.get("关联任务") == task_id]
        vers.sort(key=lambda r: r.get("版本号", "v0"))
        return vers

    def get_revision_ranges(self, version_ref: str) -> dict[str, Any]:
        """按版本查回不可变原文，以及已采用/待处理的原文坐标范围。"""
        return revision_ledger.revision_ranges(version_ref)

    def get_revision_details(self, version_ref: str) -> list[dict[str, Any]]:
        return revision_ledger.revision_ranges(version_ref).get("revision_details", [])

    def get_adopted_and_pending_ranges(self, version_ref: str) -> dict[str, Any]:
        result = revision_ledger.revision_ranges(version_ref)
        return {
            "adopted": result["adopted_ranges"],
            "pending": result["pending_ranges"],
            "已采用范围": result["adopted_ranges"],
            "待处理范围": result["pending_ranges"],
        }
