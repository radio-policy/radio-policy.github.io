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
  · 사고 대응의 적정성이 쟁점이 된 보도 — 신고 지연, 로그 삭제, 증거인멸, 조사 방해 의혹
  · 진행 중인 침해사고·제재 사건의 수사·조사·소송 경과와 선고·처분 일정
  ⚠️ 성과 홍보·구축 완료·예방 캠페인·주의보는 사고 보도가 아니다 → 금주검토 이하
  ⚠️ 이미 끝난 과거 사고를 돌아보는 회고·통계·순위 기사도 사고 보도가 아니다 → 금주검토
- **국정감사에 SK텔레콤이(또는 통신3사가 일괄로) 증인·참고인으로 채택·신청·소환·출석하는 보도** — 채택 단계든
  출석 당일이든 즉시대응. 타사만 소환된 국감 기사는 이 항목이 아니다(다른 항목으로 판단).
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
- **플랫폼 사업자의 개인정보 사건에 정부가 전기통신사업법·정보통신망법으로 조사·제재·법적 책임을
  검토한다고 밝힌 것** (예: 검색사업자의 디지털성범죄 피해자 정보 노출과 정부의 책임 추궁)
- **경쟁사 사안 중 업계 공통 규제로 번질 것** — 정부의 통신사 전수조사·일괄 점검, 국회·시민단체가
  통신사 전반을 겨냥한 문제 제기, 동일 설비·기술·관행에서 비롯된 사고.
  **"우리도 같은 지적을 받을 수 있는가"로 판단한다.**
  ⚠️ 경쟁사의 개별 경영·세무·상품·실적 사안은 여기 해당하지 않는다 → 금주검토

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
    """importance_feedback 전체 로드 (실행당 1회, 최신순 최대 500건)"""
    global _feedback_rows_cache
    if _feedback_rows_cache is None:
        try:
            res = sb.table('importance_feedback').select('title,user_importance') \
                .order('updated_at', desc=True).limit(500).execute()
            _feedback_rows_cache = [r for r in (res.data or []) if r.get('title') and r.get('user_importance')]
            if _feedback_rows_cache:
                print(f'[피드백] 누적 사례 {len(_feedback_rows_cache)}건 로드')
        except Exception as e:
            print(f'[피드백] importance_feedback 조회 실패(무시): {e}')
            _feedback_rows_cache = []
    return _feedback_rows_cache


