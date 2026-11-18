"""관리자 계정을 만들거나 기존 계정에 관리자 역할을 붙인다.

사용:
    uv run python -m scripts.create_admin --email admin@example.com --name 관리자

- 비밀번호는 실행할 때 입력받는다(화면에 보이지 않음). 자동화할 때만 환경변수 `ADMIN_PASSWORD` 를 쓴다.
  비밀번호는 코드·문서·로그에 남기지 않는다.
- 계정이 이미 있으면 비밀번호는 그대로 두고 역할만 admin 으로 바꾼다(`--reset-password` 를 주면 새로 입력받는다).
- `.env` 의 STORAGE_BACKEND(sqlite/supabase) 설정을 그대로 쓰므로, 로컬과 운영 DB 에 각각 실행해야 한다.
- 관리자 역할은 회원가입 API 로는 줄 수 없고 이 스크립트로만 붙는다.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from datetime import datetime, timezone

from pwdlib import PasswordHash

from backend.auth.sessions import owner_key
from backend.config import get_settings
from backend.deps import ADMIN_ROLE
from backend.storage import build_store

MIN_PASSWORD = 8


def _password(confirm: bool = True) -> str:
    env = os.environ.get("ADMIN_PASSWORD")
    if env:
        return env
    first = getpass.getpass("관리자 비밀번호(8자 이상): ")
    if confirm and getpass.getpass("한 번 더 입력: ") != first:
        sys.exit("비밀번호가 서로 달라요.")
    return first


async def main(email: str, name: str, reset_password: bool) -> None:
    email = email.strip().lower()
    store = build_store(get_settings())
    try:
        owner = owner_key(email)
        account = await store.get(owner, "identity", "account")
        if account:
            account["role"] = ADMIN_ROLE
            account.pop("disabled", None)
            if reset_password:
                password = _password()
                if len(password) < MIN_PASSWORD:
                    sys.exit("비밀번호는 8자 이상이어야 해요.")
                account["password_hash"] = PasswordHash.recommended().hash(password)
            await store.put(owner, "identity", "account", account)
            print(f"기존 계정 {email} 에 관리자 역할을 붙였어요.")
            return
        password = _password()
        if len(password) < MIN_PASSWORD:
            sys.exit("비밀번호는 8자 이상이어야 해요.")
        await store.put(owner, "identity", "account", {
            "email": email,
            "name": name,
            "password_hash": PasswordHash.recommended().hash(password),
            "role": ADMIN_ROLE,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        print(f"관리자 계정 {email} 을 만들었어요.")
    finally:
        await store.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="관리자 계정 만들기")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="관리자")
    parser.add_argument("--reset-password", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.email, args.name, args.reset_password))
