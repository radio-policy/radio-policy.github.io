#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
해외 규제기관 모니터링 수집기 (매일 실행)
대상 5개: FCC(미) / Ofcom(영) / BEREC(EU) / 일본 총무성(MIC) / ITU

동작:
1. 각 기관 최신 보도자료 목록 수집 (RSS 우선, 소스당 최근 최대 15건)
2. news_feed 기존 url 대비 신규만 → Haiku 1콜로 [관련성 판정 + 한글 제목 번역 + 한글 3문장 요약]
3. 관련 항목만 news_feed 저장 (category='해외', urgency/importance='참고',
   upsert on_conflict='url' + ignore_duplicates)
4. system_health heartbeat key='last_foreign_press_run'

판정 기준문 원본은 app_config key='foreign_relevance_criteria' — 조회 실패 시 내장 폴백.

소스별 실측 확정 (2026-08-02):
- FCC:   https://api2.fcc.gov/api/exp/v1.0.0/edocspublic/rss/docTypes/News_Release
         (EDOCS News Release RSS — Daily Digest 성격 피드는 사용하지 않음.
          www.fcc.gov/news-events/headlines/rss 류는 RSS가 아니라 HTML 반환)
- Ofcom: www.ofcom.org.uk 는 Cloudflare JS 챌린지로 직접 접근 전면 403(curl_cffi
         chrome110~131·safari·firefox 전부 실측 차단) → Google News RSS
         site:ofcom.org.uk 검색 피드로 우회 수집 (crawler.py의 Google RSS 폴백과 동일 관례)
- BEREC: https://www.berec.europa.eu/en/rss.xml (사이트 공식 RSS — 뉴스·협의·간행물 혼합,
         관련성 판정이 걸러냄)
- MIC:   https://www.soumu.go.jp/menu_news/s-news/index.html 報道資料 목록
         <table class="tableList"> HTML 파싱 (Shift_JIS). 월초로 당월분이 적으면 전월 페이지 보충
- ITU:   https://www.itu.int/hub/feed/ (ITU Hub 뉴스룸 WordPress RSS)

