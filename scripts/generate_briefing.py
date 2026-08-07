#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
모닝 마켓 브리핑 자동 생성 스크립트.

매일 GitHub Actions에서 실행되어 Anthropic Claude API (서버사이드 web_search 도구)를
사용해 '모닝 마켓 브리핑' 스타일 가이드에 맞는 최신 브리핑을 생성하고,
index.html / index.md (항상 최신) 와 archive/YYYY-MM-DD_모닝브리핑.html / .md
(당일자 사본)를 덮어씁니다.

환경변수:
  ANTHROPIC_API_KEY - Anthropic API 키 (필수, GitHub Actions secret 으로 주입됨)

실패하면 0이 아닌 종료 코드로 끝나서 워크플로우가 실패로 표시됩니다.
"""

import os
import sys
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic


REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO_ROOT / "index.html"
INDEX_MD = REPO_ROOT / "index.md"
ARCHIVE_DIR = REPO_ROOT / "archive"

MODEL = "claude-sonnet-5"
MAX_TOKENS = 64000
WEB_SEARCH_MAX_USES = 14

HTML_START = "===HTML_START==="
HTML_END = "===HTML_END==="
MD_START = "===MD_START==="
MD_END = "===MD_END==="


STYLE_GUIDE = """
# 모닝 마켓 브리핑 — 작성 규칙 (스타일 가이드)

## 0. 업데이트 요청의 의미
"모닝브리핑 업데이트해줘" = 가장 최근 하루치(간밤 미국·유럽 마감 + 오늘 아시아·미국·유럽 예정 일정)만 새로 작성.
- 지난 업데이트 이후 며칠~몇 주치를 전부 훑지 않는다.
- "간밤(가장 최근 미국 정규장 마감일)"과 "오늘(발행 시점 기준 한국시간 하루)"만 다룬다.
- 오늘 날짜 기준으로 "가장 최근 완료된 미국 정규장 마감일"이 며칠인지 먼저 확인 (요일 계산 착오 주의).

## 1. 데이터 소스 우선순위
1. investing.com (1순위) — 구조화된 시세 페이지(종목/지수/채권/원자재/환율 개별 quote 페이지)를 직접 fetch
2. Yahoo Finance (2순위) — investing.com에서 확인 안 될 때만
3. CNBC·Bloomberg는 봇 차단으로 직접 fetch 어려움 — 검색 스니펫만 부분 활용, 우선순위 제외
- 절대 뉴스 기사 프로즈에서 숫자를 긁어와 시세로 쓰지 말 것. 반드시 시세 전용 quote 페이지 값 사용.
- 구조적으로 하루 늦게 발표되는 데이터(미 국채 등)는 확인되는 가장 최근 날짜를 명시.
- 실시간 데이터(DXY, EUR/USD, USD/JPY, 유럽 지수, 원자재 선물)는 확인 시점 값 + "현재" 표기.
- 각 행마다 개별 기준 날짜/시점 표기 (표 전체 통일 X).
- 소스 간 불일치 시 다수 소스 일치값 우선, 그래도 불일치하면 그대로 두고 판단 근거를 별도 기록.

## 2. 다루는 자산 목록 (고정)
- 주가지수: 다우존스, S&P 500(Finviz 섹터맵 링크 필수), 나스닥종합, VIX, DAX, EURO STOXX50, 코스피 (FTSE100·CAC40·STOXX600 제외)
- 채권 금리: 미 10년물, 미 2년물, 미 30년물, 10Y-2Y 스프레드, 독일 10년물, 영국 10년물 (미 5년물 제외)
- 원자재: WTI, 브렌트유, 천연가스(TTF), 휘발유(RBOB), 금 (은 제외)
- 환율: 달러인덱스(DXY), EUR/USD, USD/JPY, USD/KRW(서울 종가 기준)

## 3. 본문 구성 순서
0. 오늘의 한줄 요약 (ledger, 4~5개) — 뉴스·지표 먼저, 자산가격 변동 뒤([자산] 표시). 연준 인사 발언은 "누가 무엇을" 구체적으로.
1. 시황 — 표, 2단 그리드(왼쪽: 주가지수+환율, 오른쪽: 채권+원자재). S&P 500에 https://finviz.com/map 링크.
2. 경제지표 — 항목당 1~2줄, 배경·함의 포함
3. 주요 뉴스 — 항목당 2~4줄, 왜 중요한지 포함
4. 주요 연구자료 — 연준(FRB FEDS, 각 지역 연은 블로그) 우선, 그 다음 PIIE, Brookings, Brussels Institute, IMF, BIS 순, 간밤 신규만, 제목에 원문 링크 필수, 없으면 "간밤 특별한 신규 발행물 없음"
5. 오늘 일정(한국시간) — 발언자·지표명 구체적, 컨센서스 수치 병기

