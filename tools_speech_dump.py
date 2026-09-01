# -*- coding: utf-8 -*-
"""발언 전량 재수집 — 1단계: 백업 + 원문 덤프 (AI 호출 0회, 비용 0)

배경(2026-09-01 운영자 지시): assembly_speeches 4,749건 중 1,420건이 저품질 요지
(API 키 없이 돌던 시기의 규칙 폴백 — 원문 앞 문장 절단). 원문(raw)을 저장하지 않는
테이블이라 사후 재요약이 불가능하고, chunk_seq도 현재 파서와 어긋나(실측 매칭률 0%)
행 단위 수리가 안 된다 → **국회 API로 전량 재수집**이 유일한 해법.

이 스크립트는 돈이 드는 일을 하지 않는다:
  ① 기존 테이블 JSONL 백업
  ② 회의 목록·발언 블록 수집(국회 API, 무료)
  ③ 규칙 기반 선별(select_relevant(judge=None)) 후 원문을 JSONL로 덤프
요약은 세션(서브에이전트)이 맡고, 적재는 tools_speech_load.py가 한다.
"""
import argparse, json, os, sys
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
for _p in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
    os.environ.pop(_p, None)          # 세션 셸이 주입하는 사내 프록시는 SSL을 깬다(지침)

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

import assembly_minutes as am
from press_ingest import load_press_keywords
from sb_client import make_client

OUT_DIR = os.environ.get('SPEECH_DUMP_DIR') or 'speech_rebuild'
RAW_LIMIT = 1800                      # 요약 입력 상한(원문 앞부분) — 프롬프트 비대화 방지


def backup(sb, path):
    rows, off = [], 0
    while True:                       # PostgREST 1,000행 절단 — order+range 페이징(지침)
        page = (sb.table('assembly_speeches').select('*')
                .order('id').range(off, off + 999).execute().data or [])
        rows += page
        if len(page) < 1000:
            break
        off += 1000
    with open(path, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    return len(rows)


def dump(api_key, years, out_path, kw, limit=0):
    seen_meetings, n_rows = 0, 0
    with open(out_path, 'w', encoding='utf-8') as f:
        for year in years:
            meetings = am.fetch_meetings(api_key, year)
            if year >= am.AUDIT_MIN_YEAR:
                meetings = meetings + am.fetch_audit_meetings(year)
            print('[%d년] 회의 %d건' % (year, len(meetings)), flush=True)
            for m in meetings:
                if limit and seen_meetings >= limit:
                    return seen_meetings, n_rows
                if not m['conf_date'] or (not m['dgr'] and not m.get('is_audit')):
                    continue
                is_audit = bool(m.get('is_audit'))
                viewer_id = m.get('viewer_id') or m['confer_num']
                try:
                    blocks = am.fetch_speech_blocks(viewer_id)
                except Exception as e:
                    print('  [블록 실패] %s %s' % (viewer_id, str(e)[:60]), flush=True)
                    continue
                if not blocks:
                    continue
                # judge=None → Haiku 판정 없이 규칙(키워드·관련도)만으로 선별: AI 호출 0
                _include, confirmed = am.select_relevant(
                    blocks, kw, None, m['title'],
                    max_judge=am.AUDIT_MAX_JUDGE_BLOCKS if is_audit else am.MAX_JUDGE_BLOCKS)
                max_exc = am.AUDIT_MAX_EXCERPTS if is_audit else am.MAX_EXCERPTS
                agenda = am._primary_agenda(m)
                confer_num = (am.AUDIT_CONFER_PREFIX + str(viewer_id)) if is_audit else str(m['confer_num'])
                src = am.VIEWER_URL % viewer_id
                seen_meetings += 1
                cnt = 0
                for i in am.cap_indices(confirmed, blocks, max_exc, kw):
                    b = blocks[i]
                    if am.is_noise_speech(b['text']):      # 사회·호명 발언 제외(2026-09-01)
                        continue
                    topic = ', '.join(am.matched_keywords(b['text'], kw)[:5])
                    if not topic and am.is_always_keep(b['text']):
                        topic = 'SK텔레콤 언급'
                    f.write(json.dumps({
                        'confer_num': confer_num, 'viewer_id': str(viewer_id),
                        'is_audit': is_audit, 'meeting_title': m['title'],
                        'meeting_date': (m['conf_date'] or '').strip() or None,
                        'agenda': agenda or None, 'chunk_seq': i,
                        'speaker': am.normalize_speaker(b['name']), 'speaker_raw': b['name'],
                        'position': b['pos'] or None, 'topic': topic or None,
                        'raw_text': (b['text'] or '')[:RAW_LIMIT], 'source_url': src,
                    }, ensure_ascii=False) + '\n')
                    cnt += 1
                    n_rows += 1
                print('  %-16s %-42s blocks=%-5d 수록=%d' %
                      (confer_num, (m['title'] or '')[:40], len(blocks), cnt), flush=True)
    return seen_meetings, n_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from-year', type=int, default=2016)
    ap.add_argument('--to-year', type=int, default=datetime.now().year)
    ap.add_argument('--limit', type=int, default=0, help='회의 수 상한(파일럿용)')
    ap.add_argument('--no-backup', action='store_true')
    ap.add_argument('--out', default=None)
    a = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    if not a.no_backup:
        bpath = os.path.join(OUT_DIR, 'backup_assembly_speeches.jsonl')
        print('[백업] %s → %d행' % (bpath, backup(sb, bpath)), flush=True)

    api_key = os.environ.get('ASSEMBLY_API_KEY', '')
    if not api_key:
        print('[오류] ASSEMBLY_API_KEY 없음'); return
    out = a.out or os.path.join(OUT_DIR, 'raw_speeches.jsonl')
    kw = load_press_keywords(sb)
    print('[키워드] %d개' % len(kw), flush=True)
    ms, rows = dump(api_key, range(a.from_year, a.to_year + 1), out, kw, a.limit)
    print('[완료] 회의 %d건 · 발언 %d건 → %s' % (ms, rows, out))


if __name__ == '__main__':
    main()
