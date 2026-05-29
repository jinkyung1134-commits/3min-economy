from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import html
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


DEFAULT_NEWS_KEYWORDS = "경제,증시,금리,환율,물가,부동산,반도체,AI,미국,중국"
DEFAULT_NEWS_RSS_FEEDS = (
    "https://news.google.com/rss/search?"
    "q=%EA%B2%BD%EC%A0%9C%20%EA%B8%88%EC%9C%B5%20%EC%A6%9D%EC%8B%9C&hl=ko&gl=KR&ceid=KR:ko,"
    "https://news.google.com/rss/search?"
    "q=%EA%B8%88%EB%A6%AC%20%ED%99%98%EC%9C%A8%20%EB%AC%BC%EA%B0%80&hl=ko&gl=KR&ceid=KR:ko"
)

TERM_DEFINITIONS = {
    "인플레이션": "물건과 서비스 가격이 전반적으로 오르는 현상입니다. 같은 돈으로 살 수 있는 양이 줄어드는 상태라고 보면 쉽습니다.",
    "긴축": "중앙은행이나 정부가 금리를 올리거나 돈의 흐름을 줄여 물가와 과열된 경기를 잡으려는 정책입니다.",
    "금리": "돈을 빌릴 때 내는 비용입니다. 금리가 오르면 대출 부담이 커지고 소비와 투자가 줄어들 수 있습니다.",
    "환율": "우리 돈과 외국 돈을 바꾸는 비율입니다. 원달러 환율이 오르면 수입 물가 부담이 커질 수 있습니다.",
    "물가": "생활에 필요한 상품과 서비스 가격의 전반적인 수준입니다.",
    "기준금리": "한국은행 같은 중앙은행이 정하는 대표 금리입니다. 대출금리와 예금금리에 영향을 줍니다.",
    "증시": "주식이 거래되는 시장입니다. 기업 실적, 금리, 환율, 투자 심리에 영향을 받습니다.",
    "채권": "정부나 회사가 돈을 빌리기 위해 발행하는 증서입니다. 금리 변화에 민감합니다.",
    "경기침체": "소비, 투자, 생산이 줄어 경제 활동이 전반적으로 위축되는 상태입니다.",
    "반도체": "전자제품과 AI 서버의 핵심 부품입니다. 한국 수출과 증시에 큰 영향을 줍니다.",
}


@dataclass(frozen=True)
class Settings:
    sender_mode: str
    business_message_webhook_url: str
    business_message_api_key: str
    news_keywords: list[str]
    news_rss_feeds: list[str]
    max_news_items: int
    subscribers_file: Path
    sent_file: Path
    briefing_output_file: Path
    site_dir: Path
    max_news_age_hours: int


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    source: str
    published: str


@dataclass(frozen=True)
class Subscriber:
    id: str
    name: str
    phone: str
    kakao_channel_user_key: str
    subscription_status: str
    kakao_opt_in: bool
    plan: str


class MessageSender(Protocol):
    def send(self, subscriber: Subscriber, text: str, link: str) -> None:
        ...


class DryRunSender:
    def send(self, subscriber: Subscriber, text: str, link: str) -> None:
        print(f"[DRY RUN] recipient={subscriber.id} phone={mask_phone(subscriber.phone)} link={link}")
        print(text)
        print()


