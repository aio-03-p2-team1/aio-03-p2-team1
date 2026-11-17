"""사용자별 실종 전단지 문서와 최적화 이미지 자산 API."""

from __future__ import annotations

import base64
import io
import math
import re
import uuid
import warnings
from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from backend.deps import AppContext, current_user, get_ctx
from backend.errors import ApiError

router = APIRouter(tags=["posters"])
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_PIXELS = 25_000_000
MAX_SIDE = 2000
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")

TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "basic", "name": "기본형", "description": "사진 중심, 큰 제목과 하단 연락처",
        "width": 794, "height": 1123,
        "components": [
            {"id": "title", "type": "text", "label": "전단지 제목", "fieldKey": "title", "content": "강아지를 찾습니다", "x": 50, "y": 42, "width": 694, "height": 74, "fontSize": 42, "color": "#b74335", "fontStyle": "bold", "align": "center", "zIndex": 2},
            {"id": "photo", "type": "image", "label": "반려동물 사진", "assetId": None, "x": 117, "y": 145, "width": 560, "height": 450, "opacity": 1, "zIndex": 1},
            {"id": "name", "type": "text", "label": "동물 이름", "fieldKey": "pet_name", "content": "이름을 입력해 주세요", "x": 60, "y": 625, "width": 674, "height": 58, "fontSize": 32, "color": "#322d26", "fontStyle": "bold", "align": "center", "zIndex": 3},
            {"id": "place", "type": "text", "label": "실종 장소", "fieldKey": "lost_place", "content": "실종 장소를 입력해 주세요", "x": 70, "y": 710, "width": 654, "height": 54, "fontSize": 22, "color": "#51493f", "align": "center", "zIndex": 4},
            {"id": "contact", "type": "text", "label": "연락처", "fieldKey": "contact", "content": "발견하시면 연락 부탁드립니다", "x": 55, "y": 940, "width": 684, "height": 80, "fontSize": 28, "color": "#ffffff", "fontStyle": "bold", "align": "center", "fill": "#b74335", "zIndex": 5},
        ],
    },
    {
        "id": "info", "name": "정보형", "description": "사진과 상세 특징을 균형 있게 배치",
        "width": 794, "height": 1123,
        "components": [
            {"id": "title", "type": "text", "label": "전단지 제목", "fieldKey": "title", "content": "우리 아이를 찾습니다", "x": 48, "y": 42, "width": 698, "height": 70, "fontSize": 38, "color": "#35604c", "fontStyle": "bold", "align": "center", "zIndex": 2},
            {"id": "photo", "type": "image", "label": "반려동물 사진", "assetId": None, "x": 92, "y": 140, "width": 610, "height": 430, "opacity": 1, "zIndex": 1},
            {"id": "name", "type": "text", "label": "동물 이름", "fieldKey": "pet_name", "content": "이름을 입력해 주세요", "x": 55, "y": 600, "width": 684, "height": 54, "fontSize": 30, "color": "#2f493c", "fontStyle": "bold", "align": "center", "zIndex": 3},
            {"id": "details", "type": "text", "label": "신체적 특징", "fieldKey": "features", "content": "털색, 크기, 목줄 등 특징을 적어 주세요", "x": 82, "y": 688, "width": 630, "height": 150, "fontSize": 20, "color": "#48443d", "zIndex": 4},
            {"id": "contact", "type": "text", "label": "연락처", "fieldKey": "contact", "content": "연락처를 입력해 주세요", "x": 80, "y": 930, "width": 634, "height": 68, "fontSize": 26, "color": "#35604c", "fontStyle": "bold", "align": "center", "zIndex": 5},
        ],
    },
    {
        "id": "urgent", "name": "긴급형", "description": "강조색과 큰 연락처를 사용하는 디자인",
        "width": 794, "height": 1123,
        "components": [
            {"id": "title", "type": "text", "label": "전단지 제목", "fieldKey": "title", "content": "긴급히 찾고 있습니다", "x": 42, "y": 38, "width": 710, "height": 88, "fontSize": 40, "color": "#ffffff", "fontStyle": "bold", "align": "center", "fill": "#d34435", "zIndex": 2},
            {"id": "photo", "type": "image", "label": "반려동물 사진", "assetId": None, "x": 100, "y": 165, "width": 594, "height": 460, "opacity": 1, "zIndex": 1},
            {"id": "name", "type": "text", "label": "동물 이름", "fieldKey": "pet_name", "content": "이름을 입력해 주세요", "x": 54, "y": 665, "width": 686, "height": 56, "fontSize": 32, "color": "#34302a", "fontStyle": "bold", "align": "center", "zIndex": 3},
            {"id": "place", "type": "text", "label": "실종 장소", "fieldKey": "lost_place", "content": "실종 장소와 날짜를 입력해 주세요", "x": 60, "y": 748, "width": 674, "height": 64, "fontSize": 21, "color": "#51493f", "align": "center", "zIndex": 4},
            {"id": "contact", "type": "text", "label": "긴급 연락처", "fieldKey": "contact", "content": "발견 즉시 연락 주세요", "x": 40, "y": 916, "width": 714, "height": 105, "fontSize": 34, "color": "#ffffff", "fontStyle": "bold", "align": "center", "fill": "#d34435", "zIndex": 5},
        ],
    },
]


class PosterBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    template_id: str = Field(alias="templateId", min_length=1, max_length=40)
    width: int = Field(ge=100, le=3000)
    height: int = Field(ge=100, le=4000)
    components: list[dict[str, Any]] = Field(max_length=100)


