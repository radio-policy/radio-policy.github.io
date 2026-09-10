# -*- coding: utf-8 -*-
"""
뉴스 → 기술 용어 자동 추출 (무인 반복, 매일 05:00 KST — GitHub Actions term_extract.yml, pg_cron이 주 트리거)

2026-09-09 (#141) 대시보드의 브라우저 자동 경로(autoExtractTermsIfNeeded — 승인자가 화면을 열면
60초 뒤 Haiku 추출 + 새 용어마다 Sonnet 상세 생성)를 **이 스크립트로 대체**했다. 이유:
  - 브라우저 경로는 "누가 열었나"에 묶인다(승인자 브라우저마다 / 서버 게이트를 둬도 첫 접속자 기준).
  - 새 용어 상세(Sonnet 6,000토큰)가 일반 승인자 브라우저에서 돌면 그 사람의 자문 한도가 깎인다.
  - 무인 반복 작업은 API로 돌린다는 운영 규칙(#111·#120)에 맞다. 브라우저는 더 이상 AI를 부르지 않는다.

흐름: 최근 7일 news_feed 제목 30건 → Haiku(대시보드와 같은 프롬프트) → 신규 용어 JSON →
      tech_terms insert(기존 용어 제외, is_reviewed=false) → 이어서 backfill_term_details.py --limit N 이
      설명·SVG·관련용어를 채운다(워크플로가 순서대로 실행).
heartbeat: system_health key 'last_term_extract_run'.
필요 env: SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY
"""
import os
import re
import sys
import json
import argparse
from datetime import datetime, timezone, timedelta

# Windows 스케줄러/cp949 콘솔 이모지 크래시 방지 (배경역사 #19)
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

import anthropic
from sb_client import make_client
import api_usage; api_usage.install()   # Anthropic usage 기록(#152) — 호출부 무변경, fail-open

SUPABASE_URL      = os.environ['SUPABASE_URL']
SUPABASE_KEY      = os.environ['SUPABASE_SERVICE_KEY']
ANTHROPIC_API_KEY = os.environ['ANTHROPIC_API_KEY']

MODEL = 'claude-haiku-4-5-20251001'   # 종전 app.js autoExtractTermsIfNeeded와 동일
NEWS_DAYS = 7
NEWS_LIMIT = 30

sb = make_client(SUPABASE_URL, SUPABASE_KEY)
ai = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def heartbeat(note: str) -> None:
    try:
        sb.table('system_health').upsert(
            {'key': 'last_term_extract_run',
             'updated_at': datetime.now(timezone.utc).isoformat(),
             'note': note},
            on_conflict='key').execute()
    except Exception as e:
        print('[heartbeat 오류] %s' % e)


def fetch_recent_news() -> str:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=NEWS_DAYS)).strftime('%Y-%m-%d')
    rows = (sb.table('news_feed').select('title,source,published_at')
            .gte('created_at', cutoff)
            .order('created_at', desc=True).limit(NEWS_LIMIT).execute().data) or []
    return '\n'.join('[%s] %s (%s)' % ((r.get('published_at') or '')[:10], r.get('title') or '', r.get('source') or '')
                     for r in rows)


def existing_terms() -> set:
    # 종전 브라우저 코드는 500건까지만 봤다 — 용어가 364건이라 곧 넘친다. 전량을 본다.
    rows = (sb.table('tech_terms').select('term').limit(5000).execute().data) or []
    return {(r.get('term') or '').lower() for r in rows if r.get('term')}


def extract(news_list: str) -> list:
    user_msg = ('아래 뉴스 목록에서 이동통신·전파 분야 기술 용어(영문 약어, 표준명, 새 기술명)를 추출하세요.\n'
                '흔한 용어(5G, LTE, Wi-Fi 등)는 제외하세요.\n\n'
                '뉴스 목록:\n' + news_list + '\n\n'
                'JSON 배열로만 출력 (신규 용어만, 없으면 []): '
                '[{"term":"...","term_en":"...","category":"...","definition":"...","source":"..."}]')
    resp = ai.messages.create(model=MODEL, max_tokens=1000,
                              messages=[{'role': 'user', 'content': user_msg}])
    text = ''.join(b.text for b in resp.content if b.type == 'text')
    a, b = text.find('['), text.rfind(']')
    if a < 0 or b < 0:
        return []
    try:
        terms = json.loads(text[a:b + 1])
    except Exception:
        return []
    return terms if isinstance(terms, list) else []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='DB 쓰기 없이 추출 결과만 출력')
    args = ap.parse_args()

    news_list = fetch_recent_news()
    if not news_list:
        print('[용어 추출] 최근 %d일 뉴스 없음 — 스킵' % NEWS_DAYS)
        if not args.dry_run:
            heartbeat('news=0 new=0')
        return
    have = existing_terms()
    terms = extract(news_list)
    print('[용어 추출] 후보 %d건 (기존 용어 %d건)' % (len(terms), len(have)))

    saved = 0
    for t in terms:
        term = (t.get('term') or '').strip() if isinstance(t, dict) else ''
        if not term or term.lower() in have:
            continue
        payload = {
            'term': term,
            'term_en': (t.get('term_en') or '').strip(),
            'category': (t.get('category') or '기타').strip(),
            'definition': (t.get('definition') or '').strip(),
            'source': (t.get('source') or '뉴스 자동 추출').strip(),
            'is_reviewed': False,
        }
        if args.dry_run:
            print('  [dry-run] %s (%s) — %s' % (term, payload['category'], payload['definition'][:60]))
            saved += 1
            continue
        try:
            sb.table('tech_terms').insert(payload).execute()
            have.add(term.lower())
            saved += 1
            print('  + %s (%s)' % (term, payload['category']))
        except Exception as e:
            print('  [저장 실패] %s: %s' % (term, str(e)[:100]))

    note = 'news=%d cand=%d new=%d' % (len(news_list.splitlines()), len(terms), saved)
    print('[용어 추출 완료] ' + note)
    if not args.dry_run:
        heartbeat(note)


if __name__ == '__main__':
    main()
