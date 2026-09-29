#!/usr/bin/env python3
"""
전파정책 전문가 AI — 자동 크롤러
매시간 GitHub Actions에서 실행
크롤링 대상: 국립전파연구원 · 과기정통부 · 전자신문 외 다수
결과: Supabase news_feed 저장 + 이메일 발송 + 긴급 시 텔레그램 알림
"""

import os
import re
import json
import time
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# .env 파일 자동 로딩 (PC 로컬 실행 시)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # GitHub Actions에서는 환경변수 직접 주입, dotenv 불필요

import requests
import ssl
from requests.adapters import HTTPAdapter
from bs4 import BeautifulSoup
from supabase import Client
from sb_client import make_client, ran_recently, heartbeat as sb_heartbeat
import api_usage; api_usage.install()   # Anthropic usage 기록(#152) — 호출부 무변경, fail-open
import notify   # 텔레그램 전송 공용 유틸 (개선⑪) — 전송부만 위임
import urgency_rules   # 긴급도 공통 낱말 규칙 매처(#216) — 사내판·대시보드 JS와 같은 계약
import news_known      # 뉴스 중복 대조 공용(#234) — 후보만 DB 함수로, 실패 시 전량 조회
import retry_util      # 재시도 공용(#217) — 문장 판정 기록·팀 행 쓰기(#251)에만, Anthropic 호출에는 쓰지 않는다
import anthropic

# ── 환경변수 ────────────────────────────────────────────
SUPABASE_URL       = os.environ['SUPABASE_URL']
SUPABASE_KEY       = os.environ['SUPABASE_SERVICE_KEY']
# GitHub Actions 환경 감지 (본문 수집 스킵용)
IS_GITHUB_ACTIONS  = os.environ.get('GITHUB_ACTIONS', '').lower() == 'true'
EMAIL_FROM         = os.environ.get('EMAIL_FROM', '')
EMAIL_PASS         = os.environ.get('EMAIL_PASSWORD', '')
EMAIL_TO           = os.environ.get('EMAIL_TO', '')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID   = os.environ.get('TELEGRAM_CHAT_ID', '')
ANTHROPIC_API_KEY  = os.environ.get('ANTHROPIC_API_KEY', '')
RESEND_API_KEY     = os.environ.get('RESEND_API_KEY', '')
NAVER_CLIENT_ID    = os.environ.get('NAVER_CLIENT_ID', '')
NAVER_CLIENT_SECRET = os.environ.get('NAVER_CLIENT_SECRET', '')

# ── 초기화 ─────────────────────────────────────────────
sb: Client = make_client(SUPABASE_URL, SUPABASE_KEY)
KST = timezone(timedelta(hours=9))
HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'ko-KR,ko;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}


# ═══════════════════════════════════════════════════════
#  긴급 분류 — Claude Haiku AI 판단
# ═══════════════════════════════════════════════════════

# 긴급도 판정 기준 본문 — 개별 판정(_URGENCY_SYSTEM)이 쓴다. 선별 콜은 2026-09-20(#174)부터 등급을 내지 않는다
# (그림자 1,534건 실측: 선별 등급과 개별 판정 일치 56% — 대체재가 못 되므로 규칙·출력을 선별 콜에서 뺐다).
_URGENCY_CRITERIA = """[0단계 — 영역 게이트] 먼저 이 기사가 **이동통신·전파·통신정책 영역**의 일인지 확인한다.
이동통신망·기지국·무선국·주파수·전파, 통신사업자, 통신 규제·요금·이용자보호, 통신설비 침해사고가
**본론**이어야 한다. 낱말만 겹치고 영역이 다르면 등급을 올리지 않는다. 다만 얼마나 내릴지는 거리로 가른다.
- **완전히 다른 영역 → 동향파악** (식품·화학 공장 사고, 일반 형사·실종 사건, 부동산, 해상풍력 민원 등)
  (실제 오분류: 아이스크림 공장 암모니아 '누출', 경찰 실종사건 '허위 종결', 해상풍력 '전자파' 민원)
- **통신·방송·정보보호 언저리지만 이동통신 사안은 아님 → 금주검토**
  (터널 라디오 '중계기' 고장, 언론사·병원 대상 해킹, 방송사 승인 취소, 데이터센터 입지 민원,
   재난문자 과다발송 같은 이용자 불편 — 제도 논의로 번질 수 있어 버리지는 않는다)

[1단계 — 등급은 "사건이 크냐"가 아니라 "우리가 이번 주에 손을 대야 하냐"로 가른다]
⚠️ 즉시대응은 하루 몇 건 수준이다. 애매하면 한 단계 내린다.
⚠️ **단, 실제로 터진 사고·장애·유출은 이 "내린다"의 예외다** — 제도 변화만 중요한 것이 아니다.
   사고는 당장 손대야 하는 일이고, 우리 회사 사고가 아니어도 다음 규제와 비교 잣대를 만든다.

즉시대응:
- **침해사고·장애·유출 — 통신·정보통신 영역에서 실제로 터진 일은 등급을 내리지 않는다**
  · 통신사·통신망의 해킹·개인정보 유출·대규모 장애·먹통 — **자사·경쟁사를 가리지 않는다**
  · 이동통신 품질·기지국·공공 와이파이·재난안전망·철도 통신망 등 공공 통신망의 장애·사고·민원·비판 보도
  · 플랫폼·부가통신 사업자의 **대규모** 개인정보 유출과 그 조사·보상·제재 경과
    — 여기서 대규모는 **수백만 계정 이상**이거나 **통신 서비스·통신 이용자 피해로 이어진 것**을 말한다
      (예: 3,954만 계정이 털린 OTT 유출, 통신사 보상으로 준 이용권 계정이 재유출된 사건 → 즉시대응)
    — 수만~수십만 규모이고 통신과 연결되지 않은 일반 플랫폼 유출은 → 금주검토
    — **통신과 무관한 기관·플랫폼·기업의 유출은 규모가 수백만 계정 미만이면 즉시대응이 아니다 → 금주검토**
      (수천 명 규모, 「단독」, 「당초 신고의 N배」, 추가 유출 확인·개인정보위 조사 경과 보도여도 같다 — 통신 서비스·통신 이용자
       피해로 이어진 것만 예외. 실측: 자원봉사포털 8,785명·패션몰 19.6만 건 유출 보도가 즉시대응이 됐다)
  · 사고 대응의 적정성이 쟁점이 된 보도 — 신고 지연, 로그 삭제, 증거인멸, 조사 방해 의혹
  · 진행 중인 침해사고·제재 사건의 수사·조사·소송 경과와 선고·처분 일정
  ⚠️ 성과 홍보·구축 완료·예방 캠페인·주의보는 사고 보도가 아니다 → 금주검토 이하
  ⚠️ 이미 끝난 과거 사고를 돌아보는 회고·통계·순위 기사도 사고 보도가 아니다 → 금주검토
- **국정감사에 SK텔레콤이(또는 통신3사가 일괄로) 증인·참고인으로 채택·신청·소환·출석하는 보도** — 채택 단계든
  출석 당일이든 즉시대응. 타사만 소환된 국감 기사는 이 항목이 아니다(다른 항목으로 판단).
  ⚠️ **타 상임위(복지위·정무위·산자위·환노위 등) 국감의 플랫폼·유통·제약 등 타 업종 증인 채택·신청은 통신 사안이 아니다
     → 동향파악** — 정보보호 언저리라도 금주검토를 넘지 않는다
     (실측: 복지위 국감의 미용의료·약배송 플랫폼 증인 신청 기사가 '국감 + 증인 신청' 모양만으로 즉시대응이 됐다)
- **제도가 실제로 움직인 것** — 법·시행령·고시·기준의 제개정과 시행, 정부·위원회의 의결·처분·행정지도,
  국회의 법안 처리, 요금·약관 규제, 무선국·통신설비 제도 변경
  · **이용자보호 업무 평가의 결과·등급 공표**는 특정 사업자 성과 보도처럼 보여도 제도 사안이다 → 즉시대응
- **주파수가 본론인 기사** — 할당·재할당·경매·대가 산정·효율·간섭·회수
  · ⚠️ **주파수가 본론이면 아래 "정책 논의 단계"보다 이 항목이 우선한다** — 세미나·학회·연구·전문가 제언
    단계라도 즉시대응이다. 재할당 대가는 회사 비용에 직결되고, 제도 변화는 논의 단계에서 먼저 드러난다.
  · 주파수를 **스쳐 지나가듯 한 번 언급**하고 본론이 전혀 다른 기사만 예외다 → 금주검토
    ▸ **판별법**: 기사의 **주장·결론이 주파수 제도**(대가 산정·할당 방식·일정·회수)**에 관한 것이면 본론**이고,
      주파수가 **다른 주장의 배경·변수로만** 쓰였으면 스친 언급이다
      (스친 언급 예: 통신사 실적·임원 인사 기사에서 "재할당을 앞두고" 정도로만 스친 경우).
      · 기업·기관이 **자기 특화망(이음5G)용으로 전용 주파수를 할당받았다**는 언급은 그 기업의 망 구축 사안이지
        주파수 제도 사안이 아니다 → 주파수 본론이 아니다(협력 통신사가 SK텔레콤이어도 같다 → 금주검토)
      ⚠️ **망 투자·5G SA 전환·기지국 구축은 그 자체가 팀 소관 사안이다** — 주파수 항목에 안 걸려도
      "스쳤으니 하찮다"로 읽지 말 것. **동향파악으로 내리지 않고 금주검토로 둔다.**
      (위쪽도 닫는다: 정부-통신3사 공동 사업·제도 변경 등 **다른 즉시대응 항목에 따로 걸리지 않는 한**
       망 투자·구축 기사 자체를 즉시대응으로 올리지는 않는다.)
    ⚠️ 경매·재할당·대가가 **기사의 축이면 관점이 무엇이든 즉시대응** — 장비·투자·시장 전망 관점도 포함한다.
    ▸ 증권면·재테크 코너 기사에는 **이 줄을 위 판별법보다 먼저 적용한다** —
      경매·재할당 일정이나 대가 자체를 분석하면 즉시대응, **수혜 종목 나열이 전부면 동향파악**.
      제목만으로 갈리지 않으면(예: "…경매 전망, 수혜주는") 본문 첫 문단을 보고, 그래도 애매하면 동향파악.
- **정부가 통신 3사와 함께 추진하는 사업·협의체** — 투자·자원·인프라 정책, 폐기지국·통신설비의
  자원 재활용처럼 정부가 통신사와 공동으로 벌이는 사업, 재난·공공 통신 체계 개선
  ⚠️ **가르는 기준은 "우리가 지금 새로 해야 할 일이 생기는가"다.** 이통3사가 함께 했다는 사실이나
     '재난'이라는 낱말만으로 올리지 않는다 — **제도·의무·설비가 바뀌지 않고 이미 시행을 마친
     자발적 조치는 → 동향파악** (실측: 네팔 홍수 구호인력 로밍요금 면제를 '이통3사 공동 + 재난'으로
     읽어 즉시대응이 됐고, 같은 사건이 한 시간 간격으로 두 번 발송됐다)
- **SK텔레콤이 당사자인 부정적 사안** (과징금·제재·소송·장애·해킹·점유율 하락·불공정 논란·비판 보도)
  및 상장·투자·수주·실적 등 재무 이벤트
  · 여기서 **수주·투자**는 정부·공공 사업 수주, M&A·상장·유상증자처럼 규제·공시가 따르는 것을 말한다.
    **민간 기업 고객의 망 구축·5G 특화망(이음5G)·전용망·B2B 계약·업무협약은 일상적 영업 활동이다 → 금주검토**
    (실측: 하나금융 5G 특화망 스마트오피스 구축 보도 170건 중 30건이 즉시대응이 됐다 — 제휴·구축은 재무 이벤트가 아니다)
- **플랫폼 사업자의 개인정보 사건에 정부가 전기통신사업법·정보통신망법으로 조사·제재·법적 책임을
  검토한다고 밝힌 것** (예: 검색사업자의 디지털성범죄 피해자 정보 노출과 정부의 책임 추궁)
- **경쟁사 사안 중 업계 공통 규제로 번질 것** — 정부의 통신사 전수조사·일괄 점검, 국회·시민단체가
  통신사 전반을 겨냥한 문제 제기, 동일 설비·기술·관행에서 비롯된 사고.
  **"우리도 같은 지적을 받을 수 있는가"로 판단한다.**
  ⚠️ 경쟁사의 개별 경영·세무·상품·실적 사안은 여기 해당하지 않는다 → 금주검토
  ⚠️ **경쟁사의 해외 기관·표준화 회의 참여, 해외 협력·MOU, 국방·공공 사업 수주도 개별 경영 사안이다 → 금주검토**
     — 정부가 통신 3사 공동으로 제도·의무를 만드는 경우만 즉시대응이다
     (실측: KT의 NATO 국방통신 표준화 회의 참여 보도 77건 중 32건이 즉시대응이 됐다)

금주검토:
- 정책 논의 단계 — 토론회·연구·전문가 제언·입법예고 이전의 검토 보도
  (단, **주파수가 본론이면 즉시대응이 우선** — 위 즉시대응 주파수 항목 참조)
- 이동통신·전파 관련 기술 소개, 망 고도화·투자 동향, 업계 통계·시황·전망(ARPU·가입자 추이 등)
- SK텔레콤의 일상적 영업 활동(요금제·단말·부가서비스 출시, 제휴, 마케팅)
  ⚠️ 다만 **요금 인상·약관 변경처럼 이용자 부담이나 규제 쟁점이 걸리면 즉시대응**
- 경쟁사의 개별 경영·세무·상품 사안
- 통신·정보통신 영역 밖 업종의 해킹·유출 사건 (0단계 게이트에서 내려온 것)
- 통신장비사·타 업종·공공기관이 당사자인 통신 관련 사안 (기본에서 한 단계 내린 결과)

동향파악:
- **재난·사고에 대한 통신사의 구호·지원 발표** — 로밍 요금 면제, 국제전화 감면, 기부·성금,
  피해지역 요금 유예. 사업자가 자발적으로 정하고 발표 시점에 이미 시행이 끝난 일이라
  우리가 새로 해야 할 일이 없다
  ⚠️ **다만 국내 재난으로 우리 망에 장애가 났거나, 정부의 재난로밍 명령·협조 요청이 걸린 것은
     즉시대응이다**(방발법 제37조의2 — 경보 발령과 피해사업자 요청 두 요건). 가르는 것은 '재난'이라는
     소재가 아니라 **우리에게 대응 시한이 생기느냐**다
- **정부·기관의 공모전·캠페인·시상·홍보성 발표** (전자파 공모전 등)
  ⚠️ 다만 **수상·우수사례 형식이어도 제도 변경이나 정부-통신사 공동 사업이 본론이면 내리지 않는다**
     (예: "망중립성 예외 적용, 소방관 통신 우선" 보도는 제도 사안이라 금주검토 — 제도가 이미 시행 중이고
      수상 사실이 새 소식이면 즉시대응까지 올리지는 않는다)
- **특정 지자체 단신** — 지역 공공 와이파이 설치·확대, 지역 행사
- 해외 일반 동향·업계 트렌드·참고용 기사
- **통신과 무관한** 일반 사건의 판결·구속·수사결과 등 사후 보도
  (통신 사건의 수사·소송 경과는 진행 중이면 즉시대응, 완전히 종결된 건만 여기)
- 통신장비사·그 외 기업의 상장·투자유치·수주·실적
- 자동번역투의 출처 불명 기사, 본문이 광고·시황 나열인 기사"""

_URGENCY_SYSTEM = """당신은 SK텔레콤 Comm센터 기술정책팀의 전파정책 모니터링 AI입니다.
기사 제목과 본문을 읽고 SKT 관점에서 대응 우선순위를 판단합니다.

아래 기준으로 셋 중 하나만 출력하세요 (다른 말 없이 단어만):

""" + _URGENCY_CRITERIA

# 선별 콜 판정 규칙 — system 블록 끝에 붙인다(#174). 종전에는 사용자 메시지 앞에 매 배치 붙여 보냈는데,
# 기준문·피드백과 함께 system에 두면 프롬프트 캐시(1시간)에 통째로 실려 배치마다 0.1배 요금으로 읽힌다.
# 사용자 메시지에는 기사 JSON만 남는다. 6번(대응 우선순위) 규칙은 뺐다 — 선별 등급은 개별 판정이 전건 덮어쓰므로.
_SCREEN_RULES = (
    '\n\n[판정 규칙 — 사용자 메시지의 기사 목록에 적용]\n'
    '1. 각 기사를 목록 내 다른 기사·순서와 무관하게 한 건씩 독립적으로 판정하라.\n'
    '2. 위 기준문을 문자 그대로 적용하라. 기준문에 없는 근거로 추측하지 말라.\n'
    '3. 관련/무관이 애매하면 관련으로 판정하라(놓침보다 과잉 포함이 낫다).\n'
    '4. 관련으로 판정한 기사에는 분야 태그를 붙여라. 태그는 아래 6종뿐이다.\n'
    '   - spectrum: 주파수 할당·재할당, 무선국·기지국, 전자파, 비면허 대역, '
    '통신망 구축·투자·품질·장애, 해저케이블, 규제 대상 통신시설(집적정보통신시설 보호조치·IDC 장애)\n'
    '   - market: 요금제, 알뜰폰·도매대가, 번호이동, 단말 유통·보조금, 결합상품\n'
    '   - regulation: 과징금·시정명령, 인허가·심사, 표시·광고, 약관, 이용자보호\n'
    '   - security: 해킹·유출, ISMS, 개인정보위 처분, 위치정보, 통신시설 보호조치\n'
    '   - ai: AI 기본법·규제, 국가 AI 전략, AI 데이터센터 정책(전력 특례·입지 규제 등)\n'
    '   태그는 기사 제목에 나온 단어가 아니라 기사가 다루는 사안을 기준으로 고른다. '
    '한 기사가 여러 사안을 다루면 해당 태그를 모두 붙인다(최대 3개). '
    '5종 중 어느 것도 확실하지 않으면 tags를 비워 둔다 — 억지로 채우지 말라.\n'
    '5. 관련으로 판정한 기사에는 그 기사가 다루는 사건을 event에 한 줄로 적어라.\n'
    '   - 12~25자. 언론사 수사·따옴표·기자 해석을 빼고 사실만 쓴다.\n'
    '   - 같은 사건을 다룬 다른 기사와 표현이 같아지도록 '
    '「핵심 주체 + 행위 + 수치」 순으로 쓴다. 예: SKT 1~7월 번호이동 순증 1위\n'
    '   - 기사 제목을 그대로 베끼지 말라. 제목이 달라도 사건이 같으면 같은 문장이 나와야 한다.\n'
    '   - 사건이 뚜렷하지 않으면(전망·해설·기획 기사 등) event를 빈 문자열로 둔다. '
    '억지로 만들지 말라.\n'
    '관련으로 판정된 기사만 record_relevant_news 도구의 relevant 배열에 '
    '{id, tags, event} 형태로 기록하라. 관련이 하나도 없으면 빈 배열을 기록하라.\n'
)

_AI_PRIORITY_MAP = {'즉시대응': '긴급', '금주검토': '보통', '동향파악': '참고'}
_REVERSE_PRIORITY = {'긴급': '즉시대응', '보통': '금주검토', '참고': '동향파악'}
_FALLBACK_MOBILE = ['이동통신', '기지국', '공공와이파이', '와이파이', '전파', '전자파', '무선국', '주파수']

_feedback_rows_cache = None
_distilled_rules_cache = None

def _load_feedback_rows() -> list:
    """importance_feedback 공통 행 로드 (실행당 1회, 최신순 최대 500건)"""
    global _feedback_rows_cache
    if _feedback_rows_cache is None:
        try:
            # 공통 행(team_id null)만 — 팀 행은 그 팀의 관점이라 섞으면 공통 AI 판정·증류 규칙이 흔들린다(#250, 결정 E8)
            res = sb.table('importance_feedback').select('title,user_importance') \
                .is_('team_id', 'null').order('updated_at', desc=True).limit(500).execute()
            _feedback_rows_cache = [r for r in (res.data or []) if r.get('title') and r.get('user_importance')]
            if _feedback_rows_cache:
                print(f'[피드백] 누적 사례 {len(_feedback_rows_cache)}건 로드')
        except Exception as e:
            print(f'[피드백] importance_feedback 조회 실패(무시): {e}')
            _feedback_rows_cache = []
    return _feedback_rows_cache


def _fb_tokens(s: str) -> set:
    """제목 → 유사 사례 겹침 비교용 낱말. 한글 낱말은 조사를 뗀다(#256, 2026-09-29 — 「국감도」·「삼성전자와」가 「국감」·「삼성전자」와
    다른 낱말로 세어져 09-26 피드백(식품·유통 국감 → 동향파악)이 09-29 복지위 국감 기사에 붙지 않았다). 조사 규칙은
    news_dedup의 것(억제·묶기와 같은 규칙), 뗀 뒤 2자 미만이면 원형. 고정 블록(캐시 접두)에는 영향이 없다 — 유사 블록은 캐시 밖."""
    from news_dedup import _JOSA_RE
    out = set()
    for w in re.findall(r'[가-힣A-Za-z0-9]{2,}', (s or '').lower()):
        d = _JOSA_RE.sub('', w)
        out.add(d if len(d) >= 2 else w)
    return out


DISTILL_MIN_FEEDBACK = 50   # 증류 착수 최소 표본. 아래 주석 참조 — 20건에서 실패했다.


def _get_distilled_rules() -> str:
    """피드백이 DISTILL_MIN_FEEDBACK건 이상이면 Haiku로 일반화 규칙 증류 → feedback_rules 캐시.
    마지막 증류 이후 10건 이상 추가됐을 때만 재생성 (실행당 최대 1회 API 호출).

    ⚠️ 임계값을 20 → 50으로 올렸다(2026-08-21, 배경역사 #109). 20건에서 처음 돌자마자
    쓸 수 없는 규칙이 나왔다: ①**각 항목에 등급이 안 적혀** "올려라"인지 "내려라"인지 알 수
    없는 목록이었고 ②「통신 기술 고도화(AI·5G)」와 「정부 공모전·홍보 등 일반 정보성」이
    같은 목록에 섞여 서로 모순됐다(운영자는 전자를 올리고 후자를 내렸다).
    그 규칙이 판정 프롬프트의 **최우선 기준**으로 들어가 오분류를 키웠다.
    임계값을 내리지 말 것 — 표본이 적으면 규칙이 없느니만 못하다."""
    global _distilled_rules_cache
    if _distilled_rules_cache is not None:
        return _distilled_rules_cache
    rows = _load_feedback_rows()
    if len(rows) < DISTILL_MIN_FEEDBACK or not ANTHROPIC_API_KEY:
        _distilled_rules_cache = ''
        return ''
    saved = None
    try:
        cur = sb.table('feedback_rules').select('rules,feedback_count').eq('id', 1).execute()
        saved = cur.data[0] if cur.data else None
        if saved and len(rows) < (saved.get('feedback_count') or 0) + 10:
            _distilled_rules_cache = saved.get('rules') or ''
            return _distilled_rules_cache
        sample = "\n".join(
            f"- \"{r['title'][:70]}\" → {_REVERSE_PRIORITY.get(r['user_importance'], r['user_importance'])}"
            for r in rows[:200]
        )
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001', max_tokens=600,
            # ⚠️ "규칙을 요약하라"만 시키면 **등급이 빠진 목록**이 나온다(#109 실패 사례).
            #    규칙은 판정 프롬프트에 최우선 기준으로 들어가므로 방향이 없으면 해롭다.
            system='다음은 뉴스 긴급도 분류(즉시대응/금주검토/동향파악)에 대한 담당자 수정 사례입니다.\n'
                   '사례를 일반화한 분류 규칙 5~10개를 불릿(-)으로 쓰세요.\n'
                   '**각 규칙은 반드시 "<조건> → <즉시대응|금주검토|동향파악>" 형식으로 등급을 명시**하세요. '
                   '등급 없는 규칙은 쓸모가 없습니다.\n'
                   '서로 모순되는 규칙을 함께 쓰지 마세요 — 사례가 엇갈리면 그 주제는 규칙에서 빼세요.\n'
                   '사례에서 확인되지 않는 일반론은 쓰지 마세요. 규칙 외 다른 말 금지.',
            messages=[{'role': 'user', 'content': sample}],
        )
        rules = resp.content[0].text.strip()
        sb.table('feedback_rules').upsert({
            'id': 1, 'rules': rules, 'feedback_count': len(rows),
            'updated_at': datetime.now(KST).isoformat(),
        }).execute()
        print(f'[피드백] 분류 규칙 재증류 완료 ({len(rows)}건 기반)')
        _distilled_rules_cache = rules
    except Exception as e:
        print(f'[피드백] 규칙 증류 실패(무시): {e}')
        _distilled_rules_cache = (saved.get('rules') or '') if saved else ''
    return _distilled_rules_cache


def _fb_line(r: dict) -> str:
    return f"- \"{r['title'][:70]}\" → {_REVERSE_PRIORITY.get(r['user_importance'], r['user_importance'])}"


_feedback_fixed_cache = None
# 등급당 사례 수. 4 → 12(#175-보론): 선별 콜 system이 3,145토큰이라 캐시 최소(4,096, **도구 776토큰 포함해 계산됨**)에
# 못 미쳐 캐시가 조용히 안 걸렸다(count_tokens는 도구를 1,100으로 세어 4,245로 보였지만 캐시 회계는 3,921). 사례를 늘려
# system을 ≈3,900토큰으로 키운다 — 패딩이 아니라 판정 재료라 선별·긴급도 둘 다에 유익하고, 캐시라 요금은 0.1배.
FEEDBACK_PER_CLASS = 12


def _feedback_fixed_block() -> str:
    """기사와 무관한 피드백 블록(#175): ① 증류 규칙 ② 등급별 균형 최신 사례(등급당 최대 FEEDBACK_PER_CLASS건).
    실행 안에서 바이트 단위로 동일 — 긴급도 콜의 **캐시 접두**가 된다. 정렬은 importance_feedback.updated_at 내림차순
    (DB 정렬)이라 피드백이 추가·수정될 때만 바뀐다(그때 캐시 1회 재작성). 시각·난수를 넣지 말 것."""
    global _feedback_fixed_cache
    if _feedback_fixed_cache is not None:
        return _feedback_fixed_cache
    rows = _load_feedback_rows()
    if not rows:
        _feedback_fixed_cache = ''
        return ''
    picked, per_class = [], {}
    for r in rows:
        c = r['user_importance']
        if per_class.get(c, 0) >= FEEDBACK_PER_CLASS:
            continue
        picked.append(r)
        per_class[c] = per_class.get(c, 0) + 1
    block = ''
    rules = _get_distilled_rules()
    if rules:
        block += "\n\n[담당자 분류 규칙 — 누적 피드백에서 추출. 최우선 적용]\n" + rules
    block += ("\n\n[담당자 분류 피드백 — 실제 담당자가 직접 수정한 사례. 유사한 기사는 반드시 이 기준을 우선 적용]\n"
              + "\n".join(_fb_line(r) for r in picked))
    _feedback_fixed_cache = block
    return block


def _feedback_similar_block(title: str) -> str:
    """기사 제목과 키워드가 2개 이상 겹치는 담당자 사례 최대 5건(#175). 기사마다 달라지므로 캐시 접두 **뒤**에 둔다.
    고정 블록에 이미 실린 사례는 뺀다(같은 줄 중복 방지). 없으면 ''."""
    rows = _load_feedback_rows()
    tt = _fb_tokens(title)
    if not rows or not tt:
        return ''
    fixed = _feedback_fixed_block()
    scored = [(len(tt & _fb_tokens(r['title'])), r) for r in rows]
    similar = [r for sc, r in sorted(scored, key=lambda x: -x[0]) if sc >= 2]
    lines = [_fb_line(r) for r in similar if _fb_line(r) not in fixed][:5]
    if not lines:
        return ''
    return "\n\n[이 기사와 유사한 담당자 피드백 사례 — 반드시 우선 적용]\n" + "\n".join(lines)


def get_feedback_examples(title: str = '') -> str:
    """피드백 블록 전체 = 고정 블록 + 기사별 유사 사례. 선별 콜은 title=''로 고정 블록만 쓴다.
    (#175 전에는 유사 사례를 앞에, 균형 사례를 뒤에 한 문자열로 붙였다 — 기사마다 문자열이 달라 캐시가 불가능했다.)"""
    return _feedback_fixed_block() + _feedback_similar_block(title)


def classify_urgency(title: str, content: str = '', summary: str = '') -> str:
    """
    Claude Haiku로 기사 긴급도 AI 판단.
    API 키 없거나 오류 시 키워드 기반 폴백.
    summary = 네이버 검색 요약(≤300자). 본문이 없을 때만 판정 재료로 쓴다(#188).
    반환값: '긴급' | '보통' | '참고'
    """
    if not ANTHROPIC_API_KEY:
        # API 키 없을 때 간단 폴백
        text = title + ' ' + ((content or '')[:300] or (summary or ''))
        return '보통' if any(k in text for k in _FALLBACK_MOBILE) else '참고'

    snippet = re.sub(r'\s+', ' ', content or '').strip()[:600]
    summ = re.sub(r'\s+', ' ', summary or '').strip()[:300]
    if snippet:
        user_msg = f"제목: {title}\n본문: {snippet}"
    elif summ:
        user_msg = f"제목: {title}\n요약: {summ}"
    else:
        user_msg = f"제목: {title}"

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        # 프롬프트 캐시(#175, 2026-09-20): system을 두 블록으로 나눈다 — [기준문 + 고정 피드백 블록](캐시 1h) 뒤에
        # [이 기사와 유사한 사례](기사마다 다름, 캐시 밖). 종전에는 한 문자열이라 기사마다 달라 캐시가 안 걸렸다
        # (콜당 입력 ≈4,700토큰을 매번 정가로 지불, 월 ≈$34). 캐시 접두 실측은 배경역사 #175 — Haiku 4.5 최소 4,096.
        # 검증: api_usage(site=crawler.py:classify_urgency)의 cache_read>0. 0이면 접두가 4,096 미만이거나 매번 달라지는 것.
        sys_blocks = [{'type': 'text', 'text': _URGENCY_SYSTEM + _feedback_fixed_block(),
                       'cache_control': {'type': 'ephemeral', 'ttl': '1h'}}]
        similar = _feedback_similar_block(title)
        if similar:
            sys_blocks.append({'type': 'text', 'text': similar})
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=10,
            system=sys_blocks,
            messages=[{'role': 'user', 'content': user_msg}],
        )
        answer = resp.content[0].text.strip()
        # 응답에서 키워드 추출 (앞뒤 공백·줄바꿈 제거)
        for key in _AI_PRIORITY_MAP:
            if key in answer:
                return _AI_PRIORITY_MAP[key]
        return '참고'
    except Exception as e:
        print(f'  [AI 분류 오류] {title[:30]}... → 폴백 사용: {e}')
        text = title + ' ' + (content or '')[:300]
        return '보통' if any(k in text for k in _FALLBACK_MOBILE) else '참고'


# ═══════════════════════════════════════════════════════
#  유틸 함수
# ═══════════════════════════════════════════════════════

def _fetch_all_rows(table: str, columns: str, order: str = 'id') -> list:
    """PostgREST는 무제한 select도 최대 1,000행만 돌려준다 — 반드시 페이지네이션.
    (2026-08-03 사고: news_feed가 1,086건이 되자 최신 86건이 잘려 '기존' 판정에서
    빠졌고, 이미 알림한 긴급 기사를 신규로 착각해 재발송. 총량이 상한을 넘는 첫날
    조용히 터지는 유형이라 전량 조회는 이 헬퍼만 쓸 것.)
    order는 표의 유일 열(기본 id, news_screen_cache는 url) — 정렬이 없거나 겹치면 요청마다
    행 순서가 달라져 페이지 경계에서 행이 빠지거나 겹친다(#233). 본체는 news_known(#234)."""
    return news_known.fetch_all_rows(sb, table, columns, order)


def get_existing_urls(items: list) -> tuple:
    """이번 후보(items) 중 이미 저장된 URL·제목 (Google RSS 중복 방지)
    + 사용자가 대시보드에서 삭제한 기사(deleted_news)도 포함해 재수집 방지.
    후보만 DB 함수로 대조한다(#234 — 종전엔 세 표 전량 47요청). 실패하면 전량 조회로 되돌아가고,
    news_feed 전량 조회까지 실패하면 예외를 올린다(빈 명단으로 진행하면 전부 '새 기사'가 된다)."""
    return news_known.known_or_full(sb, items, include_deleted=True, label='기존')


def detect_category(title: str) -> str:
    if any(k in title for k in ['주파수', '할당', '경매', '분배', '재배치']): return '주파수'
    if any(k in title for k in ['전자파', 'SAR', 'EMC', '인체보호']): return '전자파'
    if any(k in title for k in ['적합성평가', '기자재', '시험기관', '인증']): return '기술기준'
    if any(k in title for k in ['ITU', 'WRC', 'IMT', '6G', '5G', 'AI']): return 'ITU·WRC'
    if any(k in title for k in ['기술기준', '무선설비', '무선국', '단말']): return '기술기준'
    if any(k in title for k in ['전기통신사업', '통신사업', '망중립', '번호이동']): return '전기통신사업'
    if any(k in title for k in ['정보통신망', '정보보호', '사이버', '개인정보']): return '정보통신망'
    return '기타'