def _validate_document(body: PosterBody) -> dict[str, Any]:
    if body.template_id not in {item["id"] for item in TEMPLATES}:
        raise ApiError(422, "poster_component_invalid", "등록된 템플릿을 선택해 주세요.")
    ids: set[str] = set()
    for component in body.components:
        component_id = str(component.get("id", ""))
        kind = component.get("type")
        if not ID_RE.fullmatch(component_id) or component_id in ids:
            raise ApiError(422, "poster_component_invalid", "전단지 구성 요소 ID를 확인해 주세요.")
        ids.add(component_id)
        if kind not in {"text", "image", "shape"}:
            raise ApiError(422, "poster_component_invalid", "지원하지 않는 전단지 구성 요소입니다.")
        for key in ("x", "y", "width", "height"):
            value = component.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or abs(value) > 5000 or not math.isfinite(value):
                raise ApiError(422, "poster_component_invalid", "구성 요소의 위치와 크기를 확인해 주세요.")
        if component["width"] <= 0 or component["height"] <= 0:
            raise ApiError(422, "poster_component_invalid", "구성 요소의 크기는 0보다 커야 합니다.")
        if kind == "text" and len(str(component.get("content", ""))) > 2000:
            raise ApiError(422, "poster_component_invalid", "텍스트는 2,000자 이하로 입력해 주세요.")
    return {"templateId": body.template_id, "width": body.width, "height": body.height, "components": body.components}


@router.get("/poster/templates")
async def list_templates():
    return {"items": [{k: v for k, v in template.items() if k != "components"} for template in TEMPLATES]}


@router.get("/poster/templates/{template_id}")
async def get_template(template_id: str):
    template = next((item for item in TEMPLATES if item["id"] == template_id), None)
    if template is None:
        raise ApiError(404, "poster_template_not_found", "전단지 템플릿을 찾을 수 없습니다.")
    return template


@router.post("/poster/assets", status_code=201)
async def upload_asset(
    file: UploadFile = File(...),
    ctx: AppContext = Depends(get_ctx),
    user=Depends(current_user),
):
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ApiError(413, "poster_asset_too_large", "사진은 15MB 이하로 올려 주세요.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ALLOWED_FORMATS:
                    raise ApiError(415, "poster_asset_format", "JPG, PNG, WebP 사진만 올릴 수 있어요.")
                if image.width * image.height > MAX_PIXELS:
                    raise ApiError(413, "poster_asset_pixels", "사진 해상도가 너무 큽니다.")
                image.load()
                normalized = ImageOps.exif_transpose(image)
                normalized.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
                if normalized.mode not in {"RGB", "RGBA"}:
                    normalized = normalized.convert("RGBA" if "transparency" in normalized.info else "RGB")
                output = io.BytesIO()
                normalized.save(output, format="WEBP", quality=85, method=6)
                width, height = normalized.size
    except ApiError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ApiError(422, "poster_asset_invalid", "이미지 파일을 읽을 수 없습니다.")

    asset_id = uuid.uuid4().hex
    await ctx.store.put(user.owner, "asset", asset_id, {"content": base64.b64encode(output.getvalue()).decode("ascii"), "width": width, "height": height})
    return {"assetId": asset_id, "url": f"/poster/assets/{asset_id}", "width": width, "height": height, "format": "webp"}


@router.get("/poster/assets/{asset_id}")
async def get_asset(asset_id: str, user=Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    if not re.fullmatch(r"[0-9a-f]{32}", asset_id):
        raise ApiError(404, "poster_asset_not_found", "사진을 찾을 수 없습니다.")
    asset = await ctx.store.get(user.owner, "asset", asset_id)
    if not asset:
        raise ApiError(404, "poster_asset_not_found", "사진을 찾을 수 없습니다.")
    return Response(base64.b64decode(asset["content"]), media_type="image/webp", headers={"Cache-Control": "private, max-age=3600"})


@router.post("/posters", status_code=201)
async def create_poster(body: PosterBody, user=Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    doc = _validate_document(body)
    poster_id = uuid.uuid4().hex
    await ctx.store.put(user.owner, "poster", poster_id, doc)
    return {"id": poster_id, **doc}


@router.get("/posters/{poster_id}")
async def read_poster(poster_id: str, user=Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    if not re.fullmatch(r"[0-9a-f]{32}", poster_id):
        raise ApiError(404, "poster_not_found", "전단지를 찾을 수 없습니다.")
    doc = await ctx.store.get(user.owner, "poster", poster_id)
    if not doc:
        raise ApiError(404, "poster_not_found", "전단지를 찾을 수 없습니다.")
    return {"id": poster_id, **doc}


@router.put("/posters/{poster_id}")
async def update_poster(poster_id: str, body: PosterBody, user=Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    if not re.fullmatch(r"[0-9a-f]{32}", poster_id):
        raise ApiError(404, "poster_not_found", "전단지를 찾을 수 없습니다.")
    if not await ctx.store.get(user.owner, "poster", poster_id):
        raise ApiError(404, "poster_not_found", "전단지를 찾을 수 없습니다.")
    doc = _validate_document(body)
    await ctx.store.put(user.owner, "poster", poster_id, doc)
    return {"id": poster_id, **doc}


@router.delete("/posters/{poster_id}", status_code=204)
async def delete_poster(poster_id: str, user=Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    if not re.fullmatch(r"[0-9a-f]{32}", poster_id) or not await ctx.store.delete(user.owner, "poster", poster_id):
        raise ApiError(404, "poster_not_found", "전단지를 찾을 수 없습니다.")
