# -*- coding: utf-8 -*-
"""과방위 발언 분야 집계 백필 (#248, 2026-09-27) — AI 0회.

22대(2024-05-30~) 과방위 상임위·국정감사 회의록을 다시 받아(뷰어 best-of-N + 상임위는 PDF 대조, #99·#120-보론)
원문을 **저장소 밖** 로컬 폴더(speech_fields.default_raw_dir())에 보관하고, speech_fields 낱말 규칙으로 센 발언자별
분야 건수를 speech_field_stats 에 회의 단위로 통째 교체 적재한다.

  py -3.12 speech_fields_backfill.py --dry-run --limit 3          # 회의 목록·수신·분류만 (DB 무변경)
  py -3.12 speech_fields_backfill.py --workers 3                  # 22대 전체 (뷰어 병렬 ≤3~4, #120)
  py -3.12 speech_fields_backfill.py --from-raw                   # 보관 원문으로 다시 세기 (네트워크 0, 규칙 바꾼 뒤)

- 이미 원문 파일이 있는 회의는 다시 받지 않는다(--refetch 로 강제). 적재는 메인 스레드에서 순차(#120 단일·순차 원칙).
- 16:30~17:30(lampmanH-pc gov 체인 — assembly_minutes 가 같은 표를 쓴다)에는 돌리지 않는다(#178).
- 구독자 큐·운영자 알림·assembly_speeches 는 건드리지 않는다.
"""
import argparse
import glob
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

import assembly_minutes as am
import speech_fields as sf
from sb_client import make_client

SINCE_22 = '2024-05-30'        # 22대 개원


def list_meetings(api_key: str, since: str, until: str) -> list:
    out, seen = [], set()
    for y in range(int(since[:4]), int(until[:4]) + 1):
        ms = am.fetch_meetings(api_key, y)
        for m in ms:
            m.setdefault('viewer_id', m['confer_num'])
            m.setdefault('is_audit', False)
        try:
            ms += am.fetch_audit_meetings(y)
        except Exception as e:
            print('[국감 목록 실패] %d: %s' % (y, str(e)[:80]))
        for m in ms:
            d = m.get('conf_date') or ''
            if not d or d < since or d > until or m['confer_num'] in seen:
                continue
            if not m.get('dgr') and not m.get('is_audit'):
                continue
            seen.add(m['confer_num'])
            out.append(m)
    out.sort(key=lambda m: (m['conf_date'], str(m['confer_num'])))
    return out


def fetch_one(m: dict, raw_dir: str, refetch: bool):
    """(m, blocks, src, from_cache). 네트워크 작업만 — DB는 메인 스레드."""
    p = sf.raw_path(m, raw_dir)
    if os.path.exists(p) and not refetch:
        _meta, blocks, src = sf.load_raw(p)
        return m, blocks, src, True
    blocks, src = am.fetch_verified_blocks(m)
    # 국감은 독립 PDF 사본이 없어 대조를 못 한다 — 직함 검사로 다른 위원회 본문만 거른다(#120-보론).
    if blocks and m.get('is_audit'):
        foreign = am.looks_foreign_committee(blocks)
        if foreign:
            print('  [국감 뷰어 타 위원회 직함→스킵] %s (%s)' % (m['title'][:40], foreign))
            return m, [], '뷰어 불일치(국감)', False
    if blocks:
        sf.save_raw(m, blocks, src, raw_dir)
    return m, blocks, src, False


def main():
    ap = argparse.ArgumentParser(description='과방위 발언 분야 집계 백필(#248)')
    ap.add_argument('--since', default=SINCE_22)
    ap.add_argument('--until', default=datetime.now().strftime('%Y-%m-%d'))
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--only', nargs='*', help='confer_num 목록만')
    ap.add_argument('--refetch', action='store_true', help='원문 파일이 있어도 다시 받기')
    ap.add_argument('--from-raw', action='store_true', help='보관 원문으로만 다시 세기(네트워크 0)')
    ap.add_argument('--raw-dir', default=None)
    ap.add_argument('--dry-run', action='store_true', help='DB 무변경(분류 결과만 출력)')
    args = ap.parse_args()
    for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
        os.environ.pop(k, None)                      # 세션 프록시가 국회 사이트 SSL을 깬다
    raw_dir = args.raw_dir or sf.default_raw_dir()
    now = datetime.now()
    if not args.dry_run and (16 * 60 + 30) <= now.hour * 60 + now.minute <= (17 * 60 + 30):
        print('[거부] 16:30~17:30은 gov 체인(assembly_minutes)이 같은 표를 쓴다(#178) — 그 뒤에 돌리세요.')
        return
    sb = None if args.dry_run else make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    print('[분야 백필] 규칙 %s · 원문 폴더 %s' % (sf.RULES_VERSION, raw_dir))

    if args.from_raw:
        files = sorted(glob.glob(os.path.join(raw_dir, '*', '*.json')))
        done = rows_n = 0
        for p in files:
            m, blocks, src = sf.load_raw(p)
            if (m.get('conf_date') or '') < args.since or (m.get('conf_date') or '') > args.until:
                continue
            if args.only and str(m['confer_num']) not in args.only:
                continue
            rows = sf.build_rows(m, blocks, src)
            if sb:
                sf.write_rows(sb, m['confer_num'], rows)
            done += 1
            rows_n += len(rows)
        print('[분야 백필 완료 — 원문 재계산] 회의 %d · 행 %d%s' % (done, rows_n, ' (dry-run)' if not sb else ''))
        return

    api_key = os.environ.get('ASSEMBLY_API_KEY', '')
    if not api_key:
        print('[오류] ASSEMBLY_API_KEY 없음')
        return
    ms = list_meetings(api_key, args.since, args.until)
    if args.only:
        ms = [m for m in ms if str(m['confer_num']) in args.only]
    if args.limit:
        ms = ms[:args.limit]
    print('[분야 백필] 대상 회의 %d건 (%s ~ %s, 국감 %d)' % (
        len(ms), args.since, args.until, sum(1 for m in ms if m.get('is_audit'))))
    t0 = time.time()
    ok = fail = cached = rows_n = 0
    fails = []
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 4))) as ex:
        futs = [ex.submit(fetch_one, m, raw_dir, args.refetch) for m in ms]
        for i, fu in enumerate(as_completed(futs), 1):
            try:
                m, blocks, src, from_cache = fu.result()
            except Exception as e:
                fail += 1
                fails.append(('?', str(e)[:80]))
                print('  [예외] %s' % str(e)[:100])
                continue
            if not blocks:
                fail += 1
                fails.append((m['confer_num'], src))
                continue
            cached += from_cache
            rows = sf.build_rows(m, blocks, src)
            if sb:
                try:
                    sf.write_rows(sb, m['confer_num'], rows)
                except Exception as e:
                    fail += 1
                    fails.append((m['confer_num'], 'DB ' + str(e)[:60]))
                    print('  [적재 실패] %s %s' % (m['confer_num'], str(e)[:100]))
                    continue
            ok += 1
            rows_n += len(rows)
            print('  [%d/%d] %s %s %s 블록 %d · 발언자 %d%s' % (
                i, len(ms), m['conf_date'], m['confer_num'], src, len(blocks), len(rows),
                ' (보관본)' if from_cache else ''))
    print('[분야 백필 완료] 성공 %d(보관본 %d) · 실패 %d · 행 %d · %.0f초%s' % (
        ok, cached, fail, rows_n, time.time() - t0, ' (dry-run)' if not sb else ''))
    for c, why in fails:
        print('  실패: %s %s' % (c, why))


if __name__ == '__main__':
    main()