def parse_date(date_str: str) -> str:
    """다양한 날짜 형식 → ISO 8601 변환. 파싱 실패 시 빈 문자열 반환."""
    if not date_str:
        return ''
    s = date_str.strip()
    now = datetime.now(KST)

    # 1) ISO 8601 / RFC 3339 (meta 태그에서 추출한 날짜)
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?', s)
    if m:
        y, mo, d, h, mi, sec = m.group(1,2,3,4,5,6)
        sec = sec or '00'
        try:
            dt = datetime(int(y), int(mo), int(d), int(h), int(mi), int(sec), tzinfo=KST)
            return dt.isoformat()
        except Exception:
            pass

    # 2) YYYY.MM.DD HH:MM:SS  /  YYYY.MM.DD HH:MM  /  YYYY.MM.DD
    m = re.match(r'(\d{4})[./\-](\d{1,2})[./\-](\d{1,2})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?', s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        h  = int(m.group(4)) if m.group(4) else 0
        mi = int(m.group(5)) if m.group(5) else 0
        sec = int(m.group(6)) if m.group(6) else 0
        try:
            dt = datetime(y, mo, d, h, mi, sec, tzinfo=KST)
            return dt.isoformat()
        except Exception:
            pass

    # 3) 한국어 형식: 2024년 05월 28일 14:30
    m = re.match(r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일(?:\s*(\d{1,2}):(\d{2})(?::(\d{2}))?)?', s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        h  = int(m.group(4)) if m.group(4) else 0
        mi = int(m.group(5)) if m.group(5) else 0
        sec = int(m.group(6)) if m.group(6) else 0
        try:
            dt = datetime(y, mo, d, h, mi, sec, tzinfo=KST)
            return dt.isoformat()
        except Exception:
            pass

    # 4) 상대 날짜: N분 전, N시간 전, N일 전
    m = re.search(r'(\d+)\s*(분|시간|일)\s*전', s)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit == '분':
            dt = now - timedelta(minutes=n)
        elif unit == '시간':
            dt = now - timedelta(hours=n)
        else:
            dt = now - timedelta(days=n)
        return dt.isoformat()

    # 5) 어제
    if '어제' in s:
        dt = now - timedelta(days=1)
        return dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

    # 6) MM.DD 형식 (연도 없음) → 현재 연도로 보정
    m = re.match(r'^(\d{1,2})[./](\d{1,2})$', s)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        try:
            dt = datetime(now.year, mo, d, tzinfo=KST)
            # 미래 날짜라면 전년도로
            if dt > now:
                dt = dt.replace(year=now.year - 1)
            return dt.isoformat()
        except Exception:
            pass

    return ''  # 파싱 실패 — 호출자가 fallback 처리


# ═══════════════════════════════════════════════════════
#  크롤러 — 네이버 뉴스 검색 (1순위)
# ═══════════════════════════════════════════════════════

_NAVER_PRESS_DOMAINS = {
    'yna.co.kr': '연합뉴스', 'newsis.com': '뉴시스', 'etnews.com': '전자신문',
    'dt.co.kr': '디지털타임스', 'ddaily.co.kr': '디지털데일리', 'zdnet.co.kr': 'ZDNet Korea',
    'inews24.com': '아이뉴스24', 'bloter.net': '블로터', 'mk.co.kr': '매일경제',
    'mt.co.kr': '머니투데이', 'hankyung.com': '한국경제', 'sedaily.com': '서울경제',
    'chosun.com': '조선일보', 'joongang.co.kr': '중앙일보', 'donga.com': '동아일보',
    'hani.co.kr': '한겨레', 'khan.co.kr': '경향신문',
}


def _strip_html_tags(s: str) -> str:
    import html as _html
    s = re.sub(r'<[^>]+>', '', s or '')
    return _html.unescape(s).strip()


def _naver_pubdate_to_iso(pubdate: str) -> str:
    """네이버 API pubDate(RFC 2822, '... +0900') → KST ISO 8601."""
    if not pubdate:
        return ''
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(pubdate).astimezone(KST).isoformat()
    except Exception:
        return ''


def _domain_source(url: str) -> str:
    """원문 URL 도메인 → 언론사명(매핑) 또는 도메인 본체."""
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or '').lower()
        if host.startswith('www.'):
            host = host[4:]
        for dom, name in _NAVER_PRESS_DOMAINS.items():
            if host == dom or host.endswith('.' + dom):
                return name
        parts = host.split('.')
        # 한국형 2단계 TLD(co.kr·go.kr·or.kr 등)는 본체가 parts[-3]
        if len(parts) >= 3 and parts[-1] == 'kr' and parts[-2] in ('co', 'go', 'or', 'ne', 're', 'pe'):
            return parts[-3]
        return parts[-2] if len(parts) >= 2 else (host or '네이버뉴스')
    except Exception:
        return '네이버뉴스'


def crawl_naver_news() -> tuple:
    """네이버 뉴스 검색 OpenAPI로 키워드별 기사 수집.
    구 HTML 스크래핑(ul.list_news li.bx / a.news_tit)은 네이버 검색 구조 변경/해외 IP 차단으로
    0건 회귀해 폐지 → 공식 OpenAPI(JSON, IP·HTML 변경에 안전)로 전환.
    NAVER_CLIENT_ID/SECRET 미설정·오류 시 빈 결과 반환 → 호출부가 Google RSS로 폴백.
    반환: (items: list, fail_count: int)
    """
    if not (NAVER_CLIENT_ID and NAVER_CLIENT_SECRET):
        print('[네이버 뉴스] NAVER_CLIENT_ID/SECRET 미설정 — 건너뜀 (Google RSS 폴백)')
        return [], 0

    items = []
    seen_urls: set = set()
    seen_titles: set = set()
    fail_count = 0
    api_headers = {
        'X-Naver-Client-Id': NAVER_CLIENT_ID,
        'X-Naver-Client-Secret': NAVER_CLIENT_SECRET,
    }

    for kw in NEWS_SEARCH_KEYWORDS:
        try:
            res = requests.get(
                'https://openapi.naver.com/v1/search/news.json',
                headers=api_headers,
                params={'query': kw, 'display': 30, 'sort': 'date'},
                timeout=10,
            )
            res.raise_for_status()
            articles = (res.json() or {}).get('items', [])

            for art in articles:
                title = _strip_html_tags(art.get('title', ''))
                if not title or len(title) < 8:
                    continue
                is_personnel = is_ministry_personnel_news(title)
                # 제목 RADIO_KEYWORDS 포함 여부로 걸러내던 게이트는 폐지(2026-08-03).
                # 넓게 담고 관련성은 screen_news_items()의 Haiku 1차 선별이 판정한다.
                # EXCLUDE_KEYWORDS도 여기서는 걸지 않는다(#235) — 제목 부분 일치라 '후보'·'감독'·'구속'·'영화'(민영화)가
                # 방미통위 상임위원 후보 추천 같은 관련 기사를 AI 판정 전에 버렸다. 키워드 폴백(_keyword_relevant)에서만 쓴다.
                if title in seen_titles:
                    continue
                seen_titles.add(title)

                # n.news.naver.com(link) 우선 — 본문 수집률↑, 없으면 원문
                naver_link = art.get('link', '') or ''
                origin = art.get('originallink', '') or ''
                href = naver_link if 'naver.com' in naver_link else (origin or naver_link)
                if not href or href in seen_urls:
                    continue
                # 스포츠·연예 오인 차단 — 도메인까지 봐야 하므로 URL 확정 후에 판정 (배경역사 #45)
                if not is_personnel and is_sports_noise(title, href):
                    continue
                seen_urls.add(href)

                items.append({
                    'title':        title,
                    'source':       _domain_source(origin or naver_link),
                    'category':     detect_category(title),
                    'url':          href,
                    'is_read':      False,
                    'published_at': _naver_pubdate_to_iso(art.get('pubDate', '')),
                    'content':      None,
                    # 선별 전용 임시 필드 — 네이버 API description(요약)을 판정 재료로만 쓴다.
                    # content에 넣지 않는 이유: refetch_content.py가 'content 100자 미만'을
                    # 본문 재수집 대상으로 삼는데 요약이 들어가면 재수집이 막힌다.
                    # screen_news_items()가 판정 직후 이 키를 제거하므로 DB로는 흘러가지 않는다.
                    '_screen_text': _strip_html_tags(art.get('description', ''))[:300],
                })
        except Exception as e:
            print(f'[네이버 뉴스 오류] {kw}: {str(e)[:80]}')
            fail_count += 1
        time.sleep(0.3)

    print(f'[네이버 뉴스] {len(items)}건 수집 (실패 키워드 {fail_count}개)')
    return items, fail_count


# ═══════════════════════════════════════════════════════
#  크롤러 — Google News RSS (네이버 차단 시 폴백)
# ═══════════════════════════════════════════════════════

def crawl_google_news_rss() -> list:
    """Google News RSS로 키워드 기반 뉴스 수집.
    - GitHub Actions(미국 IP)에서도 차단 없음
    - 발행일 100% 포함 (RFC 2822 → KST 자동 변환)
    - 제목 기반 중복 제거 (save_new_items에서 URL·제목 이중 체크)
    """
    try:
        import feedparser
        import calendar as _cal
    except ImportError:
        print('[Google RSS] feedparser 미설치 — pip install feedparser')
        return []

    items = []
    seen_titles: set = set()

    for kw in NEWS_SEARCH_KEYWORDS:
        rss_url = (
            'https://news.google.com/rss/search'
            f'?q={requests.utils.quote(kw)}&hl=ko&gl=KR&ceid=KR:ko'
        )
        try:
            feed = feedparser.parse(rss_url)
            for entry in (feed.entries or []):
                # 제목에서 "기사 제목 - 언론사명" 분리
                raw_title = (entry.get('title') or '').strip()
                if ' - ' in raw_title:
                    title  = raw_title.rsplit(' - ', 1)[0].strip()
                    source = raw_title.rsplit(' - ', 1)[1].strip()
                else:
                    title  = raw_title
                    source = (entry.get('source') or {}).get('title', '알수없음')

                if not title or len(title) < 8:
                    continue
                is_personnel = is_ministry_personnel_news(title)
                # 네이버 경로와 동일 — RADIO_KEYWORDS 포함 게이트 폐지(2026-08-03), EXCLUDE도 키워드 폴백에서만(#235)
                if title in seen_titles:
                    continue
                seen_titles.add(title)

                link = entry.get('link', '')
                if not link:
                    continue

                # Google News 리다이렉트 URL → 실제 기사 URL로 변환
                if 'news.google.com' in link:
                    decoded = False
                    try:
                        from googlenewsdecoder import new_decoderv1
                        result = new_decoderv1(link)
                        if result.get('status') is True and result.get('decoded_url'):
                            link = result['decoded_url']
                            decoded = True
                    except Exception:
                        pass
                    if not decoded:
                        try:
                            r = requests.get(link, headers=HEADERS, timeout=8, allow_redirects=True)
                            if r.url and 'news.google.com' not in r.url:
                                link = r.url
                        except Exception:
                            pass  # 실패 시 원본 URL 유지

                # 스포츠·연예 오인 차단 — 리다이렉트 해제 후의 실제 URL로 판정 (배경역사 #45)
                if not is_personnel and is_sports_noise(title, link):
                    continue

                # 발행일: published_parsed(UTC struct_time) → KST ISO
                pub_struct = entry.get('published_parsed')
                if pub_struct:
                    from datetime import datetime as _dt
                    pub_utc = _dt.fromtimestamp(_cal.timegm(pub_struct), tz=timezone.utc)
                    date_str = pub_utc.astimezone(KST).isoformat()
                else:
                    date_str = ''

                # RSS 요약(summary)을 content로 저장 → 대시보드 즉시 표시
                import re as _re
                raw_summary = entry.get('summary', '') or ''
                # HTML 태그 제거
                clean_summary = _re.sub(r'<[^>]+>', '', raw_summary).strip()
                # 출처 표기 제거 (예: " - 전자신문" 등)
                if ' - ' in clean_summary:
                    clean_summary = clean_summary.rsplit(' - ', 1)[0].strip()
                content_text = clean_summary[:500] if clean_summary else None

                items.append({
                    'title':        title,
                    'source':       source,
                    'category':     detect_category(title),
                    'url':          link,
                    'is_read':      False,
                    'published_at': date_str,
                    'content':      content_text,
                    '_screen_text': (content_text or '')[:300],   # 선별 재료 (판정 후 제거)
                })
        except Exception as e:
            print(f'[Google RSS 오류] {kw}: {e}')
        time.sleep(0.3)

    print(f'[Google RSS] {len(items)}건 수집')
    return items


# ═══════════════════════════════════════════════════════
#  관련성 키워드·부처 인사 판별
#  (정부 공고 수집 함수는 gov_notice_crawler.py에 있다 — 여기 있던 사본은 #213에서 삭제)
# ═══════════════════════════════════════════════════════

RADIO_KEYWORDS = [
    # 전파법 계열
    '전파', '주파수', 'ITU', 'IMT', '5G', '6G', '전자파',
    '무선', '적합성평가', '기자재', 'WRC', '스펙트럼',
    # 전기통신사업법 계열
    '전기통신사업', '통신사업', '망중립', '번호이동', '이용자보호',
    '단말장치', '통신서비스', '과징금',
    # 정보통신망법 계열
    '정보통신망', '정보보호', '사이버', '불법정보', '개인정보',
    # NEWS_SEARCH_KEYWORDS 통합 (와이파이·이동통신·기지국 등)
    '전파정책', '이동통신', '6GHz', '와이파이', '공공와이파이',
    '공공 와이파이', '지하철 와이파이', '기지국', 'LTE', '3G',
    '이동통신 품질', '5G 기지국', 'LTE 기지국', '기지국 장애', '이동통신 장비',
    '무선국', '5G주파수', '6G주파수',
]

# 비관련 기사 제외 키워드 — 스포츠·연예·부동산 등.
# ⚠️ AI 선별(screen_news_items) 앞에서는 쓰지 않는다 — AI가 죽었을 때의 키워드 폴백(_keyword_relevant)에서만(#235).
#    제목 부분 일치라 '후보'(방미통위 위원 후보 추천·후보 주파수)·'감독'(관리감독)·'구속'·'영화'(민영화)·'주식'(주식회사)이
#    관련 기사를 AI가 보기도 전에 버렸다(2026-09-26 실측: 네이버 1,216건 중 79건 차단, 그중 관련 가능 3~4건).
#    스포츠 오인은 AI 앞에서 is_sports_noise()가 계속 막는다. 이 목록에 낱말을 더 쌓지 말 것(#45).
EXCLUDE_KEYWORDS = [
    # 스포츠
    '안타', '홈런', '타율', '경기장', '야구', '축구', '농구', '골프', '테니스',
    'MLB', 'NBA', 'KBO', 'EPL', '올림픽', '월드컵', '선수', '감독', '코치',
    '우익수', '좌익수', '투수', '포수', '타자', '세리머니', '연속경기',
    # 모터스포츠 (WRC 랠리 오인 방지)
    '랠리', '레이싱', '모터스포츠', '자동차경주', 'F1', '포뮬러', 'FIA',
    'WRC 7', 'WRC 6', 'WRC 5', 'WRC 4', 'WRC 3', 'WRC 2', 'WRC 1',
    'WRC 재팬', 'WRC 저팬', 'WRC 핀란드', 'WRC 포르투갈', '타이어',
    # 야구·구기 스포츠 (3G 오인 방지)
    '득점', '이닝', '타석', '삼진', '볼넷', '스윕', '선발 라인업',
    '나성범', '김하성', '이정후', '플레이오프', '시리즈전', '연속 침묵',
    '무실점', '연속 무실점', '선발 등판', '완투', '병살', '도루', '번트',
    '1승', '2승', '3승', '연승', '연패', '경기 결과', '프로야구', '프로축구',
    '원정팀', '홈팀', '원정 승리', '연속 원정',
    '파이어볼러', '자책점', '평균자책점', '지명타자', '선발투수', '마무리투수',
    '1차 지명', '2차 지명', '신인 드래프트', '트레이드', '외야수', '내야수',
    'km/h 직구', '구속', '방어율',
    '리드오프', '햄스트링', '1라운더', '2라운더', '연속 선발', '연속 등판',
    '강백호', '이승엽', '류현진', '오재원', '박세웅',  # KBO 선수명
    '경기 후반 준비', '선발에서 사라', '불펜',
    # 선거 (LTE·3G 오인 방지)
    '선거', '선관위', '투표소', '투표용지', '지방선거', '국회의원', '대통령', '후보', '당선',
    '개표', '사전투표', '선거구', '선거운동', '출마', '지방선거일',
    # 연예·방송
    '아이돌', '드라마', '영화', '콘서트', '팬미팅', '데뷔', '컴백',
    # 부동산·금융
    '아파트', '분양', '재건축', '청약', '주식', '코스피', '나스닥',
    # 기타
    '레시피', '맛집', '여행', '날씨',
]

# ───────────────────────────────────────────────────────
#  스포츠·방송코너 오인 차단 — 단어 목록이 아니라 '패턴'으로 (배경역사 #45)
#
#  EXCLUDE_KEYWORDS에 야구 용어를 40개 넘게 쌓아 왔지만, 정작 새 나가는 제목들에는
#  그 단어가 하나도 없었다 — '3G 연속포', '3G 8타점', '3G 무패', '3G 연속골'.
#  스포츠 기사가 3G를 쓰는 방식은 정해져 있는데(3G+기록어) 목록은 선수 이름만 쫓아
#  다녔던 것. 새 선수·새 표현이 나올 때마다 뚫린다. 그래서 조합을 본다.
#
#  실측 검증(2026-08-01): DB의 3G/LTE 기사 14건에 걸어 스포츠 2건만 걸리고
#  통신 기사 12건은 전원 통과 — 특히 진행 중인 '3G 종료' 이슈 7건 모두 통과.
#   \d* 는 '3G 2골'처럼 숫자가 끼는 표기 대응(테스트로 발견). '2G/3G 종료'는
#   숫자 뒤가 'G'라 기록어에 걸리지 않아 안전하다.
_SPORTS_NUM_RE = re.compile(
    r'\b[36]G\b\s*\d*\s*(연속|무패|무실점|타점|타수|안타|홈런|골|승|패|세이브|QS|경기|보살)')
# 지역 MBC 등이 실시간 리포트 코너명으로 [LTE]를 쓴다.
# '[LTE/리포트]' 같은 변형이 있어 대괄호 안 뒷부분을 열어 둔다(테스트로 발견).
_LTE_CORNER_RE = re.compile(r'\[\s*LTE\b[^\]]*\]|^LTE\)')
# 도메인이 가장 확실하다 — 삭제 이력 25건 중 12건이 이 두 곳이었다
_SPORTS_DOMAINS = ('sports.naver.com', 'entertain.naver.com')


def is_sports_noise(title: str, url: str = '') -> bool:
    """스포츠·연예 오인 기사인가. 제목 패턴 + 출처 도메인 조합으로 판정.
    '3G 종료', 'LTE 20배', 'LTE-R'처럼 통신 맥락은 걸리지 않는다(실측 확인)."""
    t = title or ''
    if _SPORTS_NUM_RE.search(t):
        return True
    if _LTE_CORNER_RE.search(t):
        return True
    u = (url or '').lower()
    if any(d in u for d in _SPORTS_DOMAINS):
        return True
    return False


# ───────────────────────────────────────────────────────
# 과기정통부·방통위 등 소관 부처 인사이동 뉴스 — 항상 포함
# (RADIO_KEYWORDS 미포함이어도 수집, EXCLUDE_KEYWORDS보다 우선)
# ───────────────────────────────────────────────────────
MINISTRY_NAMES = [
    '과기정통부', '과학기술정보통신부', '과기부',
    '방통위', '방송통신위원회', '방미통위', '방송미디어통신위원회',   # 2026 개편 — 옛·새 이름 모두 (#154)
    '국립전파연구원', '중앙전파관리소',
]
PERSONNEL_WORDS = [
    '인사', '임명', '취임', '내정', '발탁', '승진', '경질', '교체',
    '인사이동', '인사발령', '이동', '전보', '보직', '차관', '장관', '실장', '국장',
]

def is_ministry_personnel_news(title: str) -> bool:
    """소관 부처 인사 관련 기사 여부 (부처명 + 인사 용어 동시 포함)"""
    return (any(m in title for m in MINISTRY_NAMES)
            and any(p in title for p in PERSONNEL_WORDS))


# ═══════════════════════════════════════════════════════
#  뉴스 검색어 (네이버 검색 API·Google RSS 공용)
# ═══════════════════════════════════════════════════════

# ───────────────────────────────────────────────────────
#  뉴스 검색어 — "넓게 수집 → Haiku 선별" 구조로 확대 (2026-08-03)
#  기존 27개는 좁은 검색어라 '통신요금 인하', 'AI 기본법' 등 소관 이슈인데도
#  제목에 전파 계열 단어가 없으면 아예 검색되지 않았다. 보도자료 쪽에서 이미 쓰는
#  app_config.press_keywords(33개) 중 '뉴스 검색어로서 유효한 것'만 골라 병합한다.
#  - 단독으로 쓰면 소음만 늘어나는 일반어(AI·요금·무선·사이버·단말·스펙트럼·기자재)는
#    복합어로 좁혀 넣거나 제외했다. 예: AI → 'AI 기본법'·'AI 규제', 요금 → '통신요금'
#  - 'WRC' 단독은 모터스포츠 랠리 오탐이라 기존 'WRC-27'만 유지.
#  - '전파' 단독은 '감염 전파' 등 동사 용법이 많아 '전파법'·'전파사용료'로 대체.
#  넓힌 만큼 관련성 판정은 제목 키워드가 아니라 screen_news_items()의 Haiku가 맡는다.
# ───────────────────────────────────────────────────────
NEWS_SEARCH_KEYWORDS = [
    # ── 기존 27개 (유지) ──
    '전파정책', '주파수', '5G주파수', '5G 주파수', '6G주파수', '6G 주파수',
    '전자파', '무선국', '이동통신', 'WRC-27', '6GHz',
    '공공와이파이', '공공 와이파이', '지하철 와이파이',
    '기지국', 'LTE', '3G', '이동통신 품질', '5G 기지국', 'LTE 기지국',
    '기지국 장애', '이동통신 장비',
    '과기정통부 인사', '과학기술정보통신부 인사', '과기정통부 승진',
    '과기정통부 인사이동', '방통위 인사', '방미통위 인사',
    # ── 확대분 (press_keywords 병합) ──
    '5G', '6G', '주파수 할당', '전파법', '전파사용료',
    '무선설비', '적합성평가', '방송통신기자재', 'ITU',
    '전기통신사업법', '정보통신망법', '위치정보법', '통신정책',
    '통신요금', '통신품질', '통신장애', '알뜰폰', '번호이동',
    '단말기유통', '이용자보호', '스팸문자', '재난문자',
    '위성통신', '사이버보안', 'AI 기본법', 'AI 규제',
    '과기정통부',
]


# ═══════════════════════════════════════════════════════
#  기사 본문 수집
# ═══════════════════════════════════════════════════════

class _WeakDHAdapter(HTTPAdapter):
    """DH_KEY_TOO_SMALL 오류 우회용 SSL 어댑터 (SECLEVEL=1)"""
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers('DEFAULT:@SECLEVEL=1')
        kwargs['ssl_context'] = ctx
        super().init_poolmanager(*args, **kwargs)

_KNOWN_WEAK_DH = ('rra.go.kr',)

def _http_get(url: str, timeout: int = 8):
    """일반 GET → DH_KEY_TOO_SMALL SSL 약점 사이트면 SECLEVEL=1 어댑터로 자동 재시도."""
    # 알려진 약 DH 사이트는 처음부터 어댑터 사용 (불필요한 1차 실패 회피)
    if any(d in url for d in _KNOWN_WEAK_DH):
        s = requests.Session()
        s.mount('https://', _WeakDHAdapter())
        return s.get(url, headers=HEADERS, timeout=timeout)
    try:
        return requests.get(url, headers=HEADERS, timeout=timeout)
    except requests.exceptions.SSLError as e:
        if 'dh key too small' in str(e).lower() or 'DH_KEY_TOO_SMALL' in str(e):
            s = requests.Session()
            s.mount('https://', _WeakDHAdapter())
            return s.get(url, headers=HEADERS, timeout=timeout)
        raise

# 본문 칸 대신 '본문이 아닌 상자'가 걸린 텍스트 — 그 상자의 머리말로 '시작'하는지만 본다(#232, 사내판 인계 2026-09-26).
#  · 사이드바 목록: ebn·보안뉴스(기사관리 시스템의 첫 <article>이 '많이 본 기사' 상자·상단 '최신뉴스' 목록)와
#    korea.kr('실시간 인기뉴스' 상자)은 147건 전부 목록을 본문으로 저장했고, 66건이 다른 기사 제목들로 긴급도 판정을 받았다.
#  · 공공누리 저작권 안내: korea.kr 카드뉴스·'사실은 이렇습니다'는 글 본문이 없어 trafilatura가 이 안내문을 집는다.
# 앞머리 N자 안의 메뉴 단어를 세는 방식은 쓰지 않는다 — 본문 앞에 메뉴가 붙는 템플릿(전자신문 계열, 비즈니스포스트
# '…JOB+ 최신뉴스 검색…')의 정상 기사를 통째로 버린다(#161-보론14와 같은 교훈).
_NON_BODY_RE = re.compile(
    r'^\s*(?:많이\s*본\s*(?:기사|뉴스)|실시간\s*인기\s*(?:기사|뉴스)|최신\s*뉴스'
    r'|(?:저작권법\s*제37조\s*및\s*)?-\s*제37조\s*\(출처의\s*명시\))')


def _is_non_body(text: str) -> bool:
    return bool(_NON_BODY_RE.match(text or ''))


def fetch_article_body(url: str, source: str) -> tuple:
    """기사 URL에서 본문 텍스트와 발행일 추출. 반환: (body: str, published_at: str)"""
    try:
        resp = _http_get(url, timeout=8)
        resp.raise_for_status()
        # RRA(국립전파연구원) 사이트는 EUC-KR 인코딩
        if 'rra.go.kr' in url:
            resp.encoding = 'euc-kr'
        soup = BeautifulSoup(resp.text, 'html.parser')

        # ── 발행일 추출 (meta 태그 우선) ───────────────────
        pub_date = ''

        # 1순위: Open Graph / schema.org meta 태그
        for attr_name, attr_val in [
            ('property', 'article:published_time'),
            ('property', 'og:article:published_time'),
            ('itemprop', 'datePublished'),
            ('name', 'article:published_time'),
            ('name', 'publishdate'),
            ('name', 'date'),
        ]:
            tag = soup.find('meta', attrs={attr_name: attr_val})
            if tag and tag.get('content'):
                parsed = parse_date(tag['content'])
                if parsed:
                    pub_date = parsed
                    break

        # 2순위: <time datetime="..."> 태그
        if not pub_date:
            for time_tag in soup.find_all('time', datetime=True):
                parsed = parse_date(time_tag['datetime'])
                if parsed:
                    pub_date = parsed
                    break

        # ── RRA 등 정부 게시판: 본문이 table 구조 → trafilatura 우선 ──
        #    (일반 'article' 셀렉터가 페이지 전체 네비게이션을 잡는 문제 회피)
        if 'rra.go.kr' in url:
            try:
                import trafilatura
                _ex = trafilatura.extract(resp.text, include_comments=False, include_tables=True)
                if _ex and len(_ex.strip()) > 50:
                    return _ex.strip()[:1500], pub_date
            except Exception:
                pass

        # ── 본문 추출 ───────────────────────────────────────
        # 네이버 뉴스 URL 감지 → 전용 셀렉터 우선 적용
        naver_selectors = []
        if 'naver.com' in url:
            naver_selectors = [
                'div#dic_area',
                'div.newsct_article',
                'div#articleBodyContents',
                'div._article_body_contents',
                'div.article_body',
            ]

        selectors_map = {
            '국립전파연구원': ['div.bbs_view_cont', 'td.cont', 'div.memo', 'div.bbs_cont',
                              'div.board_view_txt', 'div.view_area', 'table.bbs_view td:last-child',
                              'div.board_view', 'div.view_content', 'td.view_cont'],
            '전자신문':    ['div.article_body', 'div#articleBody', 'div.news_view', 'div#articleView'],
            '연합뉴스':    ['div.article-txt', 'article.story-news', 'div#articleWrap'],
            '디지털타임스': ['div#article_txt', 'div.article_content', 'div#articleBody'],
            'ZDNet Korea': ['div#article_body', 'div.article_view', 'div#articleContent',
                            'div.article_content', 'div.view_txt', 'div#article-view-content-div'],
            '아이뉴스24':  ['div#news_body_area', 'div.article_txt', 'div#articleBody'],
            '매일경제':    ['div#article_body', 'div.art_txt', 'div#newsDetailBody',
                            'div.article_wrap', 'div#article-body'],
            '머니투데이':  ['div#textBody', 'div.news_text', 'div#content_text'],
            '디지털데일리': ['div#articleBody', 'div.article_txt'],
            '지디넷코리아': ['div#article_content', 'div.article_view'],
            '블로터':      ['div.article_content'],
            '한국경제':    ['div#articalbody', 'div.article-body', 'div#articleBody',
                            'div.article_body', 'div#newsView', 'div.news-contents'],
            '파이낸셜뉴스': ['div#article_content', 'div.article_view', 'div#articleBody'],
            '뉴스1':       ['div.article-body', 'div#articleBody', 'div.news_body_area'],
            '정보통신신문': ['div#article_body', 'div.article-content', 'div.view_cont'],
            'Telecom Reseller': ['div.entry-content', 'article', 'div.post-content'],
        }
        # 소스 라벨이 '국립전파연구원 공지사항'처럼 접미사를 가질 수 있어 부분 매칭
        src_selectors = selectors_map.get(source, [])
        if not src_selectors and source:
            for _key, _sels in selectors_map.items():
                if _key in source:
                    src_selectors = _sels
                    break
        # 사이드바 상자가 본문 칸보다 먼저 걸리는 사이트 — 주소로 본문 칸을 먼저 본다(#232).
        # ebn·보안뉴스는 첫 <article>이 '많이 본 기사' 상자·상단 '최신뉴스' 목록, korea.kr은 div.article이 '실시간 인기뉴스'.
        # 기사관리 시스템 본문 칸(#article-view-content-div)을 아래 공용 후보에 넣지 않는다 — 넣으면 첫 <article>이
        # 짧아 div.article-body(부제+본문)를 잡던 사이트까지 결과가 바뀐다(표본 30곳 중 8곳, 부제 줄이 빠짐). 결과 불변 원칙.
        if 'korea.kr' in url:
            site_selectors = ['div.view_cont', 'div.article_body']
        elif 'ebn.co.kr' in url or 'boannews.com' in url:
            site_selectors = ['#article-view-content-div']
        else:
            site_selectors = []
        candidates = naver_selectors + site_selectors + src_selectors + [
            'article', 'div.article', 'div.news-content',
            'div.view_cont', 'div.view-content', 'div#content',
            'div.article-body', 'div.news_body', 'div.article_txt'
        ]
        # 정부 사이트 nav 텍스트 판별 (주메뉴 등으로 시작하면 nav 영역)
        NAV_STARTS = ('주메뉴', '메뉴건너뛰기', 'Skip Navigation', '본문 바로가기')
        def _is_nav(text: str) -> bool:
            return any(text.startswith(s) for s in NAV_STARTS)

        body = ''
        for sel in candidates:
            tag = soup.select_one(sel)
            if tag:
                text = tag.get_text(separator=' ', strip=True)
                # 목록 상자로 시작하는 칸은 본문이 아니다 — 다음 후보를 본다(#232)
                if len(text) > 100 and not _is_nav(text) and not _is_non_body(text):
                    body = text[:1500]
                    break

        # 셀렉터 미매칭 시 trafilatura 폴백
        if not body:
            try:
                import trafilatura
                extracted = trafilatura.extract(resp.text, include_comments=False, include_tables=False)
                if extracted and len(extracted.strip()) > 100 and not _is_nav(extracted.strip()) \
                        and not _is_non_body(extracted.strip()):
                    body = extracted.strip()[:1500]
            except Exception:
                pass

        return body, pub_date
    except Exception as e:
        print(f'  [본문 수집 실패] {url}: {e}')
        return '', ''


# ═══════════════════════════════════════════════════════
#  관련성 1차 선별 — Claude Haiku (2026-08-03)
#
#  검색어를 넓히면서 제목 키워드 게이트를 없앴으므로, 무관 기사가 그대로 들어와
#  본문 수집(건당 1초 대기 + HTTP)과 긴급도 분류(건당 Haiku 1콜)를 낭비하게 된다.
#  그래서 신규 기사만 모아 제목+요약으로 배치 판정하고, 통과분만 뒤 단계로 보낸다.
#  보도자료(press_ingest)·국회 입법예고(assembly_crawler)가 쓰는 것과 같은 패턴이다.
#
#  fail-open 원칙: 키 없음·판정 실패 시 기존 키워드 필터(RADIO_KEYWORDS 포함·EXCLUDE_KEYWORDS 미포함, #235)로 되돌아간다
#  (선별이 죽었다고 수집 자체가 멈추면 무음 누락이 된다 — 배경역사 #39).
# ═══════════════════════════════════════════════════════

ISSUE_SUGGEST_HOURS = {5, 11, 15, 20}   # 이슈맵 자동 제안 실행 시각(KST, #153) — 매시 → 하루 4회
# 같은 시간대 재실행 가드(#194). 1 이상(한 시간대 6번 크롤 중 첫 회만) ~ '가장 짧은 시각 간격 − 1' 이하여야
# 한다 — 5로 두었더니 11→15시(4시간)에 걸려 15시가 09-24부터 매일 빠졌다(#194-보론). 시각을 바꾸면 이것도 볼 것.
ISSUE_SUGGEST_GUARD_HOURS = 3
SCREEN_BATCH_SIZE = 35          # 1콜당 판정 기사 수 (제목+요약 300자 기준 ≈ 3~4K 입력토큰)
SCREEN_MODEL = 'claude-haiku-4-5-20251001'

# 판정 기준문 폴백 — 원본은 app_config.news_relevance_criteria
NEWS_RELEVANCE_CRITERIA_FALLBACK = (
    '다음 뉴스 기사가 SK텔레콤 Comm센터 기술정책팀(전파·통신 정책 모니터링) 업무와 '
    '관련 있는지 판정한다.\n'
    '관련 있음: 이동통신(5G·6G·주파수·기지국·단말·로밍·위성통신·통신장비), '
    '전파(전자파·무선국·무선설비·적합성평가·전파사용료·전파간섭), '
    '통신사업 정책·규제(전기통신사업법·통신요금·이용자보호·알뜰폰·스팸·번호이동·단말기유통), '
    '통신품질·통신장애·통신재난·재난문자, 네트워크 인프라(데이터센터·클라우드 포함), '
    '통신망 사이버보안·개인정보·위치정보, ITU·WRC 등 국제 전파·표준 동향, '
    '유료방송·OTT·망 사용료 정책, AI 정책(AI 기본법·규제·국가전략·AI 데이터센터·AI 반도체), '
    '과기정통부·방송미디어통신위원회·국립전파연구원·중앙전파관리소 등 소관 부처의 '
    '통신·전파 정책 발표와 인사.\n'
    '관련 없음: 스포츠·연예·부동산·주식 등 타 분야, 통신과 무관한 기업 실적·마케팅·제휴 홍보, '
    '단말기 신제품 리뷰·개통 이벤트 등 소비자 판촉, 과학관 전시·공모전·행사 홍보, 채용 공고, '
    '신약·바이오, 우주발사체·천문, 통신과 무관한 순수 과학 R&D 성과 홍보.\n'
    '애매하면 관련으로 판정한다(놓침보다 과잉 포함이 낫다).'
)

# 분야 태그 6종 — ASCII slug(토큰 절약). 한글 라벨 매핑은 Edge 쪽이 담당하며
# 원본은 supabase/functions/_shared/news_tags.ts 다. 여기는 사본이므로 같이 고칠 것.
# 태그 목록을 app_config로 빼지 않는 이유: Haiku 프롬프트·Edge 칩·웹훅 버튼 3곳이
# 동시에 바뀌어야 유효한데, 한 곳만 DB로 튜닝 가능하게 하면 드리프트만 생긴다.
NEWS_TAGS = ('spectrum', 'market', 'regulation', 'security', 'ai')
MAX_TAGS_PER_ITEM = 3           # 경계 기사도 3개면 충분 — 그 이상은 사실상 미판정
MAX_EVENT_LEN = 40              # 사건 라벨 상한 — 지시는 12~25자, 넘치면 잘라 DB·그룹핑을 지킨다

NEWS_SCREEN_TOOL = {
    'name': 'record_relevant_news',
    'description': '기사 목록 중 기준문에 따라 관련으로 판정된 기사의 id와 분야 태그, 사건 라벨을 기록한다.',
    'input_schema': {
        'type': 'object',
        'properties': {
            'relevant': {
                'type': 'array',
                'description': '관련 기사 목록. 관련이 하나도 없으면 빈 배열.',
                'items': {
                    'type': 'object',
                    'properties': {
                        'id': {'type': 'integer', 'description': '관련 기사의 id.'},
                        'tags': {
                            'type': 'array',
                            'description': '분야 태그 0~3개. 확실하지 않으면 빈 배열.',
                            'items': {'type': 'string', 'enum': list(NEWS_TAGS)},
                        },
                        'event': {
                            'type': 'string',
                            'description': '기사가 다루는 사건 한 줄(12~25자). 뚜렷하지 않으면 빈 문자열.',
                        },
                    },
                    # tags·event는 일부러 required에서 뺀다 — 모델이 빼먹어도 관련성 판정은 살아야 한다.
                    # urgency 필드는 #174에서 제거 — 등급은 save_new_items → classify_urgency 개별 판정이 전건 정한다.
                    'required': ['id'],
                },
            },
        },
        'required': ['relevant'],
    },
}


def load_news_criteria() -> str:
    """app_config.news_relevance_criteria 판정 기준문 조회. 없거나 실패면 코드 폴백."""
    try:
        rows = sb.table('app_config').select('value') \
            .eq('key', 'news_relevance_criteria').limit(1).execute().data
        if rows and (rows[0].get('value') or '').strip():
            return rows[0]['value'].strip()
    except Exception as e:
        print(f'[선별] 판정기준 조회 실패 — 코드 폴백 사용: {str(e)[:80]}')
    return NEWS_RELEVANCE_CRITERIA_FALLBACK


_URGENCY_RULES = None        # 공통 규칙 — 실행당 1회 로드(모듈 전역 캐시)
_TEAM_URGENCY_RULES = None   # 팀 규칙 {team_id: [규칙…]}(#250) — 같은 한 번의 조회에서 나눈다
# 켜진 팀 규칙 {id: 행}(형식 검사 전, #251). 표 조회 실패면 None. 문장 판정 대기 처리가 '규칙 꺼짐(→ stale)'과
# '조회 실패·그 팀 형식 오류로 이번 실행만 빠짐(→ 손대지 않음)'을 가르는 데만 쓴다 — 둘을 섞으면 일시 장애 한 번에
# 대기 행이 전부 stale로 굳는다(#183: 실패를 '없음'으로 삼키지 않는다).
_TEAM_RULES_ENABLED = None
# 규칙을 읽기 시작한 시각(UTC, #251). 이 뒤에 생긴 판정 요청은 이 실행의 규칙 사본보다 새 규칙(판 올림·다시 켬·낱말 수정)
# 때문에 들어왔을 수 있다 — 대기 처리가 그런 행을 stale로 만들지 않고 다음 실행으로 넘긴다.
_RULES_LOADED_AT = None


def _load_all_urgency_rules() -> None:
    """표 urgency_rules의 켜진 행 전부를 **한 번** 읽어 공통(team_id null)·팀으로 나눈다(실행당 1회).
    공통: 실패·형식 오류·0건이면 비상 사본(#216) — 로그 '[규칙] N개 로드(db|fallback)'는 운영 점검이 읽으므로 그대로 둔다.
    팀: _split_team_rules 참조. 조회 실패면 팀 규칙 없이 돈다(팀은 공통값) — 그 사실을 따로 적는다(#183)."""
    global _URGENCY_RULES, _TEAM_URGENCY_RULES, _TEAM_RULES_ENABLED, _RULES_LOADED_AT
    if _URGENCY_RULES is not None:
        return
    rules, src, rows = None, 'db', None
    _RULES_LOADED_AT = datetime.now(timezone.utc)      # 조회 **전** 시각 — 그 뒤 요청은 사본에 없는 변경일 수 있다
    try:
        rows = sb.table('urgency_rules').select('*').eq('enabled', True) \
            .order('position').order('id').execute().data or []
        common = [r for r in rows if r.get('team_id') is None]
        errs = urgency_rules.validate_rules(common)
        if errs:
            print(f'[규칙] 표 형식 오류 {len(errs)}건 — 비상 사본 사용: {errs[:3]}')
        elif common:
            rules = common
        else:
            print('[규칙] 표에 켜진 공통 규칙 0건 — 비상 사본 사용')
    except Exception as e:
        rows = None
        print(f'[규칙] 표 조회 실패 — 비상 사본 사용: {str(e)[:80]}')
    if rules is None:
        rules, src = urgency_rules.URGENCY_RULES_FALLBACK, 'fallback'
    print(f'[규칙] {len(rules)}개 로드({src})')
    _URGENCY_RULES = rules
    _TEAM_URGENCY_RULES = _split_team_rules(rows)
    try:
        _TEAM_RULES_ENABLED = None if rows is None else \
            {r['id']: r for r in rows if r.get('team_id') is not None and r.get('id')}
    except Exception:
        _TEAM_RULES_ENABLED = None


def _split_team_rules(rows) -> dict:
    """켜진 행 중 팀 규칙 → {team_id: [규칙…]}(조회 순서 = position, id 유지). 팀마다 따로 형식 검사 —
    한 팀의 형식 오류는 그 팀만 이번 실행에서 건너뛴다(그 팀은 공통값). 비상 사본은 없다(팀 규칙은 표가 정본).
    rows=None(표 조회 실패)은 '팀 규칙 없음'과 다른 상황이라 따로 적는다(#183: 실패를 '없음'으로 삼키지 않는다)."""
    if rows is None:
        print('[규칙] 팀 규칙 건너뜀 — 표 조회 실패, 이번 실행은 모든 팀이 공통값(팀 행 저장 없음)')
        return {}
    try:
        by_team = {}
        for r in rows:
            if r.get('team_id') is not None:
                by_team.setdefault(int(r['team_id']), []).append(r)
        team, bad = {}, []
        for tid in sorted(by_team):
            errs = urgency_rules.validate_rules(by_team[tid])
            if errs:
                bad.append(tid)
                print(f'[규칙] 팀 {tid} 규칙 형식 오류 {len(errs)}건 — 이번 실행은 그 팀 규칙 건너뜀(그 팀은 공통값): {errs[:3]}')
            else:
                team[tid] = by_team[tid]
    except Exception as e:
        print(f'[규칙] 팀 규칙 정리 실패 — 이번 실행은 모든 팀이 공통값(팀 행 저장 없음): {str(e)[:80]}')
        return {}
    if team or bad:
        line = f'[규칙] 팀 규칙 {sum(len(v) for v in team.values())}개({len(team)}팀)'
        print(line + (f' · 형식 오류로 건너뜀 {len(bad)}팀' if bad else ''))
    else:
        print('[규칙] 팀 규칙 없음')
    return team


def load_urgency_rules() -> list:
    """공통 규칙(team_id null, enabled)을 position 순으로. 실패·형식 오류·0건이면 비상 사본(#216).
    공통값(news_feed.urgency)은 공통 규칙으로만 정한다 — 팀 규칙은 팀 층(표 team_urgency)에만 쓴다(#250)."""
    _load_all_urgency_rules()
    return _URGENCY_RULES


def load_team_urgency_rules() -> dict:
    """팀 규칙 {team_id: [켜진 규칙, position·id 순]}(#250). 없거나 조회 실패면 {} — 구분은 로드 로그에 남는다."""
    _load_all_urgency_rules()
    return _TEAM_URGENCY_RULES or {}


def _screen_text_of(item: dict) -> str:
    """판정 재료 — 수집 시 담아 둔 요약(_screen_text), 없으면 content 앞부분."""
    txt = (item.get('_screen_text') or item.get('content') or '')
    return re.sub(r'\s+', ' ', txt).strip()[:300]


# ── 무관 판정 캐시 (2026-08-03, 비용 절감 ①) ──────────────────────────────────
#  무관 판정된 기사는 저장되지 않아 다음 실행의 '기존 URL' 대조에서 빠지고, 네이버 검색에
#  같은 기사가 ~15일 남아 매시간 재판정됐다(실측: 시간당 판정 ~470건 중 신규는 ~70건 =
#  선별 비용의 85%가 재판정). URL+제목 지문을 news_screen_cache에 남겨 건너뛴다.
#  · 제목 지문 — 언론사가 제목을 고치면([속보]→[종합], 오타 수정) 재판정한다.
#    지문에 요약문은 넣지 않는다: 네이버 요약은 검색어 주변 발췌라 검색어마다 달라진다.
#  · 기준문 지문 — 기준문이 바뀌면 캐시가 자동 무효(옛 기준의 판정이 새 기준을 가리면 안 됨).
#  · AI가 실제로 판정한 무관만 캐시한다. 키워드 폴백의 탈락분은 캐시하지 않는다 —
#    폴백은 'AI가 죽었을 때의 임시 판정'이라 AI가 살아나면 다시 판정받아야 한다.
#  · 모든 단계 fail-open: 캐시가 죽으면 전량 판정으로 돌아간다(돈만 더 쓰고 기사는 안 놓침).
SCREEN_CACHE_TTL_DAYS = 20     # 네이버 노출 기간(~15일) + 여유. 지나면 재등장 자체가 없다.


def _screen_hash(s: str) -> str:
    """공백 정규화 후 sha256 앞 16자 — 제목·기준문 지문 공용."""
    import hashlib
    norm = re.sub(r'\s+', ' ', (s or '')).strip()
    return hashlib.sha256(norm.encode('utf-8')).hexdigest()[:16]


def _load_screen_cache(criteria_hash: str, urls: list) -> dict:
    """{url: title_hash} — 후보 urls 중 현재 기준문으로 판정된 행만(#234 DB 함수 대조, 실패 시 전량 조회).
    그것도 실패하면 빈 dict(전량 판정으로 진행)."""
    return news_known.screen_cache(sb, urls, criteria_hash)


def _save_screen_cache(rows: list) -> None:
    """무관 판정분 기록 + TTL 청소. 실패해도 선별 결과에는 영향 없음(fail-open)."""
    if rows:
        try:
            sb.table('news_screen_cache').upsert(rows, on_conflict='url').execute()
        except Exception as e:
            print(f'[선별 캐시] 기록 실패(무시): {str(e)[:80]}')
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=SCREEN_CACHE_TTL_DAYS)).isoformat()
        sb.table('news_screen_cache').delete().lt('judged_at', cutoff).execute()
    except Exception as e:
        print(f'[선별 캐시] 청소 실패(무시): {str(e)[:80]}')