def _fb_tokens(s: str) -> set:
    return set(re.findall(r'[가-힣A-Za-z0-9]{2,}', (s or '').lower()))


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
    행 순서가 달라져 페이지 경계에서 행이 빠지거나 겹친다(#233, 사내 export_news 28건 누락과 같은 부류)."""
    rows, page, step = [], 0, 1000
    while True:
        res = (sb.table(table).select(columns).order(order)
               .range(page * step, (page + 1) * step - 1).execute())
        chunk = res.data or []
        rows.extend(chunk)
        if len(chunk) < step:
            return rows
        page += 1


def get_existing_urls() -> set:
    """Supabase에 이미 저장된 URL + 제목 목록 조회 (Google RSS 중복 방지)
    + 사용자가 대시보드에서 삭제한 기사(deleted_news)도 포함해 재수집 방지"""
    data = _fetch_all_rows('news_feed', 'url,title')
    urls   = {row['url']   for row in data if row.get('url')}
    titles = {row['title'] for row in data if row.get('title')}
    try:
        ddata = _fetch_all_rows('deleted_news', 'url,title')
        urls   |= {row['url']   for row in ddata if row.get('url')}
        titles |= {row['title'] for row in ddata if row.get('title')}
    except Exception as e:
        print(f'[삭제목록] deleted_news 조회 실패(무시): {e}')
    return urls, titles


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
                # EXCLUDE_KEYWORDS(스포츠·선거·부동산 오탐)는 값싼 사전 차단이라 그대로 둔다.
                if not is_personnel and any(k in title for k in EXCLUDE_KEYWORDS):
                    continue
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
                # 네이버 경로와 동일 — RADIO_KEYWORDS 포함 게이트 폐지, EXCLUDE는 유지 (2026-08-03)
                if not is_personnel and any(k in title for k in EXCLUDE_KEYWORDS):
                    continue
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

# 비관련 기사 제외 키워드 — 스포츠·연예·부동산 등
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
#  fail-open 원칙: 키 없음·판정 실패 시 기존 RADIO_KEYWORDS 키워드 필터로 되돌아간다
#  (선별이 죽었다고 수집 자체가 멈추면 무음 누락이 된다 — 배경역사 #39).
# ═══════════════════════════════════════════════════════

ISSUE_SUGGEST_HOURS = {5, 11, 15, 20}   # 이슈맵 자동 제안 실행 시각(KST, #153) — 매시 → 하루 4회
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


_URGENCY_RULES = None   # 실행당 1회 로드(모듈 전역 캐시)


def load_urgency_rules() -> list:
    """표 urgency_rules의 공통 규칙(team_id null, enabled)을 position 순으로. 실패·형식 오류·0건이면 비상 사본(#216).
    1단계는 공통 규칙만 적용한다 — 팀 규칙은 팀 값 저장소(2단계)가 생겨야 적용할 자리가 있다."""
    global _URGENCY_RULES
    if _URGENCY_RULES is not None:
        return _URGENCY_RULES
    rules, src = None, 'db'
    try:
        rows = sb.table('urgency_rules').select('*').is_('team_id', 'null').eq('enabled', True)             .order('position').order('id').execute().data or []
        errs = urgency_rules.validate_rules(rows)
        if errs:
            print(f'[규칙] 표 형식 오류 {len(errs)}건 — 비상 사본 사용: {errs[:3]}')
        elif rows:
            rules = rows
        else:
            print('[규칙] 표에 켜진 공통 규칙 0건 — 비상 사본 사용')
    except Exception as e:
        print(f'[규칙] 표 조회 실패 — 비상 사본 사용: {str(e)[:80]}')
    if rules is None:
        rules, src = urgency_rules.URGENCY_RULES_FALLBACK, 'fallback'
    print(f'[규칙] {len(rules)}개 로드({src})')
    _URGENCY_RULES = rules
    return rules


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


def _load_screen_cache(criteria_hash: str) -> dict:
    """{url: title_hash} — 현재 기준문으로 판정된 행만. 실패 시 빈 dict(전량 판정으로 진행)."""
    try:
        rows = _fetch_all_rows('news_screen_cache', 'url,title_hash,criteria_hash', order='url')
        return {r['url']: r['title_hash'] for r in rows
                if r.get('criteria_hash') == criteria_hash}
    except Exception as e:
        print(f'[선별 캐시] 로드 실패(전량 판정으로 진행): {str(e)[:80]}')
        return {}


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
    """폴백 판정 — 종전 수집 기준(제목에 RADIO_KEYWORDS 포함)과 동일."""
    return any(k in (item.get('title') or '') for k in RADIO_KEYWORDS)


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
        screen_cache = _load_screen_cache(criteria_hash)
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


# 긴급도 판정용 네이버 요약(url → ≤300자). 본문 수집이 실패한 기사(#200 이전에는 Actions 전건)에서
# 이것이 없으면 긴급도는 **제목 한 줄**만 보고 매겨진다(2026-09-24 확인, #188). DB에는 저장하지 않는다 —
# content에 넣으면 refetch_content.py의 '100자 미만 = 재수집 대상' 조건이 깨진다.
_URGENCY_SUMMARY: dict = {}


# ═══════════════════════════════════════════════════════
#  Supabase 저장
# ═══════════════════════════════════════════════════════

def grade_urgency(valid: list, rules: list, classify=None) -> dict:
    """⑤ 긴급도 — 공통 낱말 규칙(#216) + Haiku 판정을 합쳐 item['urgency'/'importance'/'urgency_rule']을 채운다.
    규칙은 AI보다 먼저 맞춰 본다(제목 + 네이버 요약만, 본문 금지). set 적중 = 그 값, AI 콜 생략 /
    min 적중 = AI를 돌린 뒤 하한만(max) / 적중 id는 값이 안 바뀌어도 urgency_rule에 남긴다(출처 표시·사내 정본).
    알림·큐·브리핑은 저장값을 쓰므로 따로 고칠 곳이 없다. 반환 = 로그용 집계."""
    classify = classify or classify_urgency
    hits, changed_n, skipped_ai = {}, 0, 0
    for item in valid:
        summary = _URGENCY_SUMMARY.get(item.get('url', ''), '')
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
    if hits:
        print(f'[규칙] 적중 {sum(hits.values())}건 (' + ', '.join(f'{k}×{v}' for k, v in hits.items()) +
              f', 값 변경 {changed_n}건, AI 생략 {skipped_ai}건)')
    else:
        print('[규칙] 적중 0건')
    return {'hits': hits, 'changed': changed_n, 'skipped_ai': skipped_ai}


def save_new_items(items: list, existing_data: tuple) -> list:
    """규칙1: 15일 이내 & 날짜 확인된 신규 기사만 저장
    existing_data: (existing_urls: set, existing_titles: set)
    URL + 제목 이중 중복 체크 (Google RSS 리다이렉트 URL 대응)

    순서(2026-08-03 재배치): 중복 제거 → ①조기 날짜 필터 → ②Haiku 관련성 선별
    → ③본문 수집 → ④날짜 필터 → ⑤긴급도 분류 → 저장.
    본문 수집·긴급도 분류는 선별 통과분에만 돈다(둘 다 건당 비용이 큰 단계).
    """
    existing_urls, existing_titles = existing_data
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
    grade_urgency(valid, load_urgency_rules())

    try:
        # upsert(on_conflict=url, ignore_duplicates): 크롤러 동시 실행 시
        # 같은 기사 중복 저장 방지 (idx_news_feed_url_unique와 한 쌍)
        sb.table('news_feed').upsert(
            valid, on_conflict='url', ignore_duplicates=True
        ).execute()
    except Exception as e:
        print(f'[저장 오류] Supabase upsert 실패: {e}')
        return []
    urgent_count = sum(1 for i in valid if i.get('urgency') == '긴급')
    print(f'[저장] {len(valid)}건 저장 완료 (긴급 {urgent_count}건)')
    return valid


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
    어떤 오류든 나면 원본 그대로 반환(fail-open) — 판정이 죽어서 알림까지 죽으면 안 된다."""
    if not urgent_items:
        return urgent_items
    try:
        from news_dedup import extract_keywords, is_followup, cluster_star

        # 이번 실행에서 방금 저장한 기사는 비교 대상에서 빼야 한다 (자기 자신과 비교 방지)
        batch_urls = {i.get('url') for i in urgent_items}
        cutoff_3d = (datetime.now(KST) - timedelta(days=3)).isoformat()
        prior, prior_at = [], {}
        resp = sb.table('news_feed').select('title,url,created_at') \
            .eq('urgency', '긴급').gte('created_at', cutoff_3d) \
            .order('created_at', desc=True).limit(1000).execute()
        for r in (resp.data or []):
            if r.get('url') not in batch_urls:
                prior.append({'title': r.get('title') or '', 'kw': extract_keywords(r.get('title') or '')})
                prior_at.setdefault(r.get('title') or '', r.get('created_at'))   # 정렬이 최신순 = 가장 최근 것

        # ── 하루 1회 리마인드 (2026-09-21 #181) ──────────────────────────────
        # 억제는 사슬로 이어진다 — 실측(30일) 억제 821건 중 660건(80%)이 '이미 억제된 기사'에
        # 걸려서 막혔다. 그래서 며칠씩 이어지는 사건은 첫 알림 뒤 영영 다시 오지 않는다
        # (9/21 LGU+ 해킹 은폐: 긴급 8건 전부 억제, 뿌리는 9/18 기사). 사건의 **대표**(실제로
        # 알림이 나간 기사)가 24시간을 넘었으면 재보도 1건을 '리마인드'로 통과시킨다.
        # 통과분은 alert_suppress_log에 `[리마인드]`로 남긴다 — 미발송이 아니라 발송 기록이며,
        # 사슬을 여기서 끊어 다음 24시간을 새로 센다. 사내판 다리도 이 접두사로 구분한다(#180).
        REMIND_AFTER_H = 24
        sup_chain = {}                       # 억제된 제목 → 그때 걸린 기존 제목(사슬 한 칸)
        try:
            cutoff_10d = (datetime.now(KST) - timedelta(days=10)).isoformat()
            _lg = (sb.table('alert_suppress_log').select('article_title,matched_title,shared_keywords')
                   .gte('created_at', cutoff_10d).order('created_at').execute().data) or []
            for r in _lg:
                if str(r.get('shared_keywords') or '').startswith('[리마인드]'):
                    continue                 # 리마인드는 '나간 기사' — 사슬을 끊는다
                if r.get('article_title'):
                    sup_chain[r['article_title']] = r.get('matched_title') or ''
        except Exception as e:
            print(f'[긴급 억제] 억제 사슬 조회 실패 — 이번 실행은 리마인드 없이 종전대로: {e}')

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

        passed, sup_rows, remind_rows, passed_kw = [], [], [], []
        for it in urgent_items:
            kw = extract_keywords(it.get('title') or '')
            matched = None
            for pv in prior:
                if is_followup(kw, pv['kw'], it.get('title') or '', pv['title']):
                    matched = pv
                    break
            if matched:
                age_h = _rep_age_h(matched['title'])
                if age_h is None or age_h >= REMIND_AFTER_H:
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
        if passed and prior and ANTHROPIC_API_KEY:
            cand = []                                  # 후보 기보도(제목 중복 제거, 최대 10건)
            seen_t = set()
            for pv in prior:
                if len(seen_t) >= 10:
                    break
                if pv['title'] and pv['title'] not in seen_t and any(kw & pv['kw'] for kw in passed_kw):
                    seen_t.add(pv['title'])
                    cand.append(pv)
            if cand:
                from news_dedup import group_same_event
                titles = [it.get('title') or '' for it in passed] + [pv['title'] for pv in cand]
                gidx = group_same_event(titles, ANTHROPIC_API_KEY)
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
                        print(f'[긴급 억제] 의미 판정으로 실행 간 재보도 {len(drop)}건 판정(리마인드 포함)')
                        passed, passed_kw = kept, kept_kw

        # 같은 실행분 내 유사 기사 묶기 — 사건 첫날 첫 실행에 재보도 수십 건이
        # 한꺼번에 들어오면 한 통에 수십 줄이 되는 것을 대표 1건으로 줄인다
        groups = []                      # [(대표, [묶인 것들])] — 아래 2차 묶기와 형태를 맞춘다
        for rep, members in cluster_star(passed):
            groups.append((rep, list(members)))

        # ── 2차: 키워드로 못 묶인 대표들을 Haiku가 의미로 다시 묶는다 (#92) ──
        # 매체마다 관점이 달라 제목에 공통 단어가 거의 없는 사건이 있다(공정위 불공정약관 4건:
        # 쌍별 공유 키워드 최대 1개). 어휘로는 못 넘으므로 여기서만 의미 판정을 쓴다.
        # 실패하면 1차 결과를 그대로 쓴다(fail-open) — 판정이 죽어서 알림이 죽으면 안 된다.
        if len(groups) >= 2 and ANTHROPIC_API_KEY:
            from news_dedup import group_same_event
            merged_idx = group_same_event([g[0].get('title') or '' for g in groups], ANTHROPIC_API_KEY)
            if merged_idx and len(merged_idx) < len(groups):
                regrouped = []
                for idxs in merged_idx:
                    head = groups[idxs[0]]
                    others = [m for i in idxs[1:] for m in ([groups[i][0]] + groups[i][1])]
                    regrouped.append((head[0], head[1] + others))
                print(f'[긴급 억제] 의미 판정으로 {len(groups)}묶음 → {len(merged_idx)}묶음')
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

        if remind_rows:
            print(f'[긴급 억제] 대표가 24시간을 넘겨 리마인드로 통과 {len(remind_rows)}건')
        if sup_rows or remind_rows:
            n_run = sum(1 for r in sup_rows if r['shared_keywords'] == '[실행내묶음]')
            print(f'[긴급 억제] 알림 미발송 {len(sup_rows)}건 기록 (3일 내 기보도 {len(sup_rows) - n_run}건 · 실행내 묶음 {n_run}건)')
            try:
                sb.table('alert_suppress_log').insert(sup_rows + remind_rows).execute()
            except Exception as e:
                print(f'[긴급 억제] 로그 저장 실패(무시): {e}')
        merged = len(passed) - len(reps)
        if merged:
            print(f'[긴급 억제] 실행분 내 유사 {merged}건 대표에 병합')
        return reps
    except Exception as e:
        print(f'[긴급 억제] 판정 오류 → 전부 알림(fail-open): {e}')
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

    lines.append('📊 <a href="https://radio-policy.github.io/?p=news">대시보드</a>')
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
        plain_lines.append('📊 대시보드: https://radio-policy.github.io/?p=news')
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
대시보드: <a href="https://radio-policy.github.io/?p=news">https://radio-policy.github.io/?p=news</a>
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
#  메인
# ═══════════════════════════════════════════════════════

def main():
    now_str = datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')
    print(f'{"="*50}')
    print(f'[시작] {now_str}')
    print(f'{"="*50}')

    # ── 크롤링 (GitHub Actions 매시간 실행) ────────────
    existing_urls, existing_titles = get_existing_urls()
    print(f'[기존] Supabase 저장 항목 {len(existing_urls)}건')

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

    new_items = save_new_items(all_items, (existing_urls, existing_titles))
    print(f'[신규] {len(new_items)}건')

    # ── 긴급 기사 즉시 알림 (발행 24시간 이내만) ────────
    now_kst = datetime.now(KST)
    cutoff_24h = now_kst - timedelta(hours=24)

    def is_within_24h(item):
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

    urgent_items = [i for i in new_items if i.get('urgency') == '긴급' and is_within_24h(i)]
    skipped = [i for i in new_items if i.get('urgency') == '긴급' and not is_within_24h(i)]
    if skipped:
        print(f'[긴급] {len(skipped)}건 발행 24시간 초과 — 알림 제외')

    # ── 재알림 억제 (배경역사 #44) ──────────────────────
    # 같은 사건 재보도가 매시간 새 긴급 기사로 들어와 텔레그램이 며칠간 수십 통
    # (KT 과징금: 8일 339건 알림). 최근 3일 내 이미 DB에 있던 긴급 기사와 제목이
    # 유사하면 후속 보도로 보고 알림만 생략한다 — 수집·브리핑·대시보드에는 그대로 반영.
    # 실패 시에는 전부 알림(fail-open): 억제가 목적이므로 판정이 죽으면 시끄러운 쪽이 안전.
    urgent_items = suppress_repeat_alerts(urgent_items)

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
        try:
            from subscriber_notify import queue_news_items
            queue_news_items(sb, urgent_items)
        except Exception as e:
            print(f'[구독자 큐 적재 실패(무시)] {e}')
    else:
        print('[긴급] 해당 없음')

    print('[모닝 브리핑] morning_briefing.yml GitHub Actions 담당 — 건너뜀')

    # ── 크롤러 heartbeat ── (check_news_health가 '크롤러 정상 vs 고장' 구분에 사용)
    # 신규 0건이어도 '크롤러는 돌았다'를 기록 → 주말 등 '뉴스 없음' 오경보 방지. 실패해도 무시.
    sb_heartbeat(sb, 'last_crawl_run', f'new={len(new_items)} total={len(all_items)}')

    # ── 이슈맵 자동 제안 파이프 (2026-08-26, P4) ──
    # fail-open 격리: 제안 파이프의 어떤 실패도 크롤러 본연의 수집·통지에 영향을 주면 안 된다.
    # 하루 4회만(05·11·15·20시 KST 실행, 2026-09-10 #153) — 매시 돌리면 경계 판정 Sonnet 1콜이 매시 나가고
    # (월 $1~3) 한 시간치 2~3건으로 만든 파편 제안이 61% 기각됐다(#111·#119). 제안은 알림이 아니라
    # 운영자 검토 큐라 최대 6시간 지연은 무해. 시각은 :47 pg_cron 주 트리거 기준.
    try:
        _kst_hour = datetime.now(timezone(timedelta(hours=9))).hour
        # 10분 크롤(#174) 뒤로 시(hour) 조건만으로는 그 시간대에 6번씩 돌았다(하루 24회, 09-20~23 실측) —
        # 5시간 가드를 함께 건다(#194).
        if _kst_hour in ISSUE_SUGGEST_HOURS and ran_recently(sb, 'last_issue_suggest_run', 5):
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
