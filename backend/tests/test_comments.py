"""실종 정보 게시판 댓글: 공개 읽기, 로그인 작성, 작성자만 삭제, 연락처 가림, 분실 신고 댓글, 글 삭제 시 함께 삭제.

분실 신고 API 는 가짜 객체로 대체한다(실제 호출 없음).
"""

from datetime import timedelta

from fastapi.testclient import TestClient

from backend.main import create_app
from backend.routers.comments import COMMENT_LIMIT_PER_MINUTE, KIND, comment_owner
from backend.routers.posts import kst_today
from backend.tools.lost_animal_api import CONTACT_MASK, normalize_lost
from backend.tools.lost_feed import LostFeed

from .conftest import ORIGIN, build_ctx, signup
from .test_lost_board import FakeLostApi, raw


def post_body(**over):
    data = {
        "pet_name": "초코", "species": "dog", "region": "서울특별시",
        "lost_date": (kst_today() - timedelta(days=2)).isoformat(), "breed": "푸들",
        "description": "갈색 작은 강아지, 노란 목줄",
    }
    data.update(over)
    return data


def make(api=None):
    ctx = build_ctx()
    ctx.lost = LostFeed(api) if api is not None else None
    return ctx, TestClient(create_app(ctx), headers={"Origin": ORIGIN})


def test_member_post_comments_public_read_login_write_author_delete():
    ctx, client = make()
    with client:
        signup(client, "a@example.com")
        post = client.post("/api/v1/posts", json=post_body()).json()
        url = f"/api/v1/posts/{post['id']}/comments"
        created = client.post(url, json={"body": "  어제 강서구청 근처에서 비슷한 아이를 봤어요  "})
        assert created.status_code == 201
        comment = created.json()
        assert comment["body"] == "어제 강서구청 근처에서 비슷한 아이를 봤어요" and comment["mine"] is True
        assert "author" not in comment and comment["author_name"]
        client.post("/api/v1/auth/logout")

        # 비로그인: 읽기는 되고 쓰기는 401
        listed = client.get(url).json()
        assert listed["count"] == 1 and listed["items"][0]["mine"] is False and "author" not in listed["items"][0]
        assert client.post(url, json={"body": "안녕하세요"}).status_code == 401

        # 다른 사용자는 남의 댓글을 지울 수 없다
        signup(client, "b@example.com")
        assert client.delete(f"{url}/{comment['id']}").status_code == 403
        mine = client.post(url, json={"body": "저도 찾아볼게요"}).json()
        items = client.get(url).json()["items"]
        assert [c["id"] for c in items] == [comment["id"], mine["id"]]  # 오래된 순
        assert client.delete(f"{url}/{mine['id']}").status_code == 204
        assert client.get(url).json()["count"] == 1


def test_comment_masks_phone_numbers_and_validates_length():
    _, client = make()
    with client:
        signup(client)
        post = client.post("/api/v1/posts", json=post_body()).json()
        url = f"/api/v1/posts/{post['id']}/comments"
        body = client.post(url, json={"body": "보신 분은 010-1234-5678 로 연락 주세요"}).json()["body"]
        assert "010" not in body and CONTACT_MASK in body
        assert client.post(url, json={"body": "   "}).status_code == 422
        assert client.post(url, json={"body": "가" * 501}).status_code == 422


def test_comment_on_missing_or_invalid_post():
    _, client = make()
    with client:
        signup(client)
        assert client.post(f"/api/v1/posts/{'0' * 32}/comments", json={"body": "있나요"}).status_code == 404
        assert client.get("/api/v1/posts/not-an-id/comments").status_code == 404
        assert client.delete(f"/api/v1/posts/{'0' * 32}/comments/{'1' * 32}").status_code == 404


def test_comment_on_lost_report_uses_computed_id():
    api = FakeLostApi({"dog": [raw(1)]})
    _, client = make(api)
    with client:
        signup(client)
        lost = normalize_lost(raw(1), "dog")["id"]
        assert lost.startswith("lost-")
        url = f"/api/v1/posts/{lost}/comments"
        created = client.post(url, json={"body": "이 아이 강동구에서 봤어요"})
        assert created.status_code == 201
        assert client.get(url).json()["items"][0]["body"] == "이 아이 강동구에서 봤어요"
        # 분실 신고 목록에 없는 ID 에는 쓸 수 없다
        missing = "lost-" + (kst_today() - timedelta(days=1)).strftime("%Y%m%d") + "-" + "0" * 12
        assert client.post(f"/api/v1/posts/{missing}/comments", json={"body": "있나요"}).status_code == 404


def test_lost_report_comments_need_lost_api():
    _, client = make(None)
    with client:
        signup(client)
        lost = normalize_lost(raw(1), "dog")["id"]
        assert client.post(f"/api/v1/posts/{lost}/comments", json={"body": "봤어요"}).status_code == 404


def test_comment_rate_limit():
    _, client = make()
    with client:
        signup(client)
        post = client.post("/api/v1/posts", json=post_body()).json()
        url = f"/api/v1/posts/{post['id']}/comments"
        codes = [client.post(url, json={"body": f"댓글 {i}"}).status_code for i in range(COMMENT_LIMIT_PER_MINUTE + 1)]
        assert codes[:-1] == [201] * COMMENT_LIMIT_PER_MINUTE and codes[-1] == 429


def test_deleting_post_deletes_its_comments():
    ctx, client = make()
    with client:
        signup(client)
        post = client.post("/api/v1/posts", json=post_body()).json()
        client.post(f"/api/v1/posts/{post['id']}/comments", json={"body": "찾았으면 좋겠어요"})
        assert client.delete(f"/api/v1/posts/{post['id']}").status_code == 204
        import asyncio

        assert asyncio.run(ctx.store.list(comment_owner(post["id"]), KIND, 10)) == []