def _keyword_relevant(item: dict) -> bool:
    """폴백 판정(AI가 죽었을 때) — 제목에 RADIO_KEYWORDS가 있고 EXCLUDE_KEYWORDS가 없으면 통과.
    #235 전에는 EXCLUDE가 수집 단계에서 먼저 걸렸으므로 폴백 결과는 종전과 같다
    (부처 인사 뉴스는 이 함수 전에 screen_news_items가 자동 통과시킨다)."""
    title = item.get('title') or ''
    return (any(k in title for k in RADIO_KEYWORDS)
            and not any(k in title for k in EXCLUDE_KEYWORDS))


_screen_system_cache = {}


def _screen_system(criteria: str) -> str:
    """선별 콜 system = 관련성 기준문 + 담당자 피드백 블록 + 판정 규칙(_SCREEN_RULES). (#174: 긴급도 기준 제거)

    피드백은 제목별 유사사례 없이 배치 공통으로 만든다 — 선별은 한 콜에 여러 기사를 판정하므로
    특정 제목에 맞출 수 없다.
    실행당 1회만 조립한다 — get_feedback_examples는 메모리 연산이지만 _get_distilled_rules가
    DB·API를 탈 수 있다. **같은 실행 안에서 바이트 단위로 동일해야 한다** — 프롬프트 캐시는 접두 일치라
    한 글자만 달라도 배치마다 새로 쓴다(1시간 캐시 쓰기 = 2배 요금). 시각·난수·정렬 안 된 목록을 넣지 말 것."""
    if criteria not in _screen_system_cache:
        _screen_system_cache[criteria] = criteria + get_feedback_examples('') + _SCREEN_RULES
    return _screen_system_cache[criteria]


def _screen_batch_haiku(client, criteria: str, batch: list):
    """배치 1개(≤SCREEN_BATCH_SIZE건)를 Haiku 1콜로 판정.
    반환: {관련 id(1-based): {'tags': list, 'event': str, 'urgency': str}}. 실패 시 None.
    None은 '판정 실패' 신호이고 호출부의 키워드 폴백이 여기 물려 있다 — 의미를 바꾸지 말 것.
    (반환값이 dict로 넓어져도 이 None 규약은 그대로다. 값이 빈 dict인 것과 None은 다르다 —
     빈 dict는 '관련이지만 태그·사건 미판정', None은 '이 배치 판정 실패'.)
    태그는 NEWS_TAGS 화이트리스트 교집합·최대 MAX_TAGS_PER_ITEM개로 자른다
    (모델이 없는 slug를 지어내도 DB·Edge로 새어 나가지 않게).
    사건 라벨(event)은 대시보드 뉴스 그룹핑용이다 — 같은 사건을 다룬 기사끼리 표현이 수렴하도록
    쓰게 하고, 공백 정규화·MAX_EVENT_LEN 절단만 적용한다. 판정에는 관여하지 않는다.
    결정성: tool_choice로 도구 호출 강제 + 기준문 문자 적용·건별 독립 판정 지시.
    (temperature류 파라미터 사용 금지 — 지침 do-not)"""
    payload = []
    for idx, it in enumerate(batch, 1):
        row = {'id': idx, 'title': (it.get('title') or '').strip()}
        summary = _screen_text_of(it)
        if summary:
            row['summary'] = summary
        payload.append(row)
    # 판정 규칙은 system(_SCREEN_RULES)으로 옮겼다(#174) — 사용자 메시지는 배치마다 다른 기사 JSON뿐.
    prompt = (
        '아래는 방금 수집한 뉴스 기사 목록이다. 시스템 지시의 기준문과 판정 규칙을 적용해 판정하라.\n\n'
        + json.dumps(payload, ensure_ascii=False)
    )
    try:
        resp = client.messages.create(
            model=SCREEN_MODEL,
            # 5000: 35건 전건 태그 시 출력 ≈1,000토큰이었고, 여기에 사건 라벨(event)이 붙어
            # 건당 한글 25자 ≈ 35토큰 + 키/따옴표 ≈ 5토큰 → 35건이면 +1,400토큰. 합계 ≈2,400.
            # 3000이면 여유가 1.25배뿐이라 라벨이 길어진 배치에서 잘릴 수 있어 5000으로 올렸다.
            # 초과하면 tool_use가 미완성으로 잘려 None(판정 실패) → 배치 전체 키워드 폴백,
            # 즉 조용한 리콜 손실이 된다. 입력이 아니라 출력 한도라 비용 영향도 없다.
            max_tokens=5000,
            # 프롬프트 캐시(W7, #174): system 전체(기준문+피드백+규칙 ≈ 수천 토큰)를 1시간 캐시에 싣는다.
            # 캐시 접두는 tools → system → messages 순이라 NEWS_SCREEN_TOOL도 함께 캐시된다.
            # 같은 실행의 2번째 배치부터, 그리고 다음 실행(30분 뒤)까지 0.1배 요금으로 읽힌다.
            # 검증: api_usage.cache_read가 0이 아니어야 한다 — 0이면 system이 매번 달라지고 있는 것.
            # Haiku 4.5의 최소 캐시 길이는 **4,096토큰**(지침 #152 정정) — tools+system 접두가 그보다 짧으면 에러 없이
            # 조용히 캐시되지 않는다. ⚠️ count_tokens는 도구 스키마를 캐시 회계보다 크게 센다(1,100 vs 776) — 첫 배포는
            # count_tokens 4,245로 보였지만 실제 회계 3,921이라 03:52 첫 실행에서 cache_write=0이었다(#175-보론).
            # 등급당 피드백 사례 4→12(FEEDBACK_PER_CLASS)로 system을 ≈4,250(캐시 회계 ≈5,030)으로 키워 해결.
            # 기준문·피드백이 줄면 다시 미달할 수 있으니 배포 뒤 api_usage.cache_write/cache_read로 반드시 확인할 것.
            system=[{'type': 'text', 'text': _screen_system(criteria),
                     'cache_control': {'type': 'ephemeral', 'ttl': '1h'}}],
            tools=[NEWS_SCREEN_TOOL],
            tool_choice={'type': 'tool', 'name': 'record_relevant_news'},
            messages=[{'role': 'user', 'content': prompt}],
        )
        for blk in resp.content:      # 적응형 추론 대비 — tool_use 블록만 취함
            if getattr(blk, 'type', '') == 'tool_use':
                rows = (blk.input or {}).get('relevant') or []
                out = {}
                for row in rows:
                    # 모델이 {id, tags, event} 대신 정수만 뱉어도 관련성 판정은 살린다
                    # (태그·사건 라벨만 비움).
                    if isinstance(row, dict):
                        raw_id = row.get('id')
                        raw_tags, raw_event = row.get('tags'), row.get('event')
                        raw_urgency = row.get('urgency')
                    else:
                        raw_id, raw_tags, raw_event, raw_urgency = row, None, None, None
                    try:
                        rid = int(raw_id)
                    except (TypeError, ValueError):
                        continue
                    tags = []
                    for t in (raw_tags or []):
                        if t in NEWS_TAGS and t not in tags:
                            tags.append(t)
                        if len(tags) >= MAX_TAGS_PER_ITEM:
                            break
                    event = ''
                    if isinstance(raw_event, str):
                        event = re.sub(r'\s+', ' ', raw_event).strip()[:MAX_EVENT_LEN]
                    # 등급 어휘(즉시대응 등) → DB 값(긴급/보통/참고). 모르는 값은 빈 문자열 =
                    # 미판정으로 두고 save_new_items가 개별 판정한다(임의 등급을 만들지 않는다).
                    urgency = _AI_PRIORITY_MAP.get((raw_urgency or '').strip(), '') \
                        if isinstance(raw_urgency, str) else ''
                    out[rid] = {'tags': tags, 'event': event, 'urgency': urgency}
                return out
        return None                   # 도구 호출 없음 → 실패 취급(호출부가 키워드 폴백)
    except Exception as e:
        print(f'  [선별 판정 오류] {str(e)[:120]}')
        return None


# 주파수 안전망 — 이 네 단어가 제목·요약에 있으면 spectrum을 '추가'한다.
# 태그 판정은 여전히 Haiku가 하고, 이건 바닥(안전망)이지 대체가 아니다:
#   · 추가만 한다. Haiku가 붙인 태그는 절대 지우지 않는다.
#   · 네 단어로만 좁힌다. 늘리면 결국 키워드 대응표가 되고, 그러면 "기지국 개설허가"와
#     "기지국 투자 축소"가 같은 태그를 받는 문제로 되돌아간다(그걸 피하려고 LLM 판정을 쓴다).
# 도입 근거(2026-08-03 실측): 「과기정통부, 이동통신 무선국 검사 간소화한다」가 3회 연속 태그 0개로
# 나왔다. 요약에 무선국·기지국·안테나·전파법이 다 있는데도 AI가 '행정절차 개정'으로 읽어
# "확실하지 않으면 비워 둬라" 지시에 따라 비운 것. 같은 사안의 다른 기사들은 정상 판정돼서
# 프롬프트 문제라기보다 경계 사례로 보이나, 전파법은 이 팀의 핵심 법이라 놓치면 손해가 크다.
_SPECTRUM_ANCHORS = ('전파법', '무선국', '주파수 할당', '주파수 재할당', '전자파')


def _spectrum_safety_net(item: dict) -> None:
    """앵커 단어가 있는데 spectrum이 빠졌으면 추가한다(추가 전용). 발동 시 로그를 남긴다 —
    로그가 잦아지면 안전망이 아니라 프롬프트를 고쳐야 한다는 신호다."""
    tags = item.get('tags')
    if not isinstance(tags, list) or 'spectrum' in tags:
        return
    text = f"{item.get('title', '')} {item.get('_screen_text', '')}"
    hit = next((a for a in _SPECTRUM_ANCHORS if a in text), None)
    if hit:
        tags.append('spectrum')
        print(f"  [태그 보정] '{hit}' → spectrum 추가: {str(item.get('title'))[:44]}")


def screen_news_items(items: list) -> list:
    """수집분에서 SKT 관련 기사만 남긴다. 반환 목록은 입력 순서를 유지한다.

    - 소관 부처 인사 뉴스(is_ministry_personnel_news)는 판정 없이 무조건 통과 (지침 do-not).
    - ANTHROPIC_API_KEY 없음/클라이언트 생성 실패 → 전량 키워드 폴백.
    - 배치 단위 실패 → 그 배치만 키워드 폴백 (다른 배치 판정은 유지).
    - 판정에만 쓰는 '_screen_text' 키는 여기서 전부 제거한다 (DB 컬럼이 아님).
    - 분야 태그(news_feed.tags)와 사건 라벨(news_feed.event)을 같이 매긴다. 판정을 못 받은
      경로(인사 자동통과·키워드 폴백·모델이 생략)는 각각 []·''이며, 그 보장은 함수 끝의
      setdefault 두 줄 한 곳에 건다.
    """
    if not items:
        return []

    keep = [False] * len(items)
    personnel = 0
    cand_idx = []
    for n, it in enumerate(items):
        if is_ministry_personnel_news(it.get('title', '')):
            keep[n] = True            # 부처 인사 뉴스 — 항상 수집
            personnel += 1
        else:
            cand_idx.append(n)

    client = None
    criteria = ''
    if cand_idx and ANTHROPIC_API_KEY:
        try:
            criteria = load_news_criteria()
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        except Exception as e:
            print(f'[선별] Haiku 초기화 실패: {str(e)[:80]}')
            client = None
    if cand_idx and client is None:
        print(f'[선별] AI 판정 불가 — RADIO_KEYWORDS 키워드 폴백 ({len(cand_idx)}건)')

    # 캐시 대조 — 같은 URL·같은 제목·같은 기준문으로 이미 무관 판정된 기사는 판정에서 뺀다.
    # client 없는 폴백 모드에서는 캐시를 쓰지 않는다(기준문을 못 읽었고, 키워드 판정은 공짜).
    cache_skip = 0
    criteria_hash = ''
    screen_cache = {}
    if cand_idx and client:
        criteria_hash = _screen_hash(criteria)
        screen_cache = _load_screen_cache(
            criteria_hash, [(items[n].get('url') or '').strip() for n in cand_idx])
        if screen_cache:
            remain = []
            for n in cand_idx:
                url = (items[n].get('url') or '').strip()
                if url and screen_cache.get(url) == _screen_hash(items[n].get('title') or ''):
                    cache_skip += 1       # keep[n]은 False 그대로 = 이전 판정 유지
                else:
                    remain.append(n)
            cand_idx = remain

    judged = len(cand_idx)
    rejected_rows = []                    # 이번에 AI가 무관 판정한 기사 → 캐시에 기록
    n_batches = (len(cand_idx) + SCREEN_BATCH_SIZE - 1) // SCREEN_BATCH_SIZE
    for i in range(0, len(cand_idx), SCREEN_BATCH_SIZE):
        chunk = cand_idx[i:i + SCREEN_BATCH_SIZE]
        batch = [items[n] for n in chunk]
        verdict = _screen_batch_haiku(client, criteria, batch) if client else None
        if verdict is None:
            if client:
                print(f'  [선별 배치 {i // SCREEN_BATCH_SIZE + 1}/{n_batches} 실패] '
                      f'키워드 폴백({len(batch)}건)')
            for n, it in zip(chunk, batch):
                keep[n] = _keyword_relevant(it)
        else:
            for pos, n in enumerate(chunk, 1):
                got = verdict.get(pos)      # None = 이 배치에서 무관 판정
                if got is not None:
                    keep[n] = True
                    items[n]['tags'] = got.get('tags') or []
                    items[n]['event'] = got.get('event') or ''
                    if got.get('urgency'):        # 미판정은 키를 만들지 않는다 — 개별 판정 폴백 대상
                        items[n]['urgency'] = got['urgency']
                    # ── 그림자 기록 (2026-09-13, #162 → 2026-09-20 #174 종료) ──────────
                    # 선별 콜이 등급을 내던 동안 news_feed.urgency_screen에 남겼다(1,534건, 일치 56% → 게이트 기각).
                    # #174부터 선별 콜은 등급을 내지 않으므로 이 값은 항상 ''이다. 컬럼·키는 남긴다 —
                    # 통과분 전건에 키가 있어야 PostgREST 벌크 upsert가 산다(#82 계열, 아래 setdefault와 한 쌍).
                    items[n]['urgency_screen'] = got.get('urgency') or ''
                else:
                    url = (items[n].get('url') or '').strip()
                    if url:
                        # ★ 모든 행의 키 집합 동일 ★ (PostgREST 벌크 upsert 요건)
                        rejected_rows.append({
                            'url': url,
                            'title_hash': _screen_hash(items[n].get('title') or ''),
                            'criteria_hash': criteria_hash,
                        })

    if client:
        _save_screen_cache(rejected_rows)

    passed  = [it for n, it in enumerate(items) if keep[n]]
    dropped = [it for n, it in enumerate(items) if not keep[n]]
    print(f'[선별] 수집 {len(items)}건 → 캐시 건너뜀 {cache_skip}건 → 판정 {judged}건 '
          f'→ 관련 {len(passed)}건 (제외 {len(dropped)}건, 인사 자동통과 {personnel}건)')
    # #235: 제외 낱말(EXCLUDE_KEYWORDS)은 이제 AI 앞에서 걸지 않는다 — 그런 제목이 AI를 통과한 건수를 남겨
    # 스포츠·선거 기사가 새어 들어오는지 로그로 보이게 한다(지침 '틀렸을 때 무엇이 보이는가').
    ex_passed = [it for it in passed if not is_ministry_personnel_news(it.get('title') or '')
                 and any(k in (it.get('title') or '') for k in EXCLUDE_KEYWORDS)]
    if ex_passed:
        print(f'[선별] 제외 낱말 포함 통과 {len(ex_passed)}건: '
              + ' | '.join((it.get('title') or '')[:40] for it in ex_passed[:3]))

    # 캐시가 데워졌는데(300행+) 판정이 150건을 넘으면 캐시가 조용히 깨진 것 — 청구서가 아니라
    # 당일에 알기 위한 경보. 첫 실행(캐시 비어 있음)은 전량 판정이 정상이라 울리지 않는다.
    if len(screen_cache) >= 300 and judged > 150:
        try:
            notify.send_telegram(
                f'⚠️ [선별 캐시] 판정 {judged}건 — 정상(~70건)의 2배 이상입니다. '
                f'캐시 적중이 깨졌을 수 있습니다(기준문 변경 직후라면 정상). '
                f'수집 {len(items)}건, 캐시 건너뜀 {cache_skip}건.',
                chat_id=TELEGRAM_CHAT_ID)
        except Exception:
            pass
    for it in dropped[:5]:            # 기준문 조정용 표본 — 제외 사유 감시
        print(f'  [제외] {(it.get("title") or "")[:50]}')

    # 임시 키 제거(_screen_text는 DB 컬럼이 아니다) + tags·event 기본값 보장.
    # ★ tags·event setdefault는 반드시 이 한 지점에만 둘 것 ★
    #   PostgREST 벌크 upsert는 리스트 안 모든 객체의 키 집합이 같아야 한다. save_new_items가
    #   valid 리스트를 통째로 넘기므로, 태그·사건 라벨 없는 경로(키워드 폴백 / 부처 인사 자동통과 /
    #   모델이 tags·event 생략) 중 하나라도 키가 빠지면 upsert 전체가 터져 뉴스 수집이 전면 중단된다.
    #   통과 기사는 전부 이 루프를 지나므로 여기가 유일한 방어선이다.
    #   '기타' 태그를 만들지 말 것 — 구독자가 그것을 끌 수 있게 되어 판정 실패 기사가 조용히 사라진다.
    for it in passed:                     # 통과분만 — 탈락 기사에 안전망을 돌리면 보정 로그가 무관 기사로 오염된다
        it.setdefault('tags', [])         # 반드시 안전망보다 먼저 — 태그가 없는 기사가 바로 보정 대상이다
        it.setdefault('event', '')        # 사건 라벨 미판정은 빈 문자열(대시보드는 이때 제목 유사도로 되돌아간다)
        it.setdefault('urgency_screen', '')   # 그림자 기록(#162) — 인사 자동통과·키워드 폴백 경로는 여기서 채운다
        _spectrum_safety_net(it)          # 판정 누락 보정 — 아래 함수 주석 참조
    for it in passed:                     # 긴급도 판정 재료로 요약을 남긴다 — 키가 아니라 별도 dict(upsert 키 집합 불변)
        _st = (it.get('_screen_text') or '').strip()
        if _st and it.get('url'):
            _URGENCY_SUMMARY[it['url']] = _st
    for it in items:
        it.pop('_screen_text', None)      # 제거는 전체 대상 — 반환 규약(판정 전용 키는 여기서 전부 제거) 유지
    return passed


# 긴급도 판정용 네이버 요약(url → ≤300자, Google RSS 폴백이면 RSS 요약). 본문 수집이 실패한 기사(#200 이전에는
# Actions 전건)에서 이것이 없으면 긴급도는 **제목 한 줄**만 보고 매겨진다(2026-09-24 확인, #188).
# #250(결정 1(가))부터 별도 칸 news_feed.screen_text에 저장한다(grade_urgency가 모든 행에 키를 채움) — 대시보드의
# 팀 규칙 재적용이 수집 때와 같은 글을 보게 하려는 것. **content에는 여전히 넣지 않는다** — refetch_content.py의
# '100자 미만 = 재수집 대상' 조건이 깨진다(#188).
_URGENCY_SUMMARY: dict = {}

# 팀 규칙 적중(url → [{'team_id', 'urgency', 'rule_id'}], #250). grade_urgency가 채우고 save_new_items가 새로 저장된
# 기사만 team_urgency에 쓴다. **item 키로 넣지 말 것** — 기사 dict는 news_feed 벌크 upsert로 그대로 가서 없는 칸이
# 되거나 키 집합이 어긋난다(#82·#222).
_TEAM_RULE_HITS: dict = {}

# 문장 조건 판정 후보(url → [{'team_id', 'rule_ids', 'common', 'text'}], #251). grade_urgency가 낱말이 걸린 팀 문장 규칙을
# 모으고 queue_new_sentence_candidates가 판정 대기 행으로 만든다. _TEAM_RULE_HITS와 같은 이유로 item 키로 넣지 않는다(#82·#222).
_SENTENCE_CANDS: dict = {}

# 이번 실행에 **실제로 새로 저장된** 기사(url → news_id, #252) — save_new_items가 upsert 응답(ON CONFLICT DO NOTHING +
# representation = 새 행만)으로 채운다. 받는 단위별 알림(run_audience_alerts 'collect')의 후보는 여기 있는 기사만 —
# 응답에 없는 url은 동시 실행이 먼저 넣은 기사라 그 실행이 맡는다(#154 'upsert 반환값으로만 판단').
_INSERTED_IDS: dict = {}


# ═══════════════════════════════════════════════════════
#  Supabase 저장
# ═══════════════════════════════════════════════════════

