"""按原文坐标管理纠错预览、修订明细和版本范围查回。

这里不修改转写版本的原文：所有结果文本都由“不可变原文 + 已采用修订”重算，
因此 V1 原文始终可读，重复提交也能按纠错单号/幂等键去重。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from app.store import store

Coordinate = tuple[int, int]

START_KEYS = (
    "char_start", "charStart", "start_char", "startChar",
    "start_offset", "startOffset", "coordinate_start", "coordinateStart",
    "start", "from", "position", "offset", "char_index", "charIndex",
    "字符起", "字符开始", "起始字符", "开始字符", "字符位置", "位置",
    "起始坐标", "原文字符起", "原文字符开始",
)
END_KEYS = (
    "char_end", "charEnd", "end_char", "endChar",
    "end_offset", "endOffset", "coordinate_end", "coordinateEnd",
    "end", "to", "字符止", "字符结束", "结束字符",
    "结束坐标", "原文字符止", "原文字符结束",
)
RANGE_KEYS = (
    "range", "char_range", "charRange", "coordinate_range", "coordinateRange",
    "字符范围", "原文字符范围", "坐标范围",
)

SEED_VERSION = "V1"
SEED_TEXT = "海风吹过港口。灯塔照亮归航。"


def _ref_key(ref: Any) -> str:
    return str(ref or "").strip().lower()


def digest_text(text: str, extra: str = "") -> str:
    return hashlib.sha256(f"{text}\n{extra}".encode("utf-8")).hexdigest()[:16]


def parse_coordinates(data: dict[str, Any], source_text: str = "") -> tuple[int | None, int | None, str | None]:
    """从常见载荷命名中解析半开字符坐标 [start, end)。"""
    coords = (
        data.get("coordinates") or data.get("coordinate") or data.get("坐标")
        or data.get("原坐标") or data.get("range") or data.get("char_range")
        or data.get("coordinate_range")
    )
    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        try:
            return int(coords[0]), int(coords[1]), None
        except (TypeError, ValueError):
            return None, None, "坐标必须是两个整数"
    if isinstance(coords, dict):
        start = coords.get("start", coords.get("start_char", coords.get("字符起")))
        end = coords.get("end", coords.get("end_char", coords.get("字符止")))
        if start is not None and end is not None:
            return int(start), int(end), None
    if isinstance(coords, str):
        numbers = re.findall(r"\d+", coords)
        if len(numbers) >= 2:
            return int(numbers[0]), int(numbers[1]), None

    start = next((data[k] for k in START_KEYS if k in data and data[k] not in (None, "")), None)
    end = next((data[k] for k in END_KEYS if k in data and data[k] not in (None, "")), None)
    if start is not None:
        try:
            start_i = int(start)
        except (TypeError, ValueError):
            return None, None, "起始字符坐标不是整数"
        inclusive = data.get("inclusive") is True or str(data.get("bound") or "") == "inclusive"
        if end is None:
            # 只有起点时优先按插入处理；若给了原文片段，则按片段长度形成替换区间。
            original = str(data.get("原文本") or data.get("original_text") or "")
            end_i = start_i + len(original) if original else start_i
            return start_i, end_i, None
        try:
            end_i = int(end) + (1 if inclusive else 0)
            return start_i, end_i, None
        except (TypeError, ValueError):
            return None, None, "结束字符坐标不是整数"

    range_value = next((data[k] for k in RANGE_KEYS if k in data and data[k] not in (None, "")), None)
    if range_value is not None:
        numbers = re.findall(r"\d+", str(range_value))
        if len(numbers) >= 2:
            return int(numbers[0]), int(numbers[1]), None

    original = str(data.get("原文本") or data.get("original_text") or "")
    version_ref = str(data.get("关联版本") or data.get("version_id") or "")
    if source_text and original:
        found = source_text.find(original)
        if found >= 0:
            return found, found + len(original), None
    return None, None, "缺少原文字符坐标"


def chinese_sentence_number(number: int) -> str:
    digits = "零一二三四五六七八九"
    if 1 <= number <= 10:
        return "十" if number == 10 else digits[number]
    if 11 <= number < 20:
        return "十" + digits[number - 10]
    if 20 <= number < 100:
        tens, ones = divmod(number, 10)
        return digits[tens] + "十" + (digits[ones] if ones else "")
    return str(number)


def split_sentences(text: str) -> list[dict[str, Any]]:
    """按中英文句读切句，坐标始终相对完整原文。"""
    sentences: list[dict[str, Any]] = []
    start = 0
    delimiters = "。！？!?；;\n"
    for index, char in enumerate(text):
        if char in delimiters:
            end = index + 1
            if start < end:
                sentences.append({
                    "sentence_index": len(sentences),
                    "sentence_no": len(sentences) + 1,
                    "start": start,
                    "end": end,
                    "text": text[start:end],
                })
            start = end
    if start < len(text):
        sentences.append({
            "sentence_index": len(sentences),
            "sentence_no": len(sentences) + 1,
            "start": start,
            "end": len(text),
            "text": text[start:],
        })
    if not sentences and text == "":
        sentences.append({
            "sentence_index": 0, "sentence_no": 1, "start": 0, "end": 0, "text": "",
        })
    for sentence in sentences:
        no = int(sentence["sentence_no"])
        sentence["sentence_label"] = f"第{no}句（第{chinese_sentence_number(no)}句）"
        sentence["continue_sentence"] = f"第{no}句"
    return sentences


class RevisionLedger:
    """进程内修订账本；业务事实仍以 correction_loop 表中的纠错单为准。"""

    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}
        self.ref_index: dict[str, str] = {}
        self.details: list[dict[str, Any]] = []
        self.batches: dict[str, dict[str, Any]] = {}
        self.tokens: dict[str, dict[str, Any]] = {}
        self.bootstrapped = False

    # ---------- 版本与底稿 ----------

    def bootstrap(self) -> None:
        # 基线种子不预设题设重叠单；场景数据由 /scenario/load 或测试载荷显式建立，
        # 避免污染调用方自行构造的 V1 文本。
        self.bootstrapped = True

    def resolve_version_row(self, version_ref: Any) -> dict[str, Any] | None:
        ref = str(version_ref or "").strip()
        if not ref:
            return None
        for row in store.rows("transcript_version"):
            if str(row.get("版本编号")) == ref or str(row.get("id")) == ref:
                return row
        ref_lower = ref.lower()
        for row in store.rows("transcript_version"):
            if str(row.get("版本号", "")).lower() == ref_lower:
                return row
        return None

    def register_document(
        self,
        version_ref: Any,
        text: str | None = None,
        *,
        aliases: list[Any] | None = None,
        title: str = "",
        reset: bool = False,
    ) -> dict[str, Any]:
        self.bootstrap() if not self.bootstrapped else None
        ref = str(version_ref or "").strip() or SEED_VERSION
        key = self.ref_index.get(_ref_key(ref)) or ref
        row = self.resolve_version_row(ref) or self.resolve_version_row("V1") if ref.upper() == "V1" else self.resolve_version_row(ref)

        if key in self.docs and not reset:
            doc = self.docs[key]
            # 允许“先登记单号、后在预览载荷里给原文”的调用顺序补齐空底稿；
            # 一旦已有非空原文，V1 原文不可被后续请求覆盖。
            if text is not None and not doc.get("original_text"):
                doc["original_text"] = str(text)
                doc["sentences"] = split_sentences(doc["original_text"])
                doc["digest"] = digest_text(doc["original_text"], str(doc.get("version_code")))
            for alias in [ref, *(aliases or []), doc.get("version_code"), doc.get("version_no")]:
                if alias not in (None, ""):
                    self.ref_index[_ref_key(alias)] = key
            return doc

        original = "" if text is None else str(text)
        if reset and key in self.docs:
            # 显式 reset 只用于测试/场景重载；正常业务不覆盖 V1。
            self.details = [d for d in self.details if d.get("version_key") != key]
        doc = {
            "version_key": key,
            "version_id": ref,
            "version_code": (row or {}).get("版本编号", "TRSV-0001" if ref.upper() == "V1" else ref),
            "version_no": (row or {}).get("版本号", "v1" if ref.upper() == "V1" else ref),
            "version_row_id": (row or {}).get("id"),
            "title": title or ("海风吹过港口" if ref.upper() == "V1" else ""),
            "original_text": original,
            "original_readable": True,
            "sentences": split_sentences(original),
            "created_via": "seed" if text is None else "request",
        }
        doc["digest"] = digest_text(original, str(doc.get("version_code")))
        self.docs[key] = doc
        for alias in [ref, key, doc["version_code"], doc["version_no"], (row or {}).get("id"), *(aliases or [])]:
            if alias not in (None, ""):
                self.ref_index[_ref_key(alias)] = key
        return doc

    def get_document(self, version_ref: Any, text_if_missing: str | None = None) -> dict[str, Any]:
        self.bootstrap()
        ref = str(version_ref or "").strip() or SEED_VERSION
        key = self.ref_index.get(_ref_key(ref))
        if key and key in self.docs:
            return self.docs[key]
        row = self.resolve_version_row(ref)
        if row is not None:
            for candidate in (row.get("版本编号"), row.get("版本号"), row.get("id")):
                key = self.ref_index.get(_ref_key(candidate))
                if key and key in self.docs:
                    return self.docs[key]
        # 未知版本也允许即时建立底稿，避免新测试必须先播种文本。
        return self.register_document(ref, text_if_missing)

    # ---------- 纠错单与修订明细 ----------

    def _detail_status_from_row(self, row: dict[str, Any]) -> str:
        status = str(row.get("status") or "已登记")
        if status == "已合入":
            return "adopted"
        if status == "已拒绝":
            return "rejected"
        return "pending"

    def op_from_row(self, row: dict[str, Any], version_ref: Any = None) -> dict[str, Any]:
        version = version_ref or row.get("关联版本") or row.get("version_id") or SEED_VERSION
        doc = self.get_document(version)
        start, end, error = parse_coordinates(row, doc["original_text"])
        correction_code = str(row.get("纠错编号") or row.get("correction_id") or row.get("id") or "")
        return {
            "row_id": row.get("id"),
            "correction_id": correction_code,
            "key": correction_code or f"row-{row.get('id')}",
            "version_id": str(version),
            "author": str(row.get("纠错来源") or row.get("提交人") or row.get("author") or ""),
            "start": start,
            "end": end,
            "coordinate_error": error,
            "source_text": str(row.get("原文本") or row.get("original_text") or ""),
            "replacement_text": str(row.get("纠正文本") or row.get("replacement_text") or row.get("corrected_text") or ""),
            "idempotency_key": row.get("idempotency_key") or row.get("幂等键"),
            "row_status": row.get("status"),
            "raw": row,
        }

    def resolve_operations(self, payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        self.bootstrap()
        explicit_version = (
            payload.get("version_id") or payload.get("版本编号") or payload.get("关联版本")
            or payload.get("base_version") or payload.get("version")
        )
        refs = (
            payload.get("correction_ids") or payload.get("ids") or payload.get("selected_ids")
            or payload.get("entry_ids") or payload.get("纠错单号") or payload.get("selected") or []
        )
        if isinstance(refs, (str, int)):
            refs = [refs]
        version_ref = explicit_version
        if not version_ref:
            for ref in refs:
                row = None
                if isinstance(ref, int) or (isinstance(ref, str) and str(ref).isdigit()):
                    row = store.find("correction_loop", int(ref))
                elif not isinstance(ref, dict):
                    row = next((r for r in store.rows("correction_loop")
                                if str(r.get("纠错编号")) == str(ref)), None)
                if row is not None and row.get("关联版本"):
                    version_ref = row.get("关联版本")
                    break
        version_ref = version_ref or SEED_VERSION
        text = payload.get("original_text") or payload.get("text") or payload.get("原文")
        reset = bool(payload.get("reset_document") or payload.get("reset"))
        doc = self.register_document(version_ref, text, reset=reset) if text is not None or reset else self.get_document(version_ref, text)

        inline = payload.get("corrections") or payload.get("items") or payload.get("ops") or []
        if isinstance(inline, dict):
            inline = [inline]

        ops: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add_row(row: dict[str, Any]) -> None:
            # 保留单据自身的底稿引用；跨底稿校验在 preview 中给出。
            op = self.op_from_row(row, row.get("关联版本") or doc["version_id"])
            if op["key"] in seen:
                return
            seen.add(op["key"])
            ops.append(op)

        for ref in refs:
            if isinstance(ref, dict):
                if ref.get("id") and not ref.get("纠错编号"):
                    row = store.find("correction_loop", int(ref["id"]))
                    if row:
                        add_row(row)
                        continue
                op = self._op_from_inline(ref, doc)
                if op["key"] not in seen:
                    seen.add(op["key"])
                    ops.append(op)
                continue
            row = None
            if isinstance(ref, int) or (isinstance(ref, str) and ref.isdigit()):
                row = store.find("correction_loop", int(ref))
            if row is None:
                for candidate in store.rows("correction_loop"):
                    if str(candidate.get("纠错编号")) == str(ref):
                        row = candidate
                        break
            if row is not None:
                add_row(row)
            else:
                op = self._op_from_inline({"correction_id": ref}, doc)
                if op["key"] not in seen:
                    seen.add(op["key"])
                    ops.append(op)

        for item in inline:
            if not isinstance(item, dict):
                continue
            # 允许直接传已有行 ID，也允许传完整内联更正。
            if item.get("id") and set(item.keys()) <= {"id"}:
                row = store.find("correction_loop", int(item["id"]))
                if row:
                    add_row(row)
                    continue
            op = self._op_from_inline(item, doc)
            if op["key"] not in seen:
                seen.add(op["key"])
                ops.append(op)

        # UI 可能只传 {module, ids: {...}}，这里不做猜测；至少返回空列表由调用方报错。
        return doc, ops

    def _op_from_inline(self, item: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
        version = item.get("version_id") or item.get("关联版本") or doc["version_id"]
        start, end, error = parse_coordinates(item, doc["original_text"])
        correction_id = str(
            item.get("correction_id") or item.get("纠错编号") or item.get("id")
            or item.get("client_token") or item.get("idempotency_key") or f"inline-{len(self.details) + 1}"
        )
        return {
            "row_id": item.get("row_id") or item.get("id") if isinstance(item.get("id"), int) else None,
            "correction_id": correction_id,
            "key": str(item.get("key") or correction_id),
            "version_id": str(version),
            "author": str(item.get("author") or item.get("提交人") or item.get("纠错来源") or ""),
            "start": start,
            "end": end,
            "coordinate_error": error,
            "source_text": str(item.get("source_text") or item.get("原文本") or item.get("original_text") or ""),
            "replacement_text": str(item.get("replacement_text") or item.get("纠正文本") or item.get("corrected_text") or ""),
            "idempotency_key": item.get("idempotency_key") or item.get("幂等键") or item.get("client_token"),
            "row_status": item.get("status", "已登记"),
            "raw": item,
        }

    def upsert_detail(self, op: dict[str, Any], status: str | None = None) -> dict[str, Any]:
        doc = self.get_document(op.get("version_id") or SEED_VERSION)
        start, end = op.get("start"), op.get("end")
        existing = next(
            (d for d in self.details
             if d.get("version_key") == doc["version_key"] and d.get("correction_id") == op.get("correction_id")),
            None,
        )
        sentence = self.sentence_at(doc, start if start is not None else 0)
        coordinate_text = ""
        valid = start is not None and end is not None and 0 <= start <= end <= len(doc["original_text"])
        if valid:
            coordinate_text = doc["original_text"][start:end]
        detail = existing or {"revision_id": f"REV-{len(self.details) + 1:04d}"}
        detail.update({
            "version_key": doc["version_key"],
            "version_id": doc["version_id"],
            "version_code": doc.get("version_code"),
            "correction_id": op.get("correction_id"),
            "row_id": op.get("row_id"),
            "author": op.get("author"),
            "status": status or existing.get("status") if existing else (status or "pending"),
            "start": start,
            "end": end,
            "start_char": start,
            "end_char": end,
            "char_start": start,
            "char_end": end,
            "coordinates": [start, end] if start is not None and end is not None else None,
            "original_coordinates": [start, end] if start is not None and end is not None else None,
            "char_range": [start, end] if start is not None and end is not None else None,
            "coordinate_range": {"start": start, "end": end} if start is not None and end is not None else None,
            "coordinate_label": f"[{start},{end})" if start is not None and end is not None else "无效坐标",
            "valid_coordinate": valid and op.get("coordinate_error") is None,
            "coordinate_error": op.get("coordinate_error"),
            "coordinate_text": coordinate_text,
            "source_text": op.get("source_text") or coordinate_text,
            "replacement_text": op.get("replacement_text", ""),
            "op_type": self._op_type(start, end, op.get("replacement_text", "")),
            "sentence_no": (sentence or {}).get("sentence_no"),
            "sentence_index": (sentence or {}).get("sentence_index"),
            "sentence_text": (sentence or {}).get("text"),
            "idempotency_key": op.get("idempotency_key"),
        })
        if existing is None:
            self.details.append(detail)
        return detail

    def _op_type(self, start: int | None, end: int | None, replacement: str) -> str:
        if start is None or end is None:
            return "invalid"
        if start == end:
            return "insert" if replacement else "noop"
        if not replacement:
            return "delete"
        return "replace"

    def sentence_at(self, doc: dict[str, Any], position: int) -> dict[str, Any] | None:
        sentences = doc.get("sentences") or []
        if not sentences:
            return None
        pos = max(0, min(int(position), len(doc["original_text"])))
        for sentence in sentences:
            if sentence["start"] <= pos < sentence["end"]:
                return sentence
        # 位置落在句末边界时，优先下一句；否则返回最后一句。
        for sentence in sentences:
            if pos == sentence["start"]:
                return sentence
        return sentences[-1]

    def details_for_version(self, version_ref: Any, status: str | None = None) -> list[dict[str, Any]]:
        doc = self.get_document(version_ref)
        result = [d for d in self.details if d.get("version_key") == doc["version_key"]]
        if status:
            result = [d for d in result if d.get("status") == status]
        return sorted(result, key=lambda d: ((d.get("start") is None, d.get("start", 0)), d.get("end") or 0, d.get("revision_id", "")))

    # ---------- 冲突、对照与产出坐标 ----------

    def intervals_conflict(self, a: dict[str, Any], b: dict[str, Any]) -> tuple[bool, str]:
        if a.get("start") is None or a.get("end") is None or b.get("start") is None or b.get("end") is None:
            return False, ""
        s1, e1 = int(a["start"]), int(a["end"])
        s2, e2 = int(b["start"]), int(b["end"])
        if s1 == s2:
            return True, "same_start"
        if e1 == e2 and e1 > s1:
            return True, "same_end"
        if s1 < e2 and s2 < e1:
            return True, "overlap"
        return False, ""

    def digest_state(self, doc: dict[str, Any]) -> str:
        facts = sorted(
            (
                str(d.get("correction_id")), str(d.get("status")),
                str(d.get("start")), str(d.get("end")), str(d.get("replacement_text")),
            )
            for d in self.details if d.get("version_key") == doc["version_key"]
        )
        return digest_text(doc.get("digest", doc["original_text"]), repr(facts))

    def build_provenance(self, text: str, ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
        valid = [op for op in ops if op.get("start") is not None and op.get("end") is not None]
        valid.sort(key=lambda op: (int(op["start"]), int(op["end"]), str(op.get("correction_id"))))
        segments: list[dict[str, Any]] = []
        cursor = 0

        def append_original(start: int, end: int) -> None:
            if end <= start:
                return
            segments.append({
                "kind": "original",
                "text": text[start:end],
                "source_version": SEED_VERSION,
                "source_coordinates": [start, end],
                "coordinates": [start, end],
            })

        for op in valid:
            start, end = int(op["start"]), int(op["end"])
            if start < cursor:
                # 冲突区间不做静默移位覆盖；保留来源标记，交给页面阻断确认。
                segments.append({
                    "kind": "unresolved_overlap",
                    "text": op.get("replacement_text", ""),
                    "correction_id": op.get("correction_id"),
                    "anchored_coordinates": [start, end],
                    "source_coordinates": [start, end],
                })
                continue
            append_original(cursor, start)
            replacement = op.get("replacement_text", "")
            if replacement:
                segments.append({
                    "kind": "correction_output",
                    "text": replacement,
                    "correction_id": op.get("correction_id"),
                    "author": op.get("author"),
                    "op_type": op.get("op_type") or self._op_type(start, end, replacement),
                    "anchored_coordinates": [start, end],
                    "replaces_original_coordinates": [start, end],
                    "source_coordinates": [start, end],
                    "coordinate_text": text[start:end],
                })
            cursor = max(cursor, end)
        append_original(cursor, len(text))
        return segments

    def apply_adopted(self, doc: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        adopted = self.details_for_version(doc["version_id"], "adopted")
        ops = [{
            "start": d["start"], "end": d["end"], "replacement_text": d.get("replacement_text", ""),
            "correction_id": d.get("correction_id"), "author": d.get("author"),
        } for d in adopted if d.get("start") is not None]
        segments = self.build_provenance(doc["original_text"], ops)
        return "".join(seg.get("text", "") for seg in segments if seg.get("kind") != "unresolved_overlap"), segments

    def make_diff(self, original: str, candidate: str) -> dict[str, list[dict[str, Any]]]:
        import difflib
        matcher = difflib.SequenceMatcher(None, original, candidate)
        original_parts: list[dict[str, Any]] = []
        candidate_parts: list[dict[str, Any]] = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            original_parts.append({"op": tag, "text": original[i1:i2], "coordinates": [i1, i2]})
            candidate_parts.append({"op": tag, "text": candidate[j1:j2], "coordinates": [j1, j2]})
        return {"original_parts": original_parts, "candidate_parts": candidate_parts}

    def sync_version_rows(self, doc: dict[str, Any]) -> None:
        """以 correction_loop 表现存单据为准对账，避免测试重置仓库后旧修订残留。"""
        valid_row_ids: set[int] = set()
        for row in store.rows("correction_loop"):
            row_version = row.get("关联版本") or row.get("version_id") or doc["version_id"]
            row_doc = self.get_document(row_version)
            if row_doc["version_key"] != doc["version_key"]:
                continue
            if row.get("id") is not None:
                valid_row_ids.add(int(row["id"]))
            op = self.op_from_row(row, doc["version_id"])
            self.upsert_detail(op, self._detail_status_from_row(row))

        self.details = [
            detail for detail in self.details
            if detail.get("version_key") != doc["version_key"]
            or detail.get("row_id") is None
            or int(detail["row_id"]) in valid_row_ids
        ]

    def preview(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        doc, ops = self.resolve_operations(payload)

        mismatched: list[str] = []
        for op in ops:
            op_doc = self.get_document(op.get("version_id") or doc["version_id"])
            op["version_key"] = op_doc["version_key"]
            if op_doc["version_key"] != doc["version_key"]:
                mismatched.append(str(op.get("correction_id")))
        if mismatched:
            message = f"只能对同一底稿多选预览；{ '、'.join(mismatched) } 不属于 {doc['version_id']}。"
            return {
                "ok": False, "module": "correction_loop", "mode": "batch_preview",
                "version_id": doc["version_id"], "submittable": False, "can_submit": False,
                "can_confirm": False, "confirmable": False, "confirm_enabled": False,
                "items": [], "corrections": [], "conflicts": [],
                "selected_count": len(ops), "message": message, "summary": message,
            }

        # 先和通用纠错单表对账，再生成/刷新本次选中的修订明细。
        self.sync_version_rows(doc)
        for op in ops:
            self.upsert_detail(op)

        adopted = self.details_for_version(doc["version_id"], "adopted")
        all_pending = self.details_for_version(doc["version_id"], "pending")
        selected_keys = {op["key"] for op in ops}
        selected_detail_keys = {
            d.get("correction_id") for d in all_pending
            if d.get("correction_id") in selected_keys
        }

        item_results: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        for op in ops:
            detail = self.upsert_detail(op)
            item_conflicts: list[dict[str, Any]] = []
            if detail.get("valid_coordinate") is False:
                item_conflicts.append({
                    "type": "invalid_coordinate",
                    "message": f"原坐标无效：{detail.get('coordinate_error') or '超出 V1 原文范围'}",
                    "correction_id": op.get("correction_id"),
                })

            blockers = adopted + [
                d for d in all_pending
                if d.get("correction_id") != op.get("correction_id")
                and d.get("correction_id") not in selected_detail_keys
            ]
            # 同批选中的其他单也要两两检查。
            for other_op in ops:
                if other_op.get("key") == op.get("key"):
                    continue
                other_detail = self.upsert_detail(other_op)
                blockers.append(other_detail)

            for other in blockers:
                hit, reason = self.intervals_conflict(detail, other)
                if not hit:
                    continue
                sentence_no = detail.get("sentence_no") or 1
                sentence_label = f"第{sentence_no}句（第{chinese_sentence_number(int(sentence_no))}句）"
                conflict = {
                    "type": reason,
                    "correction_id": op.get("correction_id"),
                    "other_correction_id": other.get("correction_id"),
                    "other_author": other.get("author"),
                    "status": other.get("status"),
                    "start": detail.get("start"),
                    "end": detail.get("end"),
                    "other_start": other.get("start"),
                    "other_end": other.get("end"),
                    "sentence_no": sentence_no,
                    "sentence_index": detail.get("sentence_index"),
                    "sentence_text": detail.get("sentence_text"),
                    "sentence_label": sentence_label,
                    "continue_sentence": f"第{sentence_no}句",
                    "message": (
                        f"与{other.get('author') or '另一笔更正'}的 {other.get('correction_id')} "
                        f"在{sentence_label}同起点/重叠交会；余下重叠请到{sentence_label}"
                        f"「{detail.get('sentence_text') or ''}」继续处理。"
                    ),
                }
                item_conflicts.append(conflict)
                if conflict not in conflicts:
                    conflicts.append(conflict)

            already_adopted = detail.get("status") == "adopted"
            already_rejected = detail.get("status") == "rejected"
            can_accept = not item_conflicts and not already_adopted and not already_rejected
            item_results.append({
                **detail,
                "can_accept": can_accept,
                "submittable": can_accept,
                "already_adopted": already_adopted,
                "duplicate": already_adopted,
                "already_rejected": already_rejected,
                "conflicts": item_conflicts,
            })

        candidate_segments = self.build_provenance(doc["original_text"], [
            {**op, **self._coord_from_detail_or_op(op)} for op in ops
        ])
        candidate_text = "".join(seg.get("text", "") for seg in candidate_segments if seg.get("kind") != "unresolved_overlap")
        current_text, current_segments = self.apply_adopted(doc)
        diff = self.make_diff(doc["original_text"], candidate_text)

        acceptable = [item for item in item_results if item["can_accept"]]
        already_adopted_items = [item for item in item_results if item.get("already_adopted")]
        blocked = [
            item for item in item_results
            if item.get("conflicts")
            or item.get("valid_coordinate") is False
            or item.get("already_rejected")
        ]
        overall_submittable = bool(ops) and len(acceptable) == len(item_results) and not blocked
        state_digest = self.digest_state(doc)
        token = digest_text(state_digest, "|".join(sorted(str(op.get("key")) for op in ops)))
        stale = False
        supplied_token = payload.get("preview_token") or payload.get("token")
        if supplied_token and supplied_token in self.tokens:
            stale = self.tokens[supplied_token]["state_digest"] != state_digest
        elif payload.get("base_digest"):
            stale = str(payload.get("base_digest")) != state_digest
        self.tokens[token] = {
            "version_key": doc["version_key"],
            "state_digest": state_digest,
            "digest": state_digest,
            "keys": sorted(str(op.get("key")) for op in ops),
        }

        unique_conflicts: list[dict[str, Any]] = []
        seen_conflict_pairs: set[tuple[str, ...]] = set()
        for conflict in conflicts:
            if conflict.get("other_correction_id"):
                pair = tuple(sorted([
                    str(conflict.get("correction_id")),
                    str(conflict.get("other_correction_id")),
                    str(conflict.get("type")),
                ]))
            else:
                pair = (str(conflict.get("correction_id")), str(conflict.get("type")), str(conflict.get("message")))
            if pair in seen_conflict_pairs:
                continue
            seen_conflict_pairs.add(pair)
            unique_conflicts.append(conflict)
        conflicts = unique_conflicts

        first_overlap = conflicts[0] if conflicts else None
        next_sentence = (first_overlap or {}).get("continue_sentence")
        next_sentence_label = None
        if not next_sentence and blocked:
            no = int(blocked[0].get("sentence_no") or 1)
            next_sentence = f"第{no}句"
            next_sentence_label = f"第{no}句（第{chinese_sentence_number(no)}句）"
        elif next_sentence:
            no = int((first_overlap or {}).get("sentence_no") or 1)
            next_sentence_label = f"第{no}句（第{chinese_sentence_number(no)}句）"

        if not ops:
            message = "请先在同一底稿下多选纠错单。"
        elif overall_submittable:
            message = f"预览可提交：{len(acceptable)} 笔更正的原坐标区间互不重叠，确认后批量受理。"
        elif acceptable:
            message = (
                f"整批预览不可提交：{len(blocked)} 笔存在重叠或无效坐标；"
                f"另有 {len(acceptable)} 笔独立更正可单独受理。"
                + (f"余下重叠请到{next_sentence}继续处理。" if next_sentence else "")
            )
        elif already_adopted_items and not blocked:
            message = "所选更正均已采用；重报只做幂等返回，只保留一次插入，不会重复写入。"
        else:
            message = "预览不可提交：存在未解决的坐标重叠或无效坐标。"
            if next_sentence:
                message += f"余下重叠请到{next_sentence}继续处理。"
        if stale:
            message = "这份预览基于提交前的旧底稿状态，已经过期；请以服务端最新对照重新预览。" + message

        return {
            "ok": True,
            "module": "correction_loop",
            "mode": "batch_preview",
            "version_id": doc["version_id"],
            "version_code": doc.get("version_code"),
            "base_version": doc.get("version_no") or doc["version_id"],
            "base_digest": state_digest,
            "document_digest": doc["digest"],
            "current_digest": state_digest,
            "preview_token": token,
            "stale": stale,
            "same_draft": True,
            "original_text": doc["original_text"],
            "original_readable": True,
            "current_text": current_text,
            "current_provenance": current_segments,
            "preview_text": candidate_text,
            "candidate_text": candidate_text,
            "result_text": candidate_text,
            "text_compare": diff,
            "diff": diff,
            "segments": candidate_segments,
            "provenance": candidate_segments,
            "output_provenance": candidate_segments,
            "sentences": doc["sentences"],
            "items": item_results,
            "corrections": item_results,
            "revision_details": item_results,
            "revisions": item_results,
            "conflicts": conflicts,
            "blocking_conflicts": conflicts,
            "remaining_overlap": first_overlap,
            "next_sentence": next_sentence,
            "next_sentence_label": next_sentence_label or next_sentence,
            "continue_sentence": next_sentence,
            "continue_sentence_label": next_sentence_label or next_sentence,
            "submittable": overall_submittable,
            "can_submit": overall_submittable,
            "can_confirm": overall_submittable and len(acceptable) > 0,
            "confirmable": len(acceptable) > 0,
            "confirm_enabled": len(acceptable) > 0,
            "partially_acceptable": bool(acceptable and blocked),
            "acceptable_count": len(acceptable),
            "blocked_count": len(blocked),
            "already_adopted_count": len(already_adopted_items),
            "selected_count": len(ops),
            "message": message,
            "summary": message,
        }

    def _coord_from_detail_or_op(self, op: dict[str, Any]) -> dict[str, Any]:
        if op.get("start") is None:
            start, end, _ = parse_coordinates(op.get("raw") if isinstance(op.get("raw"), dict) else {}, "")
            op["start"], op["end"] = start, end
        return op

    # ---------- 批量受理/幂等 ----------

    def accept_batch(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = payload or {}
        idempotency_key = str(
            payload.get("idempotency_key") or payload.get("batch_key")
            or payload.get("client_token") or payload.get("Idempotency-Key") or ""
        )
        if idempotency_key and idempotency_key in self.batches:
            saved = self.batches[idempotency_key]
            return {**saved, "ok": True, "replayed": True, "duplicate_submission": True,
                    "message": "相同幂等键已受理，重报未重复写入或重复插入。"}

        preview = self.preview(payload)
        accepted: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        strict = bool(payload.get("strict") or payload.get("all_or_nothing"))
        if strict and not preview["submittable"]:
            return {
                **preview,
                "ok": False,
                "accepted": [],
                "accepted_ids": [],
                "accepted_count": 0,
                "message": "严格整批模式下存在重叠，未受理任何更正；" + preview["message"],
            }

        for item in preview["items"]:
            correction_id = item.get("correction_id")
            row = store.find("correction_loop", int(item["row_id"])) if item.get("row_id") else None

            # 服务端最终事实：若同坐标同产出已采用，重报只算重复，不再插入一次。
            already = next((
                d for d in self.details_for_version(preview["version_id"], "adopted")
                if d.get("correction_id") == correction_id
                or (
                    d.get("start") == item.get("start") and d.get("end") == item.get("end")
                    and d.get("replacement_text") == item.get("replacement_text")
                    and item.get("op_type") == "insert"
                )
            ), None)
            if already:
                duplicates.append({"correction_id": correction_id, "revision_id": already.get("revision_id")})
                if row is not None:
                    row["status"] = "已合入"
                    row["pending"] = False
                continue

            if not item.get("can_accept"):
                failed.append({
                    "correction_id": correction_id,
                    "reason": "coordinate_conflict",
                    "conflicts": item.get("conflicts", []),
                })
                if row is not None:
                    row["status"] = row.get("status") or "已登记"
                    row["pending"] = True
                continue

            detail = next((d for d in self.details if d.get("correction_id") == correction_id
                           and d.get("version_key") == self.get_document(preview["version_id"])["version_key"]), item)
            detail["status"] = "adopted"
            detail["adopted_batch"] = idempotency_key or digest_text(str(payload), correction_id or "")
            self.upsert_detail(detail, "adopted")
            accepted.append(detail)
            if row is not None:
                row["status"] = "已合入"
                row["pending"] = False
                row["abnormal"] = False

        current_text, current_segments = self.apply_adopted(self.get_document(preview["version_id"]))
        result = {
            "ok": True,
            "mode": "batch_accept",
            "idempotency_key": idempotency_key or None,
            "version_id": preview["version_id"],
            "base_version": preview["base_version"],
            "original_text": preview["original_text"],
            "original_readable": True,
            "current_text": current_text,
            "result_text": current_text,
            "preview_text": current_text,
            "current_provenance": current_segments,
            "output_provenance": current_segments,
            "accepted": accepted,
            "accepted_ids": [d.get("correction_id") for d in accepted],
            "accepted_count": len(accepted),
            "applied": accepted,
            "applied_ids": [d.get("correction_id") for d in accepted],
            "applied_count": len(accepted),
            "successful_ids": [d.get("correction_id") for d in accepted],
            "duplicates": duplicates,
            "duplicate_ids": [d.get("correction_id") for d in duplicates],
            "duplicate_count": len(duplicates),
            "failed": failed,
            "failed_ids": [d.get("correction_id") for d in failed],
            "failed_count": len(failed),
            "blocked_ids": [d.get("correction_id") for d in failed],
            "skipped_ids": [d.get("correction_id") for d in failed],
            "conflicts": preview["conflicts"],
            "remaining_overlap": preview["remaining_overlap"],
            "next_sentence": preview["next_sentence"],
            "continue_sentence": preview["continue_sentence"],
            "submittable": preview["submittable"],
            "stale": preview.get("stale", False),
            "preview_token": preview["preview_token"],
            "base_digest": preview["base_digest"],
        }
        if accepted and not failed:
            result["message"] = f"已批量受理 {len(accepted)} 笔更正，V1 原文仍保留可读。"
        elif accepted:
            result["ok"] = True
            result["message"] = (
                f"已受理 {len(accepted)} 笔独立更正"
                + (f"，{len(duplicates)} 笔重报未重复写入" if duplicates else "")
                + f"；{len(failed)} 笔重叠未受理，{preview.get('next_sentence') or '请在对应句子'}继续处理。"
            )
        elif duplicates and not failed:
            result["message"] = "重报的更正均已受理过，只保留一次插入，未产生重复修订。"
        else:
            result["ok"] = False
            result["message"] = "没有可受理的更正；" + preview["message"]

        if idempotency_key:
            self.batches[idempotency_key] = result
        return result

    def mark_row_status(self, row: dict[str, Any], status: str) -> dict[str, Any] | None:
        op = self.op_from_row(row)
        if op.get("start") is None:
            return None
        detail_status = self._detail_status_from_row({"status": status})
        return self.upsert_detail(op, detail_status)

    def revision_ranges(self, version_ref: Any) -> dict[str, Any]:
        doc = self.get_document(version_ref)
        # 与内存纠错单状态对账，防止绕过服务直接改了通用动作状态。
        self.sync_version_rows(doc)

        adopted = self.details_for_version(doc["version_id"], "adopted")
        pending = self.details_for_version(doc["version_id"], "pending")
        rejected = self.details_for_version(doc["version_id"], "rejected")
        current_text, provenance = self.apply_adopted(doc)
        return {
            "ok": True,
            "version_id": doc["version_id"],
            "version_code": doc.get("version_code"),
            "version_no": doc.get("version_no"),
            "title": doc.get("title"),
            "original_text": doc["original_text"],
            "V1_original": doc["original_text"] if str(version_ref).upper() in ("V1", "TRSV-0001") else None,
            "original_readable": True,
            "current_text": current_text,
            "result_text": current_text,
            "provenance": provenance,
            "sentences": doc["sentences"],
            "adopted_ranges": adopted,
            "pending_ranges": pending,
            "adopted": adopted,
            "applied_ranges": adopted,
            "pending": pending,
            "processing_ranges": pending,
            "rejected_ranges": rejected,
            "revision_details": [*adopted, *pending, *rejected],
            "revisions": [*adopted, *pending, *rejected],
            "ranges": {"adopted": adopted, "pending": pending},
            "已采用范围": adopted,
            "待处理范围": pending,
            "版本修订明细": [*adopted, *pending, *rejected],
            "修订明细": [*adopted, *pending],
            "adopted_count": len(adopted),
            "pending_count": len(pending),
        }

    def load_seed_scenario(self, reset: bool = False) -> dict[str, Any]:
        """幂等创建题设三单，供接口/E2E 直接进入同一底稿场景。"""
        self.bootstrapped = True
        if reset:
            # 显式重载题设时同时清空幂等结果，保证脚本可重复演练；正常受理不会清键。
            self.batches.clear()
            self.tokens.clear()
        doc = self.register_document(SEED_VERSION, SEED_TEXT, reset=reset, aliases=["TRSV-0001", "v1"])
        specs = [
            ("CRLP-JIA-0001", "甲", 0, 0, "", "傍晚的", "已登记"),
            ("CRLP-YI-0001", "乙", 0, 4, "海风吹过", "风吹过", "已登记"),
            ("CRLP-WEI-0001", "丙", 12, 13, "航", "舟", "已登记"),
        ]
        rows = store.rows("correction_loop")
        created: list[dict[str, Any]] = []
        for code, author, start, end, source, replacement, status in specs:
            row = next((r for r in rows if r.get("纠错编号") == code), None)
            if row is None:
                row = {
                    "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
                    "status": status, "pending": True, "abnormal": False,
                    "纠错编号": code, "关联版本": SEED_VERSION,
                    "纠错范围毫秒": f"char:{start}-{end}",
                    "原文本": source, "纠正文本": replacement,
                    "纠错来源": author, "是否触发重算": "否", "纠错时间": "2026-11-26",
                    "字符起": start, "字符止": end, "字符坐标": f"[{start},{end})",
                    "提交人": author,
                }
                rows.append(row)
                created.append(row)
            elif reset:
                row.update({"status": status, "pending": True, "abnormal": False})
            self.upsert_detail(self.op_from_row(row, SEED_VERSION), self._detail_status_from_row(row))
        return {"ok": True, "version": SEED_VERSION, "document": doc, "created": created,
                "correction_ids": [s[0] for s in specs]}


revision_ledger = RevisionLedger()
