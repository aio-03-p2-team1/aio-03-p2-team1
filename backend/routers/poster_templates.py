"""Editable fields placed over the bundled SVG backgrounds."""

A4_ID = "lost-a4"
SHORTS_ID = "lost-shorts"


def _text(key, label, content, box, size, color, *, bold=False, align="left"):
    x, y, width, height = box
    return {
        "id": key, "type": "text", "fieldKey": key, "label": label, "content": content,
        "x": x, "y": y, "width": width, "height": height, "fontSize": size, "color": color,
        "fontStyle": "bold" if bold else "normal", "align": align, "zIndex": 3,
    }


def _template(template_id, name, description, size, photo_box, fields):
    width, height = size
    x, y, photo_width, photo_height = photo_box
    return {
        "id": template_id, "name": name, "description": description, "width": width, "height": height,
        "components": [
            {"id": "paper", "type": "background", "backgroundKey": template_id,
             "x": 0, "y": 0, "width": width, "height": height, "zIndex": 0},
            {"id": "photo", "type": "image", "label": "반려동물 사진", "assetId": None,
             "x": x, "y": y, "width": photo_width, "height": photo_height, "zIndex": 1},
            *fields,
        ],
    }


SVG_TEMPLATES = [
    _template(A4_ID, "A4 인쇄용", "794 × 1123", (794, 1123), (70, 418, 654, 241), [
        _text("title", "전단지 제목", "우리 아이를\n찾습니다.", (56, 108, 682, 174), 62, "#332F2B", bold=True),
        _text("pet_name", "동물 이름", "", (86, 734, 420, 58), 30, "#332F2B", bold=True),
        _text("species_breed", "종류 · 품종", "", (506, 743, 203, 44), 18, "#766D63", align="right"),
        _text("lost_datetime", "실종 일시", "", (86, 829, 304, 40), 18, "#332F2B"),
        _text("lost_place", "실종 장소", "", (416, 829, 294, 40), 18, "#332F2B"),
        _text("features", "신체적 특징", "", (86, 885, 304, 46), 17, "#332F2B"),
        _text("extra_description", "추가 안내", "", (416, 885, 294, 46), 17, "#332F2B"),
        _text("contact", "발견 시 연락처", "", (89, 1001, 526, 57), 40, "#FFFFFF", bold=True),
    ]),
    _template(SHORTS_ID, "Shorts 세로형 (9:16)", "720 × 1280", (720, 1280), (42, 406, 632, 294), [
        _text("title", "전단지 제목", "우리 아이를\n찾아주세요!", (34, 113, 643, 197), 72, "#FFFAF4", bold=True),
        _text("pet_name", "동물 이름", "", (114, 825, 335, 65), 29, "#FFFFFF", bold=True),
        _text("species_breed", "종류 · 품종", "", (450, 825, 225, 65), 22, "#FFFFFF", align="right"),
        _text("lost_datetime", "실종 일시", "", (138, 897, 225, 55), 20, "#FFFFFF"),
        _text("lost_place", "실종 장소", "", (426, 897, 249, 55), 20, "#FFFFFF"),
        _text("features", "신체적 특징", "", (97, 961, 578, 69), 22, "#FFFFFF"),
        _text("extra_description", "추가 안내", "", (39, 1087, 645, 80), 29, "#FFFFFF", bold=True),
        _text("contact", "발견 시 연락처", "", (61, 1178, 530, 71), 39, "#FFFAF4", bold=True),
    ]),
]

SVG_TEMPLATE_SIZES = {item["id"]: (item["width"], item["height"]) for item in SVG_TEMPLATES}