class BusinessWebhookSender:
    def __init__(self, webhook_url: str, api_key: str) -> None:
        if not webhook_url:
            raise SystemExit("BUSINESS_MESSAGE_WEBHOOK_URL is required when SENDER_MODE=business_webhook.")
        self.webhook_url = webhook_url
        self.api_key = api_key

    def send(self, subscriber: Subscriber, text: str, link: str) -> None:
        payload = {
            "recipient": {
                "id": subscriber.id,
                "phone": subscriber.phone,
                "kakao_channel_user_key": subscriber.kakao_channel_user_key,
            },
            "message": {
                "text": text[:1000],
                "link": link,
                "type": "economic_news_digest",
            },
        }
        headers = {"Content-Type": "application/json;charset=utf-8"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        http_post_json(self.webhook_url, payload, headers)


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def get_settings() -> Settings:
    load_dotenv()
    return Settings(
        sender_mode=os.getenv("SENDER_MODE", "dry_run"),
        business_message_webhook_url=os.getenv("BUSINESS_MESSAGE_WEBHOOK_URL", ""),
        business_message_api_key=os.getenv("BUSINESS_MESSAGE_API_KEY", ""),
        news_keywords=split_csv(os.getenv("NEWS_KEYWORDS", DEFAULT_NEWS_KEYWORDS)),
        news_rss_feeds=split_csv(os.getenv("NEWS_RSS_FEEDS", DEFAULT_NEWS_RSS_FEEDS)),
        max_news_items=int(os.getenv("MAX_NEWS_ITEMS", "5")),
        subscribers_file=Path(os.getenv("SUBSCRIBERS_FILE", "data/subscribers.json")),
        sent_file=Path(os.getenv("SENT_FILE", ".state/sent_items.json")),
        briefing_output_file=Path(os.getenv("BRIEFING_OUTPUT_FILE", "output/kakao_briefing.txt")),
        site_dir=Path(os.getenv("SITE_DIR", "site")),
        max_news_age_hours=int(os.getenv("MAX_NEWS_AGE_HOURS", "24")),
    )


def http_post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code}: {body}") from error