## 4. HTML 작성 규칙
- 본문에는 시장 내용만. 메타 코멘터리("확인 못했다" 등) 제외.
- .wrap과 .ledger는 동일 max-width + margin:0 auto 유지 (정렬 버그 주의).
- 표는 컴팩트하게(패딩 3~5px, 폰트 11~12.5px), 2단 그리드.
- 전체 폰트 작게(body 12.5px 기준).
- 상승은 초록(--up), 하락은 빨강(--down).

## 5. MD 파일
- HTML과 동일 데이터·구성, 마크다운 표. S&P 500은 [S&P 500](https://finviz.com/map) 링크.

## 6. 파일명
archive/YYYY-MM-DD_모닝브리핑.html / .md
"""


TEMPLATE_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>모닝 마켓 브리핑 · 2026.08.07</title>
<style>
  :root{
    --ink:#101B2D; --ink-soft:#2C3B52; --paper:#F5F7FA; --card:#FFFFFF;
    --rule:#D9DEE6; --rule-strong:#101B2D; --up:#0F9D58; --down:#D93025; --muted:#7A8698;
    --sans:"Pretendard","Apple SD Gothic Neo",-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans KR",sans-serif;
    --mono:ui-monospace,"SFMono-Regular","Menlo","Consolas","Roboto Mono",monospace;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--sans);font-size:12.5px;line-height:1.45}
  .wrap{max-width:820px;margin:0 auto;padding:0 18px 32px}
  header.mast{background:var(--ink);color:#fff;margin:0 -18px 0;padding:16px 18px 12px}
  .mast-inner{max-width:820px;margin:0 auto}
  .kicker{font-family:var(--mono);font-size:9.5px;letter-spacing:.2em;text-transform:uppercase;color:#8FA6C4;margin:0 0 6px}
  h1.title{font-size:clamp(20px,5vw,28px);line-height:1.08;margin:0 0 6px;font-weight:800;letter-spacing:-.02em}
  .window{font-size:10px;color:#A9BCD4;font-family:var(--mono)}

  .ledger{max-width:820px;margin:0 auto 14px;background:var(--card);border:1px solid var(--rule);padding:8px 18px}
  .lede{display:flex;gap:8px;align-items:flex-start;padding:3px 0}
  .lede .dot{flex:none;width:5px;height:5px;border-radius:50%;margin-top:6px;background:var(--ink)}
  .lede.up .dot{background:var(--up)} .lede.down .dot{background:var(--down)}
  .lede p{margin:0;font-size:12.5px}
  .lede b{font-weight:700}

  section{margin:0 0 15px}
  h2{font-size:10.5px;font-family:var(--mono);letter-spacing:.13em;text-transform:uppercase;color:var(--ink);margin:0 0 3px;font-weight:700}
  .h2rule{height:2px;background:var(--rule-strong);margin:0 0 7px}
  h3{font-size:12px;margin:9px 0 3px;font-weight:700;color:var(--ink-soft)}
  h3:first-of-type{margin-top:0}

  table{width:100%;border-collapse:collapse;font-size:11.5px;background:var(--card);border:1px solid var(--rule)}
  td,th{padding:3px 8px;white-space:nowrap}
  th{text-align:left;font-family:var(--mono);font-size:8.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:600;border-bottom:1px solid var(--rule)}
  tbody tr:nth-child(even){background:#FAFBFD}
  td.name{font-weight:600;white-space:normal}
  td.num{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums;font-size:11px}
  .up{color:var(--up)} .down{color:var(--down)} .flat{color:var(--muted)}
  .asof{color:var(--muted);font-size:9px}

  ul.notes{margin:4px 0 0;padding:0;list-style:none}
  ul.notes li{position:relative;padding-left:11px;margin:0 0 5px;font-size:12px;color:var(--ink-soft)}
  ul.notes li::before{content:"";position:absolute;left:0;top:7px;width:5px;height:1px;background:var(--muted)}
  ul.notes li b{color:var(--ink)}

  .sched{background:var(--card);border:1px solid var(--rule)}
  .row{display:flex;gap:10px;padding:4px 10px;border-bottom:1px solid var(--rule);align-items:baseline}
  .row:last-child{border-bottom:none}
  .row.key{background:#FBFCFE}
  .row .t{flex:none;width:100px;font-family:var(--mono);font-size:9.5px;color:var(--muted)}
  .row.key .t{color:var(--down);font-weight:700}
  .row .e{font-size:11.5px}
  .row.key .e{font-weight:700}

  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  @media (max-width:520px){.grid2{grid-template-columns:1fr}}
</style>
</head>
<body>

<header class="mast">
  <div class="mast-inner">
    <p class="kicker">Morning Market Brief · Vol. 003</p>
    <h1 class="title">2026년 8월 7일 (금)</h1>
    <p class="window">간밤(미 8/6·목) 마감 + 오늘 아시아·미국·유럽 일정</p>
  </div>
</header>

<div class="ledger">
  <div class="lede down"><span class="dot"></span><p><b>미 ADP 민간고용(7월) +4.4만 명, 예상(+7만) 큰 폭 하회</b> — 1월 이후 최저치, 오늘 밤 NFP를 앞두고 고용 둔화 우려 확산</p></div>
  <div class="lede"><span class="dot"></span><p><b>연준 인사 발언 엇갈림</b> — 쿡 이사는 "인플레 지속 시 인상도 검토" 매파적 발언, 데일리 총재는 동결 지지하며 9/16 회의까지 관망 입장</p></div>
  <div class="lede"><span class="dot"></span><p><b>호르무즈 해협 통항 협상 지속</b> — 이란·오만 세부조건(관할권 등) 이견 남아, 진전 소식마다 유가가 민감하게 반응</p></div>
  <div class="lede down"><span class="dot"></span><p><b>[자산] 다우 −464.02p(−0.85%)</b> — 국채금리 상승에 5거래일 연속 이어가던 사상 최고 행진 마감</p></div>
  <div class="lede down"><span class="dot"></span><p><b>[자산] 코스피 −4.58%(6,296.38)</b> — 간밤 뉴욕發 반도체 단기 과열 우려 여파로 급락, 코스닥은 반대로 상승</p></div>
</div>

<div class="wrap">

<section>
  <h2>01 · 시황</h2><div class="h2rule"></div>

  <div class="grid2">
  <div>
  <h3>주가지수</h3>
  <table>
    <tbody>
      <tr><td class="name">다우존스</td><td class="num">53,885.10</td><td class="num down">−0.85%</td><td class="asof">8/6</td></tr>
      <tr><td class="name"><a href="https://finviz.com/map" target="_blank" rel="noopener" style="color:inherit;text-decoration:underline;text-decoration-color:var(--rule);text-underline-offset:2px">S&amp;P 500</a></td><td class="num">7,709.96</td><td class="num down">−0.18%</td><td class="asof">8/6</td></tr>
      <tr><td class="name">나스닥종합</td><td class="num">26,348.35</td><td class="num down">−0.06%</td><td class="asof">8/6</td></tr>
      <tr><td class="name">VIX</td><td class="num">15.11</td><td class="num down">−4.43%</td><td class="asof">8/6</td></tr>
      <tr><td class="name">DAX</td><td class="num">26,140.13</td><td class="num up">+0.05%</td><td class="asof">8/6</td></tr>
      <tr><td class="name">EURO STOXX50</td><td class="num">6,502.56</td><td class="num up">+0.39%</td><td class="asof">8/6</td></tr>
      <tr><td class="name">코스피</td><td class="num">6,296.38</td><td class="num down">−4.58%</td><td class="asof">8/6</td></tr>
    </tbody>
  </table>
  <p style="font-size:9.5px;color:var(--muted);margin:3px 2px 0">S&amp;P 500 클릭 → Finviz 실시간 섹터별 히트맵</p>

  <h3>환율</h3>
  <table>
    <tbody>
      <tr><td class="name">달러인덱스</td><td class="num">99.61</td><td class="num up">+0.06%</td><td class="asof">8/5</td></tr>
      <tr><td class="name">EUR/USD</td><td class="num">1.1548</td><td class="num down">−0.06%</td><td class="asof">8/7 현재</td></tr>
      <tr><td class="name">USD/JPY</td><td class="num">157.75</td><td class="num flat">보합</td><td class="asof">8/7 현재</td></tr>
      <tr><td class="name">USD/KRW</td><td class="num">1,423.8</td><td class="num up">−0.7원</td><td class="asof">8/6</td></tr>
    </tbody>
  </table>
  </div>

  <div>
  <h3>채권 금리</h3>
  <table>
    <tbody>
      <tr><td class="name">미 10년물</td><td class="num">4.611%</td><td class="num down">−0.6bp</td><td class="asof">8/5</td></tr>
      <tr><td class="name">미 2년물</td><td class="num">4.204%</td><td class="num up">+1.0bp</td><td class="asof">8/7 현재</td></tr>
      <tr><td class="name">미 30년물</td><td class="num">5.161%</td><td class="num down">−1.2bp</td><td class="asof">8/5</td></tr>
      <tr><td class="name">10Y−2Y 스프레드</td><td class="num">+31.3bp</td><td class="num up">+4.2bp</td><td class="asof">8/5</td></tr>
      <tr><td class="name">독일 10년물</td><td class="num">3.104%</td><td class="num down">−1.3bp</td><td class="asof">8/5</td></tr>
      <tr><td class="name">영국 10년물</td><td class="num">4.894%</td><td class="num down">−0.3bp</td><td class="asof">8/5</td></tr>
    </tbody>
  </table>

  <h3>원자재</h3>
  <table>
    <tbody>
      <tr><td class="name">WTI</td><td class="num">$74.77</td><td class="num down">−0.60%</td><td class="asof">8/5</td></tr>
      <tr><td class="name">브렌트유</td><td class="num">$79.10</td><td class="num down">−0.44%</td><td class="asof">8/5</td></tr>
      <tr><td class="name">천연가스(TTF)</td><td class="num">€54.66</td><td class="num up">+4.31%</td><td class="asof">8/7 현재</td></tr>
      <tr><td class="name">휘발유(RBOB)</td><td class="num">$2.9845</td><td class="num down">−4.16%</td><td class="asof">8/7 현재</td></tr>
      <tr><td class="name">금</td><td class="num">$4,318.92</td><td class="num up">+0.32%</td><td class="asof">8/5</td></tr>
    </tbody>
  </table>
  </div>
  </div>
</section>

<section>
  <h2>02 · 경제지표</h2><div class="h2rule"></div>
  <ul class="notes">
    <li><b>미 ADP 민간고용(7월) +4.4만 명, 예상(+7만) 큰 폭 하회.</b> 1월 이후 최저치로, 오늘 밤 NFP를 앞두고 고용 둔화 우려를 키운 지표. 다만 ADP·NFP 간 상관관계가 최근 약해진 편이라 과도한 해석은 경계할 필요.</li>
    <li><b>미 신규 실업수당 청구 컨센서스 20.3만 건(전주 19.7만 건).</b> 완만한 증가가 예상되나 여전히 역사적으로 낮은 수준 — 노동시장이 급격히 무너지는 신호는 아직 아님.</li>
    <li><b>미 2분기 비농업생산성 컨센서스 +0.6%(전분기 +0.3%).</b> 생산성 개선이 확인되면 임금발 인플레이션 압력을 일부 상쇄하는 요인으로 해석 가능.</li>
    <li><b>한국 6월 경상수지 497.3억 달러 흑자, 2개월 연속 월간 사상 최대.</b> 반도체 중심 IT 수출이 6월 상품수출 최초 월 1,000억 달러 돌파를 견인. 원화 강세 배경으로 작용.</li>
  </ul>
</section>

<section>
  <h2>03 · 주요 뉴스</h2><div class="h2rule"></div>
  <ul class="notes">
    <li><b>연준 인사 발언이 엇갈렸습니다.</b> 쿡 이사는 인플레이션이 계속 높은 수준을 유지하면 금리 인상도 검토할 수 있다는 매파적 입장을 밝힌 반면, 데일리 샌프란시스코 연은 총재는 지난주 동결 결정을 지지하며 9/16일 회의 전까지 추가 데이터를 지켜보자는 신중론을 폈습니다. 시장은 이 엇갈린 시그널을 오늘 밤 NFP로 정리하려는 분위기입니다.</li>
    <li><b>호르무즈 해협 통항 협상이 계속 진행 중입니다.</b> 이란·오만 간 통항로 합의 논의가 이어지고 있으나 세부 조건(관세, 관할권 등)에서 이견이 남아있는 것으로 전해졌습니다. 협상 진전 소식이 나올 때마다 유가가 민감하게 반응하는 흐름이 반복되고 있어, 오늘도 관련 변동성에 유의할 필요가 있습니다.</li>
    <li><b>메모리·반도체 업종에서 실적 실망이 이어졌습니다.</b> 샌디스크(SNDK) 등이 조정을 받았고, 이 흐름이 간밤 코스피 급락(−4.58%)의 직접적 배경으로 지목됐습니다. 다만 국내 반도체 수출 자체는 6월 경상수지 사상 최대치를 견인한 주역이라, 실적 우려와 수출 펀더멘털 사이의 온도차가 존재합니다.</li>
  </ul>
</section>

<section>
  <h2>04 · 주요 연구자료 <span style="font-weight:400;color:var(--muted)">(간밤 업데이트분)</span></h2><div class="h2rule"></div>
  <ul class="notes">
    <li><b><a href="https://www.federalreserve.gov/econres/feds/inflation-uncertainty-and-endogenous-planning-horizons.htm" target="_blank" rel="noopener">Inflation Uncertainty and Endogenous Planning Horizons</a></b> <span style="color:var(--muted)">— FRB, FEDS 2026-055, Gust·Herbst·López-Salido</span><br>기업이 가격을 설정할 때 "얼마나 멀리까지 내다보고 계획하는지"를 내생적으로 모형화. 수요·공급 충격이 크고 지속적일수록 기업이 더 먼 미래까지 계획하게 되어 인플레이션이 충격에 더 민감해지고, 인플레이션 불확실성도 함께 커진다는 결과.</li>
    <li><b><a href="https://libertystreeteconomics.newyorkfed.org/2026/08/why-do-fewer-renters-expect-to-move/" target="_blank" rel="noopener">Why Do Fewer Renters Expect to Move?</a></b> <span style="color:var(--muted)">— 뉴욕연은, Liberty Street Economics, Gresh·Haughwout·Lee·van der Klaauw</span><br>세입자의 3년 내 이주 예상 비율이 지난 12년간 20%p 하락. 세입자가 체감하는 예상 모기지 금리가 2021년 약 3.3%에서 2024년 6.8%로 두 배 이상 뛴 게 핵심 배경 — 자가 전환 장벽이 임차 유동성 자체를 낮추고 있다는 시사점.</li>
    <li><b>PIIE·Brookings·Brussels Institute·IMF·BIS</b> — 간밤 사이 새로 올라온 주요 자료 없음</li>
  </ul>
</section>

<section>
  <h2>05 · 오늘 일정 (한국시간)</h2><div class="h2rule"></div>
  <div class="sched">
    <div class="row key"><span class="t">밤 9:30</span><span class="e">미 7월 비농업고용지표(NFP) — 컨센서스 +8.8만 명, 실업률 4.2%</span></div>
    <div class="row key"><span class="t">밤 9:30</span><span class="e">미 7월 평균시간당임금(MoM 컨센서스 +0.3%)</span></div>
    <div class="row"><span class="t">오전 (독일시각)</span><span class="e">독일 6월 산업생산·무역수지</span></div>
    <div class="row"><span class="t">오전 (프랑스시각)</span><span class="e">프랑스 6월 무역수지</span></div>
    <div class="row"><span class="t">오늘 중</span><span class="e">FOMC 바킨 총재 발언</span></div>
    <div class="row"><span class="t">밤 11:00경</span><span class="e">뉴욕연은 1년 기대인플레이션(7월)</span></div>
  </div>
</section>

</div>
</body>
</html>
"""


TEMPLATE_MD = """# 모닝 마켓 브리핑 — 2026년 8월 7일 (금)
간밤(미 8/6·목) 마감 + 오늘 아시아·미국·유럽 일정

## 0. 오늘의 한줄 요약
- 미 ADP 민간고용(7월) +4.4만 명, 예상(+7만) 큰 폭 하회 — 1월 이후 최저치, 오늘 밤 NFP를 앞두고 고용 둔화 우려 확산
- 연준 인사 발언 엇갈림 — 쿡 이사는 "인플레 지속 시 인상도 검토" 매파적 발언, 데일리 총재는 동결 지지하며 9/16 회의까지 관망
- 호르무즈 해협 통항 협상 지속 — 이란·오만 세부조건 이견, 진전 소식마다 유가가 민감 반응
- [자산] 다우 −464.02p(−0.85%) — 국채금리 상승에 5거래일 연속 이어가던 사상 최고 행진 마감
- [자산] 코스피 −4.58%(6,296.38) — 간밤 뉴욕發 반도체 단기 과열 우려로 급락, 코스닥은 반대로 상승

## 1. 시황

**주가지수** (기준일 표시, S&P 500 클릭 시 → [Finviz 실시간 섹터별 히트맵](https://finviz.com/map))
| 지수 | 레벨 | 등락 | 기준 |
|---|---:|---:|---|
| 다우존스 | 53,885.10 | −0.85% | 8/6 |
| [S&P 500](https://finviz.com/map) | 7,709.96 | −0.18% | 8/6 |
| 나스닥종합 | 26,348.35 | −0.06% | 8/6 |
| VIX | 15.11 | −4.43% | 8/6 |
| DAX | 26,140.13 | +0.05% | 8/6 |
| EURO STOXX50 | 6,502.56 | +0.39% | 8/6 |
| 코스피 | 6,296.38 | −4.58% | 8/6 |

**채권 금리**
| 항목 | 레벨 | 등락 | 기준 |
|---|---:|---:|---|
| 미 10년물 | 4.611% | −0.6bp | 8/5 |
| 미 2년물 | 4.204% | +1.0bp | 8/7 현재 |
| 미 30년물 | 5.161% | −1.2bp | 8/5 |
| 10Y−2Y 스프레드 | +31.3bp | +4.2bp | 8/5 |
| 독일 10년물 | 3.104% | −1.3bp | 8/5 |
| 영국 10년물 | 4.894% | −0.3bp | 8/5 |

**원자재**
| 품목 | 레벨 | 등락 | 기준 |
|---|---:|---:|---|
| WTI | $74.77 | −0.60% | 8/5 |
| 브렌트유 | $79.10 | −0.44% | 8/5 |
| 천연가스(TTF) | €54.66 | +4.31% | 8/7 현재 |
| 휘발유(RBOB) | $2.9845 | −4.16% | 8/7 현재 |
| 금 | $4,318.92 | +0.32% | 8/5 |

**환율**
| 통화 | 레벨 | 등락 | 기준 |
|---|---:|---:|---|
| 달러인덱스 | 99.61 | +0.06% | 8/5 |
| EUR/USD | 1.1548 | −0.06% | 8/7 현재 |
| USD/JPY | 157.75 | 보합 | 8/7 현재 |
| USD/KRW | 1,423.8 | −0.7원 | 8/6 |

## 2. 경제지표
- **미 ADP 민간고용(7월) +4.4만 명, 예상(+7만) 큰 폭 하회.** 1월 이후 최저치로, 오늘 밤 NFP를 앞두고 고용 둔화 우려를 키운 지표. 다만 ADP·NFP 간 상관관계가 최근 약해진 편이라 과도한 해석은 경계할 필요.
- **미 신규 실업수당 청구 컨센서스 20.3만 건(전주 19.7만 건).** 완만한 증가가 예상되나 여전히 역사적으로 낮은 수준.
- **미 2분기 비농업생산성 컨센서스 +0.6%(전분기 +0.3%).** 생산성 개선이 확인되면 임금발 인플레이션 압력을 일부 상쇄하는 요인으로 해석 가능.
- **한국 6월 경상수지 497.3억 달러 흑자, 2개월 연속 월간 사상 최대.** 반도체 중심 IT 수출이 견인, 원화 강세 배경.

## 3. 주요 뉴스
- **연준 인사 발언 엇갈림** — 쿡 이사(매파: 인플레 지속 시 인상 검토) vs 데일리 총재(동결 지지, 9/16일 회의까지 관망). 시장은 오늘 밤 NFP로 방향을 정리하려는 분위기.
- **호르무즈 해협 통항 협상 지속** — 이란·오만 간 논의 진행 중이나 세부 조건 이견, 진전 소식마다 유가가 민감 반응.
- **메모리·반도체 실적 실망** — 샌디스크 등 조정, 간밤 코스피 급락의 직접 배경. 다만 국내 반도체 수출 펀더멘털은 오히려 견조.

## 4. 주요 연구자료 (간밤 업데이트분)
- **[Inflation Uncertainty and Endogenous Planning Horizons](https://www.federalreserve.gov/econres/feds/inflation-uncertainty-and-endogenous-planning-horizons.htm)** — FRB, FEDS 2026-055, Gust·Herbst·López-Salido
  기업이 가격을 설정할 때 "얼마나 멀리까지 내다보고 계획하는지"를 내생적으로 모형화. 수요·공급 충격이 크고 지속적일수록 기업이 더 먼 미래까지 계획하게 되어 인플레이션이 충격에 더 민감해지고, 인플레이션 불확실성도 함께 커진다는 결과.
- **[Why Do Fewer Renters Expect to Move?](https://libertystreeteconomics.newyorkfed.org/2026/08/why-do-fewer-renters-expect-to-move/)** — 뉴욕연은, Liberty Street Economics, Gresh·Haughwout·Lee·van der Klaauw
  세입자의 3년 내 이주 예상 비율이 지난 12년간 20%p 하락. 세입자가 체감하는 예상 모기지 금리가 2021년 약 3.3%에서 2024년 6.8%로 두 배 이상 뛴 게 핵심 배경.
- **PIIE·Brookings·Brussels Institute·IMF·BIS** — 간밤 사이 새로 올라온 주요 자료 없음

## 5. 오늘 일정 (한국시간)
| 시각 | 이벤트 |
|---|---|
| 밤 9:30 | 미 7월 비농업고용지표(NFP) — 컨센서스 +8.8만 명, 실업률 4.2% |
| 밤 9:30 | 미 7월 평균시간당임금 (MoM 컨센서스 +0.3%) |
| 오전 | 독일 6월 산업생산·무역수지, 프랑스 6월 무역수지 |
| 오늘 중 | FOMC 바킨 총재 발언 |
| 밤 11:00경 | 뉴욕연은 1년 기대인플레이션(7월) |
"""


def compute_dates():
    """오늘(KST) 날짜와, 가장 최근에 완료됐을 것으로 추정되는 미국 정규장 마감일을 계산한다.
    미국 공휴일은 반영하지 않은 단순 추정치이며, 최종 판단은 프롬프트에서 web_search로
    한 번 더 확인하도록 지시한다."""
    kst = ZoneInfo("Asia/Seoul")
    et = ZoneInfo("America/New_York")
    now_kst = datetime.now(kst)
    now_et = now_kst.astimezone(et)

    candidate = now_et.date()
    if now_et.time() < dtime(16, 0):
        candidate = candidate - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate = candidate - timedelta(days=1)

    return now_kst, candidate


def build_system_prompt():
    persona = (
        "당신은 한국 투자자를 위한 '모닝 마켓 브리핑' 뉴스레터를 매일 작성하는 "
        "전문 매크로/시장 데스크 애널리스트입니다. 아래 스타일 가이드와 두 개의 예시 "
        "템플릿(HTML, Markdown)을 반드시 그대로 따라야 합니다. 구조, CSS, 톤, 섹션 순서는 "
        "예시와 동일하게 유지하고, 내용(수치와 뉴스)만 오늘 기준으로 새로 채우세요. "
        "web_search 도구를 적극적으로 사용해서 investing.com을 1순위, Yahoo Finance를 "
        "2순위로 실제 시세 전용 페이지 값을 확인하고, 뉴스 기사 프로즈에서 숫자를 "
        "추정해서 쓰지 마세요."
    )

    parts = [
        persona,
        "",
        "=== 스타일 가이드 시작 ===",
        STYLE_GUIDE,
        "=== 스타일 가이드 끝 ===",
        "",
        "=== 예시 템플릿: index.html (2026-08-07자, 형식/스타일만 참고. 이 안의 수치와 뉴스는 그날의 예시일 뿐이며 그대로 재사용하면 안 됨) ===",
        TEMPLATE_HTML,
        "=== 예시 템플릿 끝 ===",
        "",
        "=== 예시 템플릿: index.md (2026-08-07자, 형식/스타일만 참고. 이 안의 수치와 뉴스는 그날의 예시일 뿐이며 그대로 재사용하면 안 됨) ===",
        TEMPLATE_MD,
        "=== 예시 템플릿 끝 ===",
    ]
    return chr(10).join(parts)


def build_user_prompt(now_kst, candidate_us_close):
    kst_str = now_kst.strftime("%Y-%m-%d (%a)")
    us_close_str = candidate_us_close.strftime("%Y-%m-%d (%a)")
    archive_date = now_kst.strftime("%Y-%m-%d")

    lines = [
        "오늘은 한국시간 기준 " + kst_str + " 입니다. 이 브리핑은 매일 한국시간 06:30에 발행됩니다.",
        "",
        (
            "간밤(가장 최근 완료된 미국 정규장 마감일) 추정치는 " + us_close_str + " 입니다. "
            "이 추정치는 단순 요일 계산(평일 16:00 미 동부시간 마감 기준)으로 산출된 값이며 "
            "미국 공휴일은 반영되어 있지 않습니다. 실제로 이 날짜에 미국 증시가 정상적으로 "
            "열렸는지 web_search로 반드시 확인하고, 만약 공휴일 등으로 휴장이었다면 그 이전의 "
            "실제 마지막 거래일로 정정해서 사용하세요."
        ),
        "",
        (
            "오늘 자 브리핑에서 다뤄야 할 범위는 스타일 가이드 0번 항목에 정의된 대로 "
            "간밤 미국/유럽 마감 + 오늘 아시아/미국/유럽 예정 일정, 딱 하루치만입니다. "
            "지난 업데이트 이후 며칠치를 전부 훑지 마세요."
        ),
        "",
        "이번 브리핑의 아카이브 파일명에 사용할 날짜는 " + archive_date + " 입니다.",
        "",
        (
            "출력 형식: 아래 두 블록만 정확히 출력하세요. 블록 바깥에는 어떤 설명이나 "
            "코멘트도 쓰지 마세요. 각 블록 안에는 마크다운 코드펜스 없이 순수 HTML 전체 "
            "문서 하나, 순수 Markdown 전체 문서 하나만 넣으세요."
        ),
        "",
        HTML_START,
        "(여기에 오늘자로 완성된 index.html 전체 내용을 넣으세요)",
        HTML_END,
        MD_START,
        "(여기에 오늘자로 완성된 index.md 전체 내용을 넣으세요)",
        MD_END,
    ]
    return chr(10).join(lines)


def extract_block(text, start_marker, end_marker):
    start_idx = text.find(start_marker)
    if start_idx == -1:
        return None
    start_idx += len(start_marker)
    end_idx = text.find(end_marker, start_idx)
    if end_idx == -1:
        return None
    return text[start_idx:end_idx].strip()


def call_claude(system_prompt, user_prompt):
    client = anthropic.Anthropic(timeout=600.0)
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        tools=[
            {
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": WEB_SEARCH_MAX_USES,
            }
        ],
    )

    if response.stop_reason == "max_tokens":
        print("WARNING: response stopped at max_tokens, content may be truncated.", file=sys.stderr)

    usage = getattr(response, "usage", None)
    if usage is not None:
        print("token usage: " + str(usage))

    text_parts = []
    for block in response.content:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text_parts.append(block.text)

    return chr(10).join(text_parts)


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    now_kst, candidate_us_close = compute_dates()
    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(now_kst, candidate_us_close)

    print("Calling Claude API (model=" + MODEL + ")...")
    raw_text = call_claude(system_prompt, user_prompt)

    html_content = extract_block(raw_text, HTML_START, HTML_END)
    md_content = extract_block(raw_text, MD_START, MD_END)

    if not html_content or "<html" not in html_content.lower():
        print("ERROR: failed to extract valid HTML content from model response.", file=sys.stderr)
        print("--- raw response (first 2000 chars) ---", file=sys.stderr)
        print(raw_text[:2000], file=sys.stderr)
        sys.exit(1)

    if not md_content or "모닝 마켓 브리핑" not in md_content:
        print("ERROR: failed to extract valid Markdown content from model response.", file=sys.stderr)
        print("--- raw response (first 2000 chars) ---", file=sys.stderr)
        print(raw_text[:2000], file=sys.stderr)
        sys.exit(1)

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_date = now_kst.strftime("%Y-%m-%d")

    INDEX_HTML.write_text(html_content, encoding="utf-8")
    INDEX_MD.write_text(md_content, encoding="utf-8")
    (ARCHIVE_DIR / (archive_date + "_모닝브리핑.html")).write_text(html_content, encoding="utf-8")
    (ARCHIVE_DIR / (archive_date + "_모닝브리핑.md")).write_text(md_content, encoding="utf-8")

    print("OK: briefing generated and files written for " + archive_date)


if __name__ == "__main__":
    main()
