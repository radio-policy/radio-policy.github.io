# -*- coding: utf-8 -*-
"""
tech_terms 상세(description·diagram_html·related_terms) 백필.

2026-09-09 (#141) 부터 **매일 05:00 KST 무인 실행**(GitHub Actions term_extract.yml — term_extract.py 다음 단계).
종전에는 대시보드가 새 용어를 뽑은 직후 브라우저에서 Sonnet 상세를 만들었는데(승인자의 자문 한도가 깎이는
구조), 브라우저 자동 경로를 없애고 이 스크립트가 빈 항목만 골라 채운다. 이미 채워진 필드는 덮어쓰지 않는다(멱등).

- 모델: claude-sonnet-5 (app.js generateTermDetail과 동일 — 형식·품질 일치). **thinking disabled 필수**
  (적응형 추론이 기본 ON이라 thinking 토큰이 과금되고 max_tokens를 잠식한다 — 지침 "Sonnet 5 비스트리밍" 항목)
- 형식: <description>/<diagram>/<related> XML 태그 (app.js와 동일 파싱)
- --limit N: 한 번에 처리할 최대 건수(기본 10 — 비용 상한, 나머지는 다음 날). 0=전부
- heartbeat: system_health key 'last_term_backfill_run'
- 필요 env: SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY
"""
import os
import re
import sys
import time
import argparse
from datetime import datetime, timezone

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
from supabase import Client
from sb_client import make_client
import api_usage; api_usage.install()   # Anthropic usage 기록(#152) — 호출부 무변경, fail-open

SUPABASE_URL      = os.environ['SUPABASE_URL']
SUPABASE_KEY      = os.environ['SUPABASE_SERVICE_KEY']
ANTHROPIC_API_KEY = os.environ['ANTHROPIC_API_KEY']

MODEL = 'claude-sonnet-5'  # app.js generateTermDetail과 동일 모델 유지
THINKING = {'type': 'disabled'}

sb: Client = make_client(SUPABASE_URL, SUPABASE_KEY)
ai = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def heartbeat(note: str) -> None:
    try:
        sb.table('system_health').upsert(
            {'key': 'last_term_backfill_run',
             'updated_at': datetime.now(timezone.utc).isoformat(),
             'note': note},
            on_conflict='key').execute()
    except Exception as e:
        print('[heartbeat 오류] %s' % e)


def _empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() == ''
    if isinstance(v, list):
        return len(v) == 0
    return False


def build_user_msg(t: dict) -> str:
    """app.js generateTermDetail의 userMsg와 동일한 프롬프트."""
    label = t['term'] + (f" ({t['term_en']})" if t.get('term_en') else '')
    return (
        f"기술 용어 [{label}] 에 대해 아래 형식으로 정확히 답변하세요.\n"
        f"분야: {t.get('category') or '기타'}. 현재 정의: {t.get('definition') or '없음'}.\n\n"
        "<description>\n"
        "3~5문단 상세 설명. **굵은글씨**로 핵심 개념 강조. 단락 구분은 빈 줄로.\n"
        "내용: 개념 배경/기술 원리/국내외 현황/관련 표준 순서로 서술.\n"
        "</description>\n\n"
        "<diagram>\n"
        "아래 조건을 모두 지킨 SVG를 생성하라:\n"
        '- viewBox="0 0 680 320" xmlns="http://www.w3.org/2000/svg"\n'
        '- 배경: rect fill="#f8fafc" 전체 채움\n'
        '- 한국어 레이블 사용, font-family="sans-serif"\n'
        "- 주요 구성요소를 박스/원/화살표로 시각화 (최소 4개 요소)\n"
        "- 색상: 주요 박스 #6366f1(보라), 보조 #10b981(초록), 강조 #f59e0b(노랑), 배경박스 #e0e7ff\n"
        "- 화살표는 marker-end 사용하여 방향 표시\n"
        "- 개념 흐름이나 계층 구조를 한눈에 파악할 수 있게\n"
        "</diagram>\n\n"
        "<related>관련용어1,관련용어2,관련용어3</related>"
    )