def http_get_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "kakao-economic-news-alert/1.0"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def save_json(path: Path, data: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def load_subscribers(path: Path) -> list[Subscriber]:
    rows = load_json(path, [])
    subscribers: list[Subscriber] = []
    for row in rows:
        subscribers.append(
            Subscriber(
                id=str(row.get("id", "")),
                name=str(row.get("name", "")),
                phone=str(row.get("phone", "")),
                kakao_channel_user_key=str(row.get("kakao_channel_user_key", "")),
                subscription_status=str(row.get("subscription_status", "")),
                kakao_opt_in=bool(row.get("kakao_opt_in", False)),
                plan=str(row.get("plan", "")),
            )
        )
    return subscribers


def active_subscribers(subscribers: list[Subscriber]) -> list[Subscriber]:
    return [
        subscriber
        for subscriber in subscribers
        if subscriber.subscription_status == "active" and subscriber.kakao_opt_in
    ]


def build_sender(settings: Settings) -> MessageSender:
    if settings.sender_mode == "dry_run":
        return DryRunSender()
    if settings.sender_mode == "business_webhook":
        return BusinessWebhookSender(
            webhook_url=settings.business_message_webhook_url,
            api_key=settings.business_message_api_key,
        )
    raise SystemExit(f"Unsupported SENDER_MODE: {settings.sender_mode}")


def parse_rss(xml_text: str, fallback_source: str) -> list[NewsItem]:
    root = ET.fromstring(xml_text)
    items: list[NewsItem] = []
    for item in root.findall(".//item"):
        title = html.unescape((item.findtext("title") or "").strip())
        link = html.unescape((item.findtext("link") or "").strip())
        published = (item.findtext("pubDate") or "").strip()
        source = fallback_source
        source_node = item.find("{http://search.yahoo.com/mrss/}source")
        google_source_node = item.find("{http://news.google.com/rss}source")
        if google_source_node is not None and google_source_node.text:
            source = google_source_node.text.strip()
        elif source_node is not None and source_node.text:
            source = source_node.text.strip()
        elif " - " in title:
            source = title.rsplit(" - ", 1)[-1].strip()
        if title and link:
            items.append(NewsItem(title=title, link=link, source=source, published=published))
    return items


def fetch_news(settings: Settings) -> list[NewsItem]:
    if not settings.news_rss_feeds:
        raise SystemExit("NEWS_RSS_FEEDS is required.")

    all_items: list[NewsItem] = []
    for feed_url in settings.news_rss_feeds:
        try:
            xml_text = http_get_text(feed_url)
            all_items.extend(parse_rss(xml_text, fallback_source=urllib.parse.urlparse(feed_url).netloc))
        except Exception as error:
            print(f"RSS fetch failed: {feed_url} ({error})", file=sys.stderr)

    filtered = filter_recent_news(all_items, settings.max_news_age_hours)
    return dedupe_news(filter_news(filtered, settings.news_keywords))


def filter_news(items: list[NewsItem], keywords: list[str]) -> list[NewsItem]:
    if not keywords:
        return items
    lowered_keywords = [keyword.casefold() for keyword in keywords]
    return [
        item
        for item in items
        if any(keyword in f"{item.title} {item.source}".casefold() for keyword in lowered_keywords)
    ]


def dedupe_news(items: list[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    unique: list[NewsItem] = []
    for item in items:
        if item.link in seen:
            continue
        seen.add(item.link)
        unique.append(item)
    return unique


def filter_recent_news(items: list[NewsItem], max_age_hours: int) -> list[NewsItem]:
    if max_age_hours <= 0:
        return items

    now = now_utc()
    recent: list[NewsItem] = []
    unknown_date: list[NewsItem] = []
    for item in items:
        published_at = parse_datetime(item.published)
        if published_at is None:
            unknown_date.append(item)
            continue
        age = now - published_at
        if dt.timedelta(0) <= age <= dt.timedelta(hours=max_age_hours):
            recent.append(item)

    return recent or unknown_date


def extract_terms_from_text(text: str, limit: int = 2) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    for term, definition in TERM_DEFINITIONS.items():
        if term in text:
            selected.append({"term": term, "definition": definition})
        if len(selected) == limit:
            return selected
    return selected


def extract_terms(items: list[NewsItem], limit: int = 2) -> list[dict[str, str]]:
    haystack = " ".join(item.title for item in items)
    selected = extract_terms_from_text(haystack, limit)
    if len(selected) == limit:
        return selected

    for term, definition in TERM_DEFINITIONS.items():
        if not any(row["term"] == term for row in selected):
            selected.append({"term": term, "definition": definition})
        if len(selected) == limit:
            return selected
    return selected


def build_impact_note(items: list[NewsItem]) -> str:
    titles = " ".join(item.title for item in items)
    if any(word in titles for word in ["환율", "원달러", "달러"]):
        return "환율 이슈는 수입 물가와 외국인 자금 흐름에 영향을 줄 수 있어 증시와 생활 물가를 함께 봐야 합니다."
    if any(word in titles for word in ["금리", "긴축", "인플레이션", "물가"]):
        return "금리와 물가 이슈는 대출 부담, 소비 심리, 주식시장 흐름에 직접적인 영향을 줄 수 있습니다."
    if any(word in titles for word in ["반도체", "AI", "기업"]):
        return "기업과 산업 이슈는 실적 기대와 투자 심리에 영향을 주며, 관련 업종의 주가 변동으로 이어질 수 있습니다."
    return "오늘 뉴스는 시장 심리와 정책 기대에 영향을 줄 수 있어 금리, 환율, 증시 흐름을 함께 확인하는 것이 좋습니다."


def build_digest(items: list[NewsItem]) -> tuple[str, str]:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    terms = extract_terms(items)
    lines = [f"[오늘의 3분경제] {now}", ""]
    lines.append("꼭 봐야 할 경제 뉴스만 짧게 정리했습니다.")
    lines.append("")
    for index, item in enumerate(items, start=1):
        lines.append(f"{index}. {item.title}")
        lines.append(f"   출처: {item.source}")
    lines.append("")
    lines.append("영향:")
    lines.append(build_impact_note(items))
    lines.append("")
    lines.append("오늘의 용어:")
    for term in terms:
        lines.append(f"- {term['term']}: {term['definition']}")
    lines.append("")
    lines.append("채널 추가 후 매일 경제 브리핑을 받아보세요.")
    return "\n".join(lines), items[0].link


def build_article_data(items: list[NewsItem]) -> dict[str, Any]:
    return {
        "title": "오늘의 3분경제",
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "summary": "긴 기사 대신 오늘의 경제 흐름만 빠르게 확인하세요.",
        "impact": build_impact_note(items),
        "items": [
            {
                "title": item.title,
                "source": item.source,
                "link": item.link,
                "published": item.published,
                "terms": extract_terms_from_text(item.title, limit=2),
                "relative_time": relative_time(item.published),
            }
            for item in items
        ],
    }


def preview(settings: Settings) -> None:
    news = fetch_news(settings)[: settings.max_news_items]
    if not news:
        print("No news items matched.")
        return
    text, link = build_digest(news)
    print(text)
    print()
    print(f"대표 링크: {link}")


def export_briefing(settings: Settings) -> None:
    news = fetch_news(settings)[: settings.max_news_items]
    if not news:
        print("No news items matched.")
        return

    text, link = build_digest(news)
    output = f"{text}\n\n대표 링크:\n{link}\n"
    settings.briefing_output_file.parent.mkdir(parents=True, exist_ok=True)
    settings.briefing_output_file.write_text(output, encoding="utf-8")
    print(f"Briefing exported: {settings.briefing_output_file}")


def export_site(settings: Settings) -> None:
    news = fetch_news(settings)[: settings.max_news_items]
    if not news:
        print("No news items matched.")
        return

    data = build_article_data(news)
    settings.site_dir.mkdir(parents=True, exist_ok=True)
    copy_site_assets(settings.site_dir)
    (settings.site_dir / ".nojekyll").write_text("", encoding="utf-8")
    save_json(settings.site_dir / "latest.json", data)
    (settings.site_dir / "index.html").write_text(render_site_html(data), encoding="utf-8")
    print(f"Site exported: {settings.site_dir / 'index.html'}")


def copy_site_assets(site_dir: Path) -> None:
    source = Path("assets/kakao-channel-profile.png")
    if not source.exists():
        return
    target_dir = site_dir / "assets"
    target_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target_dir / "kakao-channel-profile.png")


def render_site_html(data: dict[str, Any]) -> str:
    first_news = data["items"][0] if data["items"] else {"title": "", "link": "#", "source": ""}
    news_items = "\n".join(
        f"""
        <li class="news-item">
          <a class="{tooltip_class(item)}" href="{escape(item['link'])}" target="_blank" rel="noopener noreferrer" {tooltip_attrs(item)}>{escape(clean_title(item['title']))}</a>
          <span>{escape(item['source'])} · {escape(item.get('relative_time') or '시간 미상')}</span>
        </li>
        """
        for item in data["items"]
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="3분경제는 매일 꼭 봐야 할 경제 뉴스를 짧게 정리합니다.">
  <title>3분경제</title>
  <style>
    :root {{
      --yellow: #ffdb1f;
      --ink: #1f2328;
      --muted: #68707d;
      --line: #e4dfcf;
      --paper: #fffdf4;
      --green: #218a53;
      --blue: #315c9c;
      --orange: #a85f00;
      --surface: #f7f2df;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
      background: var(--surface);
      color: var(--ink);
      line-height: 1.58;
    }}
    a {{ color: inherit; }}
    .wrap {{
      width: min(1040px, calc(100% - 32px));
      margin: 0 auto;
    }}
    .topbar {{
      background: var(--yellow);
      border-bottom: 1px solid rgba(31, 35, 40, 0.12);
    }}
    .brand {{
      min-height: 76px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }}
    .brand-left {{
      display: flex;
      align-items: center;
      gap: 13px;
      min-width: 0;
    }}
    .brand img {{
      width: 52px;
      height: 52px;
      border-radius: 14px;
      flex: 0 0 auto;
    }}
    .brand h1 {{
      margin: 0;
      font-size: 25px;
      letter-spacing: 0;
      line-height: 1.1;
    }}
    .brand p {{
      margin: 4px 0 0;
      color: #3c3c3c;
      font-size: 13px;
    }}
    .update {{
      color: #353535;
      font-size: 13px;
      white-space: nowrap;
    }}
    main {{
      padding: 28px 0 54px;
    }}
    .hero {{
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      gap: 20px;
      align-items: stretch;
      margin-bottom: 22px;
    }}
    .lead {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 28px;
    }}
    .eyebrow {{
      margin: 0 0 10px;
      color: var(--green);
      font-weight: 800;
      font-size: 14px;
    }}
    h2 {{
      margin: 0;
      font-size: 34px;
      line-height: 1.22;
      letter-spacing: 0;
    }}
    .lead-copy {{
      margin: 14px 0 0;
      color: #45484d;
      font-size: 16px;
    }}
    .hero-link {{
      display: inline-flex;
      margin-top: 22px;
      min-height: 42px;
      align-items: center;
      justify-content: center;
      padding: 10px 16px;
      border-radius: 6px;
      background: var(--ink);
      color: white;
      text-decoration: none;
      font-weight: 800;
    }}
    .impact-panel {{
      background: #f3fff5;
      border: 1px solid #bfdfc6;
      border-radius: 8px;
      padding: 24px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: 18px;
    }}
    .impact-panel h3 {{
      margin: 0 0 8px;
      font-size: 20px;
      letter-spacing: 0;
    }}
    .impact-panel p {{
      margin: 0;
      color: #26362b;
    }}
    .section-title {{
      margin: 0 0 12px;
      font-size: 21px;
      letter-spacing: 0;
    }}
    .news-list {{
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 10px;
    }}
    .news-item {{
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 15px 16px;
    }}
    .news-item a {{
      display: block;
      text-decoration: none;
      font-weight: 800;
      color: var(--ink);
    }}
    .news-item span {{
      display: block;
      margin-top: 5px;
      color: var(--muted);
      font-size: 13px;
    }}
    .has-title-tooltip {{
      position: relative;
      outline: none;
    }}
    .has-title-tooltip::after {{
      content: attr(data-definition);
      position: absolute;
      left: 0;
      bottom: calc(100% + 10px);
      width: min(340px, 82vw);
      padding: 11px 12px;
      border-radius: 8px;
      background: #1f2328;
      color: #fff;
      font-size: 14px;
      font-weight: 500;
      line-height: 1.45;
      box-shadow: 0 12px 30px rgba(31, 35, 40, 0.2);
      opacity: 0;
      pointer-events: none;
      visibility: hidden;
      z-index: 10;
    }}
    .has-title-tooltip::before {{
      content: "";
      position: absolute;
      left: 20px;
      bottom: calc(100% + 3px);
      border: 7px solid transparent;
      border-top-color: #1f2328;
      opacity: 0;
      pointer-events: none;
      visibility: hidden;
      z-index: 11;
    }}
    .has-title-tooltip:hover::after,
    .has-title-tooltip:hover::before,
    .has-title-tooltip:focus::after,
    .has-title-tooltip:focus::before {{
      opacity: 1;
      visibility: visible;
    }}
    .notice {{
      margin-top: 20px;
      color: var(--muted);
      font-size: 13px;
    }}
    @media (max-width: 760px) {{
      .brand {{
        align-items: flex-start;
        flex-direction: column;
        padding: 14px 0;
      }}
      .update {{ white-space: normal; }}
      .hero {{ grid-template-columns: 1fr; }}
      .lead {{ padding: 22px; }}
      h2 {{ font-size: 28px; }}
    }}
  </style>
</head>
<body>
  <header class="topbar">
    <div class="wrap brand">
      <div class="brand-left">
        <img src="assets/kakao-channel-profile.png" alt="3분경제 로고">
        <div>
          <h1>3분경제</h1>
          <p>뉴스는 짧게, 영향은 쉽게, 용어는 바로 이해되게</p>
        </div>
      </div>
      <div class="update">{escape(data['generated_at'])} 업데이트</div>
    </div>
  </header>

  <main class="wrap">
    <section class="hero">
      <div class="lead">
        <p class="eyebrow">오늘의 경제 흐름</p>
        <h2>{escape(data['title'])}</h2>
        <p class="lead-copy">{escape(data['summary'])}</p>
        <a class="hero-link" href="{escape(first_news['link'])}" target="_blank" rel="noopener noreferrer">첫 기사 보기</a>
      </div>
      <aside class="impact-panel">
        <div>
          <h3>어떤 영향이 있나요?</h3>
          <p>{escape(data['impact'])}</p>
        </div>
        <p class="notice">경제 용어가 포함된 기사 제목에 마우스를 올리면 쉬운 설명이 나옵니다.</p>
      </aside>
    </section>

    <section aria-labelledby="news-title">
      <h2 class="section-title" id="news-title">오늘 확인할 뉴스</h2>
      <ol class="news-list">
        {news_items}
      </ol>
    </section>

    <p class="notice">기사 본문을 복제하지 않고, 공개된 제목과 링크를 바탕으로 경제 흐름을 쉽게 설명합니다.</p>
  </main>
</body>
</html>
"""


def tooltip_class(item: dict[str, Any]) -> str:
    return "has-title-tooltip" if item.get("terms") else ""


def tooltip_attrs(item: dict[str, Any]) -> str:
    terms = item.get("terms") or []
    if not terms:
        return ""
    definitions = " / ".join(f"{term['term']}: {term['definition']}" for term in terms)
    return f'tabindex="0" data-definition="{escape(definitions)}"'


def run_once(settings: Settings) -> None:
    subscribers = active_subscribers(load_subscribers(settings.subscribers_file))
    if not subscribers:
        print("No active subscribers. Check SUBSCRIBERS_FILE.")
        return

    sent_links = set(load_json(settings.sent_file, []))
    fresh_items = [item for item in fetch_news(settings) if item.link not in sent_links]
    selected = fresh_items[: settings.max_news_items]
    if not selected:
        print("No fresh news items to send.")
        return

    text, link = build_digest(selected)
    sender = build_sender(settings)
    for subscriber in subscribers:
        sender.send(subscriber, text, link)

    save_json(settings.sent_file, sorted(sent_links | {item.link for item in selected}))
    print(f"Sent digest to {len(subscribers)} active subscribers with {len(selected)} news items.")


def clean_title(title: str) -> str:
    if " - " in title:
        return title.rsplit(" - ", 1)[0].strip()
    return title


def parse_datetime(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def relative_time(value: str) -> str:
    published_at = parse_datetime(value)
    if published_at is None:
        return "시간 미상"
    seconds = max(0, int((now_utc() - published_at).total_seconds()))
    if seconds < 60:
        return f"{seconds}초 전"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}분 전"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}시간 전"
    days = hours // 24
    return f"{days}일 전"


def escape(value: str) -> str:
    return html.escape(str(value), quote=True)


def slugify(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z가-힣]+", "-", value).strip("-")
    return slug or "term"


def term_question(term: str) -> str:
    return f"{term}{'이란?' if has_final_consonant(term) else '란?'}"


def has_final_consonant(value: str) -> bool:
    if not value:
        return False
    code = ord(value[-1])
    if 0xAC00 <= code <= 0xD7A3:
        return (code - 0xAC00) % 28 != 0
    return False


def mask_phone(phone: str) -> str:
    if len(phone) < 7:
        return "***"
    return f"{phone[:3]}****{phone[-4:]}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate 3분경제 briefings and site pages.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("preview", help="Fetch news and print the message preview.")
    subparsers.add_parser("export-briefing", help="Export a KakaoTalk-ready briefing text file.")
    subparsers.add_parser("export-site", help="Export the latest briefing as a static web page.")
    subparsers.add_parser("run-once", help="Fetch news and send a digest to active subscribers.")

    args = parser.parse_args(argv)
    settings = get_settings()

    if args.command == "preview":
        preview(settings)
    elif args.command == "export-briefing":
        export_briefing(settings)
    elif args.command == "export-site":
        export_site(settings)
    elif args.command == "run-once":
        run_once(settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
