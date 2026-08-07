# 모닝 마켓 브리핑 (morning-briefing)

매일 한국시간(KST) 06:30에 GitHub Actions가 자동으로 실행되어, Anthropic Claude API(서버사이드 web_search 도구)로 최신 시장 브리핑을 생성하고 이 레포에 커밋합니다.

## 보기

GitHub Pages: https://neejin.github.io/morning-briefing/

이 링크는 항상 최신 브리핑을 보여줍니다. 과거 브리핑은 archive 폴더에 날짜별로 보관됩니다.

## 동작 방식

1. .github/workflows/update-briefing.yml 이 매일 UTC 21:30 (한국시간 06:30) 에 실행됩니다.
2. scripts/generate_briefing.py 가 Anthropic API를 호출해 index.html, index.md 를 새로 생성합니다.
3. 같은 내용을 archive 폴더에 YYYY-MM-DD_모닝브리핑.html, YYYY-MM-DD_모닝브리핑.md 로도 저장합니다.
4. 변경사항을 github-actions[bot] 계정으로 자동 커밋, 푸시합니다.

## 수동 갱신

레포의 Actions 탭에서 Update Morning Briefing 워크플로우를 선택하고 Run workflow 버튼을 누르면 언제든 수동으로 실행할 수 있습니다.

## 필요한 설정

레포 Settings, Secrets and variables, Actions 메뉴에 ANTHROPIC_API_KEY 시크릿이 등록되어 있어야 정상 동작합니다. API 키는 https://console.anthropic.com/settings/keys 에서 발급받을 수 있습니다. 이 값은 절대 코드나 커밋에 직접 넣지 말고, 반드시 위 시크릿 등록 화면을 통해서만 입력하세요.

## 브리핑 작성 규칙

브리핑의 데이터 소스 우선순위, 다루는 자산 목록, 본문 구성 순서 등 상세 규칙은 scripts/generate_briefing.py 안의 스타일 가이드 부분을 참고하세요. 매일 실행되는 스크립트가 이 규칙을 그대로 따라 새 브리핑을 작성합니다.
