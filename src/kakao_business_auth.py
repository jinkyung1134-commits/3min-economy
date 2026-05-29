from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


AUTHORIZE_URL = "https://kauth.kakao.com/oauth/business/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/business/token"
TOKEN_INFO_URL = "https://kapi.kakao.com/v1/business/tokeninfo"
DEFAULT_REDIRECT_URI = "http://localhost:8000/kakao/callback"
DEFAULT_SCOPES = "moment_management"


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required.")
    return value


def optional_env(name: str) -> str:
    return os.getenv(name, "").strip()


def post_form(url: str, data: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url: str, access_token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def build_auth_url() -> str:
    rest_api_key = required_env("KAKAO_REST_API_KEY")
    redirect_uri = os.getenv("KAKAO_REDIRECT_URI", DEFAULT_REDIRECT_URI)
    scopes = os.getenv("KAKAO_BUSINESS_SCOPES", DEFAULT_SCOPES)
    params = {
        "client_id": rest_api_key,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scopes,
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def exchange_token(code: str) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "client_id": required_env("KAKAO_REST_API_KEY"),
        "redirect_uri": os.getenv("KAKAO_REDIRECT_URI", DEFAULT_REDIRECT_URI),
        "code": code,
    }
    client_secret = optional_env("KAKAO_CLIENT_SECRET")
    if client_secret:
        data["client_secret"] = client_secret
    return post_form(TOKEN_URL, data)


def token_info(access_token: str) -> dict[str, Any]:
    return get_json(TOKEN_INFO_URL, access_token)


def print_token_response(data: dict[str, Any]) -> None:
    safe = dict(data)
    if "access_token" in safe:
        safe["access_token"] = "<save this as KAKAO_BUSINESS_ACCESS_TOKEN>"
    if "refresh_token" in safe:
        safe["refresh_token"] = "<save this as KAKAO_BUSINESS_REFRESH_TOKEN>"
    print(json.dumps(safe, ensure_ascii=False, indent=2))
    if data.get("access_token"):
        print()
        print("Token issued. Save the real access_token in GitHub Secrets as KAKAO_BUSINESS_ACCESS_TOKEN.")
    if data.get("refresh_token"):
        print("Save the real refresh_token in GitHub Secrets as KAKAO_BUSINESS_REFRESH_TOKEN.")


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Kakao business auth helper for 3분경제.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("auth-url", help="Print the Kakao business authorization URL.")
    token_parser = subparsers.add_parser("exchange-token", help="Exchange authorization code for a token.")
    token_parser.add_argument("--code", required=True, help="Authorization code from Kakao redirect URL.")
    info_parser = subparsers.add_parser("token-info", help="Check a Kakao business access token.")
    info_parser.add_argument("--access-token", default="", help="Access token. Defaults to KAKAO_BUSINESS_ACCESS_TOKEN.")

    args = parser.parse_args()
    if args.command == "auth-url":
        print(build_auth_url())
    elif args.command == "exchange-token":
        print_token_response(exchange_token(args.code))
    elif args.command == "token-info":
        access_token = args.access_token or required_env("KAKAO_BUSINESS_ACCESS_TOKEN")
        print(json.dumps(token_info(access_token), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