CLI: --dry-run (수집·판정·번역까지 수행, DB 무변경 — heartbeat도 생략)
"""

import os
import re
import sys
import html as html_mod
import time
import argparse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Ofcom(Cloudflare)·FCC(Akamai)는 일반 requests를 차단 — curl_cffi 우선 (press_ingest.py 관례)
try:
    from curl_cffi import requests
    USE_CURL_CFFI = True
except ImportError:
    import requests
    USE_CURL_CFFI = False

try:
    import trafilatura
except ImportError:
    trafilatura = None

try:
    import anthropic
except ImportError:
    anthropic = None

from sb_client import make_client

KST = timezone(timedelta(hours=9))

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

MAX_RETRY = 3
RETRY_DELAY = 5
MAX_PER_SOURCE = 15       # 소스당 최근 최대 처리 건수
JUDGE_EXCERPT = 3000      # Haiku 판정 입력 발췌 상한
CONTENT_EXCERPT = 2000    # news_feed.content 원문 발췌 상한
BODY_ENOUGH = 300         # description이 이보다 짧으면 상세 페이지 추출 시도

HAIKU_MODEL = 'claude-haiku-4-5-20251001'

# app_config key='foreign_relevance_criteria' 조회 실패 시 폴백
FOREIGN_CRITERIA_FALLBACK = (
    '다음 해외 규제기관 발표가 한국 통신사의 전파·통신 정책 업무에 참고할 가치가 있는지 판정한다. '
    '관련 있음: 주파수 분배·할당·경매·재배치, 5G·6G·IMT, 위성통신(NGSO·D2D 포함), '
    '스펙트럼 공유·개방(비면허 대역 포함), 무선국·무선기기 제도 변경(허가·면허·인증 제도 개편), '
    '통신시장 경쟁·요금·상호접속 규제, 망 중립성, 해저케이블·네트워크 인프라 정책, '
    '전파 이용료·대가 산정, AI·데이터 정책, ITU 표준·권고·WRC 관련 동향. '
    '관련 없음: 개별 사업자에 대한 개별 인허가 처분(개별 무선국 허가, 개별 벌금·과징금 부과), '
    '방송 콘텐츠 심의·제재, 인사·행사·채용·수상 안내, 소비자 캠페인 홍보, '
    '통신과 무관한 우정·행정·통계 발표.'
)


# ═══════════════════════════════════════════════════════
#  HTTP
# ═══════════════════════════════════════════════════════

def _get(url: str, timeout: int = 25, encoding: str = None):
    for attempt in range(1, MAX_RETRY + 1):
        try:
            if USE_CURL_CFFI:
                res = requests.get(url, impersonate='chrome110', timeout=timeout)
            else:
                res = requests.get(url, headers=HEADERS, timeout=timeout)
            res.raise_for_status()
            if encoding:
                res.encoding = encoding
            return res
        except Exception:
            if attempt < MAX_RETRY:
                time.sleep(RETRY_DELAY)
            else:
                raise


# ═══════════════════════════════════════════════════════
#  RSS 파싱 (표준 xml.etree — feedparser 미의존)
# ═══════════════════════════════════════════════════════

_ATOM_NS = '{http://www.w3.org/2005/Atom}'


def _strip_html(text: str) -> str:
    if not text:
        return ''
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html_mod.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


def _parse_feed_date(s: str):
    """RFC822/ISO 날짜 문자열 → aware datetime (실패 시 None)"""
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s.strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(s.strip().replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _parse_rss(content: bytes) -> list:
    """RSS 2.0/Atom → [{title, url, published(datetime|None), desc}]"""
    root = ET.fromstring(content)
    items = []
    for it in root.findall('.//item'):          # RSS 2.0
        items.append({
            'title': _strip_html(it.findtext('title') or ''),
            'url': (it.findtext('link') or '').strip(),
            'published': _parse_feed_date(it.findtext('pubDate') or ''),
            'desc': _strip_html(it.findtext('description') or ''),
        })
    if not items:                               # Atom 폴백
        for it in root.findall('.//%sentry' % _ATOM_NS):
            link = ''
            for l in it.findall('%slink' % _ATOM_NS):
                if l.get('rel') in (None, 'alternate'):
                    link = l.get('href', '')
                    break
            items.append({
                'title': _strip_html(it.findtext('%stitle' % _ATOM_NS) or ''),
                'url': link.strip(),
                'published': _parse_feed_date(
                    it.findtext('%spublished' % _ATOM_NS)
                    or it.findtext('%supdated' % _ATOM_NS) or ''),
                'desc': _strip_html(it.findtext('%ssummary' % _ATOM_NS)
                                    or it.findtext('%scontent' % _ATOM_NS) or ''),
            })
    return [i for i in items if i['title'] and i['url']]


# ═══════════════════════════════════════════════════════
#  소스 어댑터 5개 — 각자 [{title, url, published, desc}] 반환
# ═══════════════════════════════════════════════════════

FCC_FEED = 'https://api2.fcc.gov/api/exp/v1.0.0/edocspublic/rss/docTypes/News_Release'
OFCOM_FEED = ('https://news.google.com/rss/search?'
              'q=site:ofcom.org.uk+when:7d&hl=en-GB&gl=GB&ceid=GB:en')
BEREC_FEED = 'https://www.berec.europa.eu/en/rss.xml'
ITU_FEED = 'https://www.itu.int/hub/feed/'
MIC_LIST = 'https://www.soumu.go.jp/menu_news/s-news/index.html'
MIC_MONTH = 'https://www.soumu.go.jp/menu_news/s-news/%02d%02dm.html'   # (yy, mm)


def fetch_fcc() -> list:
    """FCC EDOCS News Release RSS (보도자료 전용 — Daily Digest 아님). pubDate 없음(실측)."""
    return _parse_rss(_get(FCC_FEED).content)


def fetch_ofcom() -> list:
    """Ofcom — 직접 접근은 Cloudflare 403(실측) → Google News site: 검색 RSS 우회.
    제목 말미의 ' - Ofcom' / ' - www.ofcom.org.uk' 출처 접미는 제거."""
    items = _parse_rss(_get(OFCOM_FEED).content)
    for it in items:
        it['title'] = re.sub(r'\s+-\s+(?:www\.)?[Oo]fcom(?:\.org\.uk)?\s*$', '', it['title']).strip()
        # Google News description은 자기 링크 재탕이라 본문 가치 없음(실측) — 비움
        if 'news.google.com' in it['desc'] or it['desc'] == it['title']:
            it['desc'] = ''
    return items


def fetch_berec() -> list:
    """BEREC 공식 RSS(뉴스·협의·간행물 혼합). description이 마크업 잔재라 정제만."""
    items = _parse_rss(_get(BEREC_FEED).content)
    for it in items:
        # 제목 반복으로 시작하는 description(실측) — 중복 제거
        if it['desc'].startswith(it['title']):
            it['desc'] = it['desc'][len(it['title']):].strip()
    return items


def fetch_itu() -> list:
    """ITU Hub 뉴스룸 RSS."""
    return _parse_rss(_get(ITU_FEED).content)


def _mic_parse(page_html: str) -> list:
    """報道資料一覧 <table class="tableList"> 행 파싱 (일본어 제목)."""
    items = []
    for m in re.finditer(
            r'<tr>\s*<td[^>]*>(\d{4})年(\d{1,2})月(\d{1,2})日</td>\s*'
            r'<td[^>]*><a href="([^"]+)"[^>]*>(.*?)</a>',
            page_html, re.S):
        y, mo, d, href, title = m.groups()
        title = _strip_html(title)
        if not title:
            continue
        url = href if href.startswith('http') else 'https://www.soumu.go.jp' + href
        try:
            published = datetime(int(y), int(mo), int(d), tzinfo=KST)
        except ValueError:
            published = None
        items.append({'title': title, 'url': url, 'published': published, 'desc': ''})
    return items


def fetch_mic() -> list:
    """일본 총무성 報道資料 목록 (Shift_JIS HTML). 월초엔 당월분이 적으므로 전월 보충."""
    res = _get(MIC_LIST, encoding='shift_jis')
    items = _mic_parse(res.text)
    if len(items) < MAX_PER_SOURCE:
        prev = datetime.now(KST).replace(day=1) - timedelta(days=1)
        try:
            res2 = _get(MIC_MONTH % (prev.year % 100, prev.month), encoding='shift_jis')
            seen = {i['url'] for i in items}
            items += [i for i in _mic_parse(res2.text) if i['url'] not in seen]
        except Exception as e:
            print('  [MIC 전월 보충 실패 — 당월분만 사용] %s' % str(e)[:80])
    return items


SOURCES = {
    # source 표기: news_feed.source 저장값
    'FCC':    fetch_fcc,
    'Ofcom':  fetch_ofcom,
    'BEREC':  fetch_berec,
    '日총무성': fetch_mic,
    'ITU':    fetch_itu,
}


# ═══════════════════════════════════════════════════════
#  Haiku 1콜: 관련성 판정 + 한글 제목 번역 + 한글 3문장 요약
# ═══════════════════════════════════════════════════════

def load_foreign_criteria(sb) -> str:
    try:
        rows = sb.table('app_config').select('value') \
            .eq('key', 'foreign_relevance_criteria').limit(1).execute().data
        if rows and (rows[0]['value'] or '').strip():
            return rows[0]['value'].strip()
    except Exception as e:
        print('[판정기준 조회 실패 — 폴백 사용] %s' % e)
    return FOREIGN_CRITERIA_FALLBACK


JUDGE_TOOL = {
    'name': 'record_judgement',
    'description': '해외 규제기관 발표의 관련성 판정과 한글 번역·요약을 기록한다.',
    'input_schema': {
        'type': 'object',
        'properties': {
            'relevant': {
                'type': 'boolean',
                'description': '기준문에 따라 한국 통신사 정책 업무 관련이면 true',
            },
            'title_ko': {
                'type': 'string',
                'description': '원문 제목의 자연스러운 한글 번역(뉴스 헤드라인체). 무관이면 빈 문자열 허용',
            },
            'summary_ko': {
                'type': 'string',
                'description': '한글 정확히 3문장 요약. 무관이면 빈 문자열 허용',
            },
            'major': {
                'type': 'boolean',
                'description': ('주요 정책이면 true — 규제·규칙의 제·개정, 공식 협의(consultation) '
                                '개시·결과, 인허가 제도 변경, 국가 전략·계획 발표 등 정책 행위. '
                                '단신·통계·보고서 소개·행사 안내는 false. 무관이면 false'),
            },
        },
        'required': ['relevant', 'title_ko', 'summary_ko', 'major'],
    },
}


def make_judge(criteria: str):
    """(source, title, excerpt) -> dict{relevant,title_ko,summary_ko} | None(호출 실패)"""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key or anthropic is None:
        return None
    client = anthropic.Anthropic(api_key=api_key)

    def judge(source: str, title: str, excerpt: str):
        prompt = (
            '아래는 해외 규제기관 발표의 관련성 판정 기준이다.\n\n'
            + criteria
            + '\n\n다음 발표를 판정하고, 관련이면 한글 제목 번역과 한글 3문장 요약을 작성하라. '
              '요약은 발표의 핵심 내용·배경·의미를 담되 발췌에 없는 내용은 지어내지 마라. '
              '관련인 경우 major(주요 정책 여부)도 판정하라 — 규제·규칙 제·개정, 공식 협의 개시·결과, '
              '인허가 제도 변경, 국가 전략 발표면 true, 단신·통계·소개면 false.\n\n'
            + '기관: %s\n원문 제목: %s\n원문 발췌:\n%s' % (source, title, (excerpt or '(본문 없음 — 제목만으로 판정)')[:JUDGE_EXCERPT])
        )
        try:
            resp = client.messages.create(
                model=HAIKU_MODEL,
                max_tokens=1000,
                tools=[JUDGE_TOOL],
                tool_choice={'type': 'tool', 'name': 'record_judgement'},
                messages=[{'role': 'user', 'content': prompt}],
            )
            for blk in resp.content:
                if getattr(blk, 'type', '') == 'tool_use':
                    out = blk.input or {}
                    return {
                        'relevant': bool(out.get('relevant')),
                        'title_ko': (out.get('title_ko') or '').strip(),
                        'summary_ko': (out.get('summary_ko') or '').strip(),
                        'major': bool(out.get('major')),
                    }
            return None
        except Exception as e:
            print('  [판정 호출 실패] %s' % str(e)[:100])
            return None

    return judge


# ═══════════════════════════════════════════════════════
#  본문 확보 (RSS description 우선, 부족 시 trafilatura)
# ═══════════════════════════════════════════════════════

def fetch_body(item: dict) -> str:
    desc = (item.get('desc') or '').strip()
    if len(desc) >= BODY_ENOUGH:
        return desc
    if trafilatura is None:
        return desc
    if 'news.google.com' in item['url']:
        return desc   # Google 리다이렉트 페이지는 JS 전용 — 추출 무의미(실측)
    try:
        res = _get(item['url'])
        out = trafilatura.extract(res.text, url=item['url'],
                                  include_comments=False, include_tables=False)
        if out and len(out.strip()) > len(desc):
            return out.strip()
    except Exception as e:
        print('  [본문 추출 실패 — 제목/발췌로 판정] %s' % str(e)[:80])
    return desc


# ═══════════════════════════════════════════════════════
#  실행
# ═══════════════════════════════════════════════════════

def load_existing_urls(sb) -> set:
    """news_feed 기존 url 셋 (60일 롤링이라 전량 조회 부담 낮음 — crawler.py와 동일 관례)"""
    urls = set()
    page = 0
    while True:
        rows = sb.table('news_feed').select('url') \
            .range(page * 1000, page * 1000 + 999).execute().data
        if not rows:
            break
        urls.update(r['url'] for r in rows if r.get('url'))
        if len(rows) < 1000:
            break
        page += 1
    return urls


def _heartbeat(sb, note: str):
    try:
        sb.table('system_health').upsert(
            {'key': 'last_foreign_press_run',
             'updated_at': datetime.now(timezone.utc).isoformat(),
             'note': note},
            on_conflict='key').execute()
    except Exception as e:
        print('[heartbeat 오류] %s' % e)


def run(dry: bool = False, only: list = None) -> int:
    sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    criteria = load_foreign_criteria(sb)
    judge = make_judge(criteria)
    if judge is None:
        # 번역·요약 없이는 저장 형식을 만들 수 없음 — fail-closed (뉴스 크롤러와 달리
        # 원문이 외국어라 키워드 폴백이 성립하지 않는다)
        print('[중단] ANTHROPIC_API_KEY 또는 anthropic 라이브러리 없음 — 판정·번역 불가')
        _heartbeat(sb, 'skip: no ANTHROPIC_API_KEY')
        return 0

    existing = load_existing_urls(sb)
    print('[해외 수집] 기존 news_feed url %d건, dry-run=%s' % (len(existing), dry))

    rows_to_save = []
    totals = {'scan': 0, 'new': 0, 'rel': 0, 'irrel': 0, 'fail': 0, 'promoted': 0}
    for src, fetch_fn in SOURCES.items():
        if only and src not in only:
            continue
        stats = {'scan': 0, 'new': 0, 'rel': 0, 'irrel': 0, 'fail': 0}
        try:
            feed_items = fetch_fn()
        except Exception as e:
            print('[%s] 목록 수집 실패: %s' % (src, str(e)[:100]))
            totals['fail'] += 1
            continue
        stats['scan'] = len(feed_items)
        seen = set()
        fresh = []
        for it in feed_items[:MAX_PER_SOURCE]:
            if it['url'] in existing or it['url'] in seen:
                continue
            seen.add(it['url'])
            fresh.append(it)
        stats['new'] = len(fresh)
        for it in fresh:
            body = fetch_body(it)
            verdict = judge(src, it['title'], body)
            time.sleep(0.5)   # Haiku 연속 호출 스로틀 (판정 결과와 무관하게)
            if verdict is None:
                stats['fail'] += 1
                continue
            if not verdict['relevant']:
                stats['irrel'] += 1
                print('  [무관 스킵][%s] %s' % (src, it['title'][:60]))
                continue
            if not verdict['title_ko'] or not verdict['summary_ko']:
                stats['fail'] += 1
                print('  [번역 누락 스킵][%s] %s' % (src, it['title'][:60]))
                continue
            stats['rel'] += 1
            pub = it['published'] or datetime.now(KST)
            content = (verdict['summary_ko']
                       + '\n\n(원제) ' + it['title']
                       + '\n' + (body or '')[:CONTENT_EXCERPT])
            row = {
                'title': verdict['title_ko'],
                'source': src,
                'category': '해외',
                'url': it['url'],
                'content': content,
                'summary': verdict['summary_ko'],
                'published_at': pub.isoformat(),
                'urgency': '참고',
                'importance': '참고',
                'is_read': False,
            }
            if dry:
                print('  [dry-run 관련%s][%s] %s' % (
                    '·주요' if verdict.get('major') else '', src, verdict['title_ko'][:70]))
                print('     원제: %s' % it['title'][:80])
                print('     요약: %s' % verdict['summary_ko'][:160])
            else:
                rows_to_save.append(row)
                # 주요 정책은 지식베이스로 승격 — 영구 보관 + AI 자문 참조 (운영자 지시 2026-08-02, #54)
                if verdict.get('major'):
                    try:
                        import press_ingest
                        year = pub.year
                        kb_body = (verdict['summary_ko']
                                   + '\n\n' + (body or '')[:2000]
                                   + '\n\n(원제) ' + it['title']
                                   + '\n(기관) ' + src)
                        header = ('# 해외 규제동향 %d년\n\n> FCC·Ofcom·BEREC·日총무성·ITU '
                                  '주요 정책 자동 승격분\n\n---\n\n' % year)
                        if press_ingest.register_kb_section(
                                sb, '해외규제동향_%d.md' % year, '해외동향',
                                pub.strftime('%y%m%d'), '[%s] %s' % (src, verdict['title_ko']),
                                kb_body, it['url'], header):
                            stats['promoted'] = stats.get('promoted', 0) + 1
                            print('  [KB 승격][%s] %s' % (src, verdict['title_ko'][:60]))
                    except Exception as e:
                        print('  [KB 승격 실패 — 무시] %s' % str(e)[:80])
        print('[%s] 스캔 %d, 신규 %d, 관련 %d, 무관 %d, 실패 %d'
              % (src, stats['scan'], stats['new'], stats['rel'],
                 stats['irrel'], stats['fail']))
        for k in totals:
            totals[k] += stats.get(k, 0)
        time.sleep(1)

    if rows_to_save and not dry:
        try:
            sb.table('news_feed').upsert(
                rows_to_save, on_conflict='url', ignore_duplicates=True).execute()
            print('[저장] %d건 news_feed 저장 완료' % len(rows_to_save))
        except Exception as e:
            print('[저장 오류] %s' % e)
            totals['fail'] += len(rows_to_save)
            totals['rel'] -= len(rows_to_save)

    note = 'scan=%d new=%d rel=%d irrel=%d fail=%d promoted=%d' % (
        totals['scan'], totals['new'], totals['rel'], totals['irrel'], totals['fail'],
        totals.get('promoted', 0))
    print('[해외 수집 완료] ' + note)
    if not dry:
        _heartbeat(sb, note)
        # KB 승격분 임베딩 백필 (NULL만 채움 — 멱등)
        if totals.get('promoted', 0) > 0:
            import subprocess
            try:
                r = subprocess.run(
                    [sys.executable, 'backfill_embeddings.py'],
                    cwd=os.path.dirname(os.path.abspath(__file__)),
                    capture_output=True, encoding='utf-8', errors='replace',
                    env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}, timeout=1800)
                print('[임베딩 백필] rc=%d' % r.returncode)
            except Exception as e:
                print('[임베딩 백필 오류] %s' % e)
    return totals['rel']


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true',
                    help='수집·판정·번역까지 수행하되 DB에 쓰지 않음')
    ap.add_argument('--source', default='',
                    help='특정 소스만 실행 (쉼표 구분: FCC,Ofcom,BEREC,日총무성,ITU)')
    args = ap.parse_args()
    only = [s.strip() for s in args.source.split(',') if s.strip()] or None
    run(dry=args.dry_run, only=only)
