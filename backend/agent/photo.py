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