def grade_urgency(valid: list, rules: list, classify=None, team_rules=None) -> dict:
    """⑤ 긴급도 — 공통 낱말 규칙(#216) + Haiku 판정을 합쳐 item['urgency'/'importance'/'urgency_rule']을 채운다.
    규칙은 AI보다 먼저 맞춰 본다(제목 + 네이버 요약만, 본문 금지). set 적중 = 그 값, AI 콜 생략 /
    min 적중 = AI를 돌린 뒤 하한만(max) / 적중 id는 값이 안 바뀌어도 urgency_rule에 남긴다(출처 표시·사내 정본).
    알림·큐·브리핑은 저장값(공통값)을 쓰므로 따로 고칠 곳이 없다.
    팀 층(#250): team_rules({team_id: 규칙들})가 있으면 기사마다 팀별로 team_rule_decision(기준 = 위에서 정한 **공통
    최종값**)을 돌려 적중을 _TEAM_RULE_HITS에 모은다 — item['urgency']는 바꾸지 않고, AI 콜도 늘지 않는다.
    문장 조건(#251): 판정 전이라 문장 규칙은 '안 걸림'으로 보고(team_rule_decision_judged, 판정 {}) 뒤 규칙이 정한다.
    낱말이 걸린 문장 규칙은 _SENTENCE_CANDS에만 모은다 — queue_new_sentence_candidates가 판정 대기 행으로 만들고, 판정과
    팀 행 고침은 같은 실행의 process_open_sentence_verdicts가 긴급 알림 **뒤에** 한다(여기서는 AI 0회 — 문장 규칙이 없으면
    종전과 바이트 단위로 같다).
    item['screen_text'] = 판정에 쓴 네이버 요약(없으면 None)을 **모든 행에** 채운다(#82·#222). 반환 = 로그용 집계."""
    classify = classify or classify_urgency
    team_rules = team_rules or {}
    hits, changed_n, skipped_ai = {}, 0, 0
    team_hits, team_err = {}, 0
    for item in valid:
        url = item.get('url', '')
        summary = _URGENCY_SUMMARY.get(url, '')
        hit = urgency_rules.match_urgency_rules(rules, item.get('title', ''), summary)
        if hit and hit['mode'] == 'set':
            val = hit['level']                              # 공통 AI 생략
            skipped_ai += 1
        else:
            val = classify(item.get('title', ''), item.get('content', '') or '', summary)
            if hit:                                         # min — AI 값에 하한
                val, _, changed = urgency_rules.combine(hit, val)
                changed_n += int(changed)
        if hit:
            hits[hit['id']] = hits.get(hit['id'], 0) + 1
        item['urgency'] = val
        item['importance'] = val
        item['urgency_rule'] = hit['id'] if hit else None   # 모든 행에 키(벌크 upsert 키 집합 동일, #82)
        # 수집 때 본 검색 요약 — 모든 행에 키(없으면 None: postgrest 벌크 upsert는 빠진 칸을 NULL로 채운다, #222)
        item['screen_text'] = summary or None
        # ── 팀 층(#250) — 공통값은 위에서 끝났다. 여기서는 팀별 적중만 옆 dict에 모은다(item 키 금지) ──
        _TEAM_RULE_HITS.pop(url, None)
        _SENTENCE_CANDS.pop(url, None)
        if team_rules:
            try:
                # 입력 글 = 대시보드 재적용과 같은 rule_input_text(screen_text, …) — 새 기사는 두 경로가 같은 글을 본다
                text = urgency_rules.rule_input_text(item['screen_text'], '')
                got, cands = [], []
                for tid, trules in team_rules.items():
                    # 문장 규칙(#251)은 아직 판정이 없다({}) = '안 걸림' → 뒤 규칙이 정한다. 문장 규칙이 없으면
                    # team_rule_decision과 같다(공용 함수 계약 — 케이스 파일 urgency_team_cases.json).
                    dec = urgency_rules.team_rule_decision_judged(trules, item.get('title', ''), text, val, {})
                    if dec:
                        got.append({'team_id': tid, 'urgency': dec['level'], 'rule_id': dec['rule_id']})
                    rids = urgency_rules.sentence_candidates(trules, item.get('title', ''), text, {})
                    if rids:
                        cands.append({'team_id': tid, 'rule_ids': rids, 'common': val, 'text': text})
                if got and url:
                    _TEAM_RULE_HITS[url] = got
                    for g in got:
                        team_hits[g['team_id']] = team_hits.get(g['team_id'], 0) + 1
                if cands and url:
                    _SENTENCE_CANDS[url] = cands
            except Exception as e:                          # fail-open — 팀 층 오류가 공통 판정·수집을 막으면 안 된다
                team_err += 1
                if team_err == 1:
                    print(f'[팀 규칙] 판정 오류(그 기사는 모든 팀이 공통값): {str(e)[:80]}')
    if hits:
        print(f'[규칙] 적중 {sum(hits.values())}건 (' + ', '.join(f'{k}×{v}' for k, v in hits.items()) +
              f', 값 변경 {changed_n}건, AI 생략 {skipped_ai}건)')
    else:
        print('[규칙] 적중 0건')
    if team_rules:
        print(f'[팀 규칙] 적중 {sum(team_hits.values())}건({len(team_hits)}팀)'
              + (f' · 판정 오류 {team_err}건' if team_err else ''))
    return {'hits': hits, 'changed': changed_n, 'skipped_ai': skipped_ai, 'team_hits': team_hits}


def save_new_items(items: list, existing_data: tuple) -> list:
    """규칙1: 15일 이내 & 날짜 확인된 신규 기사만 저장
    existing_data: (existing_urls: set, existing_titles: set)
    URL + 제목 이중 중복 체크 (Google RSS 리다이렉트 URL 대응)

    순서(2026-08-03 재배치): 중복 제거 → ①조기 날짜 필터 → ②Haiku 관련성 선별
    → ③본문 수집 → ④날짜 필터 → ⑤긴급도 분류 → 저장.
    본문 수집·긴급도 분류는 선별 통과분에만 돈다(둘 다 건당 비용이 큰 단계).
    """
    existing_urls, existing_titles = existing_data
    _INSERTED_IDS.clear()                       # 이번 실행에 새로 저장된 기사만 팀 알림 후보(#252) — 이른 반환에도 비어 있게
    now_kst = datetime.now(KST)
    cutoff_72h = now_kst - timedelta(days=15)   # 저장 기준: 15일 이내
    seen_urls   = set(existing_urls)
    seen_titles = set(existing_titles)
    unique_new = []
    for item in items:
        url   = item.get('url', '')
        title = item.get('title', '')
        # URL 중복 체크
        if url and url in seen_urls:
            continue
        # 제목 중복 체크 (Google RSS ↔ 직접 크롤링 간 같은 기사 방지)
        if title and title in seen_titles:
            continue
        if url:
            seen_urls.add(url)
        if title:
            seen_titles.add(title)
        # # 으로 시작하는 제목(태그/토픽 페이지) 제외
        if title.startswith('#'):
            continue
        unique_new.append(item)

    if not unique_new:
        print('[저장] 신규 항목 없음')
        return []

    # ① 조기 날짜 필터 — 발행일이 이미 확정된 오래된 기사는 선별·본문 수집 전에 뺀다.
    #    (뒤의 ④ 필터와 기준은 같다. 판정·본문 토큰을 어차피 버릴 기사에 쓰지 않으려는 것)
    #    발행일 불명분은 본문 수집이 날짜를 채울 수 있으므로 여기서 버리지 않는다.
    fresh, stale_old = [], 0
    for item in unique_new:
        pub = item.get('published_at', '')
        if pub:
            try:
                from dateutil import parser as _dtp0
                pub_dt0 = _dtp0.parse(pub)
                if pub_dt0.tzinfo is None:
                    pub_dt0 = pub_dt0.replace(tzinfo=KST)
                if pub_dt0 < cutoff_72h:
                    stale_old += 1
                    continue
            except Exception:
                pass      # 파싱 실패는 통과 — 뒤의 정식 필터가 처리
        fresh.append(item)
    if stale_old:
        print(f'[필터] {stale_old}건 15일 초과 — 선별 전 제외')
    unique_new = fresh
    if not unique_new:
        print('[저장] 유효한 신규 항목 없음')
        return []

    # ② 관련성 1차 선별 (Haiku) — 통과분만 본문 수집·긴급도 분류로 넘긴다.
    #    제외분은 저장하지 않는다. 저장해 두면 대시보드·RAG·브리핑 모집단이 그대로 오염되고,
    #    url UNIQUE 때문에 나중에 되살리기도 어렵다. 놓침이 걱정되면 기준문(app_config)을
    #    고치는 쪽이 맞다 — 제외 표본은 위 로그에 남는다.
    unique_new = screen_news_items(unique_new)
    if not unique_new:
        print('[저장] 선별 통과 항목 없음')
        return []

    # ③ 본문 수집 및 발행일 확정 — Actions·PC 공통 (2026-09-24, #200)
    #    2026-06-04(334ff2c)부터 Actions에서는 "미국 IP라 한국 뉴스 사이트가 막힌다"며 이 단계를 건너뛰었는데,
    #    실측 기록이 없던 가정이었다. 2026-09-24 tools_gov_reachability.py 뉴스 진단: Actions 데이터센터 IP에서
    #    상위 도메인 7곳 중 6곳 본문 열림(한국 IP와 동일, 위장 불필요). 당시 진짜 문제는 선별이 없던 시절
    #    매시 최대 500건을 8초 타임아웃으로 긁던 실행 시간이었고, 지금은 선별 통과분만이라 10분 창당
    #    중앙값 2건·p90 9건·최대 54건(최악 ≈8분 < job timeout 30분, concurrency 그룹이 겹침 방지).
    #    본문이 있어야 ⑤ 긴급도 판정이 제목+요약이 아니라 본문(600자)을 본다.
    #    실패·빈 껍데기(#113 유형: HTTP 200에 본문 없음)는 content를 비워 두어 refetch_content(lampmanH-pc)의
    #    '100자 미만=재수집' 조건이 그대로 살고, 판정은 #188 요약 폴백으로 간다. 건수는 반드시 로그에 남긴다.
    print(f'[본문 수집] {"GitHub Actions" if IS_GITHUB_ACTIONS else "PC"} 환경 — {len(unique_new)}건 본문 수집 시작...')
    body_ok = body_fail = 0
    for item in unique_new:
        if item.get('url'):
            body, article_date = fetch_article_body(item['url'], item.get('source', ''))
            if body and len(body.strip()) >= 100:
                item['content'] = body
                body_ok += 1
            else:
                body_fail += 1          # content는 기존값(None 또는 RSS 요약) 유지 → refetch 대상
            item['content_fetched_at'] = now_kst.isoformat()
            current_pub = item.get('published_at', '')
            if not current_pub and article_date:
                item['published_at'] = article_date
                print(f'  [날짜보정] {item.get("title","")[:30]}... → {article_date}')
            elif not current_pub:
                item['published_at'] = ''
            time.sleep(1)
        else:
            item['content_fetched_at'] = now_kst.isoformat()
            if not item.get('published_at'):
                item['published_at'] = ''
    print(f'[본문 수집] 성공 {body_ok}건 · 실패/100자 미만 {body_fail}건 (실패분은 refetch_content가 재수집)')

    # ④ 72시간 초과 또는 발행일 불명 제외 (규칙1)
    valid, skipped_unknown, skipped_old = [], 0, 0
    for item in unique_new:
        pub = item.get('published_at', '')
        if not pub:
            skipped_unknown += 1
            continue
        try:
            from dateutil import parser as _dtp
            pub_dt = _dtp.parse(pub)
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=KST)
            if pub_dt < cutoff_72h:
                skipped_old += 1
                continue
        except Exception:
            skipped_unknown += 1
            continue
        valid.append(item)

    if skipped_unknown:
        print(f'[필터] {skipped_unknown}건 발행일 불명 — 제외')
    if skipped_old:
        print(f'[필터] {skipped_old}건 15일 초과 — 제외')
    if not valid:
        print('[저장] 유효한 신규 항목 없음')
        return []

    # ⑤ 긴급도 — 선별 콜(screen_news_items)이 이미 매긴 값을 쓰고, 빠진 것만 개별 판정한다.
    #    통합 전에는 여기서 전건을 건당 1콜로 돌렸다(하루 ~600콜 = 비용의 큰 축).
    #    ⚠️ 2026-08-04 되돌림 — 선별 콜 통합(#82)은 **긴급률을 9.9% → 0.7%로 무너뜨렸다.**
    #    같은 기사로 확인된 A/B: 「SKT 5G 과장광고 과징금, 대법원 간다」가 8/3(개별)은 긴급,
    #    8/4(통합)은 보통. 원인은 판정 재료와 개인화 두 가지다:
    #      ① 선별은 파이프라인상 **본문 수집 전**이라 네이버 요약 300자(_screen_text)만 본다.
    #         「공정위가 상고했다」 같은 핵심이 요약에서 잘린다. 본문(중앙값 1,329자)은 여기서만 쓴다.
    #         ⚠️ 2026-06-04~2026-09-24에는 Actions가 본문 수집을 건너뛰어 이 판정이 제목만 봤다(#188에서 확인,
    #         요약 폴백 추가). #200부터 Actions도 본문을 긁으므로 본문이 있으면 본문(600자), 없으면 요약으로 판정.
    #         → 선별에 본문을 주려면 무관 기사 500건의 본문까지 매시간 긁어야 해서 캐시 절감이 무너진다.
    #      ② 개별 판정은 get_feedback_examples(title)로 **제목별 유사 사례 5건**을 넣지만,
    #         배치 판정은 여러 기사를 한 번에 보므로 공통 사례만 쓴다.
    #    월 $33을 아끼려다 긴급 알림(이 시스템의 존재 이유)을 잃는 거래라 원복했다.
    #    선별 콜은 urgency를 여전히 뱉지만(스키마 유지) **여기서 쓰지 않는다** — 프롬프트 보강으로
    #    통합을 되살릴 실험 여지를 남겨 둔 것. 되살릴 땐 반드시 긴급률을 배포 전(9.9%)과 비교할 것.
    #    ⑤-1 공통 낱말 규칙(#216, 표 urgency_rules)을 AI 판정과 합친다 — grade_urgency 주석 참조.
    #    ⑤-2 팀 규칙(#250)은 공통값 위에서 팀별 적중만 모은다(공통값·알림 불변) — 저장은 아래 save_team_rule_rows.
    #    ⑤-3 팀 규칙의 문장 조건(#251)은 여기서 **판정하지 않는다** — 낱말이 걸린 기사의 판정 대기 행(본문 있으면 pending,
    #        없으면 wait_body)만 만들고(저장은 아래 save_sentence_verdict_rows), Haiku 판정과 팀 행 고침은 같은 실행의
    #        main() 끝 process_open_sentence_verdicts(긴급 알림·구독자 큐 뒤)가 한다 — 알림 경로에 AI 지연을 넣지 않는다.
    grade_urgency(valid, load_urgency_rules(), team_rules=load_team_urgency_rules())
    queue_new_sentence_candidates(valid, load_team_urgency_rules())

    try:
        # upsert(on_conflict=url, ignore_duplicates): 크롤러 동시 실행 시
        # 같은 기사 중복 저장 방지 (idx_news_feed_url_unique와 한 쌍)
        # 응답(res.data) = 새로 들어간 행만(postgrest 기본 return=representation + ON CONFLICT DO NOTHING) —
        # 팀 규칙 행을 붙일 news_id를 여기서 얻는다(#250).
        res = sb.table('news_feed').upsert(
            valid, on_conflict='url', ignore_duplicates=True
        ).execute()
    except Exception as e:
        print(f'[저장 오류] Supabase upsert 실패: {e}')
        return []
    urgent_count = sum(1 for i in valid if i.get('urgency') == '긴급')
    print(f'[저장] {len(valid)}건 저장 완료 (긴급 {urgent_count}건)')
    inserted = getattr(res, 'data', None)
    _remember_inserted(inserted)             # 팀 알림 후보(#252) — 응답 행만
    save_sentence_verdict_rows(inserted)     # 판정 기록 먼저 — 팀 행(아래)은 이 판정에서 나온 값이다(#251)
    save_team_rule_rows(inserted)
    return valid


def _remember_inserted(inserted) -> None:
    """upsert 응답(새로 들어간 행 — id·url) → _INSERTED_IDS(url → news_id, #252). 응답이 비거나 이상하면 비운 채로 둔다
    (팀 알림 후보 없음 — 공통 알림은 종전대로 valid 전체를 본다)."""
    _INSERTED_IDS.clear()
    try:
        for r in inserted or []:
            if isinstance(r, dict) and r.get('id') and r.get('url'):
                _INSERTED_IDS[r['url']] = r['id']
    except Exception as e:
        _INSERTED_IDS.clear()
        print(f'[팀 알림] 저장 응답 정리 실패(무시 — 이번 실행은 팀 알림 후보 없음): {str(e)[:80]}')


def team_rule_rows(inserted: list) -> list:
    """새로 저장된 기사(upsert 응답 행 — id·url) × 팀 규칙 적중 → team_urgency 행(#250).
    응답에 없는 url(이미 있던 기사 = 동시 실행이 먼저 넣음)은 만들지 않는다 — 그 기사는 먼저 넣은 실행이 맡는다.
    모든 행의 키 집합이 같다(#82)."""
    rows = []
    for r in inserted or []:
        nid, url = r.get('id'), r.get('url')
        if not nid or not url:
            continue
        for h in _TEAM_RULE_HITS.get(url, ()):
            rows.append({'news_id': nid, 'team_id': h['team_id'], 'urgency': h['urgency'],
                         'source': 'rule', 'rule_id': h['rule_id']})
    return rows


TEAM_URGENCY_CHUNK = 500


def save_team_rule_rows(inserted) -> int:
    """팀 규칙 적중을 team_urgency에 쓴다(source='rule'). 반환 = 보낸 행 수. **fail-open** — 팀 층 때문에 수집이
    실패하면 안 된다(예외는 로그만). ignore_duplicates(ON CONFLICT DO NOTHING) — 이미 있는 팀 행(사람 수정 human,
    세션 C의 ai, 브라우저가 먼저 쓴 rule)을 절대 덮지 않는다(설계안 §10 쓰기 규칙 human > rule)."""
    if not _TEAM_RULE_HITS:
        return 0
    try:
        rows = team_rule_rows(inserted)
        if not rows:
            # 적중은 있는데 새 행과 하나도 안 맞음 = 전부 중복(동시 실행) 또는 응답이 비었다 — 조용히 넘기지 않는다
            print(f'[팀 규칙] 저장 0건 — 적중 기사 {len(_TEAM_RULE_HITS)}건이 이번 저장 응답(새 행 '
                  f'{len(inserted or [])}건)에 없음(이미 있던 기사이거나 응답 비어 있음)')
            return 0
        for i in range(0, len(rows), TEAM_URGENCY_CHUNK):
            sb.table('team_urgency').upsert(rows[i:i + TEAM_URGENCY_CHUNK], on_conflict='news_id,team_id',
                                            ignore_duplicates=True).execute()
        print(f"[팀 규칙] {len(rows)}건 저장({len({r['team_id'] for r in rows})}팀)")
        return len(rows)
    except Exception as e:
        print(f'[팀 규칙] 저장 실패(무시): {str(e)[:120]}')
        return 0


# ═══════════════════════════════════════════════════════
#  팀 규칙 「문장 조건」 판정 — Claude Haiku (#251, 2026-09-27, 설계안 §10-2 — ⚠️ Fable 재검토 대상)
#
#  팀 규칙의 낱말(any/and_any/none)이 1차 거름이고, 걸린 기사만 Haiku가 「조건 문장에 해당하나」를 **한 번** 판정해
#  표 urgency_rule_verdicts에 (규칙, 문장 판 sentence_rev, 기사)로 저장한다 — 같은 판의 같은 기사는 다시 묻지 않는다
#  (#249 재현성 원칙: 다시 물으면 같은 기사가 실행마다 다른 등급이 될 수 있다). 문장을 고치면 DB 트리거가 판을 올려
#  그 규칙만 새로 판정한다. 판정 대기·없음·거짓·옛 판은 '안 걸림'(urgency_rules.sentence_filtered_rules) — 뒤 규칙이 정한다.
#  · 흐름(리뷰 반영 2026-09-27): 수집(save_new_items)은 **AI 없이** 판정 대기 행만 만든다(본문 있으면 pending, 없으면
#    wait_body) → 같은 실행의 main() 끝, 긴급 알림·구독자 큐 **뒤**에서 process_open_sentence_verdicts가 판정하고 팀 행을
#    고친다. 10분 실행 안에서 판정되는 것은 같고, 판정 지연이 공통 긴급 알림을 늦추지 않는다.
#  · 판정 글(C2) = 제목 + 검색 요약(≤300자) + 본문 앞 800자. 본문(content 100자 이상 — 수집 저장·재수집 기준과 같다)이
#    있으면 바로 판정, 없으면 wait_body — lampmanH-pc 재수집이 content를 채우면 판정, 3시간이 지나면 제목+요약으로.
#  · 대시보드는 규칙 저장 뒤 지난 기사의 **대기 행만** 넣는다(C3) — 판정 지시문은 이 파일 한 곳(JS 사본 금지).
#  · 비용(C4): 팀별 이번 달 판정 비용 합계가 기준($2, app_config sentence_rule_budget_usd)을 넘으면 그 달에 한 번 운영자
#    텔레그램(보낸 달은 app_config sentence_rule_budget_alerted에 팀별 'YYYY-MM'). **판정은 멈추지 않는다**(운영자 결정).
#  · 모델(C8) Haiku 4.5, 규칙당 ≤20건 묶음, 도구 강제, 캐시 없음(접두 < 4,096토큰), temperature류 금지(지침 do-not).
#    지시문·도구는 실측(58건 정답·흔들림 0, 설계안 §10-2)에 쓴 글자 그대로다 — 고치면 그 실측이 무효가 된다.
#  · 장애: 호출이 통째로 실패하면(예외·529·시간 초과·도구 없음) 시도 수를 올리지 않고 이번 실행의 판정을 멈춘다(다음 실행에서
#    다시) — Anthropic 장애 몇 번에 멀쩡한 요청이 failed로 굳지 않게. 시도 수는 '호출은 됐는데 답에 그 기사가 빠짐'만 세고,
#    최종 멈춤은 대기 3일 기한(SENTENCE_OPEN_MAX_DAYS)이다.
# ═══════════════════════════════════════════════════════

SENTENCE_BATCH = 20              # 호출당 기사 수(규칙 하나) — 시험에서 묶음·한 건씩 판정이 같았다(C8)
SENTENCE_BODY_CHARS = 800        # 본문 앞부분(공백 정리 뒤)
SENTENCE_SNIPPET_CHARS = 300     # 검색 요약
SENTENCE_BODY_MIN = 100          # 앞뒤 공백을 뺀 content가 이 길이 이상이면 '본문 있음' — 수집 저장(③ 100자)·refetch_content
                                 # 재수집(100자 미만) 기준과 같다. 200이면 100~199자 본문은 오지 않을 재수집을 3시간 기다린다
SENTENCE_WAIT_BODY_HOURS = 3     # 본문 대기 상한 — 지나면 제목+요약으로 판정
SENTENCE_MAX_ATTEMPTS = 3        # '호출은 됐는데 답에 그 기사가 빠짐'이 이만큼 쌓이면 failed(호출 통째 실패는 세지 않는다)
SENTENCE_OPEN_MAX_DAYS = 3       # 대기 행이 이보다 오래되면 failed — 최종 멈춤(장애가 길게 이어져도 여기서 끝난다)
SENTENCE_PER_RUN_MAX = 100       # 실행당 판정 건수 상한 — 넘는 몫은 대기로 두고 다음 실행(10분 뒤)
SENTENCE_BUDGET_USD = 2.0        # 팀당 월 비용 알림 기준 기본값(app_config sentence_rule_budget_usd가 있으면 그 값)
SENTENCE_OPEN_LIMIT = 500        # 한 실행에서 읽는 대기 행·되살림 후보 수(새것부터)
SENTENCE_TIME_BUDGET_S = 120     # 대기 처리의 판정 시간 예산 — 넘으면 남은 것은 다음 실행
SENTENCE_CALL_TIMEOUT_S = 90     # 호출 하나의 제한 — SDK 기본(10분 × 재시도 2회)이면 멈춘 호출 하나가 job 30분과 heartbeat를 먹는다
SENTENCE_CHUNK = 500             # 판정 기록 upsert 묶음
SENTENCE_ID_CHUNK = 100          # news_id in_ 조회 묶음
SENTENCE_DB_RETRIES = 2          # 판정 기록·팀 행 쓰기 재시도(retry_util) — Anthropic 호출에는 걸지 않는다
SENTENCE_DB_RETRY_DELAY_S = 1
SENTENCE_SNAPSHOT_MARGIN_S = 120  # 규칙 읽은 시각(크롤러 시계)과 created_at(DB 시계) 차이 여유 — 이 안쪽 요청도 '사본 뒤'로 본다
SENTENCE_REV_CATCHUP_DAYS = 3    # 판 올림 재요청(Fable 재검토 #251): 문장을 고친 지(updated_at) 이 기간 안인 규칙의, 이 기간 안에 생긴
                                 # 옛 판 판정 행 기사 중 지금 판 행이 없고 지금 낱말이 걸리는 기사에 지금 판 대기 행을 넣는다
SENTENCE_REQUEUE_BY = '00000000-0000-0000-0000-000000000000'   # 그 재요청 행의 requested_by 표식 — 수집 경로(null)가 아니므로 늦은 팀
                                 # 알림(#252 B2 '규칙 저장·재판정으로 생긴 등급은 화면에만') 후보에서 빠진다. null로 바꾸지 말 것
_SENTENCE_PRICE_IN = 1.0 / 1_000_000     # Haiku 4.5 입력 $1/M 토큰
_SENTENCE_PRICE_OUT = 5.0 / 1_000_000    # 출력 $5/M 토큰
_BUDGET_KEY = 'sentence_rule_budget_usd'           # app_config — 팀당 월 비용 알림 기준(글자 → 실수)
_BUDGET_MARK_KEY = 'sentence_rule_budget_alerted'  # app_config — 알림을 보낸 달 {"<team_id>": "YYYY-MM"}(JSON)

SENTENCE_RUBRIC = (
    "너는 뉴스 기사 분류기다. 팀이 정한 「조건 문장」에 각 기사가 해당하는지 판정한다.\n\n"
    "판정 규칙\n"
    "1. 기사의 중심 내용이 조건 문장에 해당할 때만 match=true. 조건의 주제어가 나와도 지나가는 언급"
    "(시설·서비스 목록의 한 항목, 다른 사안의 배경 설명)이면 false.\n"
    "2. 조건 문장이 기사의 성격(문제 제기·비판, 긍정 평가, 발표·결정 등)을 정했으면 그 성격이어야 true. "
    "주제가 같아도 성격이 다르면(조건은 문제 제기인데 기사는 개선·확대·도입 소식) false.\n"
    "3. 주어진 제목·요약·본문 앞부분만 보고 판단한다(본문은 앞부분만 잘려 있다). 요약·본문이 없으면 제목만으로 "
    "판단하고, 해당하는지 분명하지 않으면 false.\n"
    "4. 기사가 회사에 중요한지, 뉴스 가치가 큰지는 판단하지 않는다. 조건 문장에 해당하는지만 본다.\n"
    "5. 기사마다 따로 판정한다(같은 사건의 다른 기사도 각자). why에는 판정 근거를 한 줄(40자 이내)로 쓴다."
)
SENTENCE_TOOL = {'name': 'record_condition_verdicts',
  'description': '기사마다 조건 문장 해당 여부를 기록한다. 입력된 모든 기사에 대해 한 줄씩.',
  'input_schema': {'type': 'object', 'properties': {'verdicts': {'type': 'array', 'items': {'type': 'object',
     'properties': {'id': {'type': 'integer', 'description': '기사 번호'},
                    'why': {'type': 'string', 'description': '판정 근거 한 줄(40자 이내)'},
                    'match': {'type': 'boolean', 'description': '조건 문장에 해당하면 true'}},
     'required': ['id', 'why', 'match']}}}, 'required': ['verdicts']}}

# 판정 대기 행(url → [행(news_id 없음)]). queue_new_sentence_candidates가 채우고 save_sentence_verdict_rows가 새로 저장된 기사
# 것만 쓴다 — _TEAM_RULE_HITS와 같은 구조(item 키 금지, #82·#222).
_SENTENCE_ROWS: dict = {}
# 이번 실행에서 저장한 판정 비용(team_id → USD). 월 비용 알림은 이번 실행에 판정이 있던 팀만 본다.
_SENTENCE_RUN_COST: dict = {}
# 실행 상태 — judged: 이번 실행에 보낸 판정 건수(상한), nokey_logged: 키 없음 로그 1회, broken: 호출 통째 실패 뒤 판정 중단
_SENTENCE_RUN: dict = {'judged': 0, 'nokey_logged': False, 'broken': False}


def _ws(s) -> str:
    """공백 정리 — 판정 입력 전부(실측과 같은 ' '.join(s.split()))."""
    return ' '.join(s.split()) if isinstance(s, str) else ''


def _sentence_body(content) -> str:
    """판정용 본문 — 앞뒤 공백을 뺀 content가 SENTENCE_BODY_MIN 이상이면 공백 정리 뒤 앞 800자, 아니면 ''(본문 없음).
    content = 수집 때 긁은 본문(fetch_article_body) 또는 재수집(refetch_content)이 채운 본문. Google RSS 폴백 기사는
    RSS 요약이 content에 들어 있어 100자를 넘으면 본문으로 본다(그 기사는 재수집 대상도 아니다)."""
    if not isinstance(content, str) or len(content.strip()) < SENTENCE_BODY_MIN:
        return ''
    return _ws(content)[:SENTENCE_BODY_CHARS]


def _rev_of(rule) -> int:
    """규칙의 지금 문장 판 — 정수가 아니면 0(urgency_rules.sentence_verdict와 같은 규칙)."""
    v = rule.get('sentence_rev', 0) if isinstance(rule, dict) else 0
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def _as_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _parse_ts(s):
    """PostgREST timestamptz 문자열 → aware datetime. 못 읽으면 None."""
    try:
        dt = datetime.fromisoformat(str(s).replace('Z', '+00:00'))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _sentence_cost(usage) -> float:
    """호출 한 번의 요금(USD) = 입력 토큰 × $1/M + 출력 토큰 × $5/M(캐시를 쓰지 않는다). usage가 없으면 0."""
    if usage is None:
        return 0.0

    def g(k):
        v = getattr(usage, k, None)
        if v is None and isinstance(usage, dict):
            v = usage.get(k)
        return _as_int(v or 0)
    return g('input_tokens') * _SENTENCE_PRICE_IN + g('output_tokens') * _SENTENCE_PRICE_OUT


def _sentence_client():
    """문장 판정용 Anthropic 클라이언트 — 판정할 것이 있을 때만 만든다. 키가 없으면(로그는 실행당 1번) None → 행은 대기로 남는다.
    호출 제한(SENTENCE_CALL_TIMEOUT_S, 재시도 1회)을 건다 — 판정이 늦어도 heartbeat·이슈 제안을 붙잡지 않게."""
    if not ANTHROPIC_API_KEY:
        if not _SENTENCE_RUN.get('nokey_logged'):
            print('[문장 판정] ANTHROPIC_API_KEY 없음 — 판정하지 않고 대기로 둔다(키가 생기면 다음 실행에서 판정)')
            _SENTENCE_RUN['nokey_logged'] = True
        return None
    try:
        return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=SENTENCE_CALL_TIMEOUT_S, max_retries=1)
    except Exception as e:
        print(f'[문장 판정] Haiku 초기화 실패 — 대기로 둔다: {str(e)[:80]}')
        return None


def _judge_sentence_batch(client, sentence: str, rows: list):
    """조건 문장 하나 × 기사 ≤SENTENCE_BATCH건을 Haiku 1콜로 판정한다.
    rows = [{'title', 'snippet', 'body'}] — 공백 정리·자르기(요약 300자·본문 800자)는 여기서 하고, 빈 요약·본문은 payload에서 뺀다.
    반환 (결과, 비용): 결과 = {기사 번호(1부터): (해당 여부 bool, 근거 ≤80자)} — 답에 없는 번호는 '판정 못 함'(부르는 쪽이
    시도 1회로 센다). 예외·도구 호출 없음 = (None, 비용) — 부르는 쪽은 이번 실행 판정을 멈춘다(시도 수 불변).
    비용 = 이 호출의 요금(부르는 쪽이 기사 수로 나눈다).
    ⚠️ client.messages.create는 **이 함수 안에서 직접** 부를 것 — api_usage.install()이 부른 함수 이름으로 비용 라벨
    ('crawler.py:_judge_sentence_batch')을 만든다. 람다·with_retry로 감싸면 라벨이 엉뚱해진다.
    결정성: 도구 강제 + 판정 규칙 문자 적용. temperature류 파라미터 금지(지침 do-not), 캐시 없음(접두가 최소 4,096토큰 미만)."""
    n = len(rows)
    payload = []
    for k, r in enumerate(rows, 1):
        row = {'id': k, 'title': _ws(r.get('title'))}
        snippet = _ws(r.get('snippet'))[:SENTENCE_SNIPPET_CHARS]
        if snippet:
            row['summary'] = snippet
        body = _ws(r.get('body'))[:SENTENCE_BODY_CHARS]
        if body:
            row['body'] = body
        payload.append(row)
    prompt = (f'조건 문장: «{sentence}»\n\n아래 기사 {n}건을 모두 판정해 record_condition_verdicts 도구로 기록하라.\n'
              + json.dumps(payload, ensure_ascii=False))
    cost = 0.0
    try:
        resp = client.messages.create(
            model=SCREEN_MODEL,
            max_tokens=4000,
            system=SENTENCE_RUBRIC,
            tools=[SENTENCE_TOOL],
            tool_choice={'type': 'tool', 'name': 'record_condition_verdicts'},
            messages=[{'role': 'user', 'content': prompt}],
        )
        cost = _sentence_cost(getattr(resp, 'usage', None))
        for blk in resp.content:          # 도구 강제 — tool_use 블록만 읽는다(_screen_batch_haiku와 같은 방식)
            if getattr(blk, 'type', '') == 'tool_use':
                out = {}
                for v in (blk.input or {}).get('verdicts') or []:
                    if not isinstance(v, dict):
                        continue
                    k = _as_int(v.get('id'), -1)
                    m = v.get('match')
                    if 1 <= k <= n and isinstance(m, bool) and k not in out:     # 참·거짓이 아닌 답은 '판정 못 함'
                        out[k] = (m, _ws(v.get('why'))[:80])
                return out, cost
        print(f'  [문장 판정 오류] 도구 호출 없음({n}건)')
        return None, cost
    except Exception as e:
        print(f'  [문장 판정 오류] {str(e)[:120]}')
        return None, cost


