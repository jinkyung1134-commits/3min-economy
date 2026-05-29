from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_INCLUDE = [
    ".env.example",
    ".gitignore",
    "README.md",
    ".github/workflows/pages.yml",
    "assets/kakao-channel-profile.png",
    "data/subscribers.example.json",
    "src/__init__.py",
    "src/kakao_news_alert.py",
    "src/github_sync.py",
    "site/.nojekyll",
    "site/index.html",
    "site/latest.json",
    "site/assets/kakao-channel-profile.png",
]


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
    value = os.getenv(name, "")
    if not value:
        raise SystemExit(f"{name} is required. Set it in your environment or .env file.")
    return value


def github_request(
    method: str,
    url: str,
    token: str,
    payload: dict[str, Any] | None = None,
    allow_not_found: bool = False,
) -> dict[str, Any]:
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("User-Agent", "3min-economy-sync")
    if data is not None:
        request.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        if error.code == 404 and allow_not_found:
            return {"_not_found": True}
        raise RuntimeError(f"GitHub API HTTP {error.code}: {body}") from error


def get_remote_sha(owner: str, repo: str, branch: str, path: str, token: str) -> str | None:
    quoted_path = urllib.parse.quote(path.replace("\\", "/"))
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{quoted_path}?ref={urllib.parse.quote(branch)}"
    response = github_request("GET", url, token, allow_not_found=True)
    if response.get("_not_found"):
        return None
    return str(response.get("sha") or "")


def upload_file(owner: str, repo: str, branch: str, local_path: Path, repo_path: str, token: str) -> None:
    content = local_path.read_bytes()
    sha = get_remote_sha(owner, repo, branch, repo_path, token)
    message_action = "Update" if sha else "Add"
    payload: dict[str, Any] = {
        "message": f"{message_action} {repo_path}",
        "content": base64.b64encode(content).decode("ascii"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    quoted_path = urllib.parse.quote(repo_path.replace("\\", "/"))
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{quoted_path}"
    github_request("PUT", url, token, payload)
    size = len(content)
    mime = mimetypes.guess_type(str(local_path))[0] or "application/octet-stream"
    print(f"{message_action}: {repo_path} ({size} bytes, {mime})")


def sync_files(files: list[str]) -> None:
    load_dotenv()
    token = required_env("GITHUB_TOKEN")
    owner = required_env("GITHUB_OWNER")
    repo = required_env("GITHUB_REPO")
    branch = os.getenv("GITHUB_BRANCH", "main")

    repo_url = f"https://api.github.com/repos/{owner}/{repo}"
    repo_data = github_request("GET", repo_url, token)
    default_branch = repo_data.get("default_branch")
    print(f"Repository: {owner}/{repo} (default branch: {default_branch})")

    for file_name in files:
        local_path = Path(file_name)
        if not local_path.exists():
            print(f"Skip missing: {file_name}")
            continue
        upload_file(owner, repo, branch, local_path, file_name.replace("\\", "/"), token)


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload 3분경제 files to GitHub via REST API.")
    parser.add_argument("files", nargs="*", help="Files to upload. Defaults to the project publish set.")
    args = parser.parse_args()
    sync_files(args.files or DEFAULT_INCLUDE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
