"""게시글 음성 파일 형식·길이·소유권 및 파일별 변경 검증."""

import io
import wave

from fastapi.testclient import TestClient

from backend.main import create_app

from .conftest import ORIGIN, build_ctx, signup
from .test_posts import body


def wav(seconds=1):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 8000 * seconds)
    return stream.getvalue()


def test_voice_upload_read_delete_and_description_is_entity_encoded():
    ctx = build_ctx()
    with TestClient(create_app(ctx), headers={"Origin": ORIGIN}) as client:
        signup(client)
        post = client.post("/api/v1/posts", json=body()).json()
        url = f"/api/v1/posts/{post['id']}/voices"
        created = client.post(url, data={"description": '<초코 & "멍멍">'}, files={"audio": ("anything.bin", wav(), "application/octet-stream")})
        assert created.status_code == 201, created.text
        voice = created.json()
        detail = client.get(f"/api/v1/posts/{post['id']}").json()
        assert detail["voices"][0]["description"] == '<초코 & "멍멍">'
        assert voice["content_type"] == "audio/wav" and voice["duration"] == 1
        audio = client.get(f"{url}/{voice['id']}/audio")
        assert audio.status_code == 200 and audio.content == wav()
        assert client.delete(f"{url}/{voice['id']}").status_code == 204
        assert client.get(f"{url}/{voice['id']}/audio").status_code == 404
        assert client.get(f"/api/v1/posts/{post['id']}").json()["voices"] == []


def test_voice_limit_owner_and_duration_validation():
    ctx = build_ctx()
    with TestClient(create_app(ctx), headers={"Origin": ORIGIN}) as client:
        signup(client, "owner@example.com")
        post = client.post("/api/v1/posts", json=body()).json()
        url = f"/api/v1/posts/{post['id']}/voices"
        voices = []
        for n in range(3):
            response = client.post(url, data={"description": f"녹음 {n}"}, files={"audio": ("voice.wav", wav(), "audio/wav")})
            assert response.status_code == 201
            voices.append(response.json())
        limited = client.post(url, data={"description": "네 번째"}, files={"audio": ("voice.wav", wav(), "audio/wav")})
        assert limited.status_code == 422 and limited.json()["detail"]["code"] == "voice_limit"
        too_long = client.post(url, data={"description": "긴 음성"}, files={"audio": ("voice.wav", wav(61), "audio/wav")})
        assert too_long.status_code == 422 and too_long.json()["detail"]["code"] == "voice_too_long"
        client.post("/api/v1/auth/logout")
        signup(client, "other@example.com")
        assert client.delete(f"{url}/{voices[0]['id']}").status_code == 403


def test_voice_rejects_unrecognized_file():
    with TestClient(create_app(build_ctx()), headers={"Origin": ORIGIN}) as client:
        signup(client)
        post = client.post("/api/v1/posts", json=body()).json()
        response = client.post(
            f"/api/v1/posts/{post['id']}/voices",
            data={"description": "not audio"},
            files={"audio": ("fake.mp3", b"not an audio stream", "audio/mpeg")},
        )
        assert response.status_code == 422 and response.json()["detail"]["code"] == "voice_invalid"


def test_owner_can_edit_post_and_other_users_cannot():
    with TestClient(create_app(build_ctx()), headers={"Origin": ORIGIN}) as client:
        signup(client, "owner@example.com")
        post = client.post("/api/v1/posts", json=body()).json()
        update = {**body(pet_name="초코 수정", description="수정한 실종 정보입니다."), "breed_code": ""}
        assert client.patch(f"/api/v1/posts/{post['id']}", json=update).status_code == 200
        assert client.get(f"/api/v1/posts/{post['id']}").json()["pet_name"] == "초코 수정"
        client.post("/api/v1/auth/logout")
        signup(client, "other@example.com")
        denied = client.patch(f"/api/v1/posts/{post['id']}", json=update)
        assert denied.status_code == 403 and denied.json()["detail"]["code"] == "post_forbidden"