def _judge_jobs(client, sentence: str, jobs: list, t0: float) -> list:
    """한 규칙(조건 문장 하나)의 판정 거리들을 ≤SENTENCE_BATCH건 묶음으로 판정 — 실행당 상한·시간 예산 안에서만.
    jobs = [{'title', 'snippet', 'body', …}]. 반환 = jobs와 같은 순서·길이:
      None = 보내지 않음(클라이언트 없음·상한·시간·이번 실행 판정 중단) **또는 호출이 통째로 실패함** → 행은 그대로(시도 수 불변)
      (해당 여부, 근거, 기사당 비용) = 판정됨 / (None, '', 0.0) = 호출은 됐는데 답에 그 기사가 빠짐(시도 1회로 센다).
    호출이 통째로 실패하면(예외·529·시간 초과·도구 없음) 이번 실행의 남은 호출을 모두 멈춘다(차단기 _SENTENCE_RUN['broken'],
    로그 1줄) — 장애 중에 호출을 거듭하면 요청마다 시도 수만 쌓여 멀쩡한 행이 failed로 굳는다.
    비용은 호출 요금을 그 호출의 기사 수로 나눈 몫 — 판정된 기사만 제 몫을 기록한다(나머지는 api_usage에만 남는다)."""
    out = [None] * len(jobs)
    pos = 0
    while client is not None and pos < len(jobs) and not _SENTENCE_RUN.get('broken'):
        room = SENTENCE_PER_RUN_MAX - _SENTENCE_RUN.get('judged', 0)
        if room <= 0 or time.monotonic() - t0 > SENTENCE_TIME_BUDGET_S:
            break
        n = min(SENTENCE_BATCH, room, len(jobs) - pos)
        _SENTENCE_RUN['judged'] = _SENTENCE_RUN.get('judged', 0) + n
        got, cost = _judge_sentence_batch(client, sentence, jobs[pos:pos + n])
        if got is None:
            _SENTENCE_RUN['broken'] = True
            print('[문장 판정] AI 호출 실패 — 이번 실행 판정 중단(다음 실행에서 다시)')
            break
        share = round(cost / n, 6)
        for k in range(n):
            v = got.get(k + 1)
            out[pos + k] = (v[0], v[1], share) if v else (None, '', 0.0)
        pos += n
    return out


def _verdict_row(rule_id, rev, team_id, status, *, verdict=None, reason='', input_kind='', model='', cost=0.0,
                 attempts=0, judged_at=None) -> dict:
    """urgency_rule_verdicts 행(news_id는 저장 때 붙인다). ★ 모든 행의 키 집합 동일 ★(PostgREST 벌크 upsert 요건, #82).
    requested_by·created_at은 보내지 않는다 — 트리거(BEFORE INSERT)·기본값 몫이고, 갱신(ON CONFLICT DO UPDATE)은 보낸 칸만
    바꾸므로 요청자 기록이 남는다. verdict는 status='done'일 때만 참·거짓(표 CHECK)."""
    return {'rule_id': rule_id, 'sentence_rev': rev, 'team_id': team_id, 'status': status, 'verdict': verdict,
            'reason': reason, 'input_kind': input_kind, 'model': model, 'cost_usd': cost, 'attempts': attempts,
            'judged_at': judged_at}


def _result_row(rule_id, rev, team_id, res, input_kind: str, attempts: int, now_iso: str):
    """_judge_jobs 결과 하나 → 판정 기록 행. None(보내지 않음·호출 통째 실패)이면 None — 행을 건드리지 않는다.
    답에 그 기사가 빠짐 = 시도 수만 올려 pending(SENTENCE_MAX_ATTEMPTS번째면 failed)."""
    if res is None:
        return None
    match, why, share = res
    if match is None:
        n = attempts + 1
        return _verdict_row(rule_id, rev, team_id, 'failed' if n >= SENTENCE_MAX_ATTEMPTS else 'pending', attempts=n)
    return _verdict_row(rule_id, rev, team_id, 'done', verdict=match, reason=why, input_kind=input_kind,
                        model=SCREEN_MODEL, cost=share, attempts=attempts + 1, judged_at=now_iso)


def _add_run_cost(rows) -> None:
    """저장에 성공한 done 행의 비용을 팀별로 더한다(월 비용 알림은 이번 실행에 판정이 있던 팀만 본다)."""
    for r in rows:
        if r.get('status') == 'done' and r.get('cost_usd'):
            t = r.get('team_id')
            _SENTENCE_RUN_COST[t] = _SENTENCE_RUN_COST.get(t, 0.0) + float(r['cost_usd'])


def _db_retry(fn, label: str):
    """문장 판정 기록·팀 행 쓰기 한 번 — 일시 오류면 SENTENCE_DB_RETRIES번까지(retry_util, #217). Anthropic 호출에는 쓰지 않는다
    (호출 재시도는 비용이 두 배가 되고, 장애 처리는 차단기가 맡는다)."""
    return retry_util.with_retry(fn, retries=SENTENCE_DB_RETRIES, delay=SENTENCE_DB_RETRY_DELAY_S, label=label,
                                 raise_status=False)


def _upsert_rows(table: str, rows: list, chunk: int, **kw) -> tuple:
    """rows를 chunk씩 upsert(쓰기마다 재시도). 묶음이 실패하면 한 행씩 다시 쓴다 — 도중에 지워진 기사(FK 오류)의 행만 빠지고
    나머지는 저장된다. 한 행씩 쓰기에서 처음 3행이 모두 실패하면 표 자체 장애로 보고 멈춘다(더 두드리지 않는다).
    반환 (저장된 행, 첫 오류 글 — 없으면 '')."""
    saved, err = [], ''
    for i in range(0, len(rows), chunk):
        part = rows[i:i + chunk]
        try:
            _db_retry(lambda p=part: sb.table(table).upsert(p, **kw).execute(), table)
            saved.extend(part)
            continue
        except Exception as e:
            err = err or str(e)[:120]
        if len(part) == 1:
            continue
        ok_any, bad_run = False, 0
        for r in part:
            try:
                _db_retry(lambda p=[r]: sb.table(table).upsert(p, **kw).execute(), table)
                saved.append(r)
                ok_any, bad_run = True, 0
            except Exception as e:
                err = err or str(e)[:120]
                bad_run += 1
                if not ok_any and bad_run >= 3:
                    return saved, err
    return saved, err


def queue_new_sentence_candidates(valid: list, team_rules) -> dict:
    """⑤-3 새 기사의 문장 조건 후보 → 판정 대기 행(#251). **AI를 부르지 않는다**(리뷰 반영 2026-09-27 — 수집·긴급 알림 경로에
    AI 지연을 넣지 않는다). 본문(SENTENCE_BODY_MIN 이상)이 있으면 pending, 없으면 wait_body. 행은 _SENTENCE_ROWS에 두고
    news_feed 저장 뒤 save_sentence_verdict_rows가 새로 들어간 기사 것만 쓴다. 판정·팀 행 고침은 같은 실행의 main() 끝
    process_open_sentence_verdicts(긴급 알림·구독자 큐 뒤)가 한다 — 그때까지 팀 결정은 '판정 없음'(문장 규칙 빼고 뒤 규칙)
    그대로다(_TEAM_RULE_HITS 불변). 후보가 없으면 아무것도 하지 않는다(조회·로그 0). fail-open. 반환 = 로그용 집계."""
    if not _SENTENCE_CANDS:
        return {}
    try:
        items = {it.get('url'): it for it in valid if it.get('url')}
        rule_by_id = {r.get('id'): r for rs in (team_rules or {}).values() for r in rs}
        st = {'cands': 0, 'pending': 0, 'wait': 0}
        for url in list(_SENTENCE_CANDS):
            entries = _SENTENCE_CANDS.pop(url, None) or []
            it = items.get(url)
            if it is None:
                continue
            _SENTENCE_ROWS.pop(url, None)
            status = 'pending' if _sentence_body(it.get('content')) else 'wait_body'
            for e in entries:
                for rid in e.get('rule_ids') or []:
                    r = rule_by_id.get(rid)
                    if r is None or not urgency_rules.has_sentence(r):
                        continue
                    _SENTENCE_ROWS.setdefault(url, []).append(_verdict_row(rid, _rev_of(r), e.get('team_id'), status))
                    st['cands'] += 1
                    st['pending' if status == 'pending' else 'wait'] += 1
        if st['cands']:
            print(f"[문장 판정] 새 기사 후보 {st['cands']}건 → 대기 {st['pending']}건 · 본문 대기 {st['wait']}건"
                  ' (판정은 긴급 알림 뒤 대기 처리에서)')
        return st
    except Exception as e:
        _SENTENCE_CANDS.clear()
        print(f'[문장 판정] 새 기사 후보 정리 오류(무시 — 그 기사들은 판정 요청 없이 저장): {str(e)[:120]}')
        return {}


def sentence_verdict_rows(inserted) -> list:
    """새로 저장된 기사(upsert 응답 행 — id·url) × 판정 대기 행 → urgency_rule_verdicts 행(#251). team_rule_rows와 같은 규칙:
    응답에 없는 url(이미 있던 기사 = 동시 실행이 먼저 넣음)은 만들지 않는다. 모든 행의 키 집합이 같다(#82)."""
    rows = []
    for r in inserted or []:
        nid, url = r.get('id'), r.get('url')
        if not nid or not url:
            continue
        for v in _SENTENCE_ROWS.get(url, ()):
            rows.append(dict(v, news_id=nid))
    return rows


def save_sentence_verdict_rows(inserted) -> int:
    """판정 대기 행을 urgency_rule_verdicts에 쓴다(#251). 반환 = 저장된 행 수. **fail-open**(예외는 로그만 — 수집을 막지 않는다).
    ignore_duplicates — 같은 (규칙·판·기사)가 이미 있으면 그대로 둔다(한 번 판정한 것은 다시 쓰지 않는다)."""
    if not _SENTENCE_ROWS:
        return 0
    try:
        rows = sentence_verdict_rows(inserted)
        if not rows:
            print(f'[문장 판정] 기록 저장 0건 — 판정 기사 {len(_SENTENCE_ROWS)}건이 이번 저장 응답(새 행 '
                  f'{len(inserted or [])}건)에 없음(이미 있던 기사이거나 응답 비어 있음)')
            return 0
        saved, err = _upsert_rows('urgency_rule_verdicts', rows, SENTENCE_CHUNK,
                                  on_conflict='rule_id,sentence_rev,news_id', ignore_duplicates=True)
        if not saved:
            print(f'[문장 판정] 저장 실패(무시): {err}')
            return 0
        by = {}
        for r in saved:
            by[r['status']] = by.get(r['status'], 0) + 1
        print(f'[문장 판정] 기록 {len(saved)}건 저장(' + ', '.join(f'{k} {v}' for k, v in sorted(by.items())) + ')'
              + (f' · 일부 실패(무시): {err}' if err else ''))
        return len(saved)
    except Exception as e:
        print(f'[문장 판정] 저장 실패(무시): {str(e)[:120]}')
        return 0


def process_open_sentence_verdicts() -> None:
    """매 실행(새 기사가 없어도) — ① 대기 행 판정(_process_open_sentence_rows — 이번 실행 새 기사의 대기 행 포함)
    ② 팀별 월 비용 알림(_sentence_budget_alert). main()이 긴급 알림·구독자 큐 **뒤**, heartbeat 앞에서 부른다 — 판정이
    느려도 알림을 늦추지 않는다. 둘 다 fail-open."""
    try:
        _process_open_sentence_rows()
    except Exception as e:
        print(f'[문장 판정] 대기 처리 실패(무시 — 대기 행은 그대로, 다음 실행에서 다시): {str(e)[:120]}')
    try:
        _sentence_budget_alert()
    except Exception as e:
        print(f'[문장 판정] 비용 점검 실패(무시): {str(e)[:120]}')


# requested_by(#252) — 수집 경로(null)의 판정만 늦은 팀 알림 후보가 된다(대시보드 요청·재판정은 화면만)
_OPEN_VERDICT_COLS = 'rule_id,sentence_rev,news_id,team_id,status,attempts,created_at,requested_by'
# 늦은 팀 알림 후보(#252, run_audience_alerts 'late') — 대기 처리가 이번 실행에 **참(verdict=true)**으로 저장한 판정 중 원 요청이
# 수집 경로(requested_by null)인 것 → {team_id: {news_id: {rule_id: 판정 행 created_at}}}. late 단계는 여기에 더해 ① 판정 행이
# 기사 저장 뒤 LATE_COLLECT_MAX_GAP_MIN 안에 생겼고 ② _rewrite_team_rows 뒤 그 팀 행이 source='rule'이며 rule_id가 그 문장
# 규칙일 때만 알린다(실장은 그 팀이 최고 등급을 본 팀일 때만). 대시보드 규칙 저장·재적용·재판정·되살림·관리자 공통 등급
# 수정으로 생긴 팀 등급은 알림 없음(화면에만 — 설계 B-2·E5).
_LATE_ALERT_PAIRS: dict = {}
_RULE_ID_RE = re.compile(r'[a-z0-9_]+')    # 표 CHECK urgency_rules_id_check와 같은 모양 — or 필터 글에 그대로 넣어도 안전
_NEWS_LIGHT_COLS = 'id,title,screen_text,summary'                   # 낱말 확인만(본문 없이)
_NEWS_JUDGE_COLS = 'id,title,screen_text,summary,content,urgency'   # 판정·팀 결정


def _fetch_news(ids, cols: str) -> dict:
    """news_feed를 id로 SENTENCE_ID_CHUNK씩 읽는다 → {id: 행}. id가 없으면 조회 0번."""
    out = {}
    ids = sorted({i for i in ids if i})
    for i in range(0, len(ids), SENTENCE_ID_CHUNK):
        for n in sb.table('news_feed').select(cols).in_('id', ids[i:i + SENTENCE_ID_CHUNK]).execute().data or []:
            out[n.get('id')] = n
    return out


def _stale_revival_rows(enabled: dict) -> list:
    """되살림 후보(#251 보강) — 켜진 문장 규칙의 **지금 판** stale 행(**새것부터** ≤SENTENCE_OPEN_LIMIT — 낱말이 끝내 안 걸리는
    옛 stale 행이 한도를 채워 새 후보를 밀어내지 않게). stale 행은 PK(규칙·판·기사)를 차지해 브라우저의 새 요청
    (ignoreDuplicates)을 막는다 — 규칙을 껐다가 같은 문장으로 다시 켜거나 낱말을 고쳐 기사가 다시 걸리게 되면 여기서
    되살려야 그 기사가 판정된다. 옛 판 stale은 되살리지 않는다(질문이 바뀌었다). failed도 되살리지 않는다(최종 — 다시 묻게
    하려면 관리자가 SQL로 status='pending', attempts=0, created_at=now() — created_at을 안 바꾸면 3일 기한에 곧바로 다시 failed).
    켜진 문장 규칙이 없으면 조회 0번, 있으면 1번. (규칙, 지금 판) 쌍으로 거른다 — 규칙 id만(in_)으로 받으면 문장을 고친
    규칙의 옛 판 행(영원히 stale)이 한도를 채운다. 조회 실패는 빈 목록(대기 행 처리는 계속)."""
    cur = {rid: _rev_of(r) for rid, r in enabled.items()
           if isinstance(rid, str) and _RULE_ID_RE.fullmatch(rid) and urgency_rules.has_sentence(r)}
    if not cur:
        return []
    pairs = ','.join(f'and(rule_id.eq.{rid},sentence_rev.eq.{rev})' for rid, rev in sorted(cur.items()))
    try:
        return sb.table('urgency_rule_verdicts').select(_OPEN_VERDICT_COLS).eq('status', 'stale').or_(pairs) \
            .order('created_at', desc=True).limit(SENTENCE_OPEN_LIMIT).execute().data or []
    except Exception as e:
        print(f'[문장 판정] 되살림 조회 실패(무시 — 대기 행 처리는 계속): {str(e)[:120]}')
        return []


def _rev_bump_catchup(enabled: dict, team_rules: dict, now, now_iso: str) -> list:
    """판 올림 재요청(Fable 재검토 #251) — 문장을 고쳐 판이 오른 규칙의 **옛 판** 기사 중 지금 판 행이 없는 기사에 지금 판 대기 행을
    넣는다. 브라우저의 저장 즉시 재적용은 그 화면이 불러온 기사만 요청하므로 ① 페이지를 연 뒤 수집된 기사(지금 판 요청 없음)
    ② 이 실행의 규칙 사본이 옛 판일 때 수집·판정된 기사(옛 판으로 판정·고정)는 판이 올라도 새 판정이 영영 안 생기고, 옛 판이 만든
    rule 행이 다음 규칙 저장까지 남았다.
    대상 규칙 = 켜진 문장 규칙 중 판 > 0이고 updated_at이 SENTENCE_REV_CATCHUP_DAYS 안인 것(updated_at은 아무 수정에도 갱신되지만
    지금 판 행이 이미 있으면 넣을 것이 없어 무해). 규칙마다 그 기간 안에 생긴 판정 행(모든 상태·모든 판)을 PK 순으로 페이지 조회 →
    지금 판 행이 없는 옛 판 기사 → 본문 없이 기사를 읽어 **지금 낱말이 걸리는 것만** → pending(created_at 지금, attempts 0,
    requested_by = SENTENCE_REQUEUE_BY). ignore_duplicates — 그사이 브라우저가 넣은 행은 그대로. 반환 = 넣은 행(대기 행 모양 —
    부르는 쪽이 이번 처리에 넣는다). 조회·저장 실패는 로그만(다음 실행에서 다시). 대상 규칙이 없으면 조회 0번."""
    cut = now - timedelta(days=SENTENCE_REV_CATCHUP_DAYS)
    targets = []
    for rid in sorted(k for k in (enabled or {}) if isinstance(k, str)):
        r = enabled[rid]
        rev = _rev_of(r)
        if rev <= 0 or not _RULE_ID_RE.fullmatch(rid) or not urgency_rules.has_sentence(r) \
                or not team_rules.get(r.get('team_id')):
            continue
        upd = _parse_ts(r.get('updated_at'))
        if upd is None or upd < cut:
            continue
        targets.append((rid, rev, r))
    if not targets:
        return []
    out = []
    for rid, rev, r in targets:
        try:
            have, old, lo, page = set(), set(), 0, 1000
            while True:
                data = sb.table('urgency_rule_verdicts').select('news_id,sentence_rev').eq('rule_id', rid) \
                    .gte('created_at', cut.isoformat()).order('rule_id').order('sentence_rev').order('news_id') \
                    .range(lo, lo + page - 1).execute().data or []
                for x in data:
                    nid, xr = x.get('news_id'), x.get('sentence_rev')
                    if not nid or not isinstance(xr, int) or isinstance(xr, bool):
                        continue
                    if xr == rev:
                        have.add(nid)
                    elif xr < rev:
                        old.add(nid)
                if len(data) < page:
                    break
                lo += page
            missing = sorted(old - have)
            if not missing:
                continue
            light = _fetch_news(missing, _NEWS_LIGHT_COLS)
            for nid in missing:
                n = light.get(nid)
                if not n:
                    continue
                snippet = urgency_rules.rule_input_text(n.get('screen_text'), n.get('summary')) or ''
                if not urgency_rules.match_urgency_rules([r], n.get('title') or '', snippet):
                    continue                     # 지금 낱말이 안 걸리는 기사 — 판정해도 쓰이지 않는다(낱말 = 1차 거름)
                out.append(dict(_verdict_row(rid, rev, r.get('team_id'), 'pending'), news_id=nid,
                                requested_by=SENTENCE_REQUEUE_BY, created_at=now_iso))
        except Exception as e:
            print(f'[문장 판정] 판 올림 재요청 조회 실패(무시 — 다음 실행에서 다시) {rid}: {str(e)[:120]}')
    if not out:
        return []
    saved, err = _upsert_rows('urgency_rule_verdicts', out, SENTENCE_CHUNK, on_conflict='rule_id,sentence_rev,news_id',
                              ignore_duplicates=True)
    if err:
        print(f'[문장 판정] 판 올림 재요청 저장 일부 실패(무시 — 다음 실행에서 다시): {err}')
    if saved:
        print(f'[문장 판정] 판 올림 재요청 {len(saved)}건({len({s["rule_id"] for s in saved})}규칙)'
              ' — 문장을 고친 뒤 브라우저 재적용이 못 본 옛 판 기사')
    return saved


def _process_open_sentence_rows() -> dict:
    """대기 행(pending — 이번 실행 새 기사·대시보드가 넣은 지난 기사 요청 / wait_body — 본문 대기)을 판정한다.
    대기 행은 **새것부터** 읽는다(≤SENTENCE_OPEN_LIMIT) — 지난 기사 요청이 많이 밀려 있어도 이번 실행 새 기사의 대기 행이
    창 안에 들어와 같은 실행에서 판정된다(실행당 상한도 먼저 쓴다).
    대기 행이 없고 이번 실행에 규칙을 아직 안 읽었으면(새 기사 없던 실행) 조회 1번으로 끝(로그 없음) — 되살림 조회도
    규칙을 읽는 다음 실행으로 미룬다(되살림만 하려고 규칙 표를 읽지 않는다). 순서:
      ⓪-1 판 올림 재요청(_rev_bump_catchup, Fable 재검토 #251): 문장을 고친 규칙의 옛 판 기사 중 지금 판 행이 없는 것에 지금 판
         대기 행(requested_by = SENTENCE_REQUEUE_BY)을 넣고 이번 처리의 대기 행에 더한다(늦은 팀 알림 후보는 아니다)
      ⓪ 되살림(_stale_revival_rows): 켜진 문장 규칙의 지금 판 stale 행 → 본문 없이 기사를 읽어 지금 낱말이 걸리는 것만 →
         pending으로 먼저 저장(시도 수 유지, created_at = 지금 — 3일 기한은 되살린 때부터 센다)하고 이번 처리에 대기 행처럼
         넣는다(실행당 상한·시간 예산에 포함). 여전히 낱말이 안 걸리면 stale 그대로(쓰기 없음), 시도가 이미 다 찼으면 failed.
      ① 규칙이 없거나 꺼졌거나 문장이 없거나 판이 바뀜 → stale / 시도 SENTENCE_MAX_ATTEMPTS번·SENTENCE_OPEN_MAX_DAYS일 초과 → failed
         (규칙 표 조회 실패·그 팀 규칙 형식 오류로 이번 실행에서 빠진 팀은 **손대지 않는다** — 일시 장애로 굳히지 않는다)
         단 **이 실행이 규칙을 읽은 뒤에 생긴 행**(_RULES_LOADED_AT − SENTENCE_SNAPSHOT_MARGIN_S 이후)은 사본이 '안 맞다'고 해도
         stale로 만들지 않고 그대로 둔다 — 사본 뒤의 새 규칙(판 올림·다시 켬·낱말 수정) 때문에 들어온 요청일 수 있다(다음 실행의
         새 사본으로 본다). 사본과 맞으면 그대로 판정한다(이번 실행 새 기사의 대기 행이 그렇다).
      ② 지금 규칙의 낱말이 그 기사(제목 + rule_input_text)에 안 걸리면 stale — 낱말이 1차 거름이자 비용 상한이다(①과 같은 예외)
      ③ pending은 지금 판정(본문 있으면 body, 없으면 검색 요약 snippet·제목 title), wait_body는 본문이 들어왔거나
         SENTENCE_WAIT_BODY_HOURS가 지났을 때만(그 전에는 그대로 둔다)
      ④ 판정 기록을 전체 행으로 upsert(PK 충돌 = 갱신) — 실행당 상한·시간 예산·호출 장애로 못 보낸 몫은 손대지 않는다(다음 실행)
      ⑤ 판정이 저장된 (기사, 팀)의 team_urgency rule 행을 지금 결정과 맞춘다(_rewrite_team_rows — human·ai 행은 불가침).
    판정 순서(Fable 재검토 #251): 수집 경로 대기 행(requested_by null — 이번 실행 새 기사·본문 대기) → 대시보드 요청·재요청 →
    되살림, 층 안에서는 규칙별 묶음. 규칙 묶음 순서로만 돌리면 지난 기사 요청 500건이 든 규칙이 실행당 상한을 다 써 다른 팀의
    새 기사 판정(늦은 팀 알림)이 몇 실행 밀린다."""
    t0 = time.monotonic()
    rows = sb.table('urgency_rule_verdicts').select(_OPEN_VERDICT_COLS) \
        .in_('status', ['pending', 'wait_body']).order('created_at', desc=True).limit(SENTENCE_OPEN_LIMIT) \
        .execute().data or []
    if not rows and _TEAM_RULES_ENABLED is None:
        return {}                            # 대기 행 없음 + 규칙을 안 읽음(또는 표 조회 실패) — 조회 1번으로 끝
    team_rules = load_team_urgency_rules()   # 이미 읽었으면 캐시(조회 0번)
    enabled = _TEAM_RULES_ENABLED
    if enabled is None:
        print(f'[문장 판정] 대기 {len(rows)}건 처리 건너뜀 — 규칙 표 조회 실패(대기 행은 그대로, 다음 실행에서 다시)')
        return {}
    stale_rows = _stale_revival_rows(enabled)
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    # ⓪-1 판 올림 재요청 — 이미 대기 행에 있는 (규칙·판·기사)는 더하지 않는다(같은 PK가 한 upsert에 두 번 들어가면 오류)
    seen = {(x.get('rule_id'), x.get('sentence_rev'), x.get('news_id')) for x in rows}
    requeued = [x for x in _rev_bump_catchup(enabled, team_rules, now, now_iso)
                if (x['rule_id'], x['sentence_rev'], x['news_id']) not in seen]
    rows = rows + requeued
    if not rows and not stale_rows:
        return {}
    snap = (_RULES_LOADED_AT - timedelta(seconds=SENTENCE_SNAPSHOT_MARGIN_S)) if _RULES_LOADED_AT else None
    st = {'open': len(rows), 'judged': 0, 'true': 0, 'kept': 0, 'stale': 0, 'nohit': 0, 'failed': 0, 'retry': 0,
          'left': 0, 'skipped': 0, 'ins': 0, 'upd': 0, 'del': 0, 'cost': 0.0, 'revived': 0, 'requeued': len(requeued)}
    updates, todo = [], []
    for row in rows:
        rid, rev, tid = row.get('rule_id'), row.get('sentence_rev'), row.get('team_id')
        attempts = _as_int(row.get('attempts'))
        created = _parse_ts(row.get('created_at'))
        after_snap = bool(snap and created and created >= snap)
        r = enabled.get(rid)
        if r is None or not urgency_rules.has_sentence(r) or _rev_of(r) != rev or r.get('team_id') != tid:
            if after_snap:                   # 규칙을 읽은 뒤 들어온 요청 — 사본보다 새 규칙 때문일 수 있다, 다음 실행에서 본다
                st['skipped'] += 1
                continue
            updates.append(dict(_verdict_row(rid, rev, tid, 'stale', attempts=attempts), news_id=row.get('news_id')))
            st['stale'] += 1
            continue
        age_h = (now - created).total_seconds() / 3600 if created else None
        if attempts >= SENTENCE_MAX_ATTEMPTS or (age_h is not None and age_h > SENTENCE_OPEN_MAX_DAYS * 24):
            updates.append(dict(_verdict_row(rid, rev, tid, 'failed', attempts=attempts), news_id=row.get('news_id')))
            st['failed'] += 1
            continue
        if not team_rules.get(tid):          # 켜져 있지만 그 팀 규칙이 이번 실행에서 빠졌다(형식 오류) — 손대지 않는다
            st['skipped'] += 1
            continue
        todo.append({'row': row, 'rule': r, 'age_h': age_h, 'attempts': attempts, 'after_snap': after_snap})
    # 늦은 팀 알림 후보(#252) — requested_by 칸을 **받았고** 값이 null인 대기 행(이번 실행 되살림은 아래 revive라 빠진다) →
    # 판정 행 created_at을 함께 넘긴다: late 단계가 '기사 created_at + LATE_COLLECT_MAX_GAP_MIN 안에 생긴 요청'만 수집 경로로
    # 본다(되살림·관리자 SQL 재대기는 requested_by null인 채 created_at만 지금으로 바뀌어 다음 실행에 수집 경로로 둔갑한다).
    collect_req = {(t['row'].get('rule_id'), t['row'].get('sentence_rev'), t['row'].get('news_id')): t['row'].get('created_at')
                   for t in todo if 'requested_by' in t['row'] and t['row']['requested_by'] is None}
    # ⓪ 되살림 후보 — 판·팀을 다시 확인하고, 본문 없이 기사를 읽어 지금 낱말이 걸리는 것만 남긴다
    revive = []
    for row in stale_rows:
        rid, rev, tid = row.get('rule_id'), row.get('sentence_rev'), row.get('team_id')
        r = enabled.get(rid)
        if r is None or not urgency_rules.has_sentence(r) or _rev_of(r) != rev or r.get('team_id') != tid \
                or not team_rules.get(tid):
            continue                         # 옛 판·다른 팀·이번 실행에서 빠진 팀 — stale 그대로
        revive.append({'row': row, 'rule': r, 'age_h': 0.0, 'attempts': _as_int(row.get('attempts'))})
    light = _fetch_news([t['row'].get('news_id') for t in revive], _NEWS_LIGHT_COLS) if revive else {}
    revive_ok = []
    for t in revive:
        row = t['row']
        n = light.get(row.get('news_id'))
        if not n:
            continue
        snippet = urgency_rules.rule_input_text(n.get('screen_text'), n.get('summary')) or ''
        if not urgency_rules.match_urgency_rules([t['rule']], n.get('title') or '', snippet):
            continue                         # 여전히 낱말 안 걸림 — stale 그대로(쓰기 없음)
        if t['attempts'] >= SENTENCE_MAX_ATTEMPTS:
            updates.append(dict(_verdict_row(row.get('rule_id'), row.get('sentence_rev'), row.get('team_id'), 'failed',
                                             attempts=t['attempts']), news_id=row.get('news_id')))
            st['failed'] += 1
            continue
        revive_ok.append(t)
    # 본문까지 읽는 것은 대기 행 + 낱말이 걸린 되살림 후보만
    news = _fetch_news([t['row'].get('news_id') for t in todo + revive_ok], _NEWS_JUDGE_COLS) \
        if (todo or revive_ok) else {}
    jobs = []
    for t in todo:
        row = t['row']
        n = news.get(row.get('news_id'))
        if not n:                            # 기사가 지워지는 중(cascade로 이 행도 사라진다) — 손대지 않는다
            st['skipped'] += 1
            continue
        snippet = urgency_rules.rule_input_text(n.get('screen_text'), n.get('summary')) or ''
        if not urgency_rules.match_urgency_rules([t['rule']], n.get('title') or '', snippet):
            if t['after_snap']:              # 사본 뒤 낱말 수정 때문에 들어온 요청일 수 있다 — 다음 실행에서 본다
                st['skipped'] += 1
                continue
            # 지금 규칙의 낱말이 안 걸리는 기사(낱말을 고쳤거나 요약이 바뀜) — 판정해도 쓰이지 않는다. 문장 판정은 낱말이
            # 걸린 기사에만(지침 do-not #251 — 낱말 = 1차 거름이자 비용 상한). 입력 글은 대시보드와 같은 rule_input_text.
            updates.append(dict(_verdict_row(row.get('rule_id'), row.get('sentence_rev'), row.get('team_id'), 'stale',
                                             attempts=t['attempts']), news_id=row.get('news_id')))
            st['nohit'] += 1
            continue
        body = _sentence_body(n.get('content'))
        if row.get('status') == 'wait_body' and not body and \
                t['age_h'] is not None and t['age_h'] < SENTENCE_WAIT_BODY_HOURS:
            st['kept'] += 1                  # 아직 본문 대기 — 재수집(lampmanH-pc 10분마다)을 기다린다
            continue
        kind = 'body' if body else ('snippet' if _ws(snippet) else 'title')
        jobs.append(dict(t, title=n.get('title') or '', snippet=snippet, body=body, kind=kind))
    revivals, revived_jobs = [], []
    for t in revive_ok:
        row = t['row']
        n = news.get(row.get('news_id'))
        if not n:
            continue
        snippet = urgency_rules.rule_input_text(n.get('screen_text'), n.get('summary')) or ''
        # created_at = 지금 — 옛 요청 시각 그대로면 다음 실행의 3일 기한에 판정 전 failed가 된다(requested_by는 보내지 않아 보존)
        revivals.append(dict(_verdict_row(row.get('rule_id'), row.get('sentence_rev'), row.get('team_id'), 'pending',
                                          attempts=t['attempts']), news_id=row.get('news_id'), created_at=now_iso))
        body = _sentence_body(n.get('content'))
        kind = 'body' if body else ('snippet' if _ws(snippet) else 'title')
        revived_jobs.append(dict(t, title=n.get('title') or '', snippet=snippet, body=body, kind=kind, revived=True))
    # 되살림은 판정 전에 먼저 저장 — 저장 못 한 것은 이번에 판정하지 않는다(stale 그대로, 다음 실행에서 다시)
    saved_rev, err = _upsert_rows('urgency_rule_verdicts', revivals, SENTENCE_CHUNK,
                                  on_conflict='rule_id,sentence_rev,news_id')
    if err:
        print(f'[문장 판정] 되살림 저장 실패(무시 — stale 그대로, 다음 실행에서 다시): {err}')
    rev_keys = {(r['rule_id'], r['sentence_rev'], r['news_id']) for r in saved_rev}
    for j in revived_jobs:                   # 대기 행 뒤에 붙인다 — 실행당 상한·시간 예산은 대기 행이 먼저 쓴다
        if (j['row'].get('rule_id'), j['row'].get('sentence_rev'), j['row'].get('news_id')) in rev_keys:
            jobs.append(j)
    st['revived'] = len(rev_keys)
    client = _sentence_client() if jobs else None
    # 판정 순서(Fable 재검토 #251): ⓐ 수집 경로 대기 행(requested_by null) → ⓑ 대시보드 요청·판 올림 재요청 → ⓒ 되살림.
    # 층 안에서는 규칙별 묶음(처음 나온 순서 = 새것부터). 실행당 상한·시간 예산은 앞 층이 먼저 쓴다.
    tiers = ({}, {}, {})
    for j in jobs:
        tier = 2 if j.get('revived') else (0 if j['row'].get('requested_by') is None else 1)
        tiers[tier].setdefault(j['rule']['id'], []).append(j)
    for grp in [g for by_rule in tiers for g in by_rule.values()]:
        sentence = (grp[0]['rule'].get('sentence') or '').strip()
        for j, res in zip(grp, _judge_jobs(client, sentence, grp, t0)):
            row = j['row']
            out = _result_row(row.get('rule_id'), row.get('sentence_rev'), row.get('team_id'), res, j['kind'],
                              j['attempts'], now_iso)
            if out is None:
                st['left'] += 1              # 상한·시간·키 없음·호출 장애 — 그대로 두고 다음 실행
                continue
            out['news_id'] = row.get('news_id')
            updates.append(out)
            if out['status'] == 'done':
                st['judged'] += 1
                st['true'] += int(out['verdict'])
            elif out['status'] == 'failed':
                st['failed'] += 1
            else:
                st['retry'] += 1
    saved, err = _upsert_rows('urgency_rule_verdicts', updates, SENTENCE_CHUNK,
                              on_conflict='rule_id,sentence_rev,news_id')
    if err:
        print(f'[문장 판정] 대기 행 갱신 일부 실패(무시 — 다음 실행에서 다시): {err}')
    _add_run_cost(saved)
    pairs = {}
    for u in saved:
        if u['status'] == 'done':
            st['cost'] += u['cost_usd']
            pairs.setdefault(u['team_id'], set()).add(u['news_id'])
            k = (u['rule_id'], u['sentence_rev'], u['news_id'])
            if u.get('verdict') is True and k in collect_req:        # 참 판정만 — 거짓은 새 팀 등급을 만들지 않는다
                _LATE_ALERT_PAIRS.setdefault(u['team_id'], {}).setdefault(u['news_id'], {})[u['rule_id']] = collect_req[k]
    if pairs:
        try:
            st['ins'], st['upd'], st['del'] = _rewrite_team_rows(pairs, news, team_rules)
        except Exception as e:
            print(f'[문장 판정] 팀 행 다시 쓰기 실패(무시): {str(e)[:120]}')
    if not rows and not st['revived'] and not updates:
        return st                            # 되살림 후보만 있었고 하나도 안 걸림 — 매 실행 같은 줄을 찍지 않는다
    print(f"[문장 판정] 대기 처리 — 대기 {st['open']}건 → 판정 {st['judged']}건(해당 {st['true']}) · 본문 대기 유지 {st['kept']}건"
          f" · 판 바뀜·꺼짐 {st['stale']}건 · 낱말 안 걸림 {st['nohit']}건 · 실패 확정 {st['failed']}건"
          f" · 재시도 {st['retry']}건 · 다음 실행 {st['left']}건"
          f" · 팀 행 +{st['ins']}/~{st['upd']}/-{st['del']} · ${st['cost']:.4f}"
          + (f" · 되살림 {st['revived']}건" if st['revived'] else '')
          + (f" · 판 올림 재요청 {st['requeued']}건" if st['requeued'] else '')
          + (f" · 건너뜀 {st['skipped']}건" if st['skipped'] else ''))
    return st


