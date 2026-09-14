#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
전파정책 AI — 모닝 브리핑 생성 스크립트
매일 08:00 KST (23:00 UTC) GitHub Actions에서 실행

동작:
1. news_feed에서 최근 24h 기사 중 본문(content) 확인된 것만 조회
2. Claude Haiku로 브리핑 생성 (본문 기반 요약)
3. daily_briefings 저장
4. 브리핑에 포함된 기사의 한 줄 요약 → news_feed.summary 역저장
5. 텔레그램 + 이메일 발송
"""

import os
import re
import smtplib
import json
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests
import anthropic
from supabase import Client
from sb_client import make_client
import api_usage; api_usage.install()   # Anthropic usage 기록(#152) — 호출부 무변경, fail-open
import notify   # 텔레그램 전송 공용 유틸 (개선⑪) — 전송부만 위임

# ── 환경변수 ──────────────────────────────────────────────
SUPABASE_URL       = os.environ['SUPABASE_URL']
SUPABASE_KEY       = os.environ['SUPABASE_SERVICE_KEY']
ANTHROPIC_API_KEY  = os.environ.get('ANTHROPIC_API_KEY', '')
EMAIL_FROM         = os.environ.get('EMAIL_FROM', '')
EMAIL_PASS         = os.environ.get('EMAIL_PASSWORD', '')
EMAIL_TO           = os.environ.get('EMAIL_TO', '')
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID   = os.environ.get('TELEGRAM_CHAT_ID', '')
RESEND_API_KEY     = os.environ.get('RESEND_API_KEY', '')

KST = timezone(timedelta(hours=9))
sb: Client = make_client(SUPABASE_URL, SUPABASE_KEY)


# ═══════════════════════════════════════════════════════
#  STEP 1 — 본문 확인된 기사 조회
# ═══════════════════════════════════════════════════════

def load_briefing_excluded() -> set:
    """브리핑에서 뺄 기사 URL 집합 — app_config.briefing_excluded_urls (JSON 배열).

    필요한 이유(#85): 오탐 기사를 브리핑에서만 빼는 수단이 없었다.
      · 삭제 → 대시보드·자문 검색에서도 사라져 과하다
      · published_at 조작 → 사실 왜곡
      · urgency 하향 → 브리핑은 24h 전체를 보므로 그래도 들어간다
    발단은 「여수 죽림터널 라디오 중계기 고장」 — 도로터널 FM 방송 설비(관리 지자체, 근거
    국토부 예규)라 통신·SKT 접점이 없는데 긴급으로 잡혔다.
    app_config를 쓰는 이유: 컬럼 추가 없이 되고, 목록을 눈으로 확인·수정할 수 있다.
    조회 실패는 빈 집합으로 넘긴다(fail-open) — 제외가 안 되는 것이 브리핑이 안 나가는 것보다 낫다."""
    try:
        rows = sb.table('app_config').select('value') \
            .eq('key', 'briefing_excluded_urls').limit(1).execute().data
        if rows and rows[0].get('value'):
            urls = json.loads(rows[0]['value'])
            if isinstance(urls, list):
                return {str(u).strip() for u in urls if str(u).strip()}
    except Exception as e:
        print(f'[제외목록] 조회 실패(무시): {str(e)[:80]}')
    return set()


def fetch_items_with_content() -> list:
    """최근 24h 기사 중 content 있는 것만 반환 (id 포함)"""
    cutoff = (datetime.now(KST) - timedelta(hours=24)).isoformat()
    try:
        resp = sb.table('news_feed') \
            .select('id,title,source,url,published_at,content,urgency') \
            .gte('published_at', cutoff) \
            .not_.is_('content', 'null') \
            .order('published_at', desc=True) \
            .limit(500) \
            .execute()
        # limit 60이던 시절, 대형 사건 재보도가 하루 261건 쏟아지자 조회 60건 중 55건이
        # 한 사건이었고 다른 뉴스가 브리핑에서 통째로 밀려났다(배경역사 #44).
        # 넉넉히 받아 클러스터링으로 줄이는 방식으로 변경. 2026-09-13: 24h 수집이 300건대로
        # 늘어 limit 300이면 창의 앞쪽(어제 아침)이 잘려 나가므로 500으로 올림(#161).
        items = [it for it in (resp.data or []) if it.get('content') and len(it['content'].strip()) > 50]
        excluded = load_briefing_excluded()
        if excluded:
            before = len(items)
            items = [it for it in items if (it.get('url') or '').strip() not in excluded]
            if before != len(items):
                print(f'[제외목록] 브리핑에서 {before - len(items)}건 제외')
        print(f'[조회] 본문 확인 기사 {len(items)}건 / 24h 내')
        return items
    except Exception as e:
        print(f'[조회 오류] {e}')
        return []


def fetch_items_fallback() -> tuple:
    """본문 0건일 때 폴백: 요약(summary) → 제목(title) 순으로 사용해 '빈 브리핑' 방지.
    generate_briefing이 그대로 동작하도록 사용 텍스트를 content 자리에 주입.
    반환: (items, mode) — mode in {'요약','헤드라인',''}"""
    cutoff = (datetime.now(KST) - timedelta(hours=24)).isoformat()
    # 1순위: summary(요약)가 있는 기사
    try:
        resp = sb.table('news_feed') \
            .select('id,title,source,url,published_at,summary,urgency') \
            .gte('published_at', cutoff) \
            .not_.is_('summary', 'null') \
            .order('published_at', desc=True).limit(300).execute()
        items = []
        for it in (resp.data or []):
            s = (it.get('summary') or '').strip()
            if len(s) > 20:
                it['content'] = s
                items.append(it)
        if items:
            print(f'[폴백] 본문 없음 → 요약(summary) 기반 {len(items)}건')
            return items, '요약'
    except Exception as e:
        print(f'[폴백/요약 오류] {e}')
    # 2순위: 제목만이라도
    try:
        resp = sb.table('news_feed') \
            .select('id,title,source,url,published_at,urgency') \
            .gte('published_at', cutoff) \
            .order('published_at', desc=True).limit(300).execute()
        items = []
        for it in (resp.data or []):
            t = (it.get('title') or '').strip()
            if len(t) > 5:
                it['content'] = t
                items.append(it)
        if items:
            print(f'[폴백] 요약도 없음 → 제목(headline) 기반 {len(items)}건')
            return items, '헤드라인'
    except Exception as e:
        print(f'[폴백/제목 오류] {e}')
    return [], ''


# ═══════════════════════════════════════════════════════
#  STEP 1.5 — 같은 사건 클러스터링 (배경역사 #44)
# ═══════════════════════════════════════════════════════

def _briefed_recently(hours: int = 96) -> tuple:
    """최근 브리핑에 실린 기사 id와 본문 토큰을 모은다 — 이월 중복 판정용."""
    ids, tokens = set(), set()
    try:
        from news_dedup import extract_keywords
        since = (datetime.now(KST) - timedelta(hours=hours)).strftime('%Y-%m-%d')
        resp = sb.table('daily_briefings').select('content') \
            .gte('briefing_date', since).order('briefing_date', desc=True).limit(4).execute()
        for row in (resp.data or []):
            c = row.get('content') or ''
            ids |= set(re.findall(r'\[ID:([0-9a-f-]{36})\]', c))
            tokens |= extract_keywords(c)
    except Exception as e:
        print(f'[이월] 과거 브리핑 조회 실패(무시): {e}')
    return ids, tokens


def fetch_carryover_items(max_items: int = 40) -> list:
    """24~72시간 전 긴급 기사 중 **한 번도 브리핑에 오르지 못한** 것을 다시 후보로 올린다(#161-보론).

    종전에는 창이 24시간 고정이라, 하루 8칸 경쟁에서 밀린 사건은 다음 날 창 밖으로 나가
    영영 브리핑에 실리지 않았다(실측 2026-09-07~13: 미언급 긴급 사건 193건).
    이월은 긴급 등급·본문 보유로만 한정하고, 제목 키워드가 최근 브리핑 본문에 이미
    나온 사건은 제외한다(대표 기사만 실린 사건의 잔여 기사가 되살아나는 것을 막는다)."""
    try:
        from news_dedup import extract_keywords
        now = datetime.now(KST)
        lo = (now - timedelta(hours=72)).isoformat()
        hi = (now - timedelta(hours=24)).isoformat()
        resp = sb.table('news_feed') \
            .select('id,title,source,url,published_at,content,urgency') \
            .gte('published_at', lo).lt('published_at', hi) \
            .eq('urgency', '긴급') \
            .order('published_at', desc=True).limit(300).execute()
        rows = [r for r in (resp.data or []) if (r.get('content') or '').strip() and len(r['content'].strip()) > 50]
        if not rows:
            return []
        ids, tokens = _briefed_recently()
        excluded = load_briefing_excluded()
        out = []
        for r in rows:
            if r['id'] in ids:
                continue
            if (r.get('url') or '').strip() in excluded:
                continue
            kw = extract_keywords(r.get('title') or '')
            if kw and len(kw & tokens) / len(kw) >= 0.34:
                continue          # 이미 다룬 사건의 잔여 보도
            r['_carry'] = True
            out.append(r)
        print(f'[이월] 미보도 긴급 기사 {len(out)}건 (후보 {len(rows)}건 중)')
        return out[:max_items]
    except Exception as e:
        print(f'[이월] 조회 실패(무시): {e}')
        return []


def cluster_briefing_items(items: list, for_date: datetime = None) -> list:
    """같은 사건 재보도를 대표 1건으로 묶어 Haiku 입력을 만든다.

    프롬프트의 '중복 주제 제외' 지시만으로는 입력 60건 중 55건이 한 사건일 때
    무력했다(실측) — 입력 자체에서 중복을 없애는 것이 확실하다.
    별-형 클러스터링(전이 없음)을 쓰는 이유는 news_dedup.py 주석 참조.
    전일(24~72h 전) 기사와 유사한 묶음에는 '전일 기보도' 꼬리표를 단다.
    실패 시 원본 그대로 반환(fail-open)."""
    if not items:
        return items
    try:
        from news_dedup import extract_keywords, cluster_star

        reps = []
        swapped = 0
        for rep, members in cluster_star(items):   # 최신순 입력 → 최신 기사가 대표
            # 최신이라는 이유만으로 뽑힌 대표의 본문이 사이트 메뉴·목차뿐인 경우가 있다.
            # 그러면 그 사건은 12칸 중 한 칸을 쓰고도 요약할 내용이 없다(#161-보론14).
            # 실측: 개정 개인정보 보호법 시행 당일, 대표로 뽑힌 기사의 본문이
            # '많이 본 기사' 목록뿐이어서 요약 세 문장이 전부 근거 없이 쓰였다.
            # 같은 묶음 안에 본문이 있는 기사가 있으면 그쪽을 대표로 바꾼다.
            if not _has_real_body(rep):
                better = next((m for m in members if _has_real_body(m)), None)
                if better is not None:
                    rep = better
                    swapped += 1
            rep['_related'] = len(members)
            reps.append(rep)
        if swapped:
            print(f'[클러스터] 본문 없는 대표 {swapped}건 → 같은 묶음의 본문 있는 기사로 교체')
        print(f'[클러스터] {len(items)}건 → {len(reps)}묶음')

        # 전일 기보도 꼬리표 — 어제 브리핑에서 이미 다룬 사건이 이어지는 것임을 표시
        try:
            # for_date 기준으로 창을 잡는다 — 과거 재생성 시 '오늘'로 계산하면
            # 엉뚱한 날과 비교해 꼬리표가 잘못 붙는다 (#46)
            base = for_date or datetime.now(KST)
            end = (base - timedelta(hours=24)).isoformat()
            start = (base - timedelta(hours=72)).isoformat()
            resp = sb.table('news_feed').select('title') \
                .gte('published_at', start).lt('published_at', end) \
                .order('published_at', desc=True).limit(1000).execute()
            prev_kws = [extract_keywords(r.get('title') or '') for r in (resp.data or [])]
            for rep in reps:
                kw = extract_keywords(rep.get('title') or '')
                if any(len(kw & pk) >= 3 for pk in prev_kws):
                    rep['_prev'] = True
        except Exception as e:
            print(f'[클러스터] 전일 꼬리표 실패(무시): {e}')
        return reps
    except Exception as e:
        print(f'[클러스터] 오류 → 원본 사용(fail-open): {e}')
        return items


# ═══════════════════════════════════════════════════════
#  STEP 2 — 브리핑 생성
# ═══════════════════════════════════════════════════════

_BRIEFING_SYSTEM = """당신은 SK텔레콤 Comm센터 기술정책팀의 통신·전파 정책 모닝 브리핑 작성 AI입니다.
제공된 뉴스 목록과 각 기사의 본문을 바탕으로 간결하고 실용적인 브리핑을 작성하세요.

작성 규칙:
- [주요 뉴스]는 제공된 기사에서만 선별 (최대 12건, 긴급·보통 기사 우선)
- **기사 본문 안에 '며칠 뒤 시행되는 제도'가 적혀 있으면 그것도 사건이다** — 기사의 주제가 아니어도,
  본문에 "오는 11일 시행되는 개정 개인정보 보호법, 매출의 10%까지" 같은 문장이 있으면 요약이나 [주목 포인트]에
  반드시 남긴다. 시행일이 확정됐고 우리가 수범자인 제도를 본문에 두고도 빠뜨리는 것이 가장 큰 누락이다.
- **오늘 시행·발효·공포·의결된 것이 있으면 무조건 [주요 뉴스] 첫 칸에 둔다** — 법·시행령·고시가 오늘부터 효력을 갖거나,
  위원회가 오늘 의결했거나, 부처 예산안·종합계획·국가 로드맵이 오늘 발표된 사안이다. **시행 그 자체가 사건이다** —
  "이미 예고된 내용이라 새롭지 않다"는 이유로 빼지 말 것.
  (실측 누락: 2026-09-12 개정 개인정보 보호법 시행(매출 10% 과징금·72시간 통지), 2026-09-06 과기정통부 2027년 예산안 29.6조원)
- **12건 중 8건 이상은 정책·규제 사안으로 채울 것** — 법령·시행령·고시 제개정, 정부·위원회 의결과 제재, 국회 논의, 주파수·번호·통신설비 제도, 침해사고 조사·수사, 요금 규제가 여기 해당한다
- 다음은 정책 함의가 분명할 때만 넣는다: 단말 출시·사전예약·프로모션, 특정 지자체 단신(지역 와이파이 설치 등), 개별 기업 실적·주가, 해외 일반 산업 동향
- **기획·해설·전망 기사는 [주요 뉴스]에 최대 1건** — 제목에 [기획]·[돋보기]·[○○즈업]·[포커스]가 붙었거나
  당일 사건 없이 배경을 설명하는 기사다. 후보가 적은 날(주말·연휴)일수록 이런 기사가 칸을 메우기 쉬운데,
  그 사이 긴급 등급 당일 사안이 [그 외]로 밀린다(실측: 기획 3건이 들어간 날 '모두의 AI 연내 출시'가 밀렸다).
- **한 주제가 [주요 뉴스] 12칸 중 3칸 이상을 먹지 못한다** — 개인정보 유출, AI 사업, 단말 경쟁처럼 같은 갈래의 사안은
  **최대 2칸**까지다. 실측 지적: 유출 사고가 3~4칸을 과점해 5G SA 전환·통신망 투자 같은 통신망 본류가 두 섹션 어디에도
  들어가지 못한 날이 있었다. 남는 것은 [그 외 오늘의 움직임]으로 내린다.
- **같은 법·같은 사업·같은 사고는 [주요 뉴스]에서 한 칸으로 묶는다** — 같은 개정법의 조항별 기사, 같은 정부 사업의 후속 보도가
  여러 칸을 먹으면 다른 사건이 통째로 밀려난다(실측: 개인정보 관련이 12칸 중 4칸을 차지해 AIDC 시행령안이 빠졌다).
  묶고 남은 것과 12칸에 못 들어간 사건은 아래 [그 외 오늘의 움직임]으로 내린다.
- **같은 통계·같은 발표에서 나온 수치를 두 섹션에 나눠 싣지 말 것** — 같은 소비자물가 발표의 '휴대전화료 26.7%'를
  위에, '통신 물가 1.8%'를 아래에 두면 기준(전년 동월비 vs 누적)이 다른 두 숫자가 나란히 모순으로 읽힌다.
  한 칸에 합치고 **각 수치의 기간을 함께 적는다.**
- **같은 사건을 [주요 뉴스]와 [그 외 오늘의 움직임]으로 갈라 싣지 말 것** — 한 법의 시행을 과징금 조항은 위에,
  통지 의무는 아래에 나눠 넣으면 독자는 두 사건으로 읽는다. 같은 사건은 위 칸 하나로 합치고 조항을 그 안에 열거한다.
  (실측: 같은 날 시행 개정법이 두 섹션으로, 같은 기획 기사 두 편이 두 섹션으로 갈렸다)
- **한 매체가 [주요 뉴스] 12칸 중 3칸 이상을 차지하지 않게 한다** — 같은 사건을 다룬 다른 매체 기사로 대체한다.
- **[그 외 오늘의 움직임]으로 내리면 안 되는 것**: 그날 최대 보도 묶음(관련 보도가 가장 많은 사건), 시행일·의결일이
  정해진 제도, 자사가 당사자인 사안. 이것들은 반드시 [주요 뉴스]에 둔다.
  (실측 지적: 당일 최대 묶음인 중국산 장비 전수점검 요구와 시행령 재입법예고가 한 줄 목록으로 밀렸다)
- **[그 외 오늘의 움직임]에 10~14건을 채운다** — 12칸에 못 들어갔지만 그날 실제로 있었던 정책·제도·사고·사업 사안이다.
  실측 지적: 긴급 등급 사건이 두 섹션 어디에도 없는 날이 반복됐다(5G 단독모드 전환, 중국산 장비 전수점검 요구,
  금융권 알뜰폰 진입, 하위법령 시행령안 공개). 이 섹션은 한 건에 두 줄뿐이니 칸을 아끼지 말 것.
- **[그 외 오늘의 움직임]도 정책 지면이다** — 기업 간 MOU·업무협약, 노조 논평, 전시회·세미나 예고, 수상 소식은
  제도 사안을 밀어내면서 들어가지 않는다(실측: 12칸 중 5칸이 MOU·논평이었고 그 사이 수어통역방송 첫 실무지침,
  정부 해킹 도입 검토, 상생협력법 겹규제가 빠졌다). 채울 제도 사안이 정말 없을 때만 마지막 자리에 둔다.
- **전체 길이는 5,000자를 넘기지 않는다** — 넘치면 [그 외]의 정책 함의가 가장 옅은 항목부터 덜어낸다.
  분량을 줄이려고 위 요약의 필수 다섯 요소를 깎지는 말 것. 순서는 항상 **항목을 덜어내는 쪽**이다.
  제목·출처·한 줄 근거·링크만 적고 영향 분석과 🔴는 붙이지 않는다. **이 섹션이 비어 있으면 그날 동향의 절반이 사라진 것이다.**
- **본문이 확보되지 않은 기사를 [주요 뉴스] 대표로 쓰지 말 것** — 같은 사건의 다른 기사 중 본문이 있는 것을 대표로 삼는다.
  요약을 제목 반복이나 보도 건수로 메우게 되면 그 칸은 정보가 없는 칸이다(실측: 당일 최대 사안이 그렇게 실렸다).
- **한 칸도 버리지 말 것** — 본문이 사이트 안내문·목차뿐인 기사, 제목만 있고 내용이 없는 행정 공고, 특정 인물 칼럼·인터뷰는
  그 자리에 들어갈 정책 사안을 밀어낸다. 공고를 넣을 때는 **무엇이 바뀌는지**를 본문에서 찾아 요약에 적고, 찾지 못하면 그 항목을 뺀다.
- 같은 사건·주제를 다룬 기사가 여러 건일 경우 가장 중요한 1건만 선별 (중복 주제 제외)
- 제목 뒤 (관련 보도 N건)은 같은 사건을 다룬 기사 수 — 선별한 항목에 그대로 표기해 보도 규모가 보이게 할 것
- **같은 사건이 여러 항목으로 나뉘어 들어올 수 있다**(예: 같은 과징금 건이 금액 표기만 다르게 2~3건). 이때는 (관련 보도 N건)이 가장 큰 1건만 [주요 뉴스]에 넣고 나머지는 버릴 것 — 사건이 같은지는 제목의 주체·사안으로 판단
- 〔전일 기보도 이어짐〕 표시가 있는 기사는 **새로 알려진 사실이 있을 때만** 선별하고 **최대 2건까지만** 넣으며,
  **[주요 뉴스] 5번 이후에 배치한다 — 1~4번에 두는 것은 어떤 경우에도 안 된다.** 앞자리는 그날 새로 생긴 사건의 자리다.
  실측 지적: 5일 전 발표된 예산안 재게재가 1번을 차지하고, 그날 유일하게 새로 확인된 제도 개정이 2번으로 밀렸다.
  **그날 새 사건이 4건이 안 되면 칸을 비우지 말고 [그 외]에서 당일 제도 사안을 끌어올려 앞을 채운다** — 진전 없는 재보도로 칸을 채우지 말 것. 선별하면 그 표시를 제목 뒤에 유지하고, 요약은 새로 알려진 내용만 짧게 쓸 것
- 〔이월 — 아직 브리핑에 못 실린 사건〕 표시는 어제까지 한 번도 브리핑에 오르지 못한 사건이다. 정책·규제 사안이면 지금이라도 [주요 뉴스]에 넣고, 제목 뒤 표시는 지울 것(독자에게는 새 소식이다)
- [주목 포인트]는 SKT Comm센터 정책·기술 관점에서 핵심 이슈 1~3개 도출
- 반드시 제공된 본문 내용에 근거해서만 요약 작성 — 추측·외부 지식 금지
- **등록일·보도일과 시행일·고시일을 섞지 말 것** — 공고문에는 '등록일'과 '고시 일자'가 따로 적혀 있다.
  실측 오류: 등록일 8월 19일을 고시일로 적어 폐지 효력 시점이 일주일 어긋났고, 뒤따른 분석이
  "지금 근거 표준이 사라진다"며 즉시 조치를 지시했다. **효력이 언제부터인지가 요약의 값이다.**
- **본문이 특정한 범위를 넓히지 말 것** — 본문의 '1개 혼신원'을 '복수의 혼신'으로, '최우수 1건'을 발표 전체로
  바꿔 쓰면 사실이 달라진다. 보도자료 부제보다 본문 서술을 따른다.
- **본문에 없는 수식어를 붙이지 말 것** — "올해 마지막 신규과제" 같은 표현이 본문에 없으면 쓰지 않는다.
  그 자리에는 본문에 실제로 있는 수치(연구비·기한·대상)를 넣는다.
- **숫자와 날짜는 제공된 본문에 적힌 그대로만 쓴다** — 기억이나 환산으로 바꾸지 말 것.
  실측 오류: 본문에 원제 'Repays $3.08 Billion'이 붙어 있는데 요약은 3억 8천만 달러로 적었고(8배 차이),
  과징금 부과일을 본문에 없는 날짜로 썼다. 본문에 없으면 숫자를 쓰지 말고 문장에서 뺀다.
- **전망·추정은 누가 한 말인지 밝힌다** — 증권사 보고서·애널리스트 전망·업계 관측을 출처 없이 적으면
  규제기관 방침으로 읽힌다(실측: 하나증권 전망인 "내년 5G 추가 경매 가능성"이 주요 뉴스 3번에 정책 사실처럼 실렸다).
- **수사·조사가 진행 중인 사안은 '의혹'·'혐의' 표기를 반드시 유지한다** — 본문이 "증거인멸 의혹, 경찰 수사 중"이라고
  적었는데 요약에서 "쟁점은 증거인멸"이라고 단정형으로 옮기면, 사내 타 부서에는 확정 사실로 읽힌다.
  경쟁사 사안일수록 본문의 유보 표현을 그대로 옮긴다.
- **자극적·조롱조 표현은 중립어로 바꾼다** — 원문 헤드라인의 "털리고", "생색", "도마 위" 같은 표현을
  그대로 옮기지 말 것. 사내 타 부서가 함께 보는 문서에서 타사 사고를 조롱조로 적지 않는다.
- **제목을 '…'로 잘라 쓰지 말 것** — 화면에서 제목이 그대로 링크로 뜬다. 인용부호가 열린 채 끊기면
  발언 취지가 반대로 읽힌다(실측: '류신환 위원 "일률적 규제나...'). 길면 줄이지 말고 그대로 싣는다.
- 각 뉴스에 본문 기반 한 줄 요약 포함 — **한두 문장, 130자 이내**. 수식어·배경 설명·기자 해설을 빼되,
  다음 다섯 가지는 글자 수를 줄이려고 버리지 말 것. **하나라도 빠지면 독자가 사안을 오해한다**:
  ①적용 대상·범위(예: "전년도 이동통신 매출 1조원 이상 사업자") ②시점(시행일·의결일·집계 구간·소급 여부)
  ③핵심 수치(금액·건수는 상한만이 아니라 구간과 정액 대안까지) ④소관 부처·기관 ⑤완화·예외·균형 단서
  (예: "자율성 보장", "시행 이후 위반부터 적용", "미제출이 법 위반은 아니다")
  실측 지적: 90자로 조였더니 개정법 요약이 과징금만 남고 72시간 통지 의무가 통째로 사라졌고,
  과징금 "매출 최대 6%"만 남아 1~6% 구간과 1억~20억원 정액 대안이 지워졌다.
- **한 발표에 여러 항목이 담겼으면 대표 1건만 옮기고 끝내지 말 것** — "적극행정 최우수 1건"만 쓰고
  같은 발표의 저궤도 위성통신망·QoS 확대를 버리면 그 칸의 정보 대부분이 사라진다. 나머지는 "외 ○○·○○ 등"으로 열거한다.
- [ID:기사id] 태그를 제목 뒤에 반드시 포함 (역저장에 사용)
- 🔴 긴급 표시는 입력 뉴스 목록에서 🔴 아이콘이 붙은 기사에만 사용할 것 (크롤러·담당자 검증 분류 기준)
  ※ 입력에서 🔴인 기사를 [주요 뉴스]에 선별하면 🔴를 그대로 유지하고, 🟡·🟢 기사에 새로 🔴를 붙이지 말 것

출력 형식 (아래 형식 그대로):
📡 통신·전파 정책 모닝 브리핑 — {날짜}

[주요 뉴스]
• 제목 — 출처 [ID:기사id]
  → 한 줄 요약 (본문 근거, 1~2문장)
  🔗 URL

[그 외 오늘의 움직임]
• 제목 — 출처 [ID:기사id]
  → 한 줄 근거 (본문 기반, **60자 이내** — 제목에 없는 사실을 적는다. 무엇이 신설·변경되는지,
    누가 대상인지, 언제부터인지 중 실무에 가장 걸리는 하나. "행정절차법 제41조에 따라 의견 수렴" 같은
    절차 상투구나 제목 반복으로 채우지 말 것)
  🔗 URL

[주목 포인트]
• 핵심 이슈 1
• 핵심 이슈 2

[새로 추가된 기술 용어]
• 용어: 정의
  ※ **브리핑 본문 어느 항목과도 연결되지 않는 용어는 싣지 않는다** — 독자가 왜 오늘 이 용어인지 알 수 없다.
  ※ **정의에 용어 자체를 되풀이하지 않는다** — "저궤도 위성 통신: 저궤도 위성을 이용한 통신 기술"은 정의가 아니다.
     무엇에 쓰이는지·왜 지금 나왔는지를 한 구절 덧붙인다.
  ※ 뜻을 확신할 수 없으면 그 용어를 빼라. 실측 오류: 제로 트러스트를 "신뢰도 기반 보안 프레임워크"로 적어
     의미가 정반대가 됐다(실제는 아무것도 신뢰하지 않고 매번 검증하는 모델).

[저장 결과]
뉴스 N건 / 기술 용어 N건"""


def select_for_prompt(items: list, limit: int = 60) -> list:
    """모델에 넘길 묶음을 고른다 — 시각순이 아니라 중요도순(#161).

    종전에는 최신순 50묶음을 그대로 잘라 넘겨, 하루 사건이 50개를 넘는 날은
    늦게 뜬(=창의 앞쪽) 정책 기사가 모델 눈에 닿지도 못하고 탈락했다.
    실측(2026-09-07~13): 긴급 기사를 사건 단위로 묶어 브리핑에 언급조차 없는 것이 193건 —
    LG유플러스 증거인멸 수사·불법스팸 6% 과징금 의결·주파수 재할당 제도 개편이 모두 여기 있었다.
    정렬 기준: 긴급 > 보통 > 참고, 같은 등급이면 전일 기보도가 아닌 것, 보도 규모가 큰 것, 최신 것.
    """
    rank = {'긴급': 0, '보통': 1, '참고': 2}

    def tier(it):
        # 보도가 10건 이상 쏟아진 사건은 등급과 무관하게 긴급과 같은 층에서 겨룬다 —
        # 긴급 등급이 과잉 부여돼(1건짜리 긴급 다수) 실제 대형 사건이 밀리는 것을 막는다(#161).
        if (it.get('_related') or 0) + 1 >= 10:
            return 0
        return rank.get(it.get('urgency') or '참고', 2)

    return sorted(
        items,
        key=lambda it: (
            tier(it),
            1 if it.get('_prev') else 0,
            1 if it.get('_carry') else 0,
            -(it.get('_related') or 0),
            -_pub_key(it),
        ),
    )[:limit]


_BOILER_RE = re.compile(u'로그인|회원가입|전체보기|모바일웹|구독하기|바로가기|최종편집|발행일|'
                        u'기사제보|무단전재|저작권자|많이 본 기사|주요뉴스|전체메뉴|댓글 정책|포토뉴스')
_ENDER_RE = re.compile('다[.]|다["]|했다|밝혔다|말했다|이다|된다|한다|었다|겠다|습니다')


def _has_real_body(it: dict) -> bool:
    """본문이 실제 기사인지, 사이트 메뉴·목차뿐인지 가른다(#161-보론14).

    실측 지적: 그날 선두 항목의 대표 기사 본문이 '많이 본 기사' 목록뿐이어서
    요약 세 문장이 전부 인용 본문으로 검증되지 않았다.
    판정은 **문장 종결 개수**로 한다 — 메뉴·목차는 토막 나열이라 종결어미가 거의 없고,
    실제 기사는 짧아도 대여섯 문장은 된다.
    앞머리 250자만 보는 방식은 쓰지 않는다: 전자신문 계열처럼 본문 앞에 메뉴가 길게 붙는
    템플릿에서 정상 기사 30여 건이 통째로 오검출됐다(AI-RAN·AIDC 하위법령·최적요금제 등).
    """
    body = ' '.join((it.get('content') or '').split())
    if len(body) < 50:
        return False
    # 정부 공고는 표로 온다 — 문장이 없어도 담당부서·기간·내용이 칸에 들어 있어 요약할 수 있다.
    if body.count(chr(124)) >= 6:
        return True
    return len(_ENDER_RE.findall(body)) >= 2


_SOURCE_ALIAS = {
    'news1': '뉴스1', 'edaily': '이데일리', 'fnnews': '파이낸셜뉴스', 'dailian': '데일리안',
    'digitaltoday': '디지털투데이', 'asiae': '아시아경제', 'etoday': '이투데이', 'newspim': '뉴스핌',
    'heraldcorp': '헤럴드경제', 'ajunews': '아주경제', 'itdaily': 'IT데일리', 'hankooki': '데일리한국',
    'enewstoday': '이뉴스투데이', 'metroseoul': '메트로신문', 'gukjenews': '국제뉴스',
    'viva100': '브릿지경제', 'yonhapnewstv': '연합뉴스TV', 'm-i': '매일일보',
    'businesspost': '비즈니스포스트', 'nocutnews': '노컷뉴스', 'koit': '정보통신신문',
    'pinpointnews': '핀포인트뉴스', 'seoul': '서울신문', 'asiatime': '아시아타임즈',
    'newsworks': '뉴스웍스', 'g-enews': '글로벌이코노믹', 'newdaily': '뉴데일리',
    'financialpost': '파이낸셜포스트', 'hansbiz': '한스경제', 'shinailbo': '신아일보',
    'segye': '세계일보', 'newscj': '천지일보', 'sentv': '서울경제TV', 'newstomato': '뉴스토마토',
    'mtn': '머니투데이방송', 'hankookilbo': '한국일보', 'topstarnews': '톱스타뉴스',
    'techm': '테크M', 'kukinews': '쿠키뉴스', 'tf': '더팩트', 'weeklytoday': '위클리오늘',
    'einfomax': '연합인포맥스', 'pointdaily': '포인트데일리', 'thepublic': '더퍼블릭',
    'econovill': '이코노믹리뷰', 'epnc': '테크월드뉴스', 'tokenpost': '토큰포스트',
    'cstimes': '컨슈머타임스', 'aitimes': 'AI타임스', 'newsway': '뉴스웨이',
    'popcornnews': '팝콘뉴스', 'srtimes': 'SR타임스', 'hellot': '헬로티',
    'vegannews': '비건뉴스', 'ggilbo': '금강일보', 'legaltimes': '리걸타임즈',
    'ebn': 'EBN', 'sbs': 'SBS', 'kbs': 'KBS', 'ytn': 'YTN', 'tvchosun': 'TV조선',
    'zdnet korea': 'ZDNet코리아',
    'safetimes': '세이프타임즈', 'ekn': '에너지경제', 'dealsite': '딜사이트',
    'fpn119': '소방방재신문', 'chungnamilbo': '충남일보', 'thescoop': '더스쿠프',
    'goodmorningcc': '굿모닝충청', 'ksilbo': '경상일보', 'businessplus': '비즈니스플러스',
    'economist': '이코노미스트', 'sisaon': '시사오늘', 'ppss': 'ppss',
    'kbmaeil': '경북매일', 'it-b': '아이티비즈', 'webeconomy': '웹이코노미',
    'newsprime': '프라임경제', 'nongaek': '논객닷컴', 'idomin': '경남도민일보',
    'sportsworldi': '스포츠월드', 'financialreview': '파이낸셜리뷰',
    'm-economynews': '엠이코노미뉴스', 'etnews': '전자신문', 'inews24': '아이뉴스24',
    'zdnet': 'ZDNet코리아', 'bloter': '블로터', 'ddaily': '디지털데일리',
    'dt': '디지털타임스', 'mk': '매일경제', 'mt': '머니투데이', 'khan': '경향신문',
    'donga': '동아일보', 'chosun': '조선일보', 'joongang': '중앙일보',
    'hani': '한겨레', 'hankyung': '한국경제', 'sedaily': '서울경제',
    'imaeil': '매일신문', 'kmib': '국민일보', 'munhwa': '문화일보',
}


def _pretty_source(name: str) -> str:
    """도메인 슬러그로 저장된 매체명을 한글 표기로 바꾼다(#161-보론14).

    news_feed.source의 80%(11,495건 중 9,162건)가 'hellot'·'ggilbo' 같은 도메인 본체다.
    크롤러의 _NAVER_PRESS_DOMAINS에 없는 매체는 도메인을 그대로 쓰기 때문인데,
    한 브리핑 안에서 '연합뉴스'와 'thepublic'이 섞여 사내 공유물의 마감 품질을 떨어뜨린다는
    독립 채점 지적이 나왔다. 매핑에 없으면 원래 값을 그대로 둔다(fail-soft).
    """
    key = (name or '').strip()
    return _SOURCE_ALIAS.get(key.lower(), key)


def _pub_key(it: dict) -> float:
    """정렬용 발행시각 — 파싱 실패 시 0(맨 뒤)."""
    try:
        return datetime.fromisoformat(str(it.get('published_at') or '').replace('Z', '+00:00')).timestamp()
    except Exception:
        return 0.0


def generate_briefing(items: list, new_terms: list, for_date: datetime = None) -> str:
    """for_date: 과거 브리핑 재생성용. 미지정 시 오늘(정상 운영 경로).
    지정하지 않으면 재생성본에 '오늘' 날짜가 찍혀 7/31 브리핑에 8/1이 박힌다(#46)."""
    if not ANTHROPIC_API_KEY:
        print('[브리핑] ANTHROPIC_API_KEY 없음 — 건너뜀')
        return ''

    today_str = (for_date or datetime.now(KST)).strftime('%Y년 %m월 %d일')

    news_lines = []
    for it in select_for_prompt(items):
        icon = {'긴급': '🔴', '보통': '🟡', '참고': '🟢'}.get(it.get('urgency', '참고'), '🟢')
        # 400자면 리드 문단까지밖에 안 들어간다 — 적용 범위·수치 구간·소급 여부 같은
        # 요약의 핵심 조건은 본문 중반에 나온다(#161-보론16).
        body = (it.get('content') or '').replace('\n', ' ').strip()[:900]
        # 클러스터 대표에는 보도 규모·전일 연속 여부를 병기 (배경역사 #44)
        rel = it.get('_related', 0)
        tags = (('' if _has_real_body(it) else ' 〔본문 미확보 — 대표로 쓰지 말 것〕')
                + (f' (관련 보도 {rel + 1}건)' if rel else '')
                + (' 〔전일 기보도 이어짐〕' if it.get('_prev') else '')
                + (' 〔이월 — 아직 브리핑에 못 실린 사건〕' if it.get('_carry') else ''))
        news_lines.append(
            f"{icon} {it['title']}{tags} — {_pretty_source(it.get('source',''))} [ID:{it['id']}]\n"
            f"   URL: {it.get('url','')}\n"
            f"   발행: {str(it.get('published_at',''))[:10]}\n"
            f"   본문: {body}"
        )

    term_lines = '\n'.join(
        f"- {t.get('term','')}: {t.get('definition','')}" for t in new_terms
    ) if new_terms else '신규 용어 없음'

    user_msg = (
        f"날짜: {today_str}\n\n"
        f"[브리핑 대상 뉴스 {len(items)}건 — 본문 확인된 기사만]\n"
        + '\n'.join(news_lines)
        + f"\n\n[오늘 신규 추출된 기술 용어]\n{term_lines}"
    )

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        # 브리핑 생성만 Sonnet 5 (2026-08-02 운영자 결정 — 선별·통찰 품질, 일 1콜이라 비용 미미).
        # Sonnet 5는 적응형 추론이 기본 ON: thinking을 끄고, content[0]이 아니라 text 블록을 찾는다.
        # temperature 등 샘플링 파라미터 금지(400). 판정·번역·짧은 요약류는 Haiku 유지.
        resp = client.messages.create(
            model='claude-sonnet-5',
            # 3500 → 6000 (2026-09-14). 실측 최장 브리핑이 7,265자(09-10)로 상한에 닿아 있었고,
            # 09-14 브리핑은 '• 없음 (' 에서 잘린 채 저장·발송됐다. 출력 토큰은 실제 쓴 만큼만
            # 과금되므로(일 1콜) 상한을 올려도 비용은 늘지 않는다.
            # 6,000 → 12,000 (#161-보론17). [주요 뉴스] 12건 + [그 외] 10~14건으로 항목이
            # 두 배가 됐고 본문 입력도 900자로 키웠다 — 6,000으로는 다시 잘릴 여지가 크다.
            max_tokens=12000,
            thinking={'type': 'disabled'},
            system=_BRIEFING_SYSTEM,
            messages=[{'role': 'user', 'content': user_msg}],
        )
        text = ''
        for blk in resp.content:
            if getattr(blk, 'type', '') == 'text':
                text = (blk.text or '').strip()
                break
        if not text:
            raise RuntimeError('text 블록 없음')
        # 잘린 응답을 성공으로 통과시키지 않는다 — 상한을 올려도 언젠가 또 닿는다.
        # 브리핑 자체는 버리지 않되(대부분 쓸 만하다) 잘렸다는 사실을 본문과 운영자 알림에 남긴다.
        if getattr(resp, 'stop_reason', '') == 'max_tokens':
            print('[브리핑] max_tokens 에서 잘림 — 본문 표시 + 운영자 알림')
            text += '\n\n⚠️ 이 브리핑은 길이 제한에서 잘렸습니다 — 대시보드에서 원문 확인이 필요합니다.'
            try:
                import notify
                notify.send_telegram('⚠️ [브리핑] 오늘 브리핑이 길이 제한(max_tokens)에서 잘렸습니다. '
                                     'morning_briefing.py 의 max_tokens 상향 검토가 필요합니다.')
            except Exception as _e:
                print('[브리핑] 절단 알림 실패: %s' % _e)
        print(f'[브리핑] 생성 완료 (Sonnet 5, {len(text)}자)')
        return text
    except Exception as e:
        print(f'[브리핑 생성 오류] {e}')
        return ''


# ═══════════════════════════════════════════════════════
#  STEP 2.5 — 긴급 기사 SKT 영향 분석 (DB 긴급도 기준, 생성 시 1회 저장)
# ═══════════════════════════════════════════════════════

_IMPACT_SYSTEM = """당신은 SKT Comm센터 기술정책팀의 정책 분석 AI입니다.
긴급 분류된 기사 1건에 대해 SKT 관점의 영향 분석을 작성하세요.
- **2~3문장, 250자 이내** (현재 평균 392자로 길다 — 요약 반복과 부재 설명이 분량을 먹는다)
- 제공된 본문에 근거한 내용만 (추측·과장 금지)
- **없는 것을 설명하는 데 문장을 쓰지 말 것** — "본문에는 실려 있지 않다", "기재돼 있지 않아", "추가 정보 수집이 필요하다"
  같은 서술로 한 문장을 소비하지 않는다. 있는 것만 쓰고, 꼭 필요하면 마지막에 한 구절로 짧게 붙인다
- **바로 위 한 줄 요약을 다시 쓰지 말 것** — 사건 설명은 이미 요약에 있다. 분석은 요약에 **없는 것**만 담는다:
  ①우리에게 무엇이 걸리는가(적용 대상·의무·리스크) ②언제까지 무엇을 해야 하는가(기한·준비 항목)
  ③비교 사례나 선례. 실측 지적: 분석 다섯 건 모두 첫 두세 문장이 요약의 재서술이고 새 정보는 마지막 한 줄뿐이었다
- **제공된 본문을 끝까지 읽고 쓸 것** — 본문 후반에 있는 사실을 두고 "본문에 없다", "추가 정보 수집이 필요하다"고 쓰는
  오류가 반복 지적됐다(실측: 정부 조치 착수·분기 매출 수치·유출 규모가 본문에 있는데도 없다고 서술).
  그 문구는 본문을 다 읽고도 정말 없을 때만 쓰고, 그때는 무엇이 없는지 구체적으로 적는다
- **본문이 말하지 않은 것을 구체화하지 말 것** — 본문이 "사업 구조를 반영하지 못한다"까지만 말했는데
  "임대형으로 운영되는 AIDC는"이라고 한 단계 앞서 나가면 근거 없는 단정이 된다.
  기준을 정할 주체도 본문대로 쓴다(하위법령이 규제심사 중이면 "사업자가 확정해야 한다"가 아니다).
- 마지막 문장에 권고 대응 1가지 포함
- 줄바꿈 없이 한 단락으로만 출력
- "SKT 관점 영향 분석:" 같은 제목·머리말을 앞에 붙이지 말고 첫 문장부터 바로 쓸 것 (표시는 시스템이 이미 붙인다)"""


_RANK_SELF = re.compile(r'SKT|SK텔레콤|에스케이텔레콤')
_RANK_RULE = re.compile(r'주파수|재할당|경매|무선국|번호|설비|요금|약관|이용자보호|과징금|시정명령|제재|처분|'
                        r'고시|시행령|시행규칙|개정|제정|입법|국회|의결|수사|조사|소송|판결')
_RANK_RISK = re.compile(r'해킹|유출|침해|장애|먹통|증거인멸|보안')


_RANK_DUE = re.compile(r'시행|발효|공포|의결|제정|개정안 통과|부과|상한|의무|기한|'
                       r'\d+월\s*\d+일부터|내년\s*\d+월부터')
_RANK_CARRIER = re.compile(r'통신사|이동통신사|이통3사|기간통신|전기통신사업자|부가통신|알뜰폰|'
                           r'SKT|SK텔레콤|KT|LG유플러스')


def _impact_rank(it: dict) -> tuple:
    """영향 분석 대상 정렬 키 — 작을수록 먼저.

    시행일이 확정됐고 통신사가 수범자인 제도 > 자사 당사자 > 제도·자원 > 보안 > 나머지.
    5차 채점 지적(#161-보론13): 10월 1일 시행이 확정된 불법스팸 매출 6% 과징금(수범자가 통신사)에
    분석이 없고 해저케이블에 붙었다. "언제부터 우리가 무엇을 해야 하나"가 분석의 값이므로
    기한이 박힌 항목을 가장 앞에 둔다.
    """
    t = (it.get('title') or '') + ' ' + (it.get('content') or '')[:300]
    tier = 4
    if _RANK_RULE.search(t) and _RANK_DUE.search(t) and _RANK_CARRIER.search(t):
        tier = 0
    elif _RANK_SELF.search(t) and _RANK_RULE.search(t):
        tier = 1
    elif _RANK_RULE.search(t):
        tier = 2
    elif _RANK_RISK.search(t):
        tier = 3
    return (tier, -(it.get('_related') or 0))


def add_urgent_analyses(items: list, briefing_text: str) -> str:
    """DB 긴급도='긴급' 기사 중 브리핑에 포함된 기사에 SKT 영향 분석을 생성해
    해당 기사 블록 뒤에 삽입. 저장본에 포함되므로 이메일·대시보드가 동일 내용 표시."""
    if not ANTHROPIC_API_KEY or not briefing_text:
        return briefing_text
    urgent = [it for it in items if it.get('urgency') == '긴급' and f"[ID:{it['id']}]" in briefing_text]
    if not urgent:
        return briefing_text
    # 대상 선정은 긴급 표시 순서가 아니라 **SKT 이해관계 순**이다(#161-보론10).
    # 독립 채점 지적: 주파수 재할당·해저케이블처럼 이해가 큰 항목에 분석이 없고,
    # 멤버십 등급 칼럼 같은 항목에 붙은 날이 있었다. 3건 고정도 5건으로 늘린다.
    urgent.sort(key=_impact_rank)
    # [주요 뉴스] 1번 항목은 무조건 분석 대상에 넣는다(#161-보론11) — 그날 시행·의결된 제도가
    # 1번인데 분석이 다른 항목에만 붙은 날이 있었다(실측: 매출 10% 과징금 신설 당일).
    _first = re.search(r'\[ID:([0-9a-f-]{36})\]', briefing_text)
    if _first:
        _fid = _first.group(1)
        for _i, _it in enumerate(urgent):
            if str(_it['id']) == _fid and _i > 0:
                urgent.insert(0, urgent.pop(_i))
                break
    # 그날 최대 보도 묶음과 자사가 당사자인 사안은 분석 대상에서 빠지지 않게 끌어올린다(#161-보론14).
    # 실측 지적: 후보 323건 중 100건이 몰린 당일 최대 사안이자 자사가 직접 당사자인 건에
    # 분석이 없고, 분석 5건이 모두 다른 항목에 배정된 날이 있었다.
    if urgent:
        _top = max(urgent, key=lambda x: (x.get('_related') or 0))
        if (_top.get('_related') or 0) > 0 and _top in urgent[5:]:
            urgent.remove(_top)
            urgent.insert(1, _top)
        for _it in list(urgent[5:]):
            if _RANK_SELF.search((_it.get('title') or '')):
                urgent.remove(_it)
                urgent.insert(2, _it)
                break
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    lines = briefing_text.split('\n')
    for it in urgent[:5]:
        try:
            # 1,500자로 자르면 본문 후반의 수치·조치가 모델 눈에 닿지 않는다 —
            # '본문에 없다'는 서술과 환각이 동시에 늘어난 원인이다(#161-보론14).
            body = (it.get('content') or '').replace('\n', ' ').strip()[:3000]
            resp = client.messages.create(
                model='claude-haiku-4-5-20251001', max_tokens=400,
                system=_IMPACT_SYSTEM,
                messages=[{'role': 'user', 'content': f"제목: {it['title']}\n본문: {body}"}],
            )
            analysis = resp.content[0].text.strip().replace('\n', ' ')
            # 생성된 분석의 수치가 본문에 있는지 대조해 경고를 남긴다(#161-보론14).
            # 지우지는 않는다 — 한 숫자를 들어내면 문장이 무너지고, 판단은 운영자가 한다.
            _warn_unbacked_numbers(str(it.get('title', '')), analysis, body)
        except Exception as e:
            print(f'  [영향 분석 오류] {str(it.get("title",""))[:30]}: {e}')
            continue
        tag = f"[ID:{it['id']}]"
        idx = next((i for i, l in enumerate(lines) if tag in l), None)
        if idx is None:
            continue
        ins = idx
        for j in range(idx + 1, min(idx + 5, len(lines))):
            if '🔗' in lines[j]:
                ins = j
                break
            if lines[j].strip() == '' or lines[j].startswith('['):
                break
            ins = j
        lines.insert(ins + 1, f"  ⚠️ SKT 영향 분석: {analysis}")
        print(f'  [영향 분석] {str(it.get("title",""))[:30]}... 삽입')
    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════
#  STEP 3 — daily_briefings 저장
# ═══════════════════════════════════════════════════════

def save_briefing(briefing_text: str, news_count: int, terms_count: int):
    today_date = datetime.now(KST).strftime('%Y-%m-%d')
    try:
        sb.table('daily_briefings').upsert({
            'briefing_date': today_date,
            'content': briefing_text,
            'news_count': news_count,
            'terms_count': terms_count,
        }, on_conflict='briefing_date').execute()
        print(f'[저장] daily_briefings {today_date} 완료')
    except Exception as e:
        print(f'[저장 오류] {e}')


# ═══════════════════════════════════════════════════════
#  STEP 4 — news_feed.summary 역저장
# ═══════════════════════════════════════════════════════

def backfill_summaries(briefing_text: str):
    """브리핑의 [ID:xxx] → 요약 패턴으로 news_feed.summary 역저장 (병렬)"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    pattern = r'\[ID:([^\]]+)\].*?\n\s*→\s*(.+)'
    matches = re.findall(pattern, briefing_text)
    pairs = [(aid.strip(), sl.strip()) for aid, sl in matches if aid.strip() and sl.strip()]
    if not pairs:
        print('[역저장] 업데이트할 항목 없음')
        return
    def _update(aid, summary):
        try:
            sb.table('news_feed').update({'summary': summary}).eq('id', aid).execute()
            return True
        except Exception as e:
            print(f'  [역저장 오류] id={aid}: {e}')
            return False
    count = 0
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(_update, aid, sl): aid for aid, sl in pairs}
        for fut in as_completed(futs):
            if fut.result():
                count += 1
    print(f'[역저장] news_feed.summary {count}/{len(pairs)}건 업데이트')


# ═══════════════════════════════════════════════════════
#  STEP 5 — 텔레그램 + 이메일 발송
# ═══════════════════════════════════════════════════════

# ── 텔레그램 HTML 변환 ──────────────────────────────────
# 기사 제목 자체를 하이퍼링크로 만들고 별도 "🔗 URL" 줄은 없앤다(줄 수 절감 + 가독성).
# Edge Function _shared/telegram_format.ts 의 briefingToTelegramHtml 과 동일 규칙 — 한쪽만 고치지 말 것.
_BULLET_RE = re.compile(r'^(\s*[•·]\s*)([🔴🟡🟢]\s*)?(.+?)(\s+[—–-]\s+[^—–]+)?$')
_LINK_RE = re.compile(r'^\s*🔗\s*(https?:\S+)\s*$')


def _tg_esc(s: str) -> str:
    """텔레그램 HTML 이스케이프 — 이스케이프 누락 시 sendMessage가 400으로 전체 실패한다."""
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _dedup_terms(rows: list) -> list:
    """같은 용어의 표기 변형을 하나로 — '솔트 타이푼'과 '소금 타이푼'이 같은 날 함께 실렸다(#161-보론11).
    공백·중점·괄호를 지운 뒤 비교하고, 한쪽이 다른 쪽을 포함하면 더 긴 쪽(대개 정식 표기)을 남긴다."""
    out = []
    for r in rows:
        key = re.sub(r'[\s·\-_()]', '', (r.get('term') or '')).lower()
        if not key:
            continue
        dup = None
        for i, kept in enumerate(out):
            k2 = re.sub(r'[\s·\-_()]', '', (kept.get('term') or '')).lower()
            # 유사도 기반 병합은 쓰지 않는다 — '설계전력'과 '계약전력'처럼 별개 용어가
            # 합쳐진다(실측). 오역·이형 표기는 tech_terms 데이터에서 정리한다(#161-보론11).
            if key == k2 or key in k2 or k2 in key:
                dup = i
                break
        if dup is None:
            out.append(r)
        elif len(r.get('term') or '') > len(out[dup].get('term') or ''):
            out[dup] = r
    return out


_NL = chr(10)
_ID_IN_LINE_RE = re.compile(r'\[ID:([0-9a-f-]{36})\]')
_WS = r'\s'
_NO_TERM_RE = re.compile('^(없음|해당 없음|해당 사항 없음|신규 용어 없음|용어 없음)$')
_TERM_COUNT_RE = r'(뉴스 \d+건 / 기술 용어 )\d+(건)'


_TITLE_HEAD_RE = re.compile(r'^(\s*[•-]\s*(?:🔴|🟡|🟢)?\s*)')
_TITLE_CUT_RE = re.compile(r'(…|\.\.\.)\s*$')
_TAG_PIECE_RE = re.compile(r'\(관련 보도 \d+건\)|〔[^〕]*〕')
_TAG_MARKS = (' (관련 보도', ' \u3014')


_NUM_RE = re.compile(r'[0-9][0-9,.]*')


def _warn_unbacked_numbers(label: str, generated: str, body: str) -> None:
    """생성문의 숫자가 제공 본문에 없으면 경고만 남긴다(#161-보론14).

    지우지 않는 이유: 한 숫자를 들어내면 문장이 무너지고, 단위 환산처럼
    정당한 경우도 있다. 판단은 사람이 하고, 코드는 눈에 띄게만 해 준다.
    비교는 자릿수 구분 쉼표를 뗀 뒤 문자열 포함으로 본다(보수적).
    """
    flat = body.replace(',', '')
    bad = []
    for n in _NUM_RE.findall(generated or ''):
        t = n.strip('.').replace(',', '')
        if len(t) < 2:          # 한 자리 수는 오탐이 많다
            continue
        if t not in flat:
            bad.append(n)
    if bad:
        print('[분석 경고] ' + label[:24] + ' — 본문에 없는 수치: ' + ', '.join(bad[:6]))


def _restore_titles(text: str, items: list) -> str:
    """모델이 '…'로 줄여 쓴 제목을 원제목으로 되돌린다(#161-보론14).

    화면에서는 제목이 그대로 링크로 뜬다. 인용부호가 열린 채 끊기면
    발언 취지가 반대로 읽힌다(실측: '류신환 위원 "일률적 규제나...').
    프롬프트로 금지해도 하루 3~4건씩 남아 코드에서 되돌린다.
    바꾸는 것은 잘린 제목뿐 — 태그·출처·[ID:]는 손대지 않는다.
    """
    # 제목에 꼬리표가 이미 붙어 오는 입력이 있다(briefing_offline 내보내기는
    # '제목 + (관련 보도 N건)' 형태로 준다). 그대로 쓰면 복원할 때마다 꼬리표가
    # 한 벌씩 더 붙어 배지가 줄줄이 늘어난다(#161-보론14 실측 4~5곳).
    title_by_id = {str(it.get('id')): _TAG_PIECE_RE.sub('', it.get('title') or '').strip()
                   for it in items}
    out, fixed = [], 0
    for line in text.split(chr(10)):
        m = _ID_IN_LINE_RE.search(line)
        if not m:
            out.append(line)
            continue
        full = title_by_id.get(m.group(1))
        head, rest_id = line[:m.start()], line[m.start():]
        if ' — ' not in head:
            out.append(line)
            continue
        left, _, source = head.rpartition(' — ')
        hm = _TITLE_HEAD_RE.match(left)
        prefix = hm.group(1) if hm else ''
        body = left[len(prefix):]
        cut = len(body)
        for mark in _TAG_MARKS:
            i = body.find(mark)
            if 0 <= i < cut:
                cut = i
        title, tags = body[:cut], body[cut:]
        # 꼬리표 중복 정리는 제목이 잘렸든 아니든 모든 줄에 적용한다 —
        # 잘리지 않은 줄에 남은 중복이 채점에서 4~5곳씩 지적됐다.
        seen, uniq = set(), []
        for piece in _TAG_PIECE_RE.findall(tags):
            if piece not in seen:
                seen.add(piece)
                uniq.append(piece)
        tags = (' ' + ' '.join(uniq)) if uniq else ''
        if not full or not _TITLE_CUT_RE.search(title):
            rebuilt = prefix + title + tags + ' — ' + source + rest_id
            out.append(rebuilt if rebuilt != line else line)
            continue
        rebuilt = prefix + full + tags + ' — ' + source + rest_id
        # 원제목 자체가 '…'로 끝나는 기사가 있다(수집 시점에 이미 잘린 제목).
        # 그때는 복원해도 값이 같으므로 '고쳤다'고 세지 않는다.
        if rebuilt != line:
            fixed += 1
        out.append(rebuilt)
    if fixed:
        print('[제목] 잘린 제목 ' + str(fixed) + '건 원제목으로 복원')
    return chr(10).join(out)


def _prune_orphan_terms(text: str) -> str:
    """[새로 추가된 기술 용어]에서 본문과 연결되지 않는 용어를 지운다(#161-보론13).

    독립 채점에서 세 날 연속 지적된 것 — '솔트 타이푼'이 용어로 올라 있는데 정작 그 사건은
    두 섹션 어디에도 없고, '저궤도 맨팩 안테나'는 출처 기사 자체가 실리지 않았다.
    독자는 왜 오늘 이 용어가 나왔는지 알 수 없고, 용어만 떠 있으면 본문 누락이 도리어 드러난다.
    프롬프트로도 막지만 모델이 어기는 날이 있어 코드에서 한 번 더 거른다.
    판정은 느슨하게 — 공백을 지운 형태가 본문에 있으면 남긴다(영문 약어는 대소문자 무시).
    """
    head = '[새로 추가된 기술 용어]'
    i = text.find(head)
    if i < 0:
        return text
    body = text[:i]                       # 용어 섹션 위쪽이 '본문'
    rest = text[i + len(head):]
    end = rest.find(_NL + '[')        # 다음 섹션 머리
    seg, tail = (rest[:end], rest[end:]) if end >= 0 else (rest, '')
    body_flat = re.sub(_WS, '', body).lower()
    kept, dropped = [], []
    for line in seg.split(_NL):
        t = line.strip()
        if not t.startswith('•'):
            kept.append(line)
            continue
        term = t.lstrip('•').split(':')[0].strip()
        # '없음'·'신규 용어 없음' 같은 상태 표시는 용어가 아니다 — 지우지 않고 그대로 둔다.
        # (지우면 섹션까지 사라져 다른 날과 표기가 갈린다. 실측 2026-09-14)
        if _NO_TERM_RE.match(term):
            kept.append(line)
            continue
        flat = re.sub(_WS, '', term).lower()
        if flat and flat in body_flat:
            kept.append(line)
        else:
            dropped.append(term)
    if dropped:
        print('[용어] 본문 미연결 ' + str(len(dropped)) + '건 제외: ' + ', '.join(dropped))
    # 줄이 하나라도 남아 있으면 섹션은 유지한다 — '없음' 표시도 한 줄이다.
    # 건수에는 상태 표시를 세지 않는다(다른 날과 표기를 맞춘다).
    bullets = [l for l in kept if l.strip().startswith('•')]
    n_kept = sum(1 for l in bullets
                 if not _NO_TERM_RE.match(l.strip().lstrip('•').split(':')[0].strip()))
    if not bullets:
        # 헤더만 남은 빈 섹션을 내보내지 않는다 — 구조 항목 하나가 빈 채로 발송됐다는
        # 채점 지적이 있었다. 섹션을 통째로 들어낸다.
        out = (text[:i].rstrip() + _NL + _NL + tail.lstrip(_NL)) if tail else text[:i].rstrip()
        print('[용어] 남은 용어가 없어 섹션을 제거')
        return re.sub(_TERM_COUNT_RE, lambda m: m.group(1) + '0' + m.group(2), out)
    out = text[:i] + head + _NL.join(kept) + tail
    # [저장 결과]의 용어 건수도 실제 남은 수로 맞춘다(상태 표시는 세지 않는다)
    out = re.sub(_TERM_COUNT_RE, lambda m: m.group(1) + str(n_kept) + m.group(2), out)
    return out


def _briefing_to_telegram_html(text: str) -> str:
    lines = [l.rstrip() for l in text.split('\n')]
    skip, out = set(), []
    for i, line in enumerate(lines):
        if i in skip:
            continue
        esc = _tg_esc(line)
        if line.startswith('📡') or line.startswith('📢') or re.fullmatch(r'\[.+\]', line.strip() or ' '):
            out.append(f'<b>{esc}</b>')
            continue
        m = _BULLET_RE.match(line)
        if m and m.group(3):
            url = ''
            for j in range(i + 1, min(i + 4, len(lines))):
                if lines[j].lstrip().startswith(('•', '·')):
                    break                       # 다음 기사에 도달하면 중단
                lm = _LINK_RE.match(lines[j])
                if lm:
                    url = lm.group(1)
                    skip.add(j)
                    break
            head = _tg_esc(m.group(1)) + _tg_esc(m.group(2) or '')
            title = _tg_esc(m.group(3))
            tail = _tg_esc(m.group(4) or '')
            body = f'<a href="{_tg_esc(url)}">{title}</a>' if url else f'<b>{title}</b>'
            out.append(head + body + tail)
            continue
        lm = _LINK_RE.match(line)
        if lm:                                   # 짝 못 찾은 고아 링크만 링크 줄로 유지
            out.append(f'🔗 <a href="{_tg_esc(lm.group(1))}">기사 보기</a>')
            continue
        out.append(esc)
    return '\n'.join(out)


def send_telegram(briefing_text: str) -> bool:
    """발송 성공 여부를 반환 (입법예고 1회 노출 마킹이 이 결과에 의존 — 2026-08-03)"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print('[텔레그램] 환경변수 미설정 — 건너뜀')
        return False
    # 4000자에서 자르지 않는다 — notify.send_telegram이 3800자 개행 경계로 나눠 순차 발송한다.
    # (2026-08-03: 잘라 보내던 탓에 운영자만 [해외 동향]·[기술 용어] 섹션을 통째로 못 받고 있었다.
    #  구독자 봇은 분할 발송이라 전문을 받는데 운영자가 더 적게 받는 역전 상태였다.)
    # 브리핑 HTML은 태그가 줄을 넘지 않으므로 개행 경계 분할이 안전하다.
    text = _briefing_to_telegram_html(briefing_text)
    text += '\n\n📊 <a href="https://radio-policy.gitlab.io/">대시보드</a>'
    # 전송부는 notify 위임 (개선⑪) — 400 등 4xx는 notify가 재시도 없이 False 반환
    ok = notify.send_telegram(text, chat_id=TELEGRAM_CHAT_ID, parse_mode='HTML',
                              disable_web_page_preview=True)
    if not ok:
        # HTML 파싱 실패(400 등) 시 평문으로 재시도 — 포맷 때문에 브리핑 자체를 잃지 않도록(fail-open)
        print('[텔레그램] HTML 발송 실패 → 평문 재시도')
        plain = re.sub(r'<[^>]+>', '', text)
        ok = notify.send_telegram(plain, chat_id=TELEGRAM_CHAT_ID,
                                  disable_web_page_preview=True)
    if ok:
        print('[텔레그램] 발송 완료')
    return bool(ok)


def _briefing_to_html(text: str) -> str:
    """이메일 본문 HTML. 제목에 원문 링크를 걸고 URL 줄은 지운다(#161-보론18).

    텔레그램(_briefing_to_telegram_html)과 같은 규칙이다 — 같은 브리핑이 경로마다
    다르게 보이지 않도록 맞췄다. 제목 줄 다음 3줄 안에서 링크를 찾아 짝을 짓고,
    짝지은 링크 줄은 건너뛴다. 짝을 못 찾은 링크만 '원문 보기' 줄로 남긴다.
    """
    import html as hl
    lines = [l.rstrip() for l in text.split(chr(10))]
    skip, out = set(), []
    in_box = False
    for i, line in enumerate(lines):
        if i in skip:
            continue
        e = hl.escape(line)
        is_urgent = '\U0001F534' in line
        if in_box and not is_urgent and (e.startswith('[') or '\U0001F4E1' in line or e == ''):
            out.append('</div>')
            in_box = False

        m = _BULLET_RE.match(line)
        if m and m.group(3):
            url = ''
            for j in range(i + 1, min(i + 4, len(lines))):
                if lines[j].lstrip().startswith(('\u2022', '\u00b7')):
                    break                      # 다음 기사에 도달하면 중단
                lm = _LINK_RE.match(lines[j])
                if lm:
                    url = lm.group(1)
                    skip.add(j)
                    break
            head = hl.escape(m.group(1)) + hl.escape(m.group(2) or '')
            title = hl.escape(m.group(3))
            tail = hl.escape(m.group(4) or '')
            body = (f'<a href="{hl.escape(url, quote=True)}" '
                    f'style="color:#534AB7;text-decoration:none">{title}</a>') if url else f'<b>{title}</b>'
            item = head + body + tail
            if is_urgent:
                if not in_box:
                    out.append('<div style="border:2px solid #c53030;border-radius:6px;'
                               'background:#fff5f5;padding:10px 14px;margin:10px 0">')
                    in_box = True
                out.append(f'<p style="margin:3px 0">{item}</p>')
            else:
                out.append(f'<p style="margin:4px 0 4px 12px">{item}</p>')
            continue

        if is_urgent:
            if not in_box:
                out.append('<div style="border:2px solid #c53030;border-radius:6px;'
                           'background:#fff5f5;padding:10px 14px;margin:10px 0">')
                in_box = True
            out.append(f'<p style="margin:3px 0">{e}</p>')
        elif '\U0001F4E1' in line:
            out.append(f'<h2 style="color:#534AB7;margin-bottom:4px">{e}</h2>')
        elif e.startswith('[') and e.endswith(']'):
            out.append(f'<h3 style="color:#1a1a1a;margin:18px 0 6px;'
                       f'border-bottom:1px solid #eee;padding-bottom:4px">{e}</h3>')
        elif '\u26a0\ufe0f SKT 영향 분석' in line:
            out.append(f'<p style="margin:6px 0 4px 24px;color:#9b2c2c;font-size:13px">{e.strip()}</p>')
        elif e.startswith('  \u2192'):
            out.append(f'<p style="margin:2px 0 2px 24px;color:#555;font-size:13px">{e}</p>')
        elif _LINK_RE.match(line):
            # 짝 못 찾은 고아 링크만 링크 줄로 남긴다
            u = _LINK_RE.match(line).group(1)
            out.append(f'<p style="margin:2px 0 8px 24px;font-size:12px">'
                       f'<a href="{hl.escape(u, quote=True)}" '
                       f'style="color:#534AB7;text-decoration:none">\U0001F517 원문 보기</a></p>')
        elif e == '':
            out.append('<br>')
        else:
            out.append(f'<p style="margin:4px 0">{e}</p>')
    if in_box:
        out.append('</div>')
    return chr(10).join(out)


def send_email(briefing_text: str, news_count: int) -> bool:
    """발송 성공 여부를 반환 (입법예고 1회 노출 마킹이 이 결과에 의존 — 2026-08-03)"""
    today = datetime.now(KST).strftime('%Y.%m.%d')
    subject = f'☀️ [전파정책 AI] {today} 모닝 브리핑 — {news_count}건'
    body_html = f'''
<html><body style="font-family:sans-serif;max-width:640px;margin:auto;padding:20px">
{_briefing_to_html(briefing_text)}
<hr style="margin-top:24px">
<p style="color:#999;font-size:11px">
이 메일은 자동 발송됩니다. SKT Comm센터 기술정책팀<br>
대시보드: <a href="https://radio-policy.gitlab.io/">https://radio-policy.gitlab.io/</a>
</p>
</body></html>'''
    extra_to = 'lampman@sktelecom.com'
    all_to = list({a.strip() for a in (EMAIL_TO + ',' + extra_to).split(',') if a.strip()})

    # Resend API 우선 (GitHub Actions 미국 IP에서도 동작)
    # 도메인 미인증 상태: you.jinwoong@gmail.com으로만 발송 가능
    resend_to = ['you.jinwoong@gmail.com']
    if RESEND_API_KEY:
        return _send_via_resend(subject, body_html, resend_to)
    elif all([EMAIL_FROM, EMAIL_PASS, EMAIL_TO]):
        # 폴백: Gmail SMTP (PC 로컬 실행 시)
        return _send_via_gmail(subject, body_html, all_to)
    else:
        print('[이메일] RESEND_API_KEY 또는 Gmail 환경변수 미설정 — 건너뜀')
        return False


def _send_via_resend(subject: str, body_html: str, all_to: list) -> bool:
    """Resend API로 이메일 발송 — 미국 IP 차단 없음"""
    payload = {
        'from': '전파정책 AI <onboarding@resend.dev>',
        'to': all_to,
        'subject': subject,
        'html': body_html,
    }
    try:
        resp = requests.post(
            'https://api.resend.com/emails',
            headers={
                'Authorization': f'Bearer {RESEND_API_KEY}',
                'Content-Type': 'application/json',
            },
            data=json.dumps(payload),
            timeout=30,
        )
        if resp.status_code in (200, 201):
            print(f'[이메일/Resend] {", ".join(all_to)} 발송 완료')
            return True
        print(f'[이메일/Resend 오류] HTTP {resp.status_code}: {resp.text[:200]}')
    except Exception as e:
        print(f'[이메일/Resend 오류] {e}')
    return False


def _send_via_gmail(subject: str, body_html: str, all_to: list) -> bool:
    """Gmail SMTP — PC 로컬 실행 전용 폴백"""
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f'전파정책 AI <{EMAIL_FROM}>'
    msg['To'] = ', '.join(all_to)
    msg.attach(MIMEText(body_html, 'html', 'utf-8'))
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30) as smtp:
            smtp.login(EMAIL_FROM, EMAIL_PASS)
            smtp.sendmail(EMAIL_FROM, all_to, msg.as_string())
        print(f'[이메일/Gmail] {", ".join(all_to)} 발송 완료')
        return True
    except Exception as e:
        print(f'[이메일/Gmail 오류] {e}')
    return False


# ═══════════════════════════════════════════════════════
#  STEP 5.5 — 신규 입법예고 조회 (law_amendments)
# ═══════════════════════════════════════════════════════

def fetch_new_law_announcements() -> list:
    """최근 24h 신규 입법예고(lsAnc) 조회 — law_amendments"""
    cutoff = (datetime.now(KST) - timedelta(hours=24)).isoformat()
    try:
        resp = sb.table('law_amendments') \
            .select('law_nm,ann_type,public_dt,enf_dt,link_url,matched_keywords,summary') \
            .eq('law_type', 'lsAnc') \
            .gte('created_at', cutoff) \
            .execute()
        items = resp.data or []
        print(f'[입법예고] 최근 24h 신규 {len(items)}건')
        return items
    except Exception as e:
        print(f'[입법예고 조회 오류] {e}')
        return []


def _fmt_dt(dt: str) -> str:
    """'20260612' → '2026.06.12'"""
    if dt and len(dt) == 8:
        return f'{dt[:4]}.{dt[4:6]}.{dt[6:]}'
    return dt or '—'


def _format_law_anc_section(items: list) -> str:
    """신규 입법예고 브리핑 섹션 (🔴 → 이메일에서 빨간 박스로 렌더링)"""
    lines = [f'📢 [신규 입법예고] {len(items)}건 — 확인 필요']
    for it in items:
        law_nm = it.get('law_nm', '')
        ann_type = it.get('ann_type', '입법예고')
        public_dt = _fmt_dt(it.get('public_dt', ''))
        enf_dt = _fmt_dt(it.get('enf_dt', ''))
        link = it.get('link_url', '')
        summary = (it.get('summary') or '').strip()
        lines.append(f'🔴 [입법예고] {law_nm}')
        lines.append(f'  → {ann_type} | 예고: {public_dt}~{enf_dt}')
        if summary:
            lines.append(f'  → {summary}')
        if link:
            lines.append(f'  🔗 {link}')
    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════
#  STEP 5.6 — 해외 규제기관 동향 조회 (foreign_press.py 수집분)
# ═══════════════════════════════════════════════════════

def fetch_overseas_items() -> list:
    """최근 24h 신규 해외 동향(category='해외') 조회 — news_feed, 최대 3건.
    피드 발행일(published_at)은 수집 시점보다 오래될 수 있어 created_at 기준."""
    cutoff = (datetime.now(KST) - timedelta(hours=24)).isoformat()
    try:
        resp = sb.table('news_feed') \
            .select('title,source,url,summary') \
            .eq('category', '해외') \
            .gte('created_at', cutoff) \
            .order('created_at', desc=True) \
            .limit(3) \
            .execute()
        items = resp.data or []
        print(f'[해외 동향] 최근 24h 신규 {len(items)}건')
        return items
    except Exception as e:
        print(f'[해외 동향 조회 오류] {e}')
        return []


def _format_overseas_section(items: list) -> str:
    """해외 규제기관 동향 브리핑 섹션"""
    lines = [f'🌐 [해외 동향] {len(items)}건']
    for it in items:
        title = it.get('title', '')
        source = it.get('source', '')
        url = it.get('url', '')
        summary = (it.get('summary') or '').strip()
        # 첫 문장만 (한글 평서문 '…다.' 우선, 없으면 '. ' 기준)
        m = re.match(r'.+?다\.', summary)
        first = m.group(0) if m else summary.split('. ')[0]
        lines.append(f'• {title} — {source}')
        if first:
            lines.append(f'  → {first}')
        if url:
            lines.append(f'  🔗 {url}')
    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════
#  STEP 5.7 — 국회 법안 동향 조회 (assembly_bills)
# ═══════════════════════════════════════════════════════

# '신규 발의'로 인정할 발의일 상한. 수집이 며칠 밀렸다 몰아 도는 경우를 흡수할 만큼은 넉넉하되,
# 1~2년 전 법안이 신규로 실리지는 않을 만큼 짧게. 주말·연휴 공백(최대 3~4일)을 감안해 7일.
NEW_BILL_MAX_AGE_DAYS = 7

# 의견등록(입법예고)을 '갓 시작한 것'으로 볼 잔여 기간 하한.
# 국회법상 입법예고 기간은 10일 이상 → 시작 당일에 잡히면 잔여가 9~10일이다.
# 9일로 두면 주말 하루 밀린 정도는 흡수하고, 절반 이상 지난 예고는 걸러진다.
NOTICE_MIN_REMAIN_DAYS = 9

# 처리 변경 섹션 상한·잡음 필터 (2026-09-04, 배경역사 #122-보론)
#  단계 파생 규칙(bill_stage) 배포 백필이 442건을 '접수 → 소관위 …'로 바꾸자 06:00 브리핑·구독자
#  다이제스트에 그 전부가 [처리 변경]으로 쏟아졌다(크롤러 알림은 억제했지만 이 섹션은 prev≠now만 본다).
#  ① '소관위 회부'로의 전이는 접수와 무게가 같아 싣지 않는다. ② 상한을 넘으면 '외 N건'으로 접는다.
CHANGED_MAX_LINES = 12
NEW_MAX_LINES = 15
CHANGED_SKIP_TO = {'소관위 회부'}


def fetch_assembly_items(sb) -> dict:
    """국회 법안 동향 3종 조회 — assembly_bills
    (a) 신규 발의: created_at 최근 24h
    (b) 처리 변경: updated_at 최근 24h & prev_proc_result ≠ proc_result
    (c) 의견등록: 진행 중(notice_end_dt >= 오늘) & 아직 브리핑에 안 실린 것(notice_briefed_at IS NULL)

    운영자 지시(2026-08-03): 입법예고는 "처음 감지될 때 딱 한 번"만 싣는다.
      - 기존 'D-3 창(오늘~오늘+3)' 조건은 같은 법안을 D-3·D-2·D-1·당일 4일 연속 노출시켜 제거.
      - 감지 시점이 마감 3일 전이든 12일 전이든 최초 1회. 대신 표기에 마감일·잔여일수를 넣는다.
      - 실제 표시분은 briefed_ids 로 돌려주고, main()이 **발송 성공 후에만** notice_briefed_at 을 채운다.
        (발송 실패 시 미리 채우면 그 법안은 영영 안 실린다 — 순서 주의)
    반환 dict의 'briefed_ids'는 출력 목록이 아니라 사후 마킹 대상 id 목록."""
    cutoff = (datetime.now(KST) - timedelta(hours=24)).isoformat()
    today = datetime.now(KST).date()
    cols = ('bill_id,bill_name,proposer,committee,proc_result,prev_proc_result,'
            'notice_end_dt,notice_url,notice_briefed_at')
    result = {'new': [], 'changed': [], 'deadline': [], 'briefed_ids': []}
    try:
        # (a) 신규 발의 — **우리가 오늘 처음 적재했고(created_at) + 실제로도 최근 발의(propose_dt)**
        #   두 조건을 모두 본다. created_at만 보면 수집이 며칠 밀렸다가 한 번에 도는 순간
        #   과거 법안 수백 건이 "신규 발의"로 쏟아진다.
        #   (2026-08-03 실측 사고: GitHub Actions 정지로 31시간 밀린 뒤 수동 실행하자
        #    203건이 한꺼번에 적재됐고 발의일이 2024-05-31~2026-07-21로 전부 과거였다.
        #    운영자 텔레그램에 개별 알림 수십 통이 쏟아졌다.)
        propose_floor = (datetime.now(KST) - timedelta(days=NEW_BILL_MAX_AGE_DAYS)).strftime('%Y-%m-%d')
        resp = sb.table('assembly_bills') \
            .select(cols + ',propose_dt') \
            .gte('created_at', cutoff) \
            .gte('propose_dt', propose_floor) \
            .execute()
        result['new'] = resp.data or []

        # (b) 처리 변경 — 컬럼 간 비교는 PostgREST로 불가 → 후보 조회 후 Python 비교
        resp = sb.table('assembly_bills') \
            .select(cols) \
            .gte('updated_at', cutoff) \
            .not_.is_('prev_proc_result', 'null') \
            .execute()
        result['changed'] = [
            r for r in (resp.data or [])
            if r.get('prev_proc_result') and r.get('prev_proc_result') != r.get('proc_result')
            and (r.get('proc_result') or '').strip() not in CHANGED_SKIP_TO
        ]

        # (c) 의견등록 — 진행 중 & 미노출 & **갓 시작한 것만** ('YYYY-MM-DD' 문자열 비교)
        #   국회 API(nknalejkafmvgzmpt)는 마감일(NOTI_ED_DT)만 주고 시작일을 안 준다.
        #   그래서 '남은 기간'으로 역산한다 — 국회법상 입법예고 기간은 10일 이상이므로,
        #   갓 시작한 건이면 잔여가 10일 가까이 남아 있고, 뒤늦게 발견한 건은 잔여가 짧다.
        #   (2026-08-03 사고: 수집이 31시간 밀린 뒤 몰아 돌자 이미 절반 이상 지난 예고 7건이
        #    "신규 의견등록"으로 브리핑에 잡혔다. 운영자 지시 — 오늘 발생한 것이 아니면 제외.)
        #   정상 운영(매일 수집)에서는 시작 당일에 잡히므로 잔여 ≈ 10일이라 그대로 실린다.
        notice_floor = (datetime.now(KST) + timedelta(days=NOTICE_MIN_REMAIN_DAYS)).strftime('%Y-%m-%d')
        resp = sb.table('assembly_bills') \
            .select(cols) \
            .gte('notice_end_dt', notice_floor) \
            .is_('notice_briefed_at', 'null') \
            .execute()
        notices = resp.data or []
        # 표시 여부와 무관하게 이번 브리핑에 노출되는 전량이 마킹 대상 (병합된 건 포함)
        result['briefed_ids'] = [r['bill_id'] for r in notices if r.get('bill_id')]

        # (a)신규 발의 ∩ (c)의견등록 → 한 줄로 병합, (c) 목록에서는 제외 (중복 출력 방지)
        # 운영자 지시(2026-08-03): 같은 법안이 두 섹션에 동시에 실리던 문제
        merged = set()
        for it in result['new']:
            hit = None
            for r in notices:
                if (it.get('bill_id') and it['bill_id'] == r.get('bill_id')) or \
                   (it.get('bill_name') and it['bill_name'] == r.get('bill_name')):
                    hit = r
                    break
            if hit:
                it['notice_end_dt'] = hit.get('notice_end_dt') or it.get('notice_end_dt')
                it['notice_url'] = it.get('notice_url') or hit.get('notice_url')
                it['notice_merged'] = True
                merged.add(id(hit))
        result['deadline'] = [r for r in notices if id(r) not in merged]

        print(f"[국회 법안] 신규 {len(result['new'])}건 / "
              f"처리변경 {len(result['changed'])}건 / "
              f"의견등록 신규노출 {len(result['briefed_ids'])}건"
              f"(병합 {len(merged)}건 → 단독 표시 {len(result['deadline'])}건)")
    except Exception as e:
        print(f'[국회 법안 조회 오류] {e}')
        return {'new': [], 'changed': [], 'deadline': [], 'briefed_ids': []}
    return result


def mark_notice_briefed(sb, bill_ids: list) -> int:
    """브리핑에 실린 입법예고 건의 notice_briefed_at 을 now()로 마킹 — 다음 날부터 (c)에서 제외.
    **반드시 발송 성공 후에만 호출**할 것(운영자 지시 2026-08-03): 발송 실패인데 마킹하면 영영 안 실린다."""
    ids = [b for b in (bill_ids or []) if b]
    if not ids:
        return 0
    stamp = datetime.now(KST).isoformat()
    done = 0
    for bill_id in ids:
        try:
            sb.table('assembly_bills').update({'notice_briefed_at': stamp}) \
                .eq('bill_id', bill_id).execute()
            done += 1
        except Exception as e:
            print(f'[입법예고 마킹 오류] {bill_id}: {e}')
    print(f'[입법예고] 1회 노출 마킹 {done}/{len(ids)}건 — 내일부터 재등장 없음')
    return done


def _notice_tag(notice_end_dt: str, today) -> str:
    """'의견등록 ~08-06 (D-3)' — 1회만 노출하므로 마감일·잔여일수를 태그에 담는다(운영자 지시 2026-08-03)."""
    nd = (notice_end_dt or '').strip()
    if not nd:
        return '의견등록'
    try:
        d_day = (datetime.strptime(nd, '%Y-%m-%d').date() - today).days
        return f'의견등록 ~{nd[5:]} (D-{d_day})'
    except ValueError:
        return f'의견등록 ~{nd}'


def _format_assembly_section(items: dict) -> str:
    """국회 법안 동향 브리핑 섹션"""
    today = datetime.now(KST).date()
    lines = ['🏛️ [국회 법안 동향]']
    new_items = list(items.get('new', []))
    new_more = max(0, len(new_items) - NEW_MAX_LINES)
    for it in new_items[:NEW_MAX_LINES]:
        bill = it.get('bill_name', '')
        proposer = it.get('proposer', '')
        tag = '신규 발의'
        if it.get('notice_merged'):   # (a)+(c) 병합 — 한 줄로 합쳐 중복 출력 방지
            tag += ' · ' + _notice_tag(it.get('notice_end_dt'), today)
        lines.append(f'• [{tag}] {bill} — {proposer}')
        if it.get('notice_url'):
            lines.append(f"  🔗 {it['notice_url']}")
    if new_more:
        lines.append(f'  … 신규 발의 외 {new_more}건 (대시보드 국회 법안 탭)')
    changed = [it for it in items.get('changed', [])
               if (it.get('proc_result') or '').strip() not in CHANGED_SKIP_TO]   # 포맷 단계에서도 한 번 더(호출자가 필터 안 했을 때)
    changed_more = max(0, len(changed) - CHANGED_MAX_LINES)
    for it in changed[:CHANGED_MAX_LINES]:
        bill = it.get('bill_name', '')
        prev = it.get('prev_proc_result', '')
        now = it.get('proc_result', '')
        lines.append(f'• [처리 변경] {bill}: {prev} → {now}')
        if it.get('notice_url'):
            lines.append(f"  🔗 {it['notice_url']}")
    if changed_more:
        lines.append(f'  … 처리 변경 외 {changed_more}건 (대시보드 국회 법안 탭)')
    for it in items.get('deadline', []):
        bill = it.get('bill_name', '')
        proposer = (it.get('proposer') or '').strip()
        tail = f' — {proposer}' if proposer else ''
        lines.append(f"• [{_notice_tag(it.get('notice_end_dt'), today)}] {bill}{tail}")
        if it.get('notice_url'):
            lines.append(f"  🔗 {it['notice_url']}")
    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════
#  메인
# ═══════════════════════════════════════════════════════

_FALLBACK_PREFIX = '⚠️ (본문 미확보'
_NONEWS_PREFIX = '🕊️ (신규 뉴스 없음'   # 기사 0건 placeholder 마커 — 기사 들어오면 정식본으로 교체 허용


def already_sent_today() -> bool:
    """오늘 브리핑이 이미 발송됐으면 True — 중복 발송 방지.
    단, 기존 브리핑이 폴백(간이)본 또는 무뉴스 placeholder면 정식 브리핑으로 교체 허용(False)."""
    today_date = datetime.now(KST).strftime('%Y-%m-%d')
    try:
        resp = sb.table('daily_briefings').select('content') \
            .eq('briefing_date', today_date).execute()
        if resp.data:
            existing = (resp.data[0].get('content') or '')
            if _FALLBACK_PREFIX in existing or _NONEWS_PREFIX in existing:
                print(f'[중복 방지] 오늘({today_date}) 브리핑은 폴백/무뉴스 placeholder — 정식본으로 교체 허용')
                return False
            print(f'[중복 방지] 오늘({today_date}) 브리핑이 이미 생성·발송됨 — 건너뜀')
            return True
    except Exception as e:
        print(f'[중복 체크 오류] {e}')
    return False


def _handle_no_news():
    """기사 0건인 날: 대시보드 공백 방지 placeholder 저장 + 1일 1회 텔레그램 통지.
    실행 시각과 무관하게 '오늘 신규 뉴스 없음'을 알려 '왜 브리핑이 안 왔지?' 혼선을 차단한다.
    (과거: 09시 이전 실행이면 조용히 종료 → 무음 누락으로 오인)
    placeholder는 already_sent_today가 교체 허용 → 이후 기사 들어오면 정식본으로 자동 대체.
    중복 텔레그램은 placeholder(_NONEWS_PREFIX) 존재 여부로 차단(아침 워크플로 2~4회 실행 대비)."""
    today_date = datetime.now(KST).strftime('%Y-%m-%d')
    today_str = datetime.now(KST).strftime('%Y년 %m월 %d일')
    # 오늘 무뉴스 통지를 이미 보냈는지 확인 (placeholder가 있으면 이미 통지함)
    already_notified = False
    try:
        resp = sb.table('daily_briefings').select('content') \
            .eq('briefing_date', today_date).execute()
        if resp.data:
            already_notified = _NONEWS_PREFIX in (resp.data[0].get('content') or '')
    except Exception as e:
        print(f'[무뉴스 체크 오류] {e}')
    # 대시보드 공백 방지용 placeholder 저장 (upsert)
    placeholder = (
        f'{_NONEWS_PREFIX} — 자동 placeholder, 기사 입력 시 정식본으로 교체됩니다.)\n\n'
        f'📡 통신·전파 정책 모닝 브리핑 — {today_str}\n\n'
        f'[안내]\n'
        f'• 최근 24시간 내 신규 수집 기사가 없습니다.\n'
        f'• 크롤러는 정상 작동 중이며(시스템 고장 아님), 신규 기사가 들어오면 정식 브리핑으로 자동 교체됩니다.\n\n'
        f'[저장 결과]\n뉴스 0건 / 기술 용어 0건'
    )
    save_briefing(placeholder, 0, 0)
    # 1일 1회 텔레그램 통지 (시각 무관)
    if not already_notified:
        send_telegram(
            f'🕊️ 오늘({today_str}) 모닝 브리핑 — 최근 24시간 내 신규 수집 기사가 없어 생략합니다. '
            f'(크롤러 정상 작동, 시스템 이상 아님)'
        )
        print('[무뉴스] 텔레그램 통지 1회 발송')
    else:
        print('[무뉴스] 오늘 이미 통지함 — 텔레그램 생략')


def main():
    now_str = datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')
    print(f'{"="*50}')
    print(f'[모닝 브리핑 시작] {now_str}')
    print(f'{"="*50}')

    # 중복 발송 방지 (daily_crawl과 morning_briefing.yml이 동시에 실행될 경우)
    if already_sent_today():
        return

    # 신규 입법예고 조회 (법제처·opinion.lawmaking.go.kr → law_amendments)
    law_ancs = fetch_new_law_announcements()

    # 본문 확인된 기사 조회
    items = fetch_items_with_content()
    fallback_mode = ''
    if not items:
        # 빈 브리핑 방지: 본문이 없으면 요약 → 제목 순으로 폴백
        items, fallback_mode = fetch_items_fallback()
    if not items:
        print('[종료] 최근 24시간 내 수집된 기사 자체가 없음')
        _handle_no_news()   # 시각 무관 1일 1회 통지 + 대시보드 placeholder
        return

    # 한 번도 브리핑에 못 실린 긴급 사건을 후보에 합친다 (#161-보론)
    items = items + fetch_carryover_items()

    # 같은 사건 재보도 → 대표 1건 + 관련 건수 (배경역사 #44)
    items = cluster_briefing_items(items)

    # 신규 기술 용어 조회 (오늘 추가된 것)
    new_terms = []
    try:
        # created_at은 UTC(timestamptz)인데 KST 날짜 문자열('2026-09-13')로 비교하면
        # 그 경계는 KST 09:00 — 06:00 발송 시점에서 3시간 뒤 미래라 언제나 0건이었다.
        # 7일 연속 [새로 추가된 기술 용어] 공란의 원인(#161). 오프셋이 붙은 24시간 창으로 비교한다.
        since = (datetime.now(KST) - timedelta(hours=24)).isoformat()
        resp = sb.table('tech_terms').select('term,definition') \
            .gte('created_at', since) \
            .execute()
        new_terms = _dedup_terms(resp.data or [])
        print(f'[용어] 오늘 신규 {len(new_terms)}건')
    except Exception as e:
        print(f'[용어 조회 오류] {e}')

    # 브리핑 생성
    briefing_text = generate_briefing(items, new_terms)
    if not briefing_text:
        print('[종료] 브리핑 생성 실패')
        return
    briefing_text = _restore_titles(briefing_text, items)
    briefing_text = _prune_orphan_terms(briefing_text)

    # 폴백(본문 미확보) 모드면 안내 문구 삽입 — already_sent_today가 이 접두사로 '교체 허용' 판단
    if fallback_mode:
        label = '요약' if fallback_mode == '요약' else '제목'
        briefing_text = (f'{_FALLBACK_PREFIX} — 기사 {label} 기반 간이 브리핑입니다. '
                         f'전체 본문은 PC 본문수집(refetch) 후 자동 갱신됩니다.)\n\n' + briefing_text)
        print(f'[폴백] {fallback_mode} 기반 간이 브리핑 생성')

    # 국회 법안 동향 섹션 — 먼저 앞에 붙여, 아래 입법예고 삽입 후 [신규 입법예고] 바로 뒤에 오도록
    # (입법예고 0건이면 그 자리인 맨 앞) 3종 모두 0건이면 섹션 미삽입
    assembly_items = fetch_assembly_items(sb)
    assembly_shown = ('new', 'changed', 'deadline')   # briefed_ids는 마킹용이라 표시 판단에서 제외
    if any(assembly_items.get(k) for k in assembly_shown):
        briefing_text = _format_assembly_section(assembly_items) + '\n\n' + briefing_text
        total = sum(len(assembly_items.get(k) or []) for k in assembly_shown)
        print(f'[국회 법안] {total}건 브리핑에 삽입')

    # 신규 입법예고 섹션을 브리핑 앞에 삽입 (🔴 → 이메일 빨간 박스)
    if law_ancs:
        briefing_text = _format_law_anc_section(law_ancs) + '\n\n' + briefing_text
        print(f'[입법예고] {len(law_ancs)}건 브리핑 앞에 삽입')

    # 해외 규제기관 동향 섹션을 브리핑 뒤에 삽입 ('참고' 등급 — 국내 뉴스를 밀지 않도록 말미)
    overseas_items = fetch_overseas_items()
    if overseas_items:
        briefing_text = briefing_text + '\n\n' + _format_overseas_section(overseas_items)
        print(f'[해외 동향] {len(overseas_items)}건 브리핑 뒤에 삽입')

    # 긴급(DB 기준) 기사 SKT 영향 분석 — 본문 확보 시에만 (폴백은 본문 빈약 → 생략)
    if not fallback_mode:
        briefing_text = add_urgent_analyses(items, briefing_text)

    # 저장
    save_briefing(briefing_text, len(items), len(new_terms))

    # news_feed.summary 역저장
    backfill_summaries(briefing_text)

    # 발송용 텍스트 — [ID:...] 태그 제거
    display_text = re.sub(r'\s*\[ID:[^\]]+\]', '', briefing_text)

    # 발송 — 텔레그램은 4000자 제한 때문에 영향 분석 줄 제외
    telegram_text = '\n'.join(l for l in display_text.split('\n') if 'SKT 영향 분석' not in l)
    ok_tg = send_telegram(telegram_text)
    ok_mail = send_email(display_text, len(items))

    # 입법예고 1회 노출 확정 — 발송 성공 뒤에만 마킹(운영자 지시 2026-08-03).
    # 어느 한 채널이라도 나갔으면 운영자는 이미 봤으므로 마킹, 둘 다 실패면 다음 실행에서 재노출.
    briefed_ids = assembly_items.get('briefed_ids') or []
    if briefed_ids:
        if ok_tg or ok_mail:
            mark_notice_briefed(sb, briefed_ids)
        else:
            print(f'[입법예고] 발송 실패 — notice_briefed_at 미갱신 {len(briefed_ids)}건(다음 실행 재노출)')

    print(f'{"="*50}')
    print('[모닝 브리핑 완료]')


if __name__ == '__main__':
    main()
