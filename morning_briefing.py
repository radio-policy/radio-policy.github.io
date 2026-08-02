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

def fetch_items_with_content() -> list:
    """최근 24h 기사 중 content 있는 것만 반환 (id 포함)"""
    cutoff = (datetime.now(KST) - timedelta(hours=24)).isoformat()
    try:
        resp = sb.table('news_feed') \
            .select('id,title,source,url,published_at,content,urgency') \
            .gte('published_at', cutoff) \
            .not_.is_('content', 'null') \
            .order('published_at', desc=True) \
            .limit(300) \
            .execute()
        # limit 60이던 시절, 대형 사건 재보도가 하루 261건 쏟아지자 조회 60건 중 55건이
        # 한 사건이었고 다른 뉴스가 브리핑에서 통째로 밀려났다(배경역사 #44).
        # 넉넉히 300건을 받아 클러스터링으로 줄이는 방식으로 변경.
        items = [it for it in (resp.data or []) if it.get('content') and len(it['content'].strip()) > 50]
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
        for rep, members in cluster_star(items):   # 최신순 입력 → 최신 기사가 대표
            rep['_related'] = len(members)
            reps.append(rep)
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

_BRIEFING_SYSTEM = """당신은 SK텔레콤 Comm센터 기술정책팀의 전파정책 모닝 브리핑 작성 AI입니다.
제공된 뉴스 목록과 각 기사의 본문을 바탕으로 간결하고 실용적인 브리핑을 작성하세요.

작성 규칙:
- [주요 뉴스]는 제공된 기사에서만 선별 (최대 8건, 긴급·보통 기사 우선)
- 같은 사건·주제를 다룬 기사가 여러 건일 경우 가장 중요한 1건만 선별 (중복 주제 제외)
- 제목 뒤 (관련 보도 N건)은 같은 사건을 다룬 기사 수 — 선별한 항목에 그대로 표기해 보도 규모가 보이게 할 것
- **같은 사건이 여러 항목으로 나뉘어 들어올 수 있다**(예: 같은 과징금 건이 금액 표기만 다르게 2~3건). 이때는 (관련 보도 N건)이 가장 큰 1건만 [주요 뉴스]에 넣고 나머지는 버릴 것 — 사건이 같은지는 제목의 주체·사안으로 판단
- 〔전일 기보도 이어짐〕 표시가 있는 기사를 선별하면 그 표시를 제목 뒤에 유지하고, 요약은 새로 알려진 내용 위주로 짧게 쓸 것
- [주목 포인트]는 SKT Comm센터 정책·기술 관점에서 핵심 이슈 1~3개 도출
- 반드시 제공된 본문 내용에 근거해서만 요약 작성 — 추측·외부 지식 금지
- 각 뉴스에 본문 기반 한 줄 요약 포함
- [ID:기사id] 태그를 제목 뒤에 반드시 포함 (역저장에 사용)
- 🔴 긴급 표시는 입력 뉴스 목록에서 🔴 아이콘이 붙은 기사에만 사용할 것 (크롤러·담당자 검증 분류 기준)
  ※ 입력에서 🔴인 기사를 [주요 뉴스]에 선별하면 🔴를 그대로 유지하고, 🟡·🟢 기사에 새로 🔴를 붙이지 말 것

출력 형식 (아래 형식 그대로):
📡 전파정책 모닝 브리핑 — {날짜}

[주요 뉴스]
• 제목 — 출처 [ID:기사id]
  → 한 줄 요약 (본문 근거, 1~2문장)
  🔗 URL

[주목 포인트]
• 핵심 이슈 1
• 핵심 이슈 2

[새로 추가된 기술 용어]
• 용어: 정의

[저장 결과]
뉴스 N건 / 기술 용어 N건"""


