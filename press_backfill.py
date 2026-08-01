#!/usr/bin/env python3
"""
정부 보도자료 일회성 백필 (PC 실행 — 한국 IP, 배경역사 #53)
사용법:
  python press_backfill.py --delete-existing          # 기존 보도자료 전량 삭제 + 2024~ 재수집
  python press_backfill.py --agency 과기정통부        # 특정 기관만 (삭제 없이 이어서)
  python press_backfill.py --dry-run                  # 수집·추출만 시험, DB 무변경

동작:
  1. (--delete-existing) document_chunks의 doc_category='보도자료' 전량 삭제
     ※ 백필 기준일이 2024-01-01 이므로 2023년분은 복원되지 않음 — 운영자 승인됨(2026-08-02)
  2. press_ingest.run_backfill() — 6개 기관 목록을 페이지 순회하며 키워드 매칭분 등재
     (섹션 dedupe 로 재실행 안전 — 중단돼도 다시 실행하면 이어서 진행)
  3. backfill_embeddings.py 서브프로세스로 NULL 임베딩 채움
  ※ VACUUM/REINDEX 는 이 스크립트가 하지 않음 — 완료 후 SQL로 별도 수행(지침 참조)
"""

import os
import sys
import time
import subprocess
from datetime import datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Claude 세션 셸이 주입하는 사내 프록시는 정부 사이트 SSL을 깨뜨림(지침 do-not) —
# 스케줄러(SYSTEM) 환경은 원래 깨끗하므로 여기서 제거해도 부작용 없음.
for _k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
    os.environ.pop(_k, None)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from sb_client import make_client
import press_ingest

KST = timezone(timedelta(hours=9))


def delete_existing_press(sb) -> int:
    """doc_category='보도자료' 청크 전량 삭제. 삭제 건수 반환."""
    rows = sb.table('document_chunks').select('doc_name') \
        .eq('doc_category', '보도자료').execute().data or []
    total = len(rows)
    docs = sorted({r['doc_name'] for r in rows})
    print('[삭제 대상] %d청크 / 문서 %d개' % (total, len(docs)))
    for d in docs:
        print('  - %s' % d)
    if total == 0:
        return 0
    sb.table('document_chunks').delete().eq('doc_category', '보도자료').execute()
    remain = sb.table('document_chunks').select('id', count='exact') \
        .eq('doc_category', '보도자료').execute().count or 0
    if remain:
        raise RuntimeError('삭제 후에도 %d청크 잔존 — 중단' % remain)
    print('[삭제 완료] %d청크 (잔존 0 확인)' % total)
    return total


def run_embed_backfill() -> int:
    """backfill_embeddings.py 실행 (NULL 전량 반복 처리 — 멱등)."""
    r = subprocess.run(
        [sys.executable, 'backfill_embeddings.py'],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        encoding='utf-8', errors='replace',
        env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
    )
    return r.returncode


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--delete-existing', action='store_true',
                    help='시작 전 기존 보도자료 청크 전량 삭제 (2023년분 소실 — 승인됨)')
    ap.add_argument('--since', default='2024-01-01')
    ap.add_argument('--agency', default='', help='기관 slug 쉼표 구분 (기본 6개 전체)')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--skip-embed', action='store_true')
    args = ap.parse_args()

    started = datetime.now(KST)
    print('=' * 50)
    print('[보도자료 백필 시작] %s' % started.strftime('%Y-%m-%d %H:%M KST'))
    print('=' * 50)

    sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])

    if args.delete_existing and not args.dry_run:
        delete_existing_press(sb)

    since = datetime.strptime(args.since, '%Y-%m-%d').replace(tzinfo=KST)
    agencies = [a for a in args.agency.split(',') if a] or None
    grand = press_ingest.run_backfill(sb, since, agencies=agencies, dry=args.dry_run)

    print('=' * 50)
    total_new = sum(s['new'] for s in grand.values())
    for slug, s in grand.items():
        print('[요약][%s] 페이지 %d, 스캔 %d, 신규 %d, 중복 %d, 실패 %d'
              % (slug, s['pages'], s['scanned'], s['new'], s['dup'], s['fail']))
    print('[합계] 신규 %d건, 소요 %s' % (total_new, datetime.now(KST) - started))

    if not args.dry_run and not args.skip_embed and total_new > 0:
        print('[임베딩 백필 시작]')
        rc = run_embed_backfill()
        print('[임베딩 백필 종료] rc=%d' % rc)

    # heartbeat (일회성이지만 기록해 두면 운영 상태 탭에서 추적 가능)
    try:
        sb.table('system_health').upsert(
            {'key': 'last_press_ingest',
             'updated_at': datetime.now(timezone.utc).isoformat(),
             'note': 'backfill new=%d' % total_new},
            on_conflict='key').execute()
    except Exception as e:
        print('[heartbeat 오류] %s' % e)

    print('[백필 완료]')


if __name__ == '__main__':
    main()