def _rewrite_team_rows(pairs: dict, news: dict, team_rules: dict) -> tuple:
    """판정이 새로 저장된 (팀 → 기사들)의 team_urgency rule 행을 지금 결정과 맞춘다(#251). 반환 (넣은 행, 고친 행, 지운 행).
    결정 = team_rule_decision_judged(그 팀의 켜진 규칙, 제목, rule_input_text(screen_text, summary), 공통값 news_feed.urgency,
    그 기사의 done 판정 전부) — 대시보드 재적용과 같은 입력. 쓰기 규칙:
      · human(팀원 수정)·ai 행은 **절대 건드리지 않는다**(설계안 §10 human > rule)
      · 결정이 바뀐 rule 행은 **그 자리에서 고친다**(update … source='rule' 조건) — 지웠다 넣으면 그 사이 화면·알림이 공통값으로
        비고, 그 틈에 사람이 고친 행을 덮을 수 있다
      · 결정이 새로 생긴 기사는 ignore_duplicates로 넣는다(그 사이 사람이 만든 행을 덮지 않는다)
      · 결정이 없어진 rule 행만 지운다(source='rule' 조건)
    쓰기마다 재시도(retry_util), 넣기 묶음이 실패하면 한 행씩(도중에 지워진 기사의 FK 오류 행만 빠진다).
    늦게 생긴·바뀐 rule 행은 세션 B 팀별 알림 대조 대상(설계안 §10-2)."""
    ids = sorted({nid for s in pairs.values() for nid in s})
    by_news, existing = {}, {}
    for i in range(0, len(ids), SENTENCE_ID_CHUNK):
        chunk = ids[i:i + SENTENCE_ID_CHUNK]
        for v in sb.table('urgency_rule_verdicts').select('rule_id,sentence_rev,news_id,verdict') \
                .in_('news_id', chunk).eq('status', 'done').execute().data or []:
            by_news.setdefault(v.get('news_id'), []).append(v)
        for t in sb.table('team_urgency').select('news_id,team_id,source,rule_id,urgency') \
                .in_('news_id', chunk).execute().data or []:
            existing[(t.get('news_id'), t.get('team_id'))] = t
    ins, upd, dels = [], [], {}
    for tid in sorted(pairs):
        trules = team_rules.get(tid) or []
        for nid in sorted(pairs[tid]):
            n = news.get(nid)
            if not n or not trules:
                continue
            dec = urgency_rules.team_rule_decision_judged(
                trules, n.get('title') or '', urgency_rules.rule_input_text(n.get('screen_text'), n.get('summary')),
                n.get('urgency'), urgency_rules.verdict_map(by_news.get(nid)))
            ex = existing.get((nid, tid))
            if ex and ex.get('source') != 'rule':
                continue                     # human(팀원 수정)·ai — 불가침
            if ex and dec:
                if ex.get('rule_id') != dec['rule_id'] or ex.get('urgency') != dec['level']:
                    upd.append((nid, tid, dec))
            elif ex:
                dels.setdefault(tid, []).append(nid)
            elif dec:
                ins.append({'news_id': nid, 'team_id': tid, 'urgency': dec['level'], 'source': 'rule',
                            'rule_id': dec['rule_id']})
    n_upd = n_del = 0
    errs = []
    for nid, tid, dec in upd:
        try:
            _db_retry(lambda n_=nid, t_=tid, d_=dec: sb.table('team_urgency')
                      .update({'urgency': d_['level'], 'rule_id': d_['rule_id']})
                      .eq('news_id', n_).eq('team_id', t_).eq('source', 'rule').execute(), 'team_urgency')
            n_upd += 1
        except Exception as e:
            errs.append(str(e)[:120])
    for tid, nids in dels.items():
        for i in range(0, len(nids), SENTENCE_ID_CHUNK):
            part = nids[i:i + SENTENCE_ID_CHUNK]
            try:
                _db_retry(lambda p=part, t_=tid: sb.table('team_urgency').delete().eq('team_id', t_)
                          .eq('source', 'rule').in_('news_id', p).execute(), 'team_urgency')
                n_del += len(part)
            except Exception as e:
                errs.append(str(e)[:120])
    saved, err = _upsert_rows('team_urgency', ins, TEAM_URGENCY_CHUNK, on_conflict='news_id,team_id',
                              ignore_duplicates=True)
    if err:
        errs.append(err)
    if errs:
        print(f'[문장 판정] 팀 행 쓰기 일부 실패(무시 — 도중에 지워진 기사 등) {len(errs)}건: {errs[0]}')
    return len(saved), n_upd, n_del


def _sentence_budget_config():
    """(기준 금액, 알림 표시 {"<team_id>": "YYYY-MM"}) — app_config 두 키를 **한 번에** 읽는다. 값이 없거나 이상하면 기준은
    SENTENCE_BUDGET_USD, 표시는 {}. 조회 자체가 실패하면 None(이번 실행은 알림 점검을 건너뛴다 — 표시를 못 읽은 채 보내면
    같은 달에 두 번 갈 수 있다)."""
    try:
        rows = sb.table('app_config').select('key,value').in_('key', [_BUDGET_KEY, _BUDGET_MARK_KEY]) \
            .execute().data or []
    except Exception as e:
        print(f'[문장 판정] 비용 기준 조회 실패 — 이번 실행은 비용 알림 점검을 건너뜀: {str(e)[:80]}')
        return None
    cap, marks = SENTENCE_BUDGET_USD, {}
    for r in rows:
        if r.get('key') == _BUDGET_KEY:
            try:
                v = float(str(r.get('value') or '').strip())
                if 0 < v < float('inf'):
                    cap = v
            except ValueError:
                pass
        elif r.get('key') == _BUDGET_MARK_KEY:
            try:
                m = json.loads(r.get('value') or '{}')
                if isinstance(m, dict):
                    marks = {str(k): str(v) for k, v in m.items()}
            except ValueError:
                pass
    return cap, marks


def _team_month_cost(team_id, since_iso: str) -> float:
    """그 팀 판정 기록 중 judged_at ≥ since의 cost_usd 합계 — PostgREST 1,000행 상한 때문에 PK 정렬로 페이지를 넘긴다(#233)."""
    total, lo, page = 0.0, 0, 1000
    while True:
        data = sb.table('urgency_rule_verdicts').select('cost_usd').eq('team_id', team_id) \
            .gte('judged_at', since_iso).order('rule_id').order('sentence_rev').order('news_id') \
            .range(lo, lo + page - 1).execute().data or []
        total += sum(float(r.get('cost_usd') or 0) for r in data)
        if len(data) < page:
            return total
        lo += page


def _team_name(team_id) -> str:
    try:
        rows = sb.table('teams').select('id,name').eq('id', team_id).limit(1).execute().data
        if rows and rows[0].get('name'):
            return str(rows[0]['name'])
    except Exception:
        pass
    return f'팀 {team_id}'


def _sentence_budget_alert() -> int:
    """C4 — 이번 실행에 판정 비용이 생긴 팀만 본다: 이번 달(KST 1일 0시부터) 판정 비용 합계 ≥ 기준이고 그 팀의 알림 표시가
    이번 달이 아니면 운영자 텔레그램 1회 → **보낸 뒤에만** 표시(app_config sentence_rule_budget_alerted의 팀 = 'YYYY-MM')를
    남긴다(보내기가 실패하면 표시 없이 다음 실행에서 다시). 팀마다 달에 한 번. **판정은 멈추지 않는다**(운영자 결정).
    반환 = 보낸 알림 수."""
    teams = sorted((t for t, c in _SENTENCE_RUN_COST.items() if c > 0), key=str)
    if not teams:
        return 0
    cfg = _sentence_budget_config()
    if cfg is None:
        return 0
    cap, marks = cfg
    now_kst = datetime.now(KST)
    month = now_kst.strftime('%Y-%m')
    month_start = now_kst.replace(day=1, hour=0, minute=0, second=0, microsecond=0) \
        .astimezone(timezone.utc).isoformat()
    sent = 0
    for tid in teams:
        if marks.get(str(tid)) == month:
            continue                         # 이번 달 이미 알림
        total = _team_month_cost(tid, month_start)
        if total < cap:
            continue
        name = _team_name(tid)
        text = (f'⚠️ 팀 AI 문장 판정 비용\n{name}: 이번 달 ${total:.2f} — 기준 ${cap:.2f}를 넘었습니다(판정은 계속합니다).\n'
                '낱말이 너무 넓은 규칙이 없는지 「긴급도 설정 → 우리 팀」에서 확인해 주세요.')
        ok = notify.send_telegram(text, chat_id=TELEGRAM_CHAT_ID)
        print(f'[문장 판정] 비용 기준 넘김 — 팀 {tid} 이번 달 ${total:.2f} (기준 ${cap:.2f}) · 운영자 알림 '
              + ('발송' if ok else '실패(표시 없이 다음 실행에서 다시)'))
        if not ok:
            continue
        sent += 1
        marks[str(tid)] = month
        value = json.dumps(marks, ensure_ascii=False, sort_keys=True)
        try:
            _db_retry(lambda v=value: sb.table('app_config').upsert({'key': _BUDGET_MARK_KEY, 'value': v},
                                                                    on_conflict='key').execute(), 'app_config')
        except Exception as e:
            print(f'[문장 판정] 비용 알림 표시 저장 실패(다음 실행에서 한 번 더 갈 수 있음): {str(e)[:120]}')
    return sent


def generate_summary(title: str, source: str, published_at: str, content: str) -> str:
    """기사 본문을 Claude Haiku로 요약해 반환. 실패 시 빈 문자열."""
    if not ANTHROPIC_API_KEY or not content:
        return ''
    body_snippet = content.replace('\n', ' ').strip()[:3000]
    user_msg = (
        '다음 뉴스를 핵심 포인트 3~5개로 요약하세요.\n'
        '- 각 포인트를 줄바꿈으로 구분하세요.\n'
        '- 각 포인트는 1~2문장, 육하원칙(누가/무엇을/왜/어떻게) 포함.\n'
        '- 불릿 기호(•, -, * 등)는 붙이지 마세요. 순수 텍스트만.\n\n'
        f'제목: {title}\n출처: {source}\n날짜: {str(published_at)[:10]}\n\n본문:\n{body_snippet}'
    )
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=500,
            system='당신은 전파·통신 정책 뉴스를 간결하게 요약하는 전문가입니다. 사실만 기반으로 핵심 포인트를 줄바꿈으로 구분하여 작성하세요. 불릿 기호 없이 텍스트만 출력하세요.',
            messages=[{'role': 'user', 'content': user_msg}]
        )
        return (resp.content[0].text or '').strip() if resp.content else ''
    except Exception as e:
        print(f'[요약 오류] {title[:30]}: {e}')
        return ''


# ═══════════════════════════════════════════════════════
#  텔레그램 알림 (긴급 기사 전용)
# ═══════════════════════════════════════════════════════

#  분야 태그 한글 라벨 — **운영자 알림 전용** (운영자 지시 2026-08-03).
#  구독자(팀원) 메시지에는 칩을 붙이지 않는다: 태그가 틀렸을 때 팀원은 고칠 방법이 없어
#  신뢰만 깎이고, 판정 품질은 운영자가 감시하는 것이 맞다. 태그는 구독자 쪽에서 여전히
#  '누구에게 보낼지' 필터로만 쓰인다(send-subscriber-briefing).
#  라벨 원본은 supabase/functions/_shared/news_tags.ts — 사본이므로 같이 고칠 것.
#  · 최대 3개를 자르지 않고 **전부** 보여준다(구독자용 pickChips는 2개 상한). 과다 부착도
#    운영자가 봐야 할 품질 신호이기 때문이다.
#  · 태그가 없으면 '미판정' — 안전망(_spectrum_safety_net)까지 지나고도 빈 것이라
#    프롬프트를 손봐야 한다는 뜻이므로 조용히 넘기면 안 된다.
TAG_LABELS_KO = {
    'spectrum': '주파수·망', 'market': '요금·시장', 'regulation': '규제·제재',
    'security': '보안·정보', 'ai': 'AI',
}


def tag_labels(tags) -> str:
    """태그 slug 목록 → 운영자 알림용 한글 문자열. 빈 값이면 '미판정'."""
    if not isinstance(tags, list) or not tags:
        return '미판정'
    # 모르는 slug는 그대로 노출한다 — 조용히 버리면 사본 드리프트를 못 알아챈다.
    return ' · '.join(TAG_LABELS_KO.get(str(t), str(t)) for t in tags)


REMIND_AFTER_H = 24          # 사건 대표가 이 시간을 넘으면 재보도 1건을 리마인드로 통과(#181)
REMIND_MIN_SHARE = 0.5       # 리마인드 문턱(#256) — 그 사건의 3일 창 기사 중 이 채널 등급(공통 = 긴급) 비율이 이 미만이면 보류
REMIND_HOLD_MARK = '[리마인드보류]'   # 보류 기록의 shared_keywords 접두 — '[리마인드]'로 시작하지 않아 사슬·사내 다리가 '미발송'으로 읽는다
ALERT_CHAIN_DAYS = 10        # 억제 사슬 조회 창(일)
ALERT_PAGE = 1000            # PostgREST 요청당 상한 — 사슬·비교군 조회는 order + range 페이지(#66·#233)

# group_same_event 메모(#252) — 한 실행 안에서 같은 제목 목록(tuple)이면 앞 결과를 그대로 쓴다(Haiku 호출 0).
# 공통 포장과 받는 단위별 계산이 같이 쓴다 — 단위의 입력이 공통과 같으면 같은 판정·같은 비용 0.
_GROUP_MEMO: dict = {}
# 공통 포장(suppress_repeat_alerts)의 마지막 결과 — 받는 단위 '긴급' 채널의 복사 지름길이 쓴다(#252).
# {'urls': 입력 url 목록(순서), 'reps', 'sup_rows', 'remind_rows', 'fail_open'} 또는 None(이번 실행에 안 불림).
_COMMON_ALERT = None


def _group_same_event_memo(titles, timeout=None, max_retries=None, counter=None):
    """news_dedup.group_same_event(제목들, 키)의 실행 내 메모. 실패(None)도 메모한다 — 같은 입력에 같은 결과.
    공통 포장은 인자 없이 부른다(종전과 같은 호출). 받는 단위별 알림은 timeout·max_retries(짧은 제한)와 counter([n] —
    메모에 없어 실제로 나간 호출 수, 비용 관측)를 넘긴다."""
    key = tuple(titles)
    if key not in _GROUP_MEMO:
        import news_dedup
        if timeout is None and max_retries is None:
            _GROUP_MEMO[key] = news_dedup.group_same_event(list(titles), ANTHROPIC_API_KEY)
        else:
            _GROUP_MEMO[key] = news_dedup.group_same_event(list(titles), ANTHROPIC_API_KEY,
                                                           timeout=timeout, max_retries=max_retries)
        if counter is not None and len(titles) >= 2:
            counter[0] += 1
    got = _GROUP_MEMO[key]
    return [list(g) for g in got] if got else got


def _fetch_pages(make_query, page: int = ALERT_PAGE) -> list:
    """make_query() = 정렬까지 건 새 쿼리. range로 끝까지 읽는다(PostgREST 1,000행 상한, #53·#233)."""
    out, lo = [], 0
    while True:
        data = make_query().range(lo, lo + page - 1).execute().data or []
        out.extend(data)
        if len(data) < page:
            return out
        lo += page


def _prior_entries(rows, exclude_urls) -> tuple:
    """비교군 행(title·url·created_at, **최신순**) → (prior [{'title', 'kw'}], prior_at {제목: 가장 최근 created_at}).
    exclude_urls(이번 후보 — 자기 자신과 비교 방지)는 뺀다. 공통 포장과 받는 단위별 계산이 같이 쓴다."""
    from news_dedup import extract_keywords
    prior, prior_at = [], {}
    for r in rows or []:
        if r.get('url') not in exclude_urls:
            prior.append({'title': r.get('title') or '', 'kw': extract_keywords(r.get('title') or '')})
            prior_at.setdefault(r.get('title') or '', r.get('created_at'))   # 정렬이 최신순 = 가장 최근 것
    return prior, prior_at


def _chain_from_suppress_log(rows) -> dict:
    """alert_suppress_log 행(오래된 것부터) → 억제 사슬 {억제된 제목: 그때 걸린 기존 제목}. 리마인드는 '나간 기사'라 사슬을 끊는다."""
    sup_chain = {}
    for r in rows or []:
        if str(r.get('shared_keywords') or '').startswith('[리마인드]'):
            continue                 # 리마인드는 '나간 기사' — 사슬을 끊는다
        if r.get('article_title'):
            sup_chain[r['article_title']] = r.get('matched_title') or ''
    return sup_chain


def _event_share_fn(rows, is_keep):
    """리마인드 문턱(#256)용 — (후보 제목, 걸린 기보도 제목) → (이 채널 등급인 기사 수, 그 사건 기사 수).
    사건 = rows(3일 창 전체, 등급 무관) 중 두 제목 가운데 하나와 키워드 3개 이상을 공유하는 기사(억제·묶기와 같은 문턱,
    국면 신호 제외 없음). 후보 자신은 알림 전에 저장되므로 창에 들어 있다. rows가 비면 (0, 0) → 문턱은 통과(fail-open)."""
    from news_dedup import extract_keywords
    pre = [(extract_keywords(r.get('title') or ''), bool(is_keep(r))) for r in rows or []]

    def share(title_a, title_b):
        ka, kb = extract_keywords(title_a or ''), extract_keywords(title_b or '')
        n = tot = 0
        for kw, keep in pre:
            if len(kw & ka) >= 3 or len(kw & kb) >= 3:
                tot += 1
                n += int(keep)
        return n, tot
    return share


def _suppress_core(items: list, prior: list, prior_at: dict, sup_chain: dict, group_fn, log=None,
                   remind_share=None) -> tuple:
    """재알림 억제·묶기의 핵심(#44·#92·#170·#181) — **DB·전역을 만지지 않는다**. → (reps, sup_rows, remind_rows, merged).
      items     = 이번 후보(순서가 대표를 정한다). **제자리에서** 고친다(_remind·_related) — 받는 단위마다 따로 계산할 때는
                  부르는 쪽이 dict를 복사해 넘긴다(단위끼리 섞이면 안 된다).
      prior     = 비교군 [{'title', 'kw'}](최신순), prior_at = {제목: created_at}(_prior_entries)
      sup_chain = 억제 사슬 {억제된 제목: 그때 걸린 기존 제목}(한 칸씩)
      group_fn  = 같은 사건 묶기(titles → 0부터 인덱스 묶음 | None) — None이면 의미 판정 두 단계(①-2·2차)를 건너뛴다
      log       = 줄 출력(공통 포장은 print — 종전 로그 그대로, 받는 단위는 None = 조용히)
      merged    = 실행분 안에서 대표에 병합된 건수(종전 len(passed) - len(reps))
    ①·②·③의 뜻은 suppress_repeat_alerts 설명 참조. 행 모양(article_title·article_url·matched_title·shared_keywords)은
    alert_suppress_log와 같다 — 받는 단위는 이것을 subscriber_alert_log 행으로 옮긴다."""
    from news_dedup import extract_keywords, is_followup, cluster_star
    say = log or (lambda *_a, **_k: None)

    def _rep_age_h(matched_title: str):
        """사건 대표(마지막으로 실제 알림이 나간 기사)의 경과 시간(h). 모르면 None(=3일 창 밖)."""
        cur, seen = matched_title, set()
        while cur and cur in sup_chain and cur not in seen:
            seen.add(cur)
            cur = sup_chain[cur]
        at = prior_at.get(cur)
        if not at:
            return None                  # 3일 창 밖의 대표 = 72시간 초과 → 리마인드 대상
        try:
            t = datetime.fromisoformat(str(at).replace('Z', '+00:00'))
            return (datetime.now(KST) - t).total_seconds() / 3600
        except Exception:
            return None

    def _remind_label(age_h):
        return '이어지는 사건' if age_h is None else f'{int(age_h // 24) + 1}일째'

    held = [0]                       # 리마인드 보류 건수(#256)

    def _remind_ok(it, matched_title):
        """리마인드 문턱(#256): remind_share(후보 제목, 기보도 제목) → (채널 등급 기사 수, 사건 기사 수)가 REMIND_MIN_SHARE 미만이면
        보류. remind_share가 없거나(조회 실패·시험) 사건 기사가 0이거나 계산이 죽으면 종전대로 통과(fail-open).
        → (통과 여부, 'n/N')."""
        if remind_share is None:
            return True, ''
        try:
            n, tot = remind_share(it.get('title') or '', matched_title)
        except Exception:
            return True, ''
        if not tot or n / tot >= REMIND_MIN_SHARE:
            return True, f'{n}/{tot}'
        held[0] += 1
        return False, f'{n}/{tot}'

    passed, sup_rows, remind_rows, passed_kw = [], [], [], []
    for it in items:
        kw = extract_keywords(it.get('title') or '')
        matched = None
        for pv in prior:
            if is_followup(kw, pv['kw'], it.get('title') or '', pv['title']):
                matched = pv
                break
        if matched:
            age_h = _rep_age_h(matched['title'])
            if age_h is None or age_h >= REMIND_AFTER_H:
                ok, ratio = _remind_ok(it, matched['title'])
                if not ok:                                    # 사건의 긴급 비율이 낮다 — 보류(#256), 사슬은 이어진다
                    sup_rows.append({
                        'article_title': it.get('title') or '',
                        'article_url': it.get('url') or '',
                        'matched_title': matched['title'],
                        'shared_keywords': f'{REMIND_HOLD_MARK} {ratio}',
                    })
                    continue
                it['_remind'] = _remind_label(age_h)          # 하루 1회 리마인드로 통과
                remind_rows.append({
                    'article_title': it.get('title') or '',
                    'article_url': it.get('url') or '',
                    'matched_title': matched['title'],
                    'shared_keywords': f"[리마인드] {it['_remind']}",
                })
                passed.append(it)
                passed_kw.append(kw)
                continue
            sup_rows.append({
                'article_title': it.get('title') or '',
                'article_url': it.get('url') or '',
                'matched_title': matched['title'],
                'shared_keywords': ','.join(sorted(kw & matched['kw'])),
            })
        else:
            passed.append(it)
            passed_kw.append(kw)

    # ── ①-2: 키워드로 못 잡은 '실행이 갈린' 재보도를 의미 판정으로 한 번 더 거른다 (2026-09-14) ──
    #  왜 필요한가(실측): 네팔 구호인력 로밍 면제 사건은 같은 내용 기사가 10건 들어왔고 그중 2건이
    #  긴급으로 분류됐는데, 10:03·10:49 실행으로 갈려 ①의 키워드 문턱(3개)만 거쳤다. 공유는 2개
    #  (네팔·구호인력)뿐 — '로밍' vs '로밍요금', '통신업계' vs '이통'+'3사', '무료' vs '전액면제'로
    #  같은 말이 다른 토큰이 되어 통과했고 한 시간 간격으로 두 통이 나갔다.
    #  #92의 의미 판정은 아래 ②(같은 실행분 묶기)에만 붙어 있어 실행이 갈리면 적용되지 않았다.
    #  후보는 키워드를 1개라도 공유하는 기보도로 한정한다 — 무관한 제목까지 태우면 오판도 비용도 는다.
    #  실행당 Haiku 1회(후보가 있을 때만), 실패하면 원본 유지(fail-open).
    if passed and prior and group_fn:
        cand = []                                  # 후보 기보도(제목 중복 제거, 최대 10건)
        seen_t = set()
        for pv in prior:
            if len(seen_t) >= 10:
                break
            if pv['title'] and pv['title'] not in seen_t and any(kw & pv['kw'] for kw in passed_kw):
                seen_t.add(pv['title'])
                cand.append(pv)
        if cand:
            titles = [it.get('title') or '' for it in passed] + [pv['title'] for pv in cand]
            gidx = group_fn(titles)
            if gidx:
                base = len(passed)
                drop = {}                          # passed 인덱스 → 묶인 기보도
                for g in gidx:
                    news = [i for i in g if i < base]
                    olds = [i - base for i in g if i >= base]
                    if news and olds:
                        for i in news:
                            drop[i] = cand[olds[0]]
                if drop:
                    kept, kept_kw = [], []
                    for i, it in enumerate(passed):
                        pv = drop.get(i)
                        if pv is None:
                            kept.append(it)
                            kept_kw.append(passed_kw[i])
                            continue
                        age_h = _rep_age_h(pv['title'])
                        if age_h is None or age_h >= REMIND_AFTER_H:
                            ok, ratio = _remind_ok(it, pv['title'])
                            if not ok:                              # 보류(#256)
                                sup_rows.append({
                                    'article_title': it.get('title') or '',
                                    'article_url': it.get('url') or '',
                                    'matched_title': pv['title'],
                                    'shared_keywords': f'{REMIND_HOLD_MARK} {ratio}',
                                })
                                continue
                            it['_remind'] = _remind_label(age_h)   # 여기서도 하루 1회는 통과
                            remind_rows.append({
                                'article_title': it.get('title') or '',
                                'article_url': it.get('url') or '',
                                'matched_title': pv['title'],
                                'shared_keywords': f"[리마인드] {it['_remind']}",
                            })
                            kept.append(it)
                            kept_kw.append(passed_kw[i])
                            continue
                        sup_rows.append({
                            'article_title': it.get('title') or '',
                            'article_url': it.get('url') or '',
                            'matched_title': pv['title'],
                            'shared_keywords': '[의미판정] ' + ','.join(sorted(passed_kw[i] & pv['kw'])),
                        })
                    say(f'[긴급 억제] 의미 판정으로 실행 간 재보도 {len(drop)}건 판정(리마인드 포함)')
                    passed, passed_kw = kept, kept_kw

    if held[0]:
        say(f'[긴급 억제] 리마인드 보류 {held[0]}건 — 그 사건의 3일 창 기사 중 이 채널 등급 비율이 {REMIND_MIN_SHARE:.0%} 미만(#256)')

    # 같은 실행분 내 유사 기사 묶기 — 사건 첫날 첫 실행에 재보도 수십 건이
    # 한꺼번에 들어오면 한 통에 수십 줄이 되는 것을 대표 1건으로 줄인다
    groups = []                      # [(대표, [묶인 것들])] — 아래 2차 묶기와 형태를 맞춘다
    for rep, members in cluster_star(passed):
        groups.append((rep, list(members)))

    # ── 2차: 키워드로 못 묶인 대표들을 Haiku가 의미로 다시 묶는다 (#92) ──
    # 매체마다 관점이 달라 제목에 공통 단어가 거의 없는 사건이 있다(공정위 불공정약관 4건:
    # 쌍별 공유 키워드 최대 1개). 어휘로는 못 넘으므로 여기서만 의미 판정을 쓴다.
    # 실패하면 1차 결과를 그대로 쓴다(fail-open) — 판정이 죽어서 알림이 죽으면 안 된다.
    if len(groups) >= 2 and group_fn:
        merged_idx = group_fn([g[0].get('title') or '' for g in groups])
        if merged_idx and len(merged_idx) < len(groups):
            regrouped = []
            for idxs in merged_idx:
                head = groups[idxs[0]]
                others = [m for i in idxs[1:] for m in ([groups[i][0]] + groups[i][1])]
                regrouped.append((head[0], head[1] + others))
            say(f'[긴급 억제] 의미 판정으로 {len(groups)}묶음 → {len(merged_idx)}묶음')
            groups = regrouped

    reps = []
    for rep, members in groups:
        rep['_related'] = len(members)
        if not rep.get('_remind'):
            for m in members:                     # 묶음 안의 리마인드 표시는 대표가 이어받는다
                if m.get('_remind'):
                    rep['_remind'] = m['_remind']
                    break
        reps.append(rep)
        # 대표에 병합된 기사도 '알림으로 나가지 않은 기사'다 — 2026-09-21부터 로그에 남긴다.
        # 사내판 다리(export_news.py)가 alert_suppress_log만 보고 대표 1건을 가려내기 때문이며,
        # 여기 없으면 같은 사건의 첫 실행분이 TOKTOK으로 여러 통 나간다(#180). 알림 내용은 그대로다.
        for m in members:
            sup_rows.append({
                'article_title': m.get('title') or '',
                'article_url': m.get('url') or '',
                'matched_title': rep.get('title') or '',
                'shared_keywords': '[실행내묶음]',
            })
    return reps, sup_rows, remind_rows, len(passed) - len(reps)