def generate_briefing(items: list, new_terms: list, for_date: datetime = None) -> str:
    """for_date: 과거 브리핑 재생성용. 미지정 시 오늘(정상 운영 경로).
    지정하지 않으면 재생성본에 '오늘' 날짜가 찍혀 7/31 브리핑에 8/1이 박힌다(#46)."""
    if not ANTHROPIC_API_KEY:
        print('[브리핑] ANTHROPIC_API_KEY 없음 — 건너뜀')
        return ''

    today_str = (for_date or datetime.now(KST)).strftime('%Y년 %m월 %d일')

    news_lines = []
    for it in items[:50]:
        icon = {'긴급': '🔴', '보통': '🟡', '참고': '🟢'}.get(it.get('urgency', '참고'), '🟢')
        body = (it.get('content') or '').replace('\n', ' ').strip()[:400]
        # 클러스터 대표에는 보도 규모·전일 연속 여부를 병기 (배경역사 #44)
        rel = it.get('_related', 0)
        tags = (f' (관련 보도 {rel + 1}건)' if rel else '') + (' 〔전일 기보도 이어짐〕' if it.get('_prev') else '')
        news_lines.append(
            f"{icon} {it['title']}{tags} — {it.get('source','')} [ID:{it['id']}]\n"
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
            max_tokens=2500,
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
- 3~4문장, 제공된 본문에 근거한 내용만 (추측·과장 금지)
- 영향이 불명확하면 '추가 정보 수집 필요'를 명시
- 마지막 문장에 권고 대응 1가지 포함
- 줄바꿈 없이 한 단락으로만 출력"""


def add_urgent_analyses(items: list, briefing_text: str) -> str:
    """DB 긴급도='긴급' 기사 중 브리핑에 포함된 기사에 SKT 영향 분석을 생성해
    해당 기사 블록 뒤에 삽입. 저장본에 포함되므로 이메일·대시보드가 동일 내용 표시."""
    if not ANTHROPIC_API_KEY or not briefing_text:
        return briefing_text
    urgent = [it for it in items if it.get('urgency') == '긴급' and f"[ID:{it['id']}]" in briefing_text]
    if not urgent:
        return briefing_text
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    lines = briefing_text.split('\n')
    for it in urgent[:3]:
        try:
            body = (it.get('content') or '').replace('\n', ' ').strip()[:1500]
            resp = client.messages.create(
                model='claude-haiku-4-5-20251001', max_tokens=400,
                system=_IMPACT_SYSTEM,
                messages=[{'role': 'user', 'content': f"제목: {it['title']}\n본문: {body}"}],
            )
            analysis = resp.content[0].text.strip().replace('\n', ' ')
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


def send_telegram(briefing_text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print('[텔레그램] 환경변수 미설정 — 건너뜀')
        return
    html_text = _briefing_to_telegram_html(briefing_text)
    text = html_text[:4000]
    if len(html_text) > 4000:
        # 태그 중간에서 잘리면 400이 나므로 마지막 완결 줄까지만 남긴다
        text = text[:text.rfind('\n')] if '\n' in text else text
        text += '\n\n...(전문은 대시보드 참조)'
    text += '\n\n📊 <a href="https://youjinwoong.github.io/radio-policy-ai/">대시보드</a>'
    api = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    body = {'chat_id': TELEGRAM_CHAT_ID, 'text': text, 'parse_mode': 'HTML',
            'disable_web_page_preview': True}
    try:
        resp = requests.post(api, json=body, timeout=15)
        if resp.status_code == 400:
            # HTML 파싱 실패 시 평문으로 재시도 — 포맷 때문에 브리핑 자체를 잃지 않도록(fail-open)
            print(f'[텔레그램] HTML 400 → 평문 재시도: {resp.text[:150]}')
            plain = re.sub(r'<[^>]+>', '', text)
            resp = requests.post(api, json={'chat_id': TELEGRAM_CHAT_ID, 'text': plain,
                                            'disable_web_page_preview': True}, timeout=15)
        if resp.status_code == 200:
            print('[텔레그램] 발송 완료')
        else:
            print(f'[텔레그램 오류] HTTP {resp.status_code}: {resp.text[:200]}')
    except Exception as e:
        print(f'[텔레그램 오류] {e}')


def _briefing_to_html(text: str) -> str:
    import html as hl
    lines = text.split('\n')
    out = []
    in_box = False
    for line in lines:
        e = hl.escape(line)
        is_urgent = '🔴' in line
        if in_box and not is_urgent and (e.startswith('[') or '📡' in line or e == ''):
            out.append('</div>')
            in_box = False
        if is_urgent:
            if not in_box:
                out.append('<div style="border:2px solid #c53030;border-radius:6px;background:#fff5f5;padding:10px 14px;margin:10px 0">')
                in_box = True
            out.append(f'<p style="margin:3px 0">{e}</p>')
        elif '📡' in line:
            out.append(f'<h2 style="color:#534AB7;margin-bottom:4px">{e}</h2>')
        elif e.startswith('[') and e.endswith(']'):
            out.append(f'<h3 style="color:#1a1a1a;margin:18px 0 6px;border-bottom:1px solid #eee;padding-bottom:4px">{e}</h3>')
        elif e.startswith('•') or '🟡' in line or '🟢' in line:
            out.append(f'<p style="margin:4px 0 4px 12px">{e}</p>')
        elif '⚠️ SKT 영향 분석' in line:
            out.append(f'<p style="margin:6px 0 4px 24px;color:#9b2c2c;font-size:13px">{e.strip()}</p>')
        elif e.startswith('  →'):
            out.append(f'<p style="margin:2px 0 2px 24px;color:#555;font-size:13px">{e}</p>')
        elif e.startswith('  🔗'):
            url = line.strip()[2:].strip()
            out.append(f'<p style="margin:2px 0 8px 24px;font-size:12px"><a href="{url}" style="color:#534AB7">{url}</a></p>')
        elif e == '':
            out.append('<br>')
        else:
            out.append(f'<p style="margin:4px 0">{e}</p>')
    if in_box:
        out.append('</div>')
    return '\n'.join(out)


def send_email(briefing_text: str, news_count: int):
    today = datetime.now(KST).strftime('%Y.%m.%d')
    subject = f'☀️ [전파정책 AI] {today} 모닝 브리핑 — {news_count}건'
    body_html = f'''
<html><body style="font-family:sans-serif;max-width:640px;margin:auto;padding:20px">
{_briefing_to_html(briefing_text)}
<hr style="margin-top:24px">
<p style="color:#999;font-size:11px">
이 메일은 자동 발송됩니다. SKT Comm센터 기술정책팀<br>
대시보드: <a href="https://youjinwoong.github.io/radio-policy-ai/">https://youjinwoong.github.io/radio-policy-ai/</a>
</p>
</body></html>'''
    extra_to = 'lampman@sktelecom.com'
    all_to = list({a.strip() for a in (EMAIL_TO + ',' + extra_to).split(',') if a.strip()})

    # Resend API 우선 (GitHub Actions 미국 IP에서도 동작)
    # 도메인 미인증 상태: you.jinwoong@gmail.com으로만 발송 가능
    resend_to = ['you.jinwoong@gmail.com']
    if RESEND_API_KEY:
        _send_via_resend(subject, body_html, resend_to)
    elif all([EMAIL_FROM, EMAIL_PASS, EMAIL_TO]):
        # 폴백: Gmail SMTP (PC 로컬 실행 시)
        _send_via_gmail(subject, body_html, all_to)
    else:
        print('[이메일] RESEND_API_KEY 또는 Gmail 환경변수 미설정 — 건너뜀')


def _send_via_resend(subject: str, body_html: str, all_to: list):
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
        else:
            print(f'[이메일/Resend 오류] HTTP {resp.status_code}: {resp.text[:200]}')
    except Exception as e:
        print(f'[이메일/Resend 오류] {e}')


def _send_via_gmail(subject: str, body_html: str, all_to: list):
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
    except Exception as e:
        print(f'[이메일/Gmail 오류] {e}')


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

def fetch_assembly_items(sb) -> dict:
    """국회 법안 동향 3종 조회 — assembly_bills
    (a) 신규 발의: created_at 최근 24h
    (b) 처리 변경: updated_at 최근 24h & prev_proc_result ≠ proc_result
    (c) 의견등록 마감 임박: notice_end_dt 오늘(KST)~오늘+3"""
    cutoff = (datetime.now(KST) - timedelta(hours=24)).isoformat()
    today = datetime.now(KST).date()
    cols = 'bill_name,proposer,committee,proc_result,prev_proc_result,notice_end_dt,notice_url'
    result = {'new': [], 'changed': [], 'deadline': []}
    try:
        # (a) 신규 발의
        resp = sb.table('assembly_bills') \
            .select(cols) \
            .gte('created_at', cutoff) \
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
        ]

        # (c) 의견등록 마감 임박 (오늘~D+3, 'YYYY-MM-DD' 문자열 비교)
        resp = sb.table('assembly_bills') \
            .select(cols) \
            .gte('notice_end_dt', today.strftime('%Y-%m-%d')) \
            .lte('notice_end_dt', (today + timedelta(days=3)).strftime('%Y-%m-%d')) \
            .execute()
        result['deadline'] = resp.data or []

        print(f"[국회 법안] 신규 {len(result['new'])}건 / "
              f"처리변경 {len(result['changed'])}건 / 마감임박 {len(result['deadline'])}건")
    except Exception as e:
        print(f'[국회 법안 조회 오류] {e}')
        return {'new': [], 'changed': [], 'deadline': []}
    return result


def _format_assembly_section(items: dict) -> str:
    """국회 법안 동향 브리핑 섹션"""
    today = datetime.now(KST).date()
    lines = ['🏛️ [국회 법안 동향]']
    for it in items.get('new', []):
        bill = it.get('bill_name', '')
        proposer = it.get('proposer', '')
        lines.append(f'• [신규 발의] {bill} — {proposer}')
        if it.get('notice_url'):
            lines.append(f"  🔗 {it['notice_url']}")
    for it in items.get('changed', []):
        bill = it.get('bill_name', '')
        prev = it.get('prev_proc_result', '')
        now = it.get('proc_result', '')
        lines.append(f'• [처리 변경] {bill}: {prev} → {now}')
        if it.get('notice_url'):
            lines.append(f"  🔗 {it['notice_url']}")
    for it in items.get('deadline', []):
        bill = it.get('bill_name', '')
        nd = it.get('notice_end_dt') or ''
        try:
            d_day = (datetime.strptime(nd, '%Y-%m-%d').date() - today).days
            lines.append(f'• [의견등록 마감 임박] {bill} ~{nd[5:]} (D-{d_day})')
        except ValueError:
            lines.append(f'• [의견등록 마감 임박] {bill} ~{nd}')
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
        f'📡 전파정책 모닝 브리핑 — {today_str}\n\n'
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

    # 같은 사건 재보도 → 대표 1건 + 관련 건수 (배경역사 #44)
    items = cluster_briefing_items(items)

    # 신규 기술 용어 조회 (오늘 추가된 것)
    new_terms = []
    try:
        today_date = datetime.now(KST).strftime('%Y-%m-%d')
        resp = sb.table('tech_terms').select('term,definition') \
            .gte('created_at', today_date) \
            .execute()
        new_terms = resp.data or []
        print(f'[용어] 오늘 신규 {len(new_terms)}건')
    except Exception as e:
        print(f'[용어 조회 오류] {e}')

    # 브리핑 생성
    briefing_text = generate_briefing(items, new_terms)
    if not briefing_text:
        print('[종료] 브리핑 생성 실패')
        return

    # 폴백(본문 미확보) 모드면 안내 문구 삽입 — already_sent_today가 이 접두사로 '교체 허용' 판단
    if fallback_mode:
        label = '요약' if fallback_mode == '요약' else '제목'
        briefing_text = (f'{_FALLBACK_PREFIX} — 기사 {label} 기반 간이 브리핑입니다. '
                         f'전체 본문은 PC 본문수집(refetch) 후 자동 갱신됩니다.)\n\n' + briefing_text)
        print(f'[폴백] {fallback_mode} 기반 간이 브리핑 생성')

    # 국회 법안 동향 섹션 — 먼저 앞에 붙여, 아래 입법예고 삽입 후 [신규 입법예고] 바로 뒤에 오도록
    # (입법예고 0건이면 그 자리인 맨 앞) 3종 모두 0건이면 섹션 미삽입
    assembly_items = fetch_assembly_items(sb)
    if any(assembly_items.values()):
        briefing_text = _format_assembly_section(assembly_items) + '\n\n' + briefing_text
        total = sum(len(v) for v in assembly_items.values())
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
    send_telegram(telegram_text)
    send_email(display_text, len(items))

    print(f'{"="*50}')
    print('[모닝 브리핑 완료]')


if __name__ == '__main__':
    main()
