"""纠错批量预览/受理与转写版本修订范围查回接口。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.services import service_for
from app.services.revision_ledger import revision_ledger

router = APIRouter(prefix="/api", tags=["纠错修订"])


async def _payload(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        return {"items": data}
    # 允许通过请求头传递幂等键。
    key = request.headers.get("Idempotency-Key") or request.headers.get("idempotency-key")
    if key and not data.get("idempotency_key"):
        data["idempotency_key"] = key
    return data


def _correction_service():
    service = service_for("correction_loop")
    assert service is not None
    return service


def _version_service():
    service = service_for("transcript_version")
    assert service is not None
    return service


@router.post("/correction_loop/preview")
@router.post("/correction_loop/preview-batch")
@router.post("/correction_loop/preview_batch")
@router.post("/correction_loop/batch-preview")
@router.post("/correction_loop/batch_preview")
@router.post("/correction_loop/batch/preview")
@router.post("/correction_loop/diff")
@router.post("/correction_loop/text-compare")
async def preview_corrections(request: Request) -> dict[str, Any]:
    payload = await _payload(request)
    return _correction_service().preview_batch(payload)


@router.post("/corrections/preview")
@router.post("/corrections/batch-preview")
@router.post("/correction/preview")
async def preview_correction_aliases(request: Request) -> dict[str, Any]:
    payload = await _payload(request)
    return _correction_service().preview_batch(payload)


@router.post("/correction_loop/batch-accept")
@router.post("/correction_loop/batch_accept")
@router.post("/correction_loop/batch-submit")
@router.post("/correction_loop/batch_submit")
@router.post("/correction_loop/batch-confirm")
@router.post("/correction_loop/confirm-batch")
@router.post("/correction_loop/accept-batch")
@router.post("/correction_loop/accept_batch")
@router.post("/correction_loop/batch/accept")
@router.post("/correction_loop/batch/confirm")
@router.post("/correction_loop/batch")
async def accept_correction_batch(request: Request) -> dict[str, Any]:
    payload = await _payload(request)
    action = str(payload.get("action") or payload.get("mode") or "accept").strip()
    if action in {"preview", "batch_preview", "preview_batch"} or payload.get("preview_only") is True:
        return _correction_service().preview_batch(payload)
    return _correction_service().accept_batch(payload)


@router.post("/corrections/batch-accept")
@router.post("/corrections/accept-batch")
@router.post("/correction/batch-accept")
async def accept_correction_aliases(request: Request) -> dict[str, Any]:
    payload = await _payload(request)
    return _correction_service().accept_batch(payload)


@router.post("/correction_loop/scenario/load")
async def load_correction_scenario(request: Request) -> dict[str, Any]:
    payload = await _payload(request)
    return revision_ledger.load_seed_scenario(reset=bool(payload.get("reset")))


@router.get("/transcript_version/ranges")
@router.get("/transcript_version/revision-ranges")
async def version_ranges_query(version_id: str = "V1", ref: str | None = None) -> dict[str, Any]:
    return _version_service().get_revision_ranges(ref or version_id)


@router.get("/transcript_version/{version_ref}/ranges")
@router.get("/transcript_version/{version_ref}/revision-ranges")
@router.get("/transcript_version/{version_ref}/revisions")
@router.get("/transcript_version/{version_ref}/revision-details")
@router.get("/transcript_version/{version_ref}/revision_detail")
@router.get("/transcript_version/{version_ref}/coordinate-ranges")
@router.get("/transcript_version/{version_ref}/correction-ranges")
async def version_ranges(version_ref: str) -> dict[str, Any]:
    return _version_service().get_revision_ranges(version_ref)


@router.get("/transcript-versions/{version_ref}/ranges")
@router.get("/transcript_versions/{version_ref}/ranges")
async def version_ranges_aliases(version_ref: str) -> dict[str, Any]:
    return _version_service().get_revision_ranges(version_ref)