def suppress_repeat_alerts(urgent_items: list) -> list:
    """같은 사건 재보도의 재알림 억제 (배경역사 #44).

    ① 최근 3일 내 이미 DB에 있던 긴급 기사와 제목 유사(공유 키워드 3+) → 억제.
       단, 국면 신호 단어(소송·고발·상고…)가 새로 등장한 제목은 통과(새 전개).
    ② 이번 실행분 안에서도 유사 기사는 대표 1건으로 묶고 '(관련 보도 N건)' 병기.
    ③ 사건 대표(실제 알림이 나간 기사)가 24시간을 넘었으면 재보도 1건을 '리마인드'로 통과(#181, 2026-09-21).
       억제가 사슬로 이어져(실측 80%) 며칠짜리 사건이 영영 안 오던 것을 하루 1건으로 되살린다.
    ①·②·③ 모두 alert_suppress_log에 남긴다(②는 shared_keywords='[실행내묶음]', ③은 '[리마인드]', 2026-09-21~) —
       이 로그가 곧 '알림으로 나가지 않은 기사' 목록이고, 사내판 다리(export_news.py)가
       이것으로 TOKTOK 대표 1건을 가린다(#180). Haiku 판정 층 추가 여부는 계속 실측 후 결정.
    어떤 오류든 나면 원본 그대로 반환(fail-open) — 판정이 죽어서 알림까지 죽으면 안 된다.

    구조(#252, 2026-09-27): 이 함수는 **공통 경로의 얇은 포장** — 조회(3일 긴급 기보도·억제 사슬)·로그 기록·로그 줄만 하고,
    판정은 _suppress_core(DB·전역 무접촉)가 한다. 받는 단위별 알림(run_audience_alerts)이 같은 핵심을 자기 비교군으로
    돌리고, 등급이 갈라지지 않은 단위는 여기 결과(_COMMON_ALERT)를 복사한다. 공통 경로의 입력·출력·로그 행·로그 줄은
    나누기 전과 같다(tests/test_audience_alerts.py가 나누기 전 본문과 대조). 억제 사슬 조회만 1,000행에서 잘리던 것을
    order(created_at, id) + range 페이지로 고쳤다(행동 변화는 10일 로그가 1,000행을 넘을 때만 — 전에는 오래된 1,000행만 남았다)."""
    global _COMMON_ALERT
    _COMMON_ALERT = None
    if not urgent_items:
        _COMMON_ALERT = {'urls': [], 'reps': [], 'sup_rows': [], 'remind_rows': [], 'fail_open': False}
        return urgent_items
    try:
        # 이번 실행에서 방금 저장한 기사는 비교 대상에서 빼야 한다 (자기 자신과 비교 방지)
        batch_urls = {i.get('url') for i in urgent_items}
        cutoff_3d = (datetime.now(KST) - timedelta(days=3)).isoformat()
        # origin is null — 이슈맵 보강 옛 기사(created_at = 넣은 시각)가 긴급이 되면 3일간 같은 사건의 새 알림을 막는다(#236)
        resp = sb.table('news_feed').select('title,url,created_at') \
            .eq('urgency', '긴급').gte('created_at', cutoff_3d).is_('origin', 'null') \
            .order('created_at', desc=True).limit(1000).execute()
        prior, prior_at = _prior_entries(resp.data or [], batch_urls)

        # ── 하루 1회 리마인드 (2026-09-21 #181) ──────────────────────────────
        # 억제는 사슬로 이어진다 — 실측(30일) 억제 821건 중 660건(80%)이 '이미 억제된 기사'에
        # 걸려서 막혔다. 그래서 며칠씩 이어지는 사건은 첫 알림 뒤 영영 다시 오지 않는다
        # (9/21 LGU+ 해킹 은폐: 긴급 8건 전부 억제, 뿌리는 9/18 기사). 사건의 **대표**(실제로
        # 알림이 나간 기사)가 24시간을 넘었으면 재보도 1건을 '리마인드'로 통과시킨다.
        # 통과분은 alert_suppress_log에 `[리마인드]`로 남긴다 — 미발송이 아니라 발송 기록이며,
        # 사슬을 여기서 끊어 다음 24시간을 새로 센다. 사내판 다리도 이 접두사로 구분한다(#180).
        # 사슬 조회는 페이지로 끝까지(#252) — 페이지 없이 오름차순 1,000행이면 **오래된 행만** 남아 최근 사슬이 빠졌다.
        sup_chain = {}                       # 억제된 제목 → 그때 걸린 기존 제목(사슬 한 칸)
        try:
            cutoff_10d = (datetime.now(KST) - timedelta(days=ALERT_CHAIN_DAYS)).isoformat()
            _lg = _fetch_pages(lambda: sb.table('alert_suppress_log')
                               .select('article_title,matched_title,shared_keywords')
                               .gte('created_at', cutoff_10d).order('created_at').order('id'))
            sup_chain = _chain_from_suppress_log(_lg)
        except Exception as e:
            print(f'[긴급 억제] 억제 사슬 조회 실패 — 이번 실행은 리마인드 없이 종전대로: {e}')

        # ── 리마인드 문턱(#256, 2026-09-29): 사건의 3일 창 기사 전체(등급 무관) 중 긴급 비율 ≥ REMIND_MIN_SHARE일 때만 통과 ──
        # 하나금융 5G 특화망(170건 중 긴급 30)처럼 기사별 판정이 갈리는 경계 사건이 이튿날 새 기사 1건의 긴급으로 🔁[2일째]가
        # 되던 것을 막는다. 조회가 실패하면 문턱 없이 종전대로(fail-open — 리마인드가 빠지는 쪽이 아니라 나가는 쪽).
        remind_share = None
        try:
            _all = _fetch_pages(lambda: sb.table('news_feed').select('title,url,urgency,created_at')
                                .gte('created_at', cutoff_3d).is_('origin', 'null')
                                .order('created_at', desc=True).order('id', desc=True))
            remind_share = _event_share_fn(_all, lambda r: r.get('urgency') == '긴급')
        except Exception as e:
            print(f'[긴급 억제] 3일 창 전체 조회 실패 — 이번 실행은 리마인드 문턱 없이 종전대로: {e}')

        reps, sup_rows, remind_rows, merged = _suppress_core(
            urgent_items, prior, prior_at, sup_chain,
            _group_same_event_memo if ANTHROPIC_API_KEY else None, log=print, remind_share=remind_share)

        if remind_rows:
            print(f'[긴급 억제] 대표가 24시간을 넘겨 리마인드로 통과 {len(remind_rows)}건')
        if sup_rows or remind_rows:
            n_run = sum(1 for r in sup_rows if r['shared_keywords'] == '[실행내묶음]')
            print(f'[긴급 억제] 알림 미발송 {len(sup_rows)}건 기록 (3일 내 기보도 {len(sup_rows) - n_run}건 · 실행내 묶음 {n_run}건)')
            try:
                sb.table('alert_suppress_log').insert(sup_rows + remind_rows).execute()
            except Exception as e:
                print(f'[긴급 억제] 로그 저장 실패(무시): {e}')
        if merged:
            print(f'[긴급 억제] 실행분 내 유사 {merged}건 대표에 병합')
        _COMMON_ALERT = {'urls': [i.get('url') for i in urgent_items], 'reps': list(reps),
                         'sup_rows': list(sup_rows), 'remind_rows': list(remind_rows), 'fail_open': False}
        return reps
    except Exception as e:
        print(f'[긴급 억제] 판정 오류 → 전부 알림(fail-open): {e}')
        try:
            _COMMON_ALERT = {'urls': [i.get('url') for i in urgent_items], 'reps': list(urgent_items),
                             'sup_rows': [], 'remind_rows': [], 'fail_open': True}
        except Exception:
            _COMMON_ALERT = None
        return urgent_items


