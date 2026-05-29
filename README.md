# KakaoTalk Free Economic Briefing

사업자등록 없이 카카오톡 채널에서 무료 경제 뉴스 브리핑을 운영하기 위한 도구입니다.

현재 목표는 자동 대량 발송이 아니라, 매일 카카오톡 채널에 붙여넣을 브리핑 문안을 빠르게 만드는 것입니다.

## 운영 흐름

1. 카카오톡 채널을 만듭니다.
2. 채널 홈 소개글과 자동응답을 설정합니다.
3. 이 도구로 경제 뉴스 브리핑을 생성합니다.
4. 생성된 `output/kakao_briefing.txt` 내용을 카카오톡 채널 포스트나 메시지에 붙여넣습니다.
5. 친구 수, 클릭, 차단, 반응을 보며 포맷을 다듬습니다.

## 환경 파일 만들기

```powershell
Copy-Item .env.example .env
```

## 브리핑 미리보기

```powershell
python -m src.kakao_news_alert preview
```

## 카카오톡용 브리핑 파일 생성

```powershell
python -m src.kakao_news_alert export-briefing
```

결과 파일:

```text
output/kakao_briefing.txt
```

이 파일 내용을 그대로 카카오톡 채널 관리자센터에 붙여넣으면 됩니다.

## 웹페이지 생성

```powershell
python -m src.kakao_news_alert export-site
```

결과 파일:

```text
site/index.html
site/latest.json
```

`site/index.html`은 최신 기사 링크, 영향 설명, 기사별 쉬운 경제 용어 설명을 포함합니다. GitHub Pages, Netlify, Vercel 같은 정적 호스팅에 올리면 인터넷 페이지로 운영할 수 있습니다.

## 콘텐츠 운영 원칙

- 기사 본문, 사진, 그래프를 복제하지 않습니다.
- 공개된 기사 제목, 언론사명, 원문 링크를 바탕으로 경제 흐름과 용어를 설명합니다.
- 특정 종목 매수/매도 추천이나 수익 보장을 하지 않습니다.
- 투자 판단과 책임은 이용자 본인에게 있다는 문구를 사이트와 카카오톡 브리핑에 포함합니다.
- 수익화 전에는 개인정보 처리방침, 이용약관, 환불/해지 정책, 광고성 정보 수신동의 절차를 준비합니다.

## 유료 구독 준비 파일

사이트 문서:

- `site/pricing.html`: 무료/프리미엄 구독 안내
- `site/legal/terms.html`: 이용약관 초안
- `site/legal/privacy.html`: 개인정보 처리방침 초안
- `site/legal/refund.html`: 환불 및 해지 정책 초안
- `site/legal/marketing-consent.html`: 광고성 정보 수신동의 초안
- `site/legal/checklist.html`: 유료화 체크리스트

운영 데이터 예시:

- `data/plans.example.json`: 무료/프리미엄 플랜 구조
- `data/subscribers.example.json`: 구독자 데이터 구조
- `data/consents.example.json`: 약관/개인정보/마케팅 수신동의 로그
- `data/payments.example.json`: 결제/갱신/취소/환불 로그 구조

아직 결제대행사와 카카오 비즈메시지 발송 솔루션은 연결하지 않았습니다. 실제 유료화 전에는 사업자등록, 결제대행사 계약, 비즈니스 채널 인증, 비즈메시지 발송 방식 결정이 필요합니다.

## GitHub Pages 자동 발행

`.github/workflows/pages.yml`은 사이트를 약 15분마다 갱신합니다. GitHub Pages는 정적 호스팅이라 초 단위 실시간은 아니지만, 최신 RSS를 자주 다시 가져와 준실시간 페이지로 운영할 수 있습니다.

1. 경제 뉴스 RSS 수집
2. `site/index.html`, `site/latest.json` 생성
3. GitHub Pages로 배포

카카오톡 발송은 사이트 갱신과 분리해서 오전 7시에 핵심 기사만 보내는 흐름으로 운영합니다.

GitHub 저장소에 올린 뒤 `Settings > Pages > Build and deployment`에서 Source를 `GitHub Actions`로 설정하세요.

수동으로 바로 발행하고 싶으면 GitHub 저장소의 `Actions > Publish 3min Economy Site > Run workflow`를 누르면 됩니다.

## GitHub API로 업로드

PC에 `git` 명령이 없어도 GitHub REST API로 파일을 올릴 수 있습니다.

1. GitHub에서 fine-grained personal access token을 만듭니다.
2. 대상 저장소에 `Contents: Read and write`, `Actions: Read and write`, `Pages: Read and write` 권한을 줍니다.
3. `.env`에 값을 넣습니다.

```text
GITHUB_TOKEN=...
GITHUB_OWNER=your-github-id
GITHUB_REPO=your-repo-name
GITHUB_BRANCH=main
```

토큰은 절대 채팅에 붙여넣지 마세요.

업로드:

```powershell
python -m src.github_sync
```

## 나중에 유료화할 때

무료 운영으로 반응이 검증되면 다음 단계로 확장합니다.

- 사업자등록
- 비즈니스 채널 인증
- 정기결제
- 구독 상태 자동 관리
- 친구톡/비즈메시지 API 발송
- 수신거부와 해지 처리

## 참고

`run-once`와 `business_webhook` 설정은 나중에 비즈메시지 API 또는 발송 대행사 API가 생겼을 때를 위한 확장 지점입니다. 지금은 카카오톡 채널용 `export-briefing`과 웹페이지용 `export-site` 위주로 쓰면 됩니다.
