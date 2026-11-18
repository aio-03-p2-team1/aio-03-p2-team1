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
from backend.routers import posts as board
from backend.tools.lost_animal_api import LostAnimalApiError

router = APIRouter(tags=["posters"])
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_PIXELS = 25_000_000
MAX_SIDE = 2000
MAX_POSTERS_PER_USER = 5
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")

TEMPLATES: list[dict[str, Any]] = [
    {
        'id': 'basic', 'name': '사진 중심형', 'description': '화이트 · 네이비 / 큰 사진과 중앙 정렬', 'width': 794, 'height': 1123,
        "components": [
            {'id': 'paper', 'type': 'shape', 'label': '배경 · 구분선', 'x': 0, 'y': 0, 'width': 794, 'height': 1123, 'fill': '#FFFFFF', 'stroke': '#FFFFFF', 'strokeWidth': 0, 'zIndex': 0},
            {'id': 'title', 'type': 'text', 'label': '전단지 제목', 'content': '강아지를 찾습니다', 'x': 48, 'y': 34, 'width': 698, 'height': 82, 'fontSize': 52, 'color': '#142D4E', 'align': 'center', 'fontStyle': 'bold', 'zIndex': 3, 'fieldKey': 'title'},
            {'id': 'photo', 'type': 'image', 'label': '반려동물 사진', 'assetId': None, 'x': 72, 'y': 138, 'width': 650, 'height': 422, 'opacity': 1, 'zIndex': 1},
            {'id': 'pet_name', 'type': 'text', 'label': '동물 이름', 'content': '이름을 입력해 주세요', 'x': 48, 'y': 576, 'width': 698, 'height': 52, 'fontSize': 32, 'color': '#142D4E', 'align': 'center', 'fontStyle': 'bold', 'zIndex': 3, 'fieldKey': 'pet_name'},
            {'id': 'species_breed', 'type': 'text', 'label': '종류 · 품종', 'content': '종류와 품종을 입력해 주세요', 'x': 48, 'y': 632, 'width': 698, 'height': 40, 'fontSize': 23, 'color': '#142D4E', 'align': 'center', 'fontStyle': 'normal', 'zIndex': 3, 'fieldKey': 'species_breed'},
            {'id': 'when-label', 'type': 'text', 'label': '실종 일시', 'content': '실종 일시', 'x': 48, 'y': 686, 'width': 130, 'height': 34, 'fontSize': 20, 'color': '#142D4E', 'align': 'left', 'fontStyle': 'bold', 'zIndex': 3},
            {'id': 'lost_datetime', 'type': 'text', 'label': '실종 일시', 'content': '실종 날짜와 시간을 입력해 주세요', 'x': 190, 'y': 680, 'width': 556, 'height': 48, 'fontSize': 24, 'color': '#142D4E', 'align': 'left', 'fontStyle': 'normal', 'zIndex': 3, 'fieldKey': 'lost_datetime'},
            {'id': 'where-label', 'type': 'text', 'label': '실종 장소', 'content': '실종 장소', 'x': 48, 'y': 746, 'width': 130, 'height': 34, 'fontSize': 20, 'color': '#142D4E', 'align': 'left', 'fontStyle': 'bold', 'zIndex': 3},
            {'id': 'lost_place', 'type': 'text', 'label': '마지막 목격 장소', 'content': '마지막 목격 장소를 입력해 주세요', 'x': 190, 'y': 734, 'width': 556, 'height': 76, 'fontSize': 25, 'color': '#142D4E', 'align': 'left', 'fontStyle': 'normal', 'zIndex': 3, 'fieldKey': 'lost_place'},
            {'id': 'features', 'type': 'text', 'label': '외형 · 식별 특징', 'content': '털색, 크기, 목줄 등 특징을 적어 주세요', 'x': 48, 'y': 822, 'width': 698, 'height': 72, 'fontSize': 24, 'color': '#142D4E', 'align': 'left', 'fontStyle': 'normal', 'zIndex': 3, 'fieldKey': 'features'},
            {'id': 'extra_description', 'type': 'text', 'label': '추가 안내', 'content': '추가 안내를 입력해 주세요', 'x': 48, 'y': 902, 'width': 698, 'height': 44, 'fontSize': 20, 'color': '#142D4E', 'align': 'left', 'fontStyle': 'normal', 'zIndex': 3, 'fieldKey': 'extra_description'},
            {'id': 'contact-band', 'type': 'shape', 'label': '배경 · 구분선', 'x': 32, 'y': 968, 'width': 730, 'height': 123, 'fill': '#142D4E', 'stroke': '#142D4E', 'strokeWidth': 0, 'zIndex': 0},
            {'id': 'contact-label', 'type': 'text', 'label': '보셨다면 연락해 주세요', 'content': '보셨다면 연락해 주세요', 'x': 48, 'y': 976, 'width': 698, 'height': 30, 'fontSize': 18, 'color': '#FFFFFF', 'align': 'center', 'fontStyle': 'bold', 'zIndex': 3},
            {'id': 'contact', 'type': 'text', 'label': '발견 시 연락처', 'content': '연락처를 입력해 주세요', 'x': 48, 'y': 1010, 'width': 698, 'height': 66, 'fontSize': 38, 'color': '#FFFFFF', 'align': 'center', 'fontStyle': 'bold', 'zIndex': 3, 'fieldKey': 'contact'},
        ],
    },
    {
        'id': 'info', 'name': '정보 전달형', 'description': '민트 · 딥그린 / 사진 옆 이름과 항목별 정보', 'width': 794, 'height': 1123,
        "components": [
            {'id': 'paper', 'type': 'shape', 'label': '배경 · 구분선', 'x': 0, 'y': 0, 'width': 794, 'height': 1123, 'fill': '#EEF5F1', 'stroke': '#EEF5F1', 'strokeWidth': 0, 'zIndex': 0},
            {'id': 'accent', 'type': 'shape', 'label': '배경 · 구분선', 'x': 40, 'y': 40, 'width': 8, 'height': 102, 'fill': '#163E32', 'stroke': '#163E32', 'strokeWidth': 0, 'zIndex': 0},
            {'id': 'title', 'type': 'text', 'label': '전단지 제목', 'content': '이 아이를 보셨나요?', 'x': 64, 'y': 38, 'width': 682, 'height': 78, 'fontSize': 46, 'color': '#163E32', 'align': 'left', 'fontStyle': 'bold', 'zIndex': 3, 'fieldKey': 'title'},
            {'id': 'subtitle', 'type': 'text', 'label': '사진과 특징을 확인해 주세요', 'content': '사진과 특징을 확인해 주세요', 'x': 64, 'y': 116, 'width': 682, 'height': 34, 'fontSize': 21, 'color': '#163E32', 'align': 'left', 'fontStyle': 'normal', 'zIndex': 3},
            {'id': 'photo', 'type': 'image', 'label': '반려동물 사진', 'assetId': None, 'x': 48, 'y': 174, 'width': 360, 'height': 330, 'opacity': 1, 'zIndex': 1},
            {'id': 'pet_name', 'type': 'text', 'label': '동물 이름', 'content': '이름을 입력해 주세요', 'x': 436, 'y': 190, 'width': 310, 'height': 108, 'fontSize': 32, 'color': '#163E32', 'align': 'left', 'fontStyle': 'bold', 'zIndex': 3, 'fieldKey': 'pet_name'},
            {'id': 'species_breed', 'type': 'text', 'label': '종류 · 품종', 'content': '종류와 품종을 입력해 주세요', 'x': 436, 'y': 314, 'width': 310, 'height': 100, 'fontSize': 24, 'color': '#163E32', 'align': 'left', 'fontStyle': 'normal', 'zIndex': 3, 'fieldKey': 'species_breed'},
            {'id': 'photo-note', 'type': 'text', 'label': '이름 · 종류 · 품종', 'content': '이름 · 종류 · 품종', 'x': 436, 'y': 438, 'width': 310, 'height': 38, 'fontSize': 19, 'color': '#163E32', 'align': 'left', 'fontStyle': 'normal', 'zIndex': 3},
            {'id': 'rule', 'type': 'shape', 'label': '배경 · 구분선', 'x': 48, 'y': 530, 'width': 698, 'height': 2, 'fill': '#163E32', 'stroke': '#163E32', 'strokeWidth': 0, 'zIndex': 0},
            {'id': 'features-label', 'type': 'text', 'label': '외형 · 식별 특징', 'content': '외형 · 식별 특징', 'x': 48, 'y': 548, 'width': 154, 'height': 92, 'fontSize': 19, 'color': '#163E32', 'align': 'left', 'fontStyle': 'bold', 'zIndex': 3},
            {'id': 'features', 'type': 'text', 'label': '외형 · 식별 특징', 'content': '털색, 크기, 목줄 등 특징을 적어 주세요', 'x': 218, 'y': 548, 'width': 528, 'height': 92, 'fontSize': 27, 'color': '#163E32', 'align': 'left', 'fontStyle': 'bold', 'zIndex': 3, 'fieldKey': 'features'},
            {'id': 'lost_place-label', 'type': 'text', 'label': '마지막 목격 장소', 'content': '마지막 목격 장소', 'x': 48, 'y': 656, 'width': 154, 'height': 74, 'fontSize': 19, 'color': '#163E32', 'align': 'left', 'fontStyle': 'bold', 'zIndex': 3},
            {'id': 'lost_place', 'type': 'text', 'label': '마지막 목격 장소', 'content': '마지막 목격 장소를 입력해 주세요', 'x': 218, 'y': 656, 'width': 528, 'height': 74, 'fontSize': 25, 'color': '#163E32', 'align': 'left', 'fontStyle': 'normal', 'zIndex': 3, 'fieldKey': 'lost_place'},
            {'id': 'lost_datetime-label', 'type': 'text', 'label': '실종 일시', 'content': '실종 일시', 'x': 48, 'y': 746, 'width': 154, 'height': 66, 'fontSize': 19, 'color': '#163E32', 'align': 'left', 'fontStyle': 'bold', 'zIndex': 3},
            {'id': 'lost_datetime', 'type': 'text', 'label': '실종 일시', 'content': '실종 날짜와 시간을 입력해 주세요', 'x': 218, 'y': 746, 'width': 528, 'height': 66, 'fontSize': 24, 'color': '#163E32', 'align': 'left', 'fontStyle': 'normal', 'zIndex': 3, 'fieldKey': 'lost_datetime'},
            {'id': 'extra_description-label', 'type': 'text', 'label': '추가 안내', 'content': '추가 안내', 'x': 48, 'y': 828, 'width': 154, 'height': 62, 'fontSize': 19, 'color': '#163E32', 'align': 'left', 'fontStyle': 'bold', 'zIndex': 3},
            {'id': 'extra_description', 'type': 'text', 'label': '추가 안내', 'content': '추가 안내를 입력해 주세요', 'x': 218, 'y': 828, 'width': 528, 'height': 62, 'fontSize': 22, 'color': '#163E32', 'align': 'left', 'fontStyle': 'normal', 'zIndex': 3, 'fieldKey': 'extra_description'},
            {'id': 'contact-band', 'type': 'shape', 'label': '배경 · 구분선', 'x': 48, 'y': 944, 'width': 698, 'height': 145, 'fill': '#163E32', 'stroke': '#163E32', 'strokeWidth': 0, 'zIndex': 0},
            {'id': 'contact-label', 'type': 'text', 'label': '발견하시면 연락 부탁드립니다', 'content': '발견하시면 연락 부탁드립니다', 'x': 64, 'y': 954, 'width': 666, 'height': 34, 'fontSize': 19, 'color': '#FFFFFF', 'align': 'left', 'fontStyle': 'bold', 'zIndex': 3},
            {'id': 'contact', 'type': 'text', 'label': '발견 시 연락처', 'content': '연락처를 입력해 주세요', 'x': 64, 'y': 994, 'width': 666, 'height': 76, 'fontSize': 36, 'color': '#FFFFFF', 'align': 'left', 'fontStyle': 'bold', 'zIndex': 3, 'fieldKey': 'contact'},
        ],
    },
    {
        'id': 'urgent', 'name': '긴급 주목형', 'description': '노랑 · 검정 / 큰 제목과 목격 장소 강조', 'width': 794, 'height': 1123,
        "components": [
            {'id': 'paper', 'type': 'shape', 'label': '배경 · 구분선', 'x': 0, 'y': 0, 'width': 794, 'height': 1123, 'fill': '#FFFFFF', 'stroke': '#FFFFFF', 'strokeWidth': 0, 'zIndex': 0},
            {'id': 'header-band', 'type': 'shape', 'label': '배경 · 구분선', 'x': 0, 'y': 0, 'width': 794, 'height': 164, 'fill': '#FFE34D', 'stroke': '#FFE34D', 'strokeWidth': 0, 'zIndex': 0},
            {'id': 'alert', 'type': 'text', 'label': '반려동물 실종', 'content': '반려동물 실종', 'x': 40, 'y': 20, 'width': 714, 'height': 34, 'fontSize': 23, 'color': '#B42318', 'align': 'center', 'fontStyle': 'bold', 'zIndex': 3},
            {'id': 'title', 'type': 'text', 'label': '전단지 제목', 'content': '실종 · 찾습니다', 'x': 40, 'y': 58, 'width': 714, 'height': 88, 'fontSize': 60, 'color': '#151515', 'align': 'center', 'fontStyle': 'bold', 'zIndex': 3, 'fieldKey': 'title'},
            {'id': 'photo', 'type': 'image', 'label': '반려동물 사진', 'assetId': None, 'x': 48, 'y': 188, 'width': 698, 'height': 370, 'opacity': 1, 'zIndex': 1},
            {'id': 'pet_name', 'type': 'text', 'label': '동물 이름', 'content': '이름을 입력해 주세요', 'x': 48, 'y': 574, 'width': 390, 'height': 50, 'fontSize': 32, 'color': '#151515', 'align': 'left', 'fontStyle': 'bold', 'zIndex': 3, 'fieldKey': 'pet_name'},
            {'id': 'species_breed', 'type': 'text', 'label': '종류 · 품종', 'content': '종류와 품종을 입력해 주세요', 'x': 450, 'y': 576, 'width': 296, 'height': 48, 'fontSize': 23, 'color': '#151515', 'align': 'right', 'fontStyle': 'normal', 'zIndex': 3, 'fieldKey': 'species_breed'},
            {'id': 'place-band', 'type': 'shape', 'label': '배경 · 구분선', 'x': 40, 'y': 640, 'width': 714, 'height': 140, 'fill': '#FFE34D', 'stroke': '#FFE34D', 'strokeWidth': 0, 'zIndex': 0},
            {'id': 'where-label', 'type': 'text', 'label': '마지막으로 목격된 장소', 'content': '마지막으로 목격된 장소', 'x': 56, 'y': 648, 'width': 682, 'height': 32, 'fontSize': 20, 'color': '#151515', 'align': 'left', 'fontStyle': 'bold', 'zIndex': 3},
            {'id': 'lost_place', 'type': 'text', 'label': '마지막 목격 장소', 'content': '마지막 목격 장소를 입력해 주세요', 'x': 56, 'y': 686, 'width': 682, 'height': 82, 'fontSize': 30, 'color': '#151515', 'align': 'left', 'fontStyle': 'bold', 'zIndex': 3, 'fieldKey': 'lost_place'},
            {'id': 'lost_datetime', 'type': 'text', 'label': '실종 일시', 'content': '실종 날짜와 시간을 입력해 주세요', 'x': 48, 'y': 796, 'width': 698, 'height': 56, 'fontSize': 24, 'color': '#151515', 'align': 'left', 'fontStyle': 'normal', 'zIndex': 3, 'fieldKey': 'lost_datetime'},
            {'id': 'features', 'type': 'text', 'label': '외형 · 식별 특징', 'content': '털색, 크기, 목줄 등 특징을 적어 주세요', 'x': 48, 'y': 864, 'width': 698, 'height': 64, 'fontSize': 24, 'color': '#151515', 'align': 'left', 'fontStyle': 'normal', 'zIndex': 3, 'fieldKey': 'features'},
            {'id': 'extra_description', 'type': 'text', 'label': '추가 안내', 'content': '추가 안내를 입력해 주세요', 'x': 48, 'y': 936, 'width': 698, 'height': 40, 'fontSize': 20, 'color': '#151515', 'align': 'left', 'fontStyle': 'normal', 'zIndex': 3, 'fieldKey': 'extra_description'},
            {'id': 'contact-band', 'type': 'shape', 'label': '배경 · 구분선', 'x': 0, 'y': 994, 'width': 794, 'height': 129, 'fill': '#151515', 'stroke': '#151515', 'strokeWidth': 0, 'zIndex': 0},
            {'id': 'contact-label', 'type': 'text', 'label': '보셨다면 바로 연락해 주세요', 'content': '보셨다면 바로 연락해 주세요', 'x': 40, 'y': 1002, 'width': 714, 'height': 30, 'fontSize': 20, 'color': '#FFE34D', 'align': 'center', 'fontStyle': 'bold', 'zIndex': 3},
            {'id': 'contact', 'type': 'text', 'label': '발견 시 연락처', 'content': '연락처를 입력해 주세요', 'x': 40, 'y': 1040, 'width': 714, 'height': 66, 'fontSize': 40, 'color': '#FFFFFF', 'align': 'center', 'fontStyle': 'bold', 'zIndex': 3, 'fieldKey': 'contact'},
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
        if not isinstance(kind, str) or kind not in {"text", "image", "shape"}:
            raise ApiError(422, "poster_component_invalid", "지원하지 않는 전단지 구성 요소입니다.")
        for key in ("x", "y", "width", "height"):
            value = component.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or abs(value) > 5000 or not math.isfinite(value):
                raise ApiError(422, "poster_component_invalid", "구성 요소의 위치와 크기를 확인해 주세요.")
        if component["width"] <= 0 or component["height"] <= 0:
            raise ApiError(422, "poster_component_invalid", "구성 요소의 크기는 0보다 커야 합니다.")
        if kind == "text":
            content = component.get("content", "")
            if not isinstance(content, str) or len(content) > 2000:
                raise ApiError(422, "poster_component_invalid", "텍스트는 2,000자 이하로 입력해 주세요.")
        for key in ("label", "fieldKey"):
            if key in component and (not isinstance(component[key], str) or len(component[key]) > 100):
                raise ApiError(422, "poster_component_invalid", "구성 요소 이름을 확인해 주세요.")
        for key, minimum, maximum in (
            ("rotation", -360, 360), ("opacity", 0, 1), ("fontSize", 6, 200),
            ("strokeWidth", 0, 50), ("cropX", 0, 1), ("cropY", 0, 1),
            ("cropZoom", 1, 3), ("zIndex", 0, 1000),
        ):
            value = component.get(key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum):
                raise ApiError(422, "poster_component_invalid", "구성 요소의 디자인 값을 확인해 주세요.")
        for key in ("color", "fill", "stroke"):
            value = component.get(key)
            if value is not None and (not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value)):
                raise ApiError(422, "poster_component_invalid", "색상 값을 확인해 주세요.")
        font_style = component.get("fontStyle", "normal")
        align = component.get("align", "left")
        if not isinstance(font_style, str) or font_style not in {"normal", "bold"} or not isinstance(align, str) or align not in {"left", "center", "right"}:
            raise ApiError(422, "poster_component_invalid", "텍스트 스타일을 확인해 주세요.")
        if kind == "image" and component.get("assetId") is not None and not re.fullmatch(r"[0-9a-f]{32}", str(component["assetId"])):
            raise ApiError(422, "poster_component_invalid", "이미지 자산 ID를 확인해 주세요.")
    return {"templateId": body.template_id, "width": body.width, "height": body.height, "components": body.components}


async def _check_asset_ownership(doc: dict[str, Any], owner: str, ctx: AppContext) -> None:
    for component in doc["components"]:
        asset_id = component.get("assetId") if component.get("type") == "image" else None
        if asset_id and not await ctx.store.get(owner, "asset", asset_id):
            raise ApiError(422, "poster_asset_unavailable", "사용할 수 없는 사진입니다. 다시 업로드해 주세요.")


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
    return await _store_asset(raw, user.owner, ctx)


class FromPostBody(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    post_id: str = Field(alias="postId", min_length=1, max_length=80)


@router.post("/poster/assets/from-post", status_code=201)
async def asset_from_post(body: FromPostBody, ctx: AppContext = Depends(get_ctx), user=Depends(current_user)):
    """실종 정보 게시판 글의 사진을 전단지 자산으로 복사한다.

    회원 글은 저장된 사진을, 분실 신고는 원본의 사진 주소를 서버가 받아 온다(브라우저는 외부 사진을 CORS 로 못 읽음).
    사진 주소는 클라이언트가 보내지 않고 게시글 ID 로 서버가 찾는다.
    """
    post_id = body.post_id
    if board._POST_ID.match(post_id):
        photo = (await board._get(ctx, post_id)).get("photo")
        if not photo or photo.get("type") not in board.PHOTO_TYPES:
            raise ApiError(404, "photo_not_found", "사진이 없는 게시글입니다.")
        raw = base64.b64decode(photo["data"])
    elif board._LOST_ID.match(post_id) and ctx.lost is not None:
        try:
            item = await ctx.lost.get(post_id)
            if not item:
                raise ApiError(404, "post_not_found", "게시글을 찾을 수 없습니다.")
            if not item.get("photo_url"):
                raise ApiError(404, "photo_not_found", "사진이 없는 게시글입니다.")
            raw = await ctx.lost.api.fetch_photo(item["photo_url"], MAX_UPLOAD_BYTES)
        except LostAnimalApiError as exc:
            raise ApiError(502, "poster_photo_unavailable", "분실 신고 사진을 가져오지 못했어요. 사진을 직접 올려 주세요.") from exc
    else:
        raise ApiError(404, "post_not_found", "게시글을 찾을 수 없습니다.")
    return await _store_asset(raw, user.owner, ctx)


async def _store_asset(raw: bytes, owner: str, ctx: AppContext) -> dict[str, Any]:
    """이미지 바이트를 검증·축소·WebP 로 바꿔 사용자 자산으로 저장한다(메타데이터 제거)."""
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
    await ctx.store.put(owner, "asset", asset_id, {"content": base64.b64encode(output.getvalue()).decode("ascii"), "width": width, "height": height})
    return {"assetId": asset_id, "url": f"/poster/assets/{asset_id}", "width": width, "height": height, "format": "webp"}


@router.get("/poster/assets/{asset_id}")
async def get_asset(asset_id: str, user=Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    if not re.fullmatch(r"[0-9a-f]{32}", asset_id):
        raise ApiError(404, "poster_asset_not_found", "사진을 찾을 수 없습니다.")
    asset = await ctx.store.get(user.owner, "asset", asset_id)
    if not asset:
        raise ApiError(404, "poster_asset_not_found", "사진을 찾을 수 없습니다.")
    return Response(base64.b64decode(asset["content"]), media_type="image/webp", headers={"Cache-Control": "private, max-age=3600"})


MAX_POSTERS_LISTED = 50  # 마이페이지 '내가 만든 전단지' 목록 최대 개수(최근 수정 순)


def _field(doc: dict[str, Any], key: str) -> str:
    for component in doc.get("components") or []:
        if component.get("fieldKey") == key and isinstance(component.get("content"), str):
            return component["content"].strip()[:120]
    return ""


def _summary(poster_id: str, doc: dict[str, Any], updated_at: Any) -> dict[str, Any]:
    """목록용 요약: 제목·이름·장소 문구와 첫 사진 자산 ID 만 돌려준다(구성 요소 전체는 상세에서)."""
    template_names = {item["id"]: item["name"] for item in TEMPLATES}
    photo = next((c.get("assetId") for c in doc.get("components") or [] if c.get("type") == "image" and c.get("assetId")), None)
    return {
        "id": poster_id,
        "template_id": doc.get("templateId"),
        "template_name": template_names.get(doc.get("templateId"), "전단지"),
        "title": _field(doc, "title"),
        "pet_name": _field(doc, "pet_name"),
        "lost_place": _field(doc, "lost_place"),
        "photo_asset_id": photo,
        "updated_at": updated_at,
    }


@router.get("/posters")
async def list_posters(user=Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    """로그인 사용자가 저장한 전단지 목록(최근 수정 순). 다른 사람 전단지는 소유자 키가 달라 보이지 않는다."""
    rows = await ctx.store.list(user.owner, "poster", MAX_POSTERS_LISTED)
    items = [_summary(r["id"], r["data"], r.get("updated_at")) for r in rows]
    return {"items": items, "count": len(items), "limit": MAX_POSTERS_PER_USER}


@router.post("/posters", status_code=201)
async def create_poster(body: PosterBody, user=Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    doc = _validate_document(body)
    rows = await ctx.store.list(user.owner, "poster", limit=MAX_POSTERS_PER_USER)
    if len(rows) >= MAX_POSTERS_PER_USER:
        raise ApiError(422, "poster_limit", "전단지는 사용자당 5개까지 저장할 수 있어요. 마이페이지에서 기존 전단지를 삭제해 주세요.")
    await _check_asset_ownership(doc, user.owner, ctx)
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
    await _check_asset_ownership(doc, user.owner, ctx)
    await ctx.store.put(user.owner, "poster", poster_id, doc)
    return {"id": poster_id, **doc}


@router.delete("/posters/{poster_id}", status_code=204)
async def delete_poster(poster_id: str, user=Depends(current_user), ctx: AppContext = Depends(get_ctx)):
    if not re.fullmatch(r"[0-9a-f]{32}", poster_id) or not await ctx.store.delete(user.owner, "poster", poster_id):
        raise ApiError(404, "poster_not_found", "전단지를 찾을 수 없습니다.")
