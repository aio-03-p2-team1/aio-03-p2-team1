from __future__ import annotations

import base64
import binascii
import struct
import warnings
from io import BytesIO

from PIL import Image, UnidentifiedImageError

from backend.schemas.common import MAX_IMAGE_BYTES

MAX_IMAGE_PIXELS = 20_000_000
SUPPORTED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


class InvalidPhoto(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def decode_and_validate(encoded: str) -> tuple[bytes, str]:

    if len(encoded) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
        raise InvalidPhoto("photo_too_large", "사진은 8MB 이하로 선택해 주세요.")
    try:
        image_data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidPhoto("invalid_photo", "올바른 이미지 파일을 선택해 주세요.") from exc
    if not image_data:
        raise InvalidPhoto("invalid_photo", "올바른 이미지 파일을 선택해 주세요.")
    if len(image_data) > MAX_IMAGE_BYTES:
        raise InvalidPhoto("photo_too_large", "사진은 8MB 이하로 선택해 주세요.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(image_data)) as image:
                if image.format not in SUPPORTED_FORMATS:
                    raise InvalidPhoto("unsupported_photo_format", "JPG, PNG, WEBP 사진만 분석할 수 있어요.")
                width, height = image.size
                if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
                    raise InvalidPhoto("photo_too_many_pixels", "사진 크기는 최대 2,000만 픽셀까지 지원해요.")
                image.verify()
                return image_data, SUPPORTED_FORMATS[image.format]
    except InvalidPhoto:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
        EOFError,
        struct.error,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise InvalidPhoto("invalid_photo", "파일이 손상되었거나 올바른 이미지가 아니에요.") from exc


# ── 분석 전 사진 줄이기 ──────────────────────────────────────────────
# 비전 모델이 고해상도(detail=high)에서 원본 화소를 거의 그대로 처리해, 700만~900만 화소 사진 분석에 20초 넘게 걸렸다.
# 털색·크기·귀·옷·목줄 같은 특징은 긴 변 1024px 에서도 보이므로 분석 전에 줄인다(게시판 글쓰기 사진과 같은 크기).
# 부작용: 아주 작은 세부(이름표 글씨·작은 점)는 놓칠 수 있다. 원본은 지금처럼 저장하지 않는다.
ANALYSIS_MAX_SIDE = 1024
ANALYSIS_JPEG_QUALITY = 85


def shrink_for_analysis(image_data: bytes, mime_type: str) -> tuple[bytes, str]:
    """긴 변이 ANALYSIS_MAX_SIDE 를 넘으면 줄여 JPEG 로 바꾼다. 작은 사진은 그대로 둔다.

    휴대폰 사진의 방향 정보(EXIF)를 먼저 반영해 돌리고, 투명 배경은 흰색으로 채운다. 실패하면 원본을 그대로 쓴다.
    """
    from PIL import ImageOps

    try:
        with Image.open(BytesIO(image_data)) as opened:
            image = ImageOps.exif_transpose(opened)
            if max(image.size) <= ANALYSIS_MAX_SIDE:
                return image_data, mime_type
            image.thumbnail((ANALYSIS_MAX_SIDE, ANALYSIS_MAX_SIDE))
            if image.mode in ("RGBA", "LA", "P"):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")
            out = BytesIO()
            image.save(out, format="JPEG", quality=ANALYSIS_JPEG_QUALITY, optimize=True)
            return out.getvalue(), "image/jpeg"
    except (OSError, ValueError, Image.DecompressionBombError):
        return image_data, mime_type