def send_telegram(urgent_items: list):
    """긴급 기사를 Telegram Bot으로 즉시 알림 (운영자 전용 — 분야 태그를 함께 표시)"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print('[텔레그램] 환경변수 미설정 (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID) — 건너뜀')
        return
    if not urgent_items:
        return

    now_str = datetime.now(KST).strftime('%Y.%m.%d %H:%M KST')
    # HTML 조립 — 기사 원제목의 * _ [ ] ( 등이 Markdown 파싱을 깨서 400으로
    # 통째 소실되던 것을 이스케이프된 HTML로 방지 (morning_briefing.py와 동일 방식)
    import html as _html

    def _esc(s: str) -> str:
        return _html.escape(str(s), quote=False)

    lines = [f'🚨 <b>[전파정책 AI] 긴급 기사 {len(urgent_items)}건</b> — {now_str}\n']
    for i, item in enumerate(urgent_items, 1):
        title = item.get('title', '')
        source = item.get('source', '')
        url = item.get('url', '')
        rel = item.get('_related', 0)
        rel_txt = f' (관련 보도 {rel}건)' if rel else ''
        rem = item.get('_remind') or ''                      # 하루 1회 리마인드 표시 (#181)
        rem_txt = f'🔁[{rem}] ' if rem else ''
        lines.append(f'<b>{i}. {_esc(rem_txt)}{_esc(title)}</b>{_esc(rel_txt)}')
        lines.append(f'   출처: {_esc(source)}')
        lines.append(f'   🏷 {_esc(tag_labels(item.get("tags")))}')
        if url:
            # href 속성값: & → &amp;, " → &quot; (quote=True)
            lines.append(f'   🔗 <a href="{_html.escape(str(url), quote=True)}">기사 보기</a>\n')
        else:
            lines.append('')

    lines.append('📊 <a href="https://radio-policy.gitlab.io/?p=news">대시보드</a>')
    text = '\n'.join(lines)

    # 전송부는 notify 위임 (개선⑪) — 실패 로그는 notify가 출력
    ok = notify.send_telegram(text, chat_id=TELEGRAM_CHAT_ID, parse_mode='HTML',
                              disable_web_page_preview=True)
    if not ok:
        # HTML 파싱 실패(400 등) 시 평문으로 재시도 — 포맷 때문에 긴급 알림 자체를
        # 잃지 않도록(fail-open, morning_briefing.py send_telegram과 동일 패턴)
        print('[텔레그램] 긴급 HTML 발송 실패 → 평문 재시도')
        plain_lines = [f'🚨 [전파정책 AI] 긴급 기사 {len(urgent_items)}건 — {now_str}\n']
        for i, item in enumerate(urgent_items, 1):
            rel = item.get('_related', 0)
            rel_txt = f' (관련 보도 {rel}건)' if rel else ''
            rem = item.get('_remind') or ''
            plain_lines.append(f"{i}. {('🔁[' + rem + '] ') if rem else ''}{item.get('title', '')}{rel_txt}")
            plain_lines.append(f"   출처: {item.get('source', '')}")
            plain_lines.append(f"   🏷 {tag_labels(item.get('tags'))}")
            plain_lines.append(f"   🔗 {item.get('url', '')}\n")
        plain_lines.append('📊 대시보드: https://radio-policy.gitlab.io/?p=news')
        ok = notify.send_telegram('\n'.join(plain_lines), chat_id=TELEGRAM_CHAT_ID,
                                  disable_web_page_preview=True)
    if ok:
        print(f'[텔레그램] 긴급 {len(urgent_items)}건 발송 완료')
    else:
        print(f'[텔레그램] 긴급 {len(urgent_items)}건 발송 실패 (HTML·평문 모두)')


# ═══════════════════════════════════════════════════════
#  긴급 전용 이메일 알림
# ═══════════════════════════════════════════════════════

def send_urgent_email(urgent_items: list):
    """긴급 기사 발생 시 즉시 이메일 발송 — Resend API 우선, Gmail SMTP 폴백"""
    if not urgent_items:
        return

    now_str = datetime.now(KST).strftime('%Y.%m.%d %H:%M KST')
    subject = f'🚨 [전파정책 AI 긴급] {now_str} — 즉시 대응 기사 {len(urgent_items)}건'

    rows_html = ''
    for item in urgent_items:
        rows_html += f'''
  <li style="margin-bottom:14px;padding:10px;background:#fff5f5;border-left:4px solid #e53e3e;border-radius:4px">
    <a href="{item['url']}" style="color:#c53030;font-weight:700;font-size:14px">{item['title']}</a><br>
    <small style="color:#666">{item['source']}</small>
  </li>'''

    body_html = f'''
<html><body style="font-family:sans-serif;max-width:600px;margin:auto;padding:20px">
<h2 style="color:#c53030">🚨 전파정책 AI — 긴급 대응 알림</h2>
<p style="color:#666">{now_str} | 즉시 대응이 필요한 기사 <strong>{len(urgent_items)}건</strong>이 감지되었습니다.</p>
<hr style="border-color:#fed7d7">
<ul style="padding-left:20px;list-style:none">
{rows_html}
</ul>
<hr>
<p style="color:#999;font-size:12px">
이 메일은 긴급 기사 감지 시 자동 발송됩니다. SKT Comm센터 기술정책팀<br>
대시보드: <a href="https://radio-policy.gitlab.io/?p=news">https://radio-policy.gitlab.io/?p=news</a>
</p>
</body></html>'''

    # Resend 우선 (GitHub Actions 미국 IP에서도 동작)
    if RESEND_API_KEY:
        import json as _json
        try:
            resp = requests.post(
                'https://api.resend.com/emails',
                headers={'Authorization': f'Bearer {RESEND_API_KEY}', 'Content-Type': 'application/json'},
                data=_json.dumps({
                    'from': '전파정책 AI <onboarding@resend.dev>',
                    'to': ['you.jinwoong@gmail.com'],
                    'subject': subject,
                    'html': body_html,
                }),
                timeout=30,
            )
            if resp.status_code in (200, 201):
                print(f'[긴급 이메일/Resend] you.jinwoong@gmail.com 발송 완료')
            else:
                print(f'[긴급 이메일/Resend 오류] HTTP {resp.status_code}: {resp.text[:200]}')
        except Exception as e:
            print(f'[긴급 이메일/Resend 오류] {e}')
    elif all([EMAIL_FROM, EMAIL_PASS, EMAIL_TO]):
        # 폴백: Gmail SMTP (PC 로컬 실행 시)
        extra_to = 'lampman@sktelecom.com'
        all_to = list({addr.strip() for addr in (EMAIL_TO + ',' + extra_to).split(',') if addr.strip()})
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = f'전파정책 AI <{EMAIL_FROM}>'
        msg['To']      = ', '.join(all_to)
        msg.attach(MIMEText(body_html, 'html', 'utf-8'))
        try:
            with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30) as smtp:
                smtp.login(EMAIL_FROM, EMAIL_PASS)
                smtp.sendmail(EMAIL_FROM, all_to, msg.as_string())
            print(f'[긴급 이메일/Gmail] {", ".join(all_to)} 발송 완료')
        except Exception as e:
            print(f'[긴급 이메일/Gmail 오류] {e}')
    else:
        print('[긴급 이메일] RESEND_API_KEY 또는 Gmail 환경변수 미설정 — 건너뜀')


# ═══════════════════════════════════════════════════════
#  받는 단위별 알림 — 팀·실장의 중요 + 「중요+보통」의 보통 (#252, 2026-09-27, 설계안 §10 E5·E6·E9·A2 — ⚠️ Fable 재검토 대상)
#
#  구독자 봇의 주요 뉴스(긴급)만 팀 등급으로 거른다 — 브리핑·운영자 봇·긴급 메일·공통 구독자의 중요는 공통값 그대로(E5).
#  받는 단위(audience) = 실장 'd:<실>' / 팀 't:<팀 id>' / 공통 'c' — 구독자 행의 division·team_id(관리자 지정, E6).
#  채널: 팀·실장 = '긴급' + (그 단위에 「중요+보통」인 사람이 있으면) '보통' / 공통 = 「중요+보통」인 사람이 있을 때 '보통'만
#  (공통 중요는 종전 topic 'urgent' 경로 그대로). 새 큐 행은 모두 topic 'news'(subscriber_notify.news_row).
#  · 알림 등급: 팀 = urgency_rules.alert_team_level(팀원 수정은 min(팀원값, 공통값) — 올린 것은 알림 안 함·내린 것은 막음),
#    실장 = alert_division_level(실 팀들의 최고 — 같은 기사는 한 번), 공통 = 공통값.
#  · 후보는 **새로 수집한 기사만**(B-2): 'collect' = 이번 실행에 새로 저장된 기사(_INSERTED_IDS), 'late' = 수집 때 생긴 문장
#    판정 대기 행(requested_by null + 기사 저장 뒤 LATE_COLLECT_MAX_GAP_MIN 안)이 이번 실행에 **참**으로 판정되어 그 팀 행(rule·
#    그 규칙 id)을 정한 기사(_LATE_ALERT_PAIRS, 실장은 그 팀이 최고 등급을 본 팀일 때만). 대시보드 저장·재적용·재판정·되살림·
#    관리자 공통 등급 수정은 알림 없음(화면만).
#  · 억제·묶기(#44)는 공통과 같은 핵심(_suppress_core)을 그 단위가 **지금 보는** 등급의 비교군(3일, origin null)으로 돌린다 —
#    '긴급' 비교군 = 긴급, '보통' 비교군 = 긴급+보통(B-1: 중요로 이미 간 사건의 뒤 보통은 안 보내고, 보통으로 먼저 간 사건이
#    중요로 오면 중요로 다시 보낸다). 억제 사슬 = subscriber_alert_log(그 단위·채널). **alert_suppress_log에는 쓰지 않는다**
#    (사내 다리가 읽는 공통 기록, #180).
#  · 복사 지름길('collect'만): 단위의 입력(후보 목록·비교군 구성)이 기준과 같으면 계산하지 않고 기준 결과를 복사한다 —
#    '긴급' = 공통 포장 결과(_COMMON_ALERT), '보통' = 공통값으로 한 번 계산한 'c' 보통 결과. AI 호출 0.
#    복사 조건은 _aud_same_inputs — 후보 목록이 순서까지 같고, 3일 비교군 창의 모든 기사에서 그 단위의 채널 비교군 소속이
#    공통값 기준과 같을 때(사슬만 다르다). 팀 규칙 행이 이번 후보나 3일 창의 한 기사라도 채널 경계를 넘기면 계산한다.
#  · 쓰기 순서: subscriber_alert_log upsert(ignore_duplicates, 묶음 실패면 한 행씩) 먼저 → **응답으로 새로 들어간 대표만**, 그
#    단위·채널 기록 직후 바로 큐(#154 동시 실행 안전).
#  · main: 'collect' 긴급 채널(전 단위) → 즉시 배달 호출 한 번(try/finally) → 보통 채널 → 문장 판정 → 'late'(긴급 행이 들어갔고
#    앞 호출이 실패하지 않았을 때만 한 번 더). 팀 경로의 사건 묶기는 짧은 제한(20초·재시도 1회), 공통 경로는 종전 그대로.
#  · 읽기는 모두 재시도(retry_util). 그래도 단위를 계산할 수 없으면 'collect' 긴급은 **공통 결과 복사**로 대체(#44 '판정이 죽으면
#    시끄러운 쪽이 안전', 기록 shared_keywords '[대체]'), 그 밖은 건너뛴다. 구독자 목록을 끝내 못 읽으면 그 실행은 팀 알림 없음.
#    팀 규칙 표 조회가 실패한 실행은 팀 규칙 행을 쓰지 않았으므로 팀 등급을 공통값으로(규칙 없이) 계산한다.
#  · 감시: heartbeat last_crawl_run 메모 끝 ' team=긴급N/보통M/오류K'(audience_note), 단위 줄·합계 줄에 'AI N회'(메모 적중 제외).
#  · fail-open: 어떤 예외도 수집·공통 알림·즉시 배달·문장 판정·heartbeat를 막지 않는다(run_audience_alerts가 삼킨다).
# ═══════════════════════════════════════════════════════

ALERT_CHANNELS = ('긴급', '보통')
ALERT_WINDOW_DAYS = 3                  # 비교군 창 — 공통 억제와 같다
ALERT_ID_CHUNK = 100                   # news_id in_ 조회 묶음(uuid 100개 ≈ 3.7KB 주소)
ALERT_LOG_CHUNK = 500
ALERT_MAX_ROWS = 1000                  # PostgREST 요청당 상한 — in_ 두 개를 곱한 조회는 묶음 크기를 이것으로 나눠 잡는다(#233)
LATE_COLLECT_MAX_GAP_MIN = 15          # 수집 경로 판정 행 = requested_by null + (판정 행 created_at − 기사 created_at) ≤ 이 분
ALERT_GROUP_TIMEOUT_S = 20             # 받는 단위 계산의 사건 묶기 호출 제한 — 공통 경로는 종전 그대로(인자 없음)
ALERT_AI_BUDGET_S = 45           # 채널 묶음(예: collect 긴급) 전체의 사건 묶기 AI 시간 예산 — 넘으면 남은 단위는 AI 없이(공통 즉시 배달 지연 상한)
ALERT_GROUP_RETRIES = 1
_ALERT_CMP = {'긴급': ('긴급',), '보통': ('긴급', '보통')}          # 채널별 비교군 등급(B-1)
_ALERT_WINDOW_COLS = 'id,title,url,created_at,urgency'
_ALERT_LATE_COLS = 'id,title,url,source,tags,urgency,published_at,origin,created_at'
_ALERT_STRIP = ('_related', '_remind', '_label')      # 공통 포장이 제자리에 쓴 표시 — 단위 계산 전에 떼어 낸다
_LEVEL_RANK = {lv: i for i, lv in enumerate(urgency_rules.LEVELS)}
_C_UNIT = {'kind': 'c', 'team_ids': [], 'channels': ['보통']}
# 'collect' 준비 결과(후보·단위·팀 행·비교군 창·기록 확인) — main이 긴급 채널 → 즉시 배달 → 보통 채널로 나눠 부르므로 같은
# 실행 안에서 다시 쓴다. _AUD_STATS = 이번 실행 합계(heartbeat 메모 꼬리 audience_note). main 시작 때 _reset_audience_state.
_AUD_CTX: dict = {}
_AUD_STATS: dict = {'units': 0, '긴급': 0, '보통': 0, '오류': 0, 'ai': 0}


class _AudSkip(RuntimeError):
    """이미 로그를 찍고 오류로 센 조회 실패 때문에 그 단위를 계산할 수 없다(대체·건너뜀만, 오류 수는 다시 세지 않는다)."""


def _reset_audience_state() -> None:
    _GROUP_MEMO.clear()
    _AUD_CTX.clear()
    _AUD_STATS.update({'units': 0, '긴급': 0, '보통': 0, '오류': 0, 'ai': 0})


def audience_note() -> str:
    """heartbeat 메모(last_crawl_run) 꼬리 — ' team=긴급N/보통M/오류K'(이번 실행 큐에 넣은 팀·보통 행, 팀 경로 오류 수).
    받는 단위도 오류도 없으면 ''(메모는 종전 그대로). 오류가 있으면 끝에 ' fail=K'를 더 붙인다 — watchdog_scan(3시간마다)의
    실패 정규식 '(fail|failed)=[1-9]'가 잡아 운영자 봇 경보가 간다(운영자 결정 09-27 「경보 받기」). 팀 구독자만 조용히 끊기는
    것을 알리려는 것이고, 한 번 났다가 다음 실행에서 사라진 오류는 그 시각 메모에 없으므로 경보가 가지 않는다."""
    s = _AUD_STATS
    if not s.get('units') and not s.get('오류'):
        return ''
    k = s.get('오류', 0)
    return f" team=긴급{s.get('긴급', 0)}/보통{s.get('보통', 0)}/오류{k}" + (f' fail={k}' if k else '')


def is_within_24h(item, cutoff_24h=None) -> bool:
    """알림 대상 발행 시각 — 발행 24시간 이내만(main의 공통 긴급 알림과 받는 단위별 알림이 같은 판정을 쓴다, #252).
    cutoff_24h 이후면 True, 없으면 지금 − 24시간. published_at이 없거나 못 읽으면 False."""
    if cutoff_24h is None:
        cutoff_24h = datetime.now(KST) - timedelta(hours=24)
    pub = item.get('published_at', '')
    if not pub:
        return False
    try:
        from dateutil import parser as _dtp2
        pub_dt = _dtp2.parse(pub)
        if pub_dt.tzinfo is None:
            pub_dt = pub_dt.replace(tzinfo=KST)
        return pub_dt >= cutoff_24h
    except Exception:
        return False


def _chunks(seq, n: int):
    seq = list(seq)
    for i in range(0, len(seq), max(1, n)):
        yield seq[i:i + max(1, n)]


def _id_chunk(per_id: int) -> int:
    """in_(기사 id) 묶음 크기 — 기사 하나당 최대 per_id행이 오는 조회가 1,000행 상한에 잘리지 않게(#233)."""
    return max(1, min(ALERT_ID_CHUNK, ALERT_MAX_ROWS // max(1, per_id)))


def _alert_units(subs, teams) -> dict:
    """구독자 행(team_id·division·news_level) → 받는 단위 {audience: {'kind': 'c'|'t'|'d', 'team_ids': [...], 'channels': [...]}}.
    division 있으면 'd:<실>'(team_ids = teams 중 그 실의 팀, teams 순서 = sort_order·id), 아니면 team_id 있으면 't:<id>',
    둘 다 없으면 'c'. 채널: 팀·실장 = '긴급' + (normal인 사람이 있으면) '보통' / 공통 = normal인 사람이 있을 때만 '보통'.
    채널이 없는 단위는 돌려주지 않는다."""
    div_teams = {}
    for t in teams or []:
        if t.get('division') and t.get('id') is not None:
            div_teams.setdefault(t['division'], []).append(int(t['id']))
    units = {}
    for s in subs or []:
        div, tid = s.get('division'), s.get('team_id')
        if div:
            aud, kind, tids = f'd:{div}', 'd', div_teams.get(div, [])
        elif tid is not None:
            aud, kind, tids = f't:{int(tid)}', 't', [int(tid)]
        else:
            aud, kind, tids = 'c', 'c', []
        u = units.setdefault(aud, {'kind': kind, 'team_ids': list(tids), 'channels': set()})
        if kind != 'c':
            u['channels'].add('긴급')
        if s.get('news_level') == 'normal':
            u['channels'].add('보통')
    return {a: dict(u, channels=[c for c in ALERT_CHANNELS if c in u['channels']])
            for a, u in units.items() if u['channels']}


def _unit_level(unit: dict, common, rows_by_team, rules_by_id, alert: bool = True) -> tuple:
    """단위가 한 기사에서 보는 등급 → (등급, 그 등급을 본 팀 id — 실장 표시용).
    alert=True(후보) = 알림 등급(팀원 수정은 min), False(비교군) = 지금 보는 화면 등급(팀원 수정 포함)."""
    kind = unit['kind']
    if kind == 'c':
        return common, []
    if kind == 't':
        tid = unit['team_ids'][0]
        row = (rows_by_team or {}).get(tid)
        if alert:
            return urgency_rules.alert_team_level(common, row, rules_by_id), [tid]
        return urgency_rules.effective_team_urgency(common, row, rules_by_id)['level'], [tid]
    fn = urgency_rules.alert_division_level if alert else urgency_rules.division_urgency
    d = fn(common, rows_by_team, rules_by_id, unit['team_ids'])
    return d['level'], list(d['teams'])


def _alert_label(unit: dict, level, common, teams, team_names: dict) -> str:
    """B-3 — 받는 단위의 알림 등급이 공통값보다 높을 때만: 팀 '우리 팀 기준', 실장 '<그 등급을 본 팀 이름들>'(팀 순서)."""
    if _LEVEL_RANK.get(level, -1) <= _LEVEL_RANK.get(common, -1):
        return ''
    if unit['kind'] == 't':
        return '우리 팀 기준'
    if unit['kind'] == 'd':
        return '·'.join(str(team_names.get(t) or f'팀 {t}') for t in teams)
    return ''


def _alert_log_rows(audience: str, channel: str, reps: list, sup_rows: list, remind_rows: list, nid_of: dict) -> tuple:
    """억제 결과 → (subscriber_alert_log 행, 대표 [(news_id, 대표 item)]). ★ 모든 행의 키 집합 동일 ★(벌크 upsert).
    outcome: 대표 → _remind 있으면 'remind'(matched_title·shared_keywords = 리마인드 행) 아니면 'sent' / 실행내 묶음 → 'merged' /
    기보도 억제 → 'suppressed'(shared_keywords는 공통 로그와 같은 글 — '[의미판정] …' 포함). news_id를 모르는 기사는 뺀다.
    한 기사는 한 행(표 unique(audience, channel, news_id))."""
    rows, out, seen = [], [], set()
    remind_by_url = {}
    for r in remind_rows or []:
        remind_by_url.setdefault(r.get('article_url') or '', r)

    def add(nid, title, url, outcome, matched, kw):
        rows.append({'audience': audience, 'channel': channel, 'news_id': nid, 'article_title': title or '',
                     'article_url': url or None, 'outcome': outcome, 'matched_title': matched, 'shared_keywords': kw})

    for rep in reps or []:
        url = rep.get('url') or ''
        nid = nid_of.get(url)
        if not nid or nid in seen:
            continue
        seen.add(nid)
        rem = rep.get('_remind') or ''
        rr = remind_by_url.get(url) if rem else None
        if rem:
            add(nid, rep.get('title'), url, 'remind', rr.get('matched_title') if rr else None,
                rr.get('shared_keywords') if rr else f'[리마인드] {rem}')
        else:
            add(nid, rep.get('title'), url, 'sent', None, None)
        out.append((nid, rep))
    for s in sup_rows or []:
        url = s.get('article_url') or ''
        nid = nid_of.get(url)
        if not nid or nid in seen:
            continue
        seen.add(nid)
        kw = s.get('shared_keywords')
        add(nid, s.get('article_title'), url, 'merged' if kw == '[실행내묶음]' else 'suppressed',
            s.get('matched_title'), kw)
    return rows, out


def _save_alert_log(rows: list) -> tuple:
    """subscriber_alert_log upsert(on_conflict audience,channel,news_id + ignore_duplicates) → (fresh, ok, bad, err).
      fresh = 응답(= 새로 들어간 행) 중 대표(sent·remind)의 news_id — 이것만 큐에 넣는다. 이미 있던 (단위, 채널, 기사)는 응답에
              없다(다른 실행이 보냄, #154 'upsert 반환값으로만 판단').
      ok    = 쓰기가 성공한 행(새로 들어갔거나 이미 있던)의 news_id — 같은 실행의 기록 확인 집합에 더한다(R7).
      bad   = 끝내 못 쓴 행 수(묶음이 실패하면 한 행씩 다시 — 수집 직후 지워진 기사(FK 오류)의 행만 빠진다, _upsert_rows와 같은
              방식). 한 행씩 쓰기에서 처음 3행이 모두 실패하면 표 장애로 보고 그 묶음을 멈춘다.
    한 행도 못 썼으면 예외(부르는 쪽이 그 단위·채널을 이번 실행에 보내지 않는다)."""
    fresh, ok, bad, err = set(), set(), 0, ''

    def put(part):
        tries = [0]

        def _do(p=part):
            tries[0] += 1
            return sb.table('subscriber_alert_log').upsert(
                p, on_conflict='audience,channel,news_id', ignore_duplicates=True).execute()
        res = _db_retry(_do, 'subscriber_alert_log')
        for r in getattr(res, 'data', None) or []:
            if isinstance(r, dict) and r.get('outcome') in ('sent', 'remind'):
                fresh.add(r.get('news_id'))
        ok.update(x.get('news_id') for x in part)
        if tries[0] > 1:
            # 재시도로 성공 — 첫 시도가 커밋된 뒤 응답만 끊겼으면 두 번째 응답은 비어(이미 있음) 그 대표가 큐에 못 들어간다.
            # 구분할 수 없으므로 오류로 센다(heartbeat fail=K → 워치독 경보, 재검토 경미 3).
            _AUD_STATS['오류'] = _AUD_STATS.get('오류', 0) + 1
            print(f'[팀 알림] 기록 쓰기가 재시도 끝에 성공 — 첫 시도 응답이 끊겼다면 일부 대표가 큐에 못 들어갔을 수 있음({len(part)}행)')

    for part in _chunks(rows, ALERT_LOG_CHUNK):
        try:
            put(part)
            continue
        except Exception as e:
            err = err or str(e)[:120]
        if len(part) == 1:
            bad += 1
            continue
        ok_any, bad_run = False, 0
        for k, r in enumerate(part):
            try:
                put([r])
                ok_any, bad_run = True, 0
            except Exception as e:
                err = err or str(e)[:120]
                bad += 1
                bad_run += 1
                if not ok_any and bad_run >= 3:
                    bad += len(part) - k - 1
                    break
    if rows and not ok:
        raise RuntimeError(err or '기록 실패')
    return fresh, ok, bad, err


def _audience_chain(audience: str, channel: str) -> dict:
    """억제 사슬 = subscriber_alert_log(그 단위·채널, 10일, suppressed·merged — sent·remind는 '나간 기사'라 사슬을 끊는다)
    → {article_title: matched_title}, 오래된 것부터 페이지로 끝까지(#66·#233). 실패하면 {}(그 단위는 리마인드 없이 — 공통과 같다)."""
    try:
        cut = (datetime.now(KST) - timedelta(days=ALERT_CHAIN_DAYS)).isoformat()
        rows = _fetch_pages(lambda: sb.table('subscriber_alert_log').select('article_title,matched_title')
                            .eq('audience', audience).eq('channel', channel).gte('created_at', cut)
                            .in_('outcome', ['suppressed', 'merged']).order('created_at').order('id'))
    except Exception as e:
        print(f'[팀 알림] {audience} {channel} 억제 사슬 조회 실패 — 이번 실행은 리마인드 없이: {str(e)[:80]}')
        return {}
    chain = {}
    for r in rows:
        if r.get('article_title'):
            chain[r['article_title']] = r.get('matched_title') or ''
    return chain


def _late_gap_ok(requested_at, article_at) -> bool:
    """R2 — 판정 행이 기사 저장 뒤 LATE_COLLECT_MAX_GAP_MIN 안에 생겼나(수집 때 만든 대기 행). 시각을 못 읽으면 False."""
    r, a = _parse_ts(requested_at), _parse_ts(article_at)
    return bool(r and a and (r - a) <= timedelta(minutes=LATE_COLLECT_MAX_GAP_MIN))


def run_audience_alerts(stage: str, new_items=None, cutoff_24h=None, channels=ALERT_CHANNELS) -> int:
    """받는 단위별 알림(#252). stage 'collect' = main이 공통 큐 적재 직후(new_items = save_new_items 반환 — 그중 이번
    실행에 새로 저장된 기사만), 'late' = 문장 판정 대기 처리 뒤(_LATE_ALERT_PAIRS). cutoff_24h = main의 24시간 기준.
    channels — main은 'collect'를 ('긴급',) → 즉시 배달 → ('보통',)으로 나눠 부른다(준비 결과는 _AUD_CTX로 한 번만 읽는다).
    반환 = 이번 호출에서 큐에 넣은 '긴급' 행 수(즉시 배달 호출은 부르는 쪽이 정한다 — 보통만 들어갔으면 부르지 않는다).
    **어떤 예외도 밖으로 던지지 않는다**(fail-open — 수집·공통 알림·즉시 배달·heartbeat를 막지 않는다)."""
    try:
        ctx = _AUD_CTX.get(stage) if stage == 'collect' else None
        if ctx is None or ctx.get('new_items') is not new_items:
            ctx = _audience_prepare(stage, new_items, cutoff_24h)
            if stage == 'collect':
                _AUD_CTX['collect'] = ctx
        if ctx.get('empty'):
            return 0
        ctx['t0'] = time.monotonic()        # 이번 채널 묶음의 시작 — 사건 묶기 AI 전체 예산(ALERT_AI_BUDGET_S)의 기준
        return _audience_channels(ctx, tuple(channels))
    except Exception as e:
        _AUD_STATS['오류'] += 1
        print(f'[팀 알림] {stage} 오류(무시 — 수집·공통 알림은 그대로): {str(e)[:160]}')
        return 0


def _audience_prepare(stage: str, new_items, cutoff_24h) -> dict:
    """후보·받는 단위·규칙·팀 행·기록 확인을 읽는다(읽기는 모두 재시도 — R5). 할 일이 없으면 {'empty': True}.
    단위를 계산할 수 없게 만드는 조회 실패는 ctx['broken'](단위별)·ctx['broken_all']에 이유로 남긴다 — 'collect' 긴급 채널은
    공통 결과 복사로 대체, 그 밖은 건너뛴다(_audience_channels)."""
    empty = {'new_items': new_items, 'empty': True}
    cut = cutoff_24h or (datetime.now(KST) - timedelta(hours=24))
    # ① 후보(메모리) — 없으면 조회 0번
    if stage == 'collect':
        cands = [it for it in (new_items or []) if it.get('url') and it.get('url') in _INSERTED_IDS
                 and not it.get('origin') and is_within_24h(it, cut)]
        if not cands:
            return empty
        pairs = {}
    elif stage == 'late':
        pairs = {t: {n: dict(r) for n, r in m.items()} for t, m in _LATE_ALERT_PAIRS.items() if m}
        if not pairs:
            return empty
        cands = []
    else:
        print(f'[팀 알림] 알 수 없는 단계 {stage!r} — 건너뜀')
        return empty

    # ② 받는 단위 — 활성·주요 뉴스 켜진 구독자. 단위가 없으면 여기서 끝(조회 1번). 끝내 못 읽으면 단위를 모르니 팀 알림 없음
    try:
        subs = _db_retry(lambda: sb.table('telegram_subscribers').select('team_id,division,news_level')
                         .eq('active', True).eq('topic_urgent', True).execute(), 'telegram_subscribers').data or []
    except Exception as e:
        _AUD_STATS['오류'] += 1
        print(f'[팀 알림] 구독자 목록 조회 실패 — 이번 실행은 팀 알림 없음(받는 단위를 모름): {str(e)[:80]}')
        return empty
    broken = {}                                  # 단위 → 계산할 수 없는 이유
    teams = []
    if any(s.get('division') for s in subs):
        try:
            teams = _db_retry(lambda: sb.table('teams').select('id,division,name,sort_order')
                              .order('sort_order').order('id').execute(), 'teams').data or []
        except Exception as e:
            _AUD_STATS['오류'] += 1
            teams = None
            print('[팀 알림] 팀 목록 조회 실패 — 이번 실행 실장 단위는 '
                  + ('긴급만 공통 결과로 대체' if stage == 'collect' else '건너뜀') + f': {str(e)[:80]}')
    units = _alert_units(subs, teams or [])
    if teams is None:
        for a, u in units.items():
            if u['kind'] == 'd':
                broken[a] = '팀 목록 조회 실패'
    if stage == 'late':                          # 공통값은 문장 판정으로 바뀌지 않는다 — 그 팀이 든 팀·실장 단위만
        units = {a: u for a, u in units.items() if u['kind'] != 'c' and set(u['team_ids']) & set(pairs)}
    if not units:
        if stage == 'late':
            _LATE_ALERT_PAIRS.clear()            # 받을 단위가 없다 — 할 일 끝
        return empty
    _AUD_STATS['units'] = max(_AUD_STATS['units'], len(units))

    # ③ 규칙 — 표 조회 실패면 그 실행은 팀 규칙 행을 하나도 쓰지 않았다(_split_team_rules {}) → 팀 등급은 사실 공통값(R3)
    rules_by_id = {}
    if any(u['kind'] != 'c' for u in units.values()):
        load_team_urgency_rules()                # 이미 읽었으면 캐시(조회 0번)
        if _TEAM_RULES_ENABLED is None:
            print('[팀 알림] 규칙 조회 실패 — 이번 실행 팀 등급은 공통값으로')
        rules_by_id = _TEAM_RULES_ENABLED or {}
    team_names = {t.get('id'): t.get('name') for t in (teams or [])}

    # ④ 'late' 후보 — 기사 읽기에 성공한 뒤에만 _LATE_ALERT_PAIRS를 비운다(R5). R2: 판정 행이 기사 저장 직후 생긴 것만
    late_ok = {}                                 # (팀, 기사) → 수집 경로로 인정한 참 판정 규칙 id
    if stage == 'late':
        want = sorted({n for t, m in pairs.items() for n in m if any(t in u['team_ids'] for u in units.values())})
        try:
            rows = []
            for part in _chunks(want, ALERT_ID_CHUNK):
                rows += _db_retry(lambda p=part: sb.table('news_feed').select(_ALERT_LATE_COLS).in_('id', p).execute(),
                                  'news_feed').data or []
        except Exception as e:
            _AUD_STATS['오류'] += 1
            print(f'[팀 알림] 늦은 판정 기사 조회 실패 — 이번 실행 늦은 알림 없음: {str(e)[:80]}')
            return empty
        _LATE_ALERT_PAIRS.clear()
        created = {n.get('id'): n.get('created_at') for n in rows}
        for t, m in pairs.items():
            for nid, req in m.items():
                ok = {rid for rid, at in req.items() if _late_gap_ok(at, created.get(nid))}
                if ok:
                    late_ok[(t, nid)] = ok
        rows.sort(key=lambda n: (str(n.get('created_at') or ''), str(n.get('id') or '')), reverse=True)   # 최신 = 대표
        cands = [n for n in rows if n.get('id') and n.get('url') and not n.get('origin') and is_within_24h(n, cut)
                 and any((t, n['id']) in late_ok for t in pairs)]
        if not cands:
            return empty
        nid_of = {n['url']: n['id'] for n in cands}
    else:
        nid_of = {it['url']: _INSERTED_IDS[it['url']] for it in cands}

    ctx = {'new_items': new_items, 'empty': False, 'stage': stage, 'cands': cands, 'nid_of': nid_of, 'units': units,
           'auds': sorted(units), 'rules_by_id': rules_by_id, 'team_names': team_names, 'late_ok': late_ok,
           'need_teams': sorted({t for u in units.values() for t in u['team_ids']}), 'trows': {}, 'logged': set(),
           'broken': broken, 'broken_all': '', 'window': None, 'window_err': '', 'view': {}, 'ai': [0]}
    ctx['group_fn'] = (lambda titles, c=ctx['ai']: _group_same_event_memo(
        titles, timeout=ALERT_GROUP_TIMEOUT_S, max_retries=ALERT_GROUP_RETRIES, counter=c)) if ANTHROPIC_API_KEY else None

    # ⑤ 필요한 팀의 팀 행 — 먼저 후보만(비교군 창은 후보가 있는 단위·채널이 있을 때만). 못 읽으면 팀·실장 단위를 계산 못 함
    cand_ids = set(nid_of.values())
    try:
        _aud_load_team_rows(ctx, cand_ids)
    except Exception as e:
        _AUD_STATS['오류'] += 1
        print('[팀 알림] 팀 등급 조회 실패 — 이번 실행 팀·실장 단위는 '
              + ('긴급만 공통 결과로 대체' if stage == 'collect' else '건너뜀') + f': {str(e)[:80]}')
        for a, u in units.items():
            if u['kind'] != 'c':
                broken.setdefault(a, '팀 등급 조회 실패')

    # ⑥ 이미 기록된 (단위, 채널, 기사) — 뺀다('c'는 활성이 아니어도 본다 — 보통 기준 기록, R6). 묶음 = 기사 × 단위 × 2 ≤ 1,000
    log_auds = sorted(set(units) | {'c'})
    try:
        for part in _chunks(sorted(cand_ids), _id_chunk(len(log_auds) * 2)):
            data = _db_retry(lambda p=part: sb.table('subscriber_alert_log').select('audience,channel,news_id')
                             .in_('news_id', p).in_('audience', log_auds).execute(), 'subscriber_alert_log').data or []
            ctx['logged'].update((r.get('audience'), r.get('channel'), r.get('news_id')) for r in data)
    except Exception as e:
        _AUD_STATS['오류'] += 1
        ctx['broken_all'] = '기록 확인 조회 실패'
        print('[팀 알림] 기록 확인 조회 실패 — 이번 실행은 '
              + ('긴급만 공통 결과로 대체' if stage == 'collect' else '늦은 알림 없음') + f': {str(e)[:80]}')
    return ctx


def _aud_load_team_rows(ctx: dict, ids) -> None:
    """team_urgency(기사 in_ × 필요한 팀 in_) → ctx['trows'] {news_id: {team_id: 행}}. 묶음 = 1,000 // 팀 수(R8). 재시도, 실패는 예외."""
    if not ctx['need_teams'] or not ids:
        return
    for part in _chunks(sorted(ids), _id_chunk(len(ctx['need_teams']))):
        data = _db_retry(lambda p=part: sb.table('team_urgency').select('news_id,team_id,urgency,source,rule_id')
                         .in_('news_id', p).in_('team_id', ctx['need_teams']).execute(), 'team_urgency').data or []
        for r in data:
            ctx['trows'].setdefault(r.get('news_id'), {})[r.get('team_id')] = r


def _aud_window(ctx: dict) -> list:
    """비교군 창(3일, origin null, 최신순 페이지) + 그 창의 팀 행 — 처음 필요할 때 한 번(재시도). 실패하면 _AudSkip."""
    if ctx['window'] is None:
        if ctx['window_err']:
            raise _AudSkip(ctx['window_err'])
        try:
            cut3 = (datetime.now(KST) - timedelta(days=ALERT_WINDOW_DAYS)).isoformat()
            w = _db_retry(lambda: _fetch_pages(lambda: sb.table('news_feed').select(_ALERT_WINDOW_COLS)
                                               .gte('created_at', cut3).is_('origin', 'null')
                                               .order('created_at', desc=True).order('id')), 'news_feed')
            _aud_load_team_rows(ctx, {x.get('id') for x in w if x.get('id')} - set(ctx['nid_of'].values()))
        except Exception as e:
            ctx['window_err'] = f'비교군 조회 실패: {str(e)[:80]}'
            _AUD_STATS['오류'] += 1
            print(f'[팀 알림] {ctx["window_err"]} — 계산이 필요한 단위는 '
                  + ('긴급만 공통 결과로 대체' if ctx['stage'] == 'collect' else '건너뜀'))
            raise _AudSkip(ctx['window_err'])
        ctx['window'] = w
    return ctx['window']


def _aud_view(ctx: dict, aud: str, u: dict, w: dict):
    k = (aud, w.get('id'))
    if k not in ctx['view']:
        ctx['view'][k] = _unit_level(u, w.get('urgency'), ctx['trows'].get(w.get('id')), ctx['rules_by_id'],
                                     alert=False)[0]
    return ctx['view'][k]


def _aud_late_team_ok(ctx: dict, team_id, nid, common=None) -> bool:
    """R1 — 그 팀의 (참 판정·수집 경로) 문장 규칙이 지금 팀 행을 정했나: 팀 행 source='rule'이고 rule_id가 그 규칙이며,
    그 규칙이 등급을 **스스로 정했다**(set이거나 규칙 등급 > 지금 공통값). min 규칙이 지금 공통값보다 낮거나 같으면 팀 등급은
    공통값에서 온 것이다 — 수집 뒤 관리자가 공통을 올린 기사가 늦은 판정으로 팀 알림이 되지 않게(E5, 재검토 경미 1)."""
    ok = ctx['late_ok'].get((team_id, nid))
    row = (ctx['trows'].get(nid) or {}).get(team_id)
    if not (ok and row and row.get('source') == 'rule' and row.get('rule_id') in ok):
        return False
    r = (ctx.get('rules_by_id') or {}).get(row.get('rule_id')) or {}
    if r.get('mode') == 'set':
        return True
    return _LEVEL_RANK.get(r.get('level'), -1) > _LEVEL_RANK.get(common, -1)


def _aud_trip(ctx: dict, aud: str, u: dict, ch: str) -> list:
    """후보 [(item, 알림 등급, 그 등급을 본 팀)] — 그 채널 등급인 것만, 입력 순서 유지. 이미 기록된 (단위, 채널, 기사)는 빼고,
    보통 채널은 같은 단위의 긴급 기록이 있는 기사도 뺀다(R7). 'late'는 R1 조건(팀 단위 = 그 팀, 실장 = 최고 등급을 본 팀 중
    하나)을 통과한 기사만. 계산할 수 없는 단위면 _AudSkip."""
    reason = ctx['broken_all'] or ctx['broken'].get(aud)
    if reason:
        raise _AudSkip(reason)
    late, lg, out = ctx['stage'] == 'late', ctx['logged'], []
    for it in ctx['cands']:
        nid = ctx['nid_of'].get(it['url'])
        if not nid or (aud, ch, nid) in lg or (ch == '보통' and (aud, '긴급', nid) in lg):
            continue
        ok_teams = [t for t in u['team_ids'] if _aud_late_team_ok(ctx, t, nid, it.get('urgency'))] if late else None
        if late and not ok_teams:
            continue
        lv, tms = _unit_level(u, it.get('urgency'), ctx['trows'].get(nid), ctx['rules_by_id'], alert=True)
        if lv != ch or (late and not set(tms) & set(ok_teams)):
            continue
        out.append((it, lv, tms))
    return out


def _aud_compute(ctx: dict, aud: str, u: dict, ch: str, trip: list) -> dict:
    """핵심을 그 단위의 비교군·사슬로 돌린다 — 항목 dict는 복사(공통 포장이 쓴 표시는 떼어 냄), 사건 묶기는 짧은 제한."""
    window = _aud_window(ctx)
    items = [{k: v for k, v in it.items() if k not in _ALERT_STRIP} for it, _, _ in trip]
    excl = {it['url'] for it, _, _ in trip}
    keep = _ALERT_CMP[ch]
    rows = [w for w in window if w.get('url') not in excl and _aud_view(ctx, aud, u, w) in keep]
    prior, prior_at = _prior_entries(rows, excl)
    group_fn = ctx['group_fn']
    if group_fn and time.monotonic() - ctx.get('t0', time.monotonic()) > ALERT_AI_BUDGET_S:
        # 채널 묶음 전체 예산 초과 — 남은 단위는 AI 없이(키워드 억제·별형 묶기만). 호출 하나의 20초 제한만으로는 팀 수만큼
        # 공통 즉시 배달이 밀린다(재검토 경미 2). AI 묶기는 억제를 더하는 쪽이라 빼도 알림이 빠지지는 않는다(fail-open 방향).
        if not ctx.get('budget_logged'):
            ctx['budget_logged'] = True
            print(f'[팀 알림] 사건 묶기 AI 예산 {ALERT_AI_BUDGET_S}초 초과 — 이번 채널의 남은 단위는 AI 없이 계산')
        group_fn = None
    # 리마인드 문턱(#256) — 같은 3일 창을 그 단위의 시각(_aud_view)으로 센다. 채널 등급 = keep(긴급 채널은 긴급만).
    remind_share = _event_share_fn(window, lambda w: _aud_view(ctx, aud, u, w) in keep)
    reps, sup, rem, _m = _suppress_core(items, prior, prior_at, _audience_chain(aud, ch), group_fn, log=None,
                                        remind_share=remind_share)
    return {'urls': [it['url'] for it, _, _ in trip], 'reps': reps, 'sup_rows': sup, 'remind_rows': rem}


def _aud_same_inputs(ctx: dict, aud: str, u: dict, ch: str, trip: list, base_urls) -> bool:
    """복사 조건 — 후보 목록(순서까지)이 기준과 같고, 비교군 창의 모든 기사에서 그 단위의 채널 비교군 소속이 공통값 기준과
    같다(팀 행이 이 채널의 후보·비교군을 바꾼 기사가 하나도 없다 — 핵심의 입력이 같다. 사슬만 다르다)."""
    if base_urls is None or [it['url'] for it, _, _ in trip] != list(base_urls):
        return False
    keep, excl = _ALERT_CMP[ch], {it['url'] for it, _, _ in trip}
    return all((_aud_view(ctx, aud, u, w) in keep) == (w.get('urgency') in keep)
               for w in _aud_window(ctx) if w.get('url') not in excl)


def _aud_base_urls(ctx: dict) -> list:
    """'c' 보통 기준의 후보 url 목록 — 기준을 이미 계산했으면 그때의 목록(그 뒤 'c' 기록이 생겨 다시 뽑으면 비어 버린다)."""
    if 'base' in ctx:
        return list(ctx['base']['urls'])
    return [it['url'] for it, _, _ in _aud_trip(ctx, 'c', _C_UNIT, '보통')]


def _aud_normal_base(ctx: dict) -> dict:
    """'c' 보통 결과 — 복사할 단위가 있거나 'c'가 활성일 때 한 번만 계산. 'c'가 활성 단위가 아니어도 기록은 'c' 이름으로 남긴다
    (큐는 없음) — 복사하는 팀 보통 채널의 사슬(#181 리마인드)이 쌓이게(R6)."""
    if 'base' not in ctx:
        res = _aud_compute(ctx, 'c', _C_UNIT, '보통', _aud_trip(ctx, 'c', _C_UNIT, '보통'))
        ctx['base'] = res
        if 'c' not in ctx['units']:
            rows, _ = _alert_log_rows('c', '보통', res['reps'], res['sup_rows'], res['remind_rows'], ctx['nid_of'])
            if rows:
                try:
                    _save_alert_log(rows)
                except Exception as e:
                    print(f'[팀 알림] c 보통 기준 기록 실패(무시 — 사슬만 한 칸 빈다): {str(e)[:80]}')
    return ctx['base']


def _audience_channels(ctx: dict, channels: tuple) -> int:
    """채널마다 단위를 돈다 — 복사 또는 계산(실패하면 'collect' 긴급은 공통 결과 복사 대체, 그 밖은 건너뜀) → 기록 먼저 →
    **그 단위·채널의 큐 행을 바로** 넣는다(R4 ②). 반환 = 큐에 넣은 '긴급' 행 수."""
    from subscriber_notify import news_row, queue_audience_rows
    stage, urgent = ctx['stage'], 0
    for ch in channels:
        if ch not in ALERT_CHANNELS:
            continue
        queued, ai0, lines = 0, ctx['ai'][0], 0
        for aud in ctx['auds']:
            u = ctx['units'][aud]
            if ch not in u['channels']:
                continue
            a0, mode, trip = ctx['ai'][0], '', []
            try:
                trip = _aud_trip(ctx, aud, u, ch)
                if not trip:
                    continue                     # 후보 없음 — 조용히
                if stage == 'collect' and aud == 'c':
                    res, mode = _aud_normal_base(ctx), '계산'
                elif stage == 'collect' and ch == '긴급' and _COMMON_ALERT is not None \
                        and _aud_same_inputs(ctx, aud, u, ch, trip, _COMMON_ALERT.get('urls')):
                    res, mode = _COMMON_ALERT, '복사'
                elif stage == 'collect' and ch == '보통' and _aud_same_inputs(ctx, aud, u, ch, trip, _aud_base_urls(ctx)):
                    res, mode = _aud_normal_base(ctx), '복사'
                else:
                    res, mode = _aud_compute(ctx, aud, u, ch, trip), '계산'
                log_rows, reps = _alert_log_rows(aud, ch, res['reps'], res['sup_rows'], res['remind_rows'], ctx['nid_of'])
                n_cand = len(trip)
            except Exception as e:
                known = isinstance(e, _AudSkip)  # 조회 실패는 이미 로그·오류 수에 들어갔다
                if not known:
                    _AUD_STATS['오류'] += 1
                if stage == 'collect' and ch == '긴급' and _COMMON_ALERT is not None:
                    # #44 '판정이 죽으면 시끄러운 쪽이 안전' — 그 단위에 공통 결과를 복사한다(표시 없음, 기록은 '[대체]')
                    if not known:
                        print(f'[팀 알림] {aud} {ch} 판정 오류 → 공통 결과로 대체: {str(e)[:80]}')
                    try:
                        log_rows, reps = _alert_log_rows(aud, ch, _COMMON_ALERT['reps'], _COMMON_ALERT['sup_rows'],
                                                         _COMMON_ALERT['remind_rows'], ctx['nid_of'])
                        for r in log_rows:
                            r['shared_keywords'] = '[대체]' + (' ' + r['shared_keywords'] if r['shared_keywords'] else '')
                    except Exception as e2:
                        _AUD_STATS['오류'] += 1
                        lines += 1
                        print(f'[팀 알림] {aud} {ch} 대체도 실패 — 이번 실행은 보내지 않음(무시): {str(e2)[:80]}')
                        continue
                    if not log_rows:
                        continue
                    trip, mode, n_cand = [], '대체: 공통 복사', len(log_rows)
                else:
                    lines += 1
                    print(f'[팀 알림] {aud} {ch} ' + (f'건너뜀 — {e}' if known else
                                                    f'판정 오류 — 이번 실행은 보내지 않음(무시): {str(e)[:80]}'))
                    continue
            n_sup = sum(1 for r in log_rows if r['outcome'] == 'suppressed')
            n_mrg = sum(1 for r in log_rows if r['outcome'] == 'merged')
            lines += 1
            try:
                fresh, ok_nids, n_bad, err = _save_alert_log(log_rows)
            except Exception as e:
                _AUD_STATS['오류'] += 1
                print(f'[팀 알림] {aud} {ch} 후보 {n_cand} → 기록 실패 — 이번 실행은 보내지 않음({mode}): {str(e)[:80]}')
                continue
            if n_bad:
                print(f'[팀 알림] {aud} {ch} 기록 {n_bad}건 못 씀(무시 — 도중에 지워진 기사 등): {err}')
            ctx['logged'].update((aud, ch, n) for n in ok_nids)
            info = {it['url']: (lv, tms) for it, lv, tms in trip}
            qrows, r_n = [], 0
            for nid, rep in reps:
                if nid not in fresh:
                    continue                     # 이미 있던 기록 = 다른 실행이 보냄 — 큐에 넣지 않는다
                lv, tms = info.get(rep.get('url'), (ch, []))
                item = {kk: vv for kk, vv in rep.items() if kk != '_label'}
                label = _alert_label(u, lv, rep.get('urgency'), tms, ctx['team_names'])
                if label:
                    item['_label'] = label
                row = news_row(aud, ch, item)
                if row:
                    qrows.append(row)
                    r_n += 1 if rep.get('_remind') else 0
            done = queue_audience_rows(sb, qrows) if qrows else {}
            n_in = sum(done.values())
            if n_in < len(qrows):
                _AUD_STATS['오류'] += 1
                print(f'[팀 알림] {aud} {ch} 기록 {len(qrows) - n_in}건은 들어갔으나 큐 적재 실패 — 이 기사들은 다시 가지 않음')
            queued += done.get(ch, 0)
            _AUD_STATS[ch] += done.get(ch, 0)
            print(f'[팀 알림] {aud} {ch} 후보 {n_cand} → 보냄 {n_in}(리마인드 {r_n})·억제 {n_sup}·묶음 {n_mrg} ({mode})'
                  f' · AI {ctx["ai"][0] - a0}회')
        ai_n = ctx['ai'][0] - ai0
        _AUD_STATS['ai'] += ai_n
        if lines:
            print(f'[팀 알림] 합계({stage}·{ch}) — 큐 {ch} {queued}건 · AI {ai_n}회')
        if ch == '긴급':
            urgent += queued
    return urgent


def _deliver_now(needed: bool):
    """즉시 배달 호출 한 번(#252). needed가 거짓이면 부르지 않고 None, 불렀으면 성공(HTTP 200) 여부. 예외를 던지지 않는다
    (정시 :25가 받쳐 준다). main은 이 값으로 늦은 판정 알림의 두 번째 호출 여부를 정한다(R10)."""
    if not needed:
        return None
    try:
        from subscriber_notify import _trigger_delivery
        return bool(_trigger_delivery())
    except Exception as e:
        print(f'[구독자 배달] 즉시 호출 실패(무시 — 정시 :25에 발송): {str(e)[:120]}')
        return False


# ═══════════════════════════════════════════════════════
#  메인
# ═══════════════════════════════════════════════════════

def main():
    now_str = datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')
    print(f'{"="*50}')
    print(f'[시작] {now_str}')
    print(f'{"="*50}')
    _reset_audience_state()          # 사건 묶기 메모·받는 단위 준비·팀 알림 합계는 한 실행 안에서만 쓴다(#252)

    # ── 크롤링 (GitHub Actions 10분마다 실행) ────────────
    all_items: list = []

    # 1순위: 네이버 뉴스 검색
    naver_items, naver_fail = crawl_naver_news()
    all_items += naver_items

    # 네이버 차단 감지 → Google RSS 폴백
    # (전체 키워드 50% 이상 실패 또는 수집 5건 미만)
    if naver_fail > len(NEWS_SEARCH_KEYWORDS) * 0.5 or len(naver_items) < 5:
        print(f'[폴백] 네이버 부진({len(naver_items)}건, 실패{naver_fail}개) → Google RSS 전환')
        all_items += crawl_google_news_rss()

    # 정부기관은 PC Cowork gov_notice_crawler.py(매일 17:00)가 담당
    print(f'[수집] 총 {len(all_items)}건')

    # 기존 대조는 수집 뒤 후보만 (#234) — 판정은 후보의 포함 여부뿐이라 전량 명단과 결과가 같다
    existing_urls, existing_titles = get_existing_urls(all_items)

    new_items = save_new_items(all_items, (existing_urls, existing_titles))
    print(f'[신규] {len(new_items)}건')

    # ── 긴급 기사 즉시 알림 (발행 24시간 이내만) ────────
    # 판정은 모듈 함수 is_within_24h(#252 — 받는 단위별 알림도 같은 기준 시각으로 쓴다)
    now_kst = datetime.now(KST)
    cutoff_24h = now_kst - timedelta(hours=24)

    urgent_items = [i for i in new_items if i.get('urgency') == '긴급' and is_within_24h(i, cutoff_24h)]
    skipped = [i for i in new_items if i.get('urgency') == '긴급' and not is_within_24h(i, cutoff_24h)]
    if skipped:
        print(f'[긴급] {len(skipped)}건 발행 24시간 초과 — 알림 제외')

    # ── 재알림 억제 (배경역사 #44) ──────────────────────
    # 같은 사건 재보도가 매시간 새 긴급 기사로 들어와 텔레그램이 며칠간 수십 통
    # (KT 과징금: 8일 339건 알림). 최근 3일 내 이미 DB에 있던 긴급 기사와 제목이
    # 유사하면 후속 보도로 보고 알림만 생략한다 — 수집·브리핑·대시보드에는 그대로 반영.
    # 실패 시에는 전부 알림(fail-open): 억제가 목적이므로 판정이 죽으면 시끄러운 쪽이 안전.
    urgent_items = suppress_repeat_alerts(urgent_items)

    common_queued = False            # 공통 구독자 긴급 행이 큐에 들어갔나 — 즉시 배달 호출(아래 한 번) 여부(#252)
    if urgent_items:
        print(f'[긴급] {len(urgent_items)}건 — 알림 발송')
        send_telegram(urgent_items)
        send_urgent_email(urgent_items)
        # 구독자 봇: 즉시 발송이 아니라 큐에 적재 → 각자 고른 수신 시각에 모아서 발송된다.
        # 반드시 억제·클러스터링을 거친 urgent_items로만 호출할 것(#44).
        # 기사당 1행으로 적재한다(2026-08-03) — 태그를 데이터로 넘겨야 구독자 관심분야 필터가
        # 성립하고, 헤더·번호·칩은 구독자마다 달라 발송 측(Edge)이 조립한다.
        # 운영자 알림(send_telegram/send_urgent_email)보다 **뒤에** 두고 try/except로 격리하는
        # 현재 순서를 유지할 것 — 큐 장애가 유일한 감시 채널인 운영자 수신을 끊으면 안 된다.
        # trigger=False(#252) — 즉시 배달 호출은 팀 단위 행까지 넣은 뒤 아래에서 **한 번만**(두 번 부르면 두 발송 실행이
        # 겹쳐 같은 사람에게 같은 행이 두 번 갈 수 있다 — 워터마크 갱신 전 읽기).
        try:
            from subscriber_notify import queue_news_items
            common_queued = queue_news_items(sb, urgent_items, trigger=False)
        except Exception as e:
            print(f'[구독자 큐 적재 실패(무시)] {e}')
    else:
        print('[긴급] 해당 없음')

    # ── 받는 단위별 알림 — 팀·실장 중요 + 「중요+보통」의 보통 (#252) ──
    # 긴급 채널(전 단위) → 즉시 배달 호출 한 번 → 보통 채널(즉시 호출 불필요 — :25 정기 발송 몫). 어떤 실패도 공통 알림·배달·
    # heartbeat를 막지 않는다 — 공통 행이 들어갔으면 팀 단계가 죽어도 즉시 배달 호출은 반드시 나간다(finally).
    team_urgent = 0
    first_delivery = None            # 즉시 배달 호출 결과: None = 안 부름, True = 200, False = 실패(R10)
    try:
        team_urgent = run_audience_alerts('collect', new_items=new_items, cutoff_24h=cutoff_24h, channels=('긴급',))
    except Exception as e:
        print(f'[팀 알림] 실패(무시): {e}')
    finally:
        first_delivery = _deliver_now(bool(common_queued) or team_urgent > 0)
    try:
        run_audience_alerts('collect', new_items=new_items, cutoff_24h=cutoff_24h, channels=('보통',))
    except Exception as e:
        print(f'[팀 알림] 보통 채널 실패(무시): {e}')

    print('[모닝 브리핑] morning_briefing.yml GitHub Actions 담당 — 건너뜀')

    # ── 팀 규칙 문장 조건 — 대기 행 판정 + 팀별 월 비용 알림 (#251) ──
    # 긴급 알림·구독자 큐 **뒤** — Haiku 판정이 느려도 알림을 늦추지 않는다. 새 기사가 없는 실행에서도 돈다(본문 대기·
    # 대시보드가 넣은 지난 기사 요청). 대기 행이 없으면 조회 1번으로 끝난다. 어떤 실패도 heartbeat·이슈 제안을 막지 않는다.
    try:
        process_open_sentence_verdicts()
    except Exception as e:
        print(f'[문장 판정] 실패(무시): {e}')

    # ── 늦게 생긴 팀 등급의 알림 (#252) ── 수집 때 생긴 문장 판정 대기 행이 이번 실행에 참으로 판정되어 그 팀 행을 정한
    # 기사만(대시보드 요청·되살림·관리자 재대기 제외). 긴급 행이 들어갔을 때만 즉시 배달을 한 번 더 부른다 — 단, 앞 호출이
    # 실패(200 아님)했으면 그 발송 실행이 아직 돌고 있을 수 있어 겹치지 않게 생략(:25 정시가 받친다, R10). 없으면 조회 0번.
    late_urgent = 0
    try:
        late_urgent = run_audience_alerts('late', cutoff_24h=cutoff_24h)
    except Exception as e:
        print(f'[팀 알림] 늦은 판정 알림 실패(무시): {e}')
    if late_urgent > 0 and first_delivery is False:
        print('[구독자 배달] 앞 즉시 호출이 성공하지 않아 두 번째 호출 생략(겹친 발송 방지) — 늦은 판정 알림은 정시 :25에 발송')
    else:
        _deliver_now(late_urgent > 0)

    # ── 크롤러 heartbeat ── (check_news_health가 '크롤러 정상 vs 고장' 구분에 사용)
    # 신규 0건이어도 '크롤러는 돌았다'를 기록 → 주말 등 '뉴스 없음' 오경보 방지. 실패해도 무시.
    # 받는 단위가 있으면 끝에 ' team=긴급N/보통M/오류K'(#252 — 운영 상태 탭이 메모를 그대로 보여 준다, 없으면 종전 그대로)
    sb_heartbeat(sb, 'last_crawl_run', f'new={len(new_items)} total={len(all_items)}' + audience_note())

    # ── 이슈맵 자동 제안 파이프 (2026-08-26, P4) ──
    # fail-open 격리: 제안 파이프의 어떤 실패도 크롤러 본연의 수집·통지에 영향을 주면 안 된다.
    # 하루 4회만(05·11·15·20시 KST 실행, 2026-09-10 #153) — 매시 돌리면 경계 판정 Sonnet 1콜이 매시 나가고
    # (월 $1~3) 한 시간치 2~3건으로 만든 파편 제안이 61% 기각됐다(#111·#119). 제안은 알림이 아니라
    # 운영자 검토 큐라 최대 6시간 지연은 무해. 시각은 :47 pg_cron 주 트리거 기준.
    try:
        _kst_hour = datetime.now(timezone(timedelta(hours=9))).hour
        # 10분 크롤(#174) 뒤로 시(hour) 조건만으로는 그 시간대에 6번씩 돌았다(하루 24회, 09-20~23 실측) —
        # 재실행 가드를 함께 건다(#194, 시간은 ISSUE_SUGGEST_GUARD_HOURS 주석 참조).
        if _kst_hour in ISSUE_SUGGEST_HOURS and ran_recently(sb, 'last_issue_suggest_run', ISSUE_SUGGEST_GUARD_HOURS):
            print(f'[이슈 제안] {_kst_hour}시 — 이번 시간대에 이미 실행됨, 건너뜀')
        elif _kst_hour in ISSUE_SUGGEST_HOURS:
            from issue_suggest import run_suggest
            run_suggest(sb)
            sb_heartbeat(sb, 'last_issue_suggest_run', f'{_kst_hour}시 실행')
        else:
            print(f'[이슈 제안] {_kst_hour}시 — 실행 시각({sorted(ISSUE_SUGGEST_HOURS)}) 아님, 건너뜀')
    except Exception as e:
        print(f'[이슈 제안 파이프 실패(무시)] {e}')

    print(f'{"="*50}')
    print('[완료]')


if __name__ == '__main__':
    main()
