"""纠错回路回填领域服务：登记转写文本纠错并合入版本触发下游重算，产出纠错单数据集供字幕包重算与版本联动消费。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.services.revision_ledger import parse_coordinates, revision_ledger
from app.store import store


class CorrectionLoopService(BaseModuleService):
    MODULE = "correction_loop"
    ENTITY = "纠错单"
    OPERATION_TERM = "回填"
    LIST_FIELDS = ["纠错编号", "关联版本", "纠错范围毫秒", "原文本", "纠正文本", "纠错来源", "是否触发重算", "纠错时间"]
    REQUIRED_FIELDS = ["纠错编号", "关联版本", "纠错范围毫秒"]
    STATUS_ORDER = ["已登记", "处理中", "已合入", "已拒绝"]
    ACTION_RULES = {"启动处理": "处理中", "合入版本": "已合入", "拒绝纠错": "已拒绝"}
    NEGATIVE_ACTIONS = ["拒绝纠错"]

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        data = dict(values or {})
        version_ref = data.get("关联版本") or data.get("version_id") or data.get("version")
        if not version_ref:
            return None, ["关联版本"]

        full_text = data.get("底稿全文") or data.get("draft_text") or data.get("full_text")
        if full_text:
            revision_ledger.register_document(version_ref, str(full_text))

        # 新文本坐标流程允许不传毫秒范围；用字符坐标补齐通用表的必填展示字段。
        if not str(data.get("纠错范围毫秒") or "").strip():
            start, end, _ = parse_coordinates(data)
            if start is not None and end is not None:
                data["纠错范围毫秒"] = f"char:{start}-{end}"
            else:
                data["纠错范围毫秒"] = data.get("ms_range") or "0-0"

        rows = store.rows(self.MODULE)
        code = str(data.get("纠错编号") or data.get("correction_id") or "").strip()
        if code:
            existing = next((r for r in rows if str(r.get("纠错编号")) == code), None)
            if existing is not None:
                # 重报同一单只更新/确认坐标，不新增第二笔，避免同一插入被重复保留。
                self._store_coordinates(existing, data)
                revision_ledger.mark_row_status(existing, str(existing.get("status") or "已登记"))
                existing["_message"] = f"纠错单 {code} 已存在，重报未重复登记"
                return existing, []

        missing = [
            field for field in self.REQUIRED_FIELDS
            if not str(data.get(field) or "").strip()
        ]
        if missing:
            return None, missing

        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: data.get(field) for field in self.LIST_FIELDS})
        entry["status"] = self.STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        self._store_coordinates(entry, data)
        for extra_key in ("提交人", "author", "idempotency_key", "client_token", "batch_key"):
            if data.get(extra_key) not in (None, ""):
                entry[extra_key] = data[extra_key]
        rows.append(entry)
        revision_ledger.mark_row_status(entry, entry["status"])
        return entry, []

    def _store_coordinates(self, entry: dict[str, Any], data: dict[str, Any]) -> None:
        version_ref = data.get("关联版本") or data.get("version_id") or entry.get("关联版本")
        doc = revision_ledger.get_document(version_ref) if version_ref else None
        source_text = doc["original_text"] if doc else ""
        start, end, _ = parse_coordinates(data, source_text)
        if start is not None and end is not None:
            entry["字符起"] = start
            entry["字符止"] = end
            entry["字符坐标"] = f"[{start},{end})"
        for key in ("start", "end", "char_start", "char_end", "coordinates"):
            if data.get(key) is not None:
                entry[key] = data[key]

    def register_correction(
        self, correction_id: str, version_id: str, ms_range: str,
        original: str, corrected: str, source: str, trigger_recompute: bool,
        **coordinate_values: Any,
    ) -> tuple[dict[str, Any] | None, str]:
        """登记纠错单；相同纠错编号重报时保持幂等。"""
        rows = store.rows(self.MODULE)
        existing = next((r for r in rows if r.get("纠错编号") == correction_id), None)
        if existing is not None:
            revision_ledger.mark_row_status(existing, str(existing.get("status") or "已登记"))
            return existing, f"纠错单 {correction_id} 已存在，重报未重复登记"

        values: dict[str, Any] = {
            "纠错编号": correction_id, "关联版本": version_id,
            "纠错范围毫秒": ms_range, "原文本": original,
            "纠正文本": corrected, "纠错来源": source,
            "是否触发重算": "是" if trigger_recompute else "否",
            "纠错时间": coordinate_values.pop("纠错时间", "2026-11-01"),
            **coordinate_values,
        }
        entry, missing = self.create_entry(values)
        if entry is None:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        return entry, f"纠错单 {correction_id} 已登记"

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry, message = super().run_action(entry_id, action)
        if entry is not None:
            revision_ledger.mark_row_status(entry, str(entry.get("status") or ""))
            if action == "合入版本":
                message = f"{message}，版本修订明细已按原文坐标更新"
        return entry, message

    # ---------- 批量预览/受理的服务层入口 ----------

    def preview_batch(
        self,
        payload: dict[str, Any] | list[Any] | None = None,
        correction_ids: list[Any] | None = None,
        version_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if isinstance(payload, list):
            data: dict[str, Any] = {"correction_ids": payload}
        elif payload is None:
            data = {}
        else:
            data = dict(payload)
        if correction_ids is not None:
            data["correction_ids"] = correction_ids
        if version_id is not None:
            data["version_id"] = version_id
        data.update(kwargs)
        return revision_ledger.preview(data)

    def batch_preview(
        self,
        payload: dict[str, Any] | list[Any] | None = None,
        correction_ids: list[Any] | None = None,
        version_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return self.preview_batch(payload, correction_ids, version_id, **kwargs)

    def preview_corrections(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.preview_batch(*args, **kwargs)

    def accept_batch(
        self,
        payload: dict[str, Any] | list[Any] | None = None,
        correction_ids: list[Any] | None = None,
        version_id: str | None = None,
        idempotency_key: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if isinstance(payload, list):
            data: dict[str, Any] = {"correction_ids": payload}
        elif payload is None:
            data = {}
        else:
            data = dict(payload)
        if correction_ids is not None:
            data["correction_ids"] = correction_ids
        if version_id is not None:
            data["version_id"] = version_id
        if idempotency_key is not None:
            data["idempotency_key"] = idempotency_key
        data.update(kwargs)
        return revision_ledger.accept_batch(data)

    def batch_accept(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.accept_batch(*args, **kwargs)

    def batch_review(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.accept_batch(*args, **kwargs)

    def batch_submit(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self.accept_batch(*args, **kwargs)

    batch_confirm = batch_submit

    def load_scenario(self, reset: bool = False) -> dict[str, Any]:
        return revision_ledger.load_seed_scenario(reset=reset)

    def check_triggers_recompute(self, version_id: str) -> list[dict[str, Any]]:
        """获取指定版本中触发重算的纠错单。"""
        rows = store.rows(self.MODULE)
        return [
            r for r in rows
            if r.get("关联版本") == version_id
            and r.get("是否触发重算") == "是"
            and r.get("status") == "已合入"
        ]

    def get_by_version(self, version_id: str) -> list[dict[str, Any]]:
        """获取指定版本的所有纠错单。"""
        rows = store.rows(self.MODULE)
        return [r for r in rows if r.get("关联版本") == version_id]

    def count_pending(self) -> int:
        """统计待处理的纠错单数量。"""
        rows = store.rows(self.MODULE)
        return sum(1 for r in rows if r.get("status") == "已登记")