def generate(t: dict) -> dict | None:
    """반환: {description, diagram_html, related_terms} / None(실패)."""
    try:
        resp = ai.messages.create(
            model=MODEL,
            max_tokens=6000,
            thinking=THINKING,
            system='당신은 이동통신·전파 정책 전문가입니다. 반드시 지정된 XML 태그 형식으로만 답변하세요.',
            messages=[{'role': 'user', 'content': build_user_msg(t)}],
        )
        # content[0] 가정 금지 — text 블록만 이어 붙인다
        text = ''.join(b.text for b in resp.content if b.type == 'text')
    except Exception as e:
        print(f'  [API 오류] {t["term"]}: {str(e)[:100]}')
        return None

    desc    = re.search(r'<description>([\s\S]*?)</description>', text)
    diagram = re.search(r'<diagram>([\s\S]*?)</diagram>', text)
    related = re.search(r'<related>([\s\S]*?)</related>', text)
    return {
        'description':   desc.group(1).strip() if desc else '',
        'diagram_html':  diagram.group(1).strip() if diagram else '',
        'related_terms': [s.strip() for s in related.group(1).split(',') if s.strip()] if related else [],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=10, help='한 번에 처리할 최대 건수 (0=전부). 기본 10')
    ap.add_argument('--dry-run', action='store_true', help='대상만 세고 API·DB 무변경')
    ap.add_argument('--allow-api', action='store_true',
                    help='--limit 0(전부) 또는 30건 초과를 허용(#152). 없으면 거부')
    args = ap.parse_args()

    # #152 폭주 방지: 한 번에 30건 초과(용어당 Sonnet 6000토큰)는 명시 허용 없이는 돌리지 않는다.
    if not args.dry_run and not args.allow_api and (args.limit <= 0 or args.limit > 30):
        print('[중단] --limit 0 또는 30건 초과는 대량 Sonnet 호출입니다. 정말 API로 돌리려면 --allow-api 를 붙이세요. '
              '일회성 백필은 세션에서 처리하는 것이 원칙입니다(#152).')
        return

    rows = (sb.table('tech_terms')
            .select('id,term,term_en,category,definition,description,diagram_html,related_terms,created_at')
            .order('created_at', desc=True)
            .execute().data) or []
    targets = [r for r in rows if _empty(r.get('description'))
               or _empty(r.get('diagram_html'))
               or _empty(r.get('related_terms'))]
    total_targets = len(targets)
    if args.limit > 0:
        targets = targets[:args.limit]     # 최신 등록분부터 — 어제 뽑힌 용어가 먼저 채워진다
    print(f'[용어 상세 백필] 전체 {len(rows)}건 중 대상 {total_targets}건, 이번 실행 {len(targets)}건 (모델: {MODEL})')
    if args.dry_run:
        for t in targets:
            print(f'  [dry-run] {t["term"]}')
        return

    done = failed = 0
    for t in targets:
        parsed = generate(t)
        if parsed is None:
            failed += 1
            time.sleep(1)
            continue
        # 비어 있던 필드만 채움 — 기존 내용(운영자 검수분 포함) 보존
        update = {}
        if _empty(t.get('description')) and parsed['description']:
            update['description'] = parsed['description']
        if _empty(t.get('diagram_html')) and parsed['diagram_html']:
            update['diagram_html'] = parsed['diagram_html']
        if _empty(t.get('related_terms')) and parsed['related_terms']:
            update['related_terms'] = parsed['related_terms']
        if not update:
            failed += 1
            print(f'  [파싱 실패] {t["term"]} — 태그 없음')
            time.sleep(1)
            continue
        sb.table('tech_terms').update(update).eq('id', t['id']).execute()
        done += 1
        print(f'  ok {t["term"]} ({", ".join(update.keys())})')
        time.sleep(0.5)

    note = f'targets={total_targets} done={done} failed={failed} limit={args.limit}'
    print(f'[용어 상세 백필] 완료 - {note}')
    heartbeat(note)


if __name__ == '__main__':
    main()
