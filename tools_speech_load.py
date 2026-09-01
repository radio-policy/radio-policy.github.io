# -*- coding: utf-8 -*-
"""발언 전량 재수집 — 3단계: 요약 회수분을 assembly_speeches에 적재한다.

입력: raw_speeches.jsonl(원문·메타) + *.out.jsonl(요약, (confer_num, chunk_seq) 키)
동작: 회의(confer_num) 단위로 **기존 행 삭제 → 새 행 삽입**.
      chunk_seq가 옛 파서와 어긋나 행 단위 교체가 불가능하므로 회의 단위가 최소 단위다.
안전장치:
  - --dry-run 기본 검증(회의별 예상 삭제/삽입 건수만 출력)
  - 요약이 비었거나 검증(한글 비율·거절문)에 실패한 행은 **적재하지 않는다**(#99)
  - 백업은 tools_speech_dump.py가 미리 남긴다
"""
import argparse, glob, io, json, os, sys
sys.stdout.reconfigure(encoding='utf-8')
for _p in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
    os.environ.pop(_p, None)
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
import assembly_minutes as am
from sb_client import make_client


def load_jsonl(p):
    # 서브에이전트가 Write 도구로 남긴 파일에 BOM이 붙는다 — utf-8-sig로 읽는다
    return [json.loads(l) for l in io.open(p, encoding='utf-8-sig') if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw', default='speech_rebuild/raw_speeches.jsonl')
    ap.add_argument('--out-glob', default='speech_rebuild/*.out.jsonl')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--only-confer', default='')
    a = ap.parse_args()

    raw = load_jsonl(a.raw)
    summ = {}
    for p in glob.glob(a.out_glob):
        for r in load_jsonl(p):
            summ[(r['confer_num'], int(r['chunk_seq']))] = (r.get('summary') or '').strip()
    print('[입력] 원문 %d행 · 요약 %d행' % (len(raw), len(summ)))

    rows_by_conf = {}
    skipped = 0
    for r in raw:
        if a.only_confer and r['confer_num'] != a.only_confer:
            continue
        s = summ.get((r['confer_num'], int(r['chunk_seq'])), '')
        if not s or not am.is_valid_summary(s):     # 검증 실패분은 버린다(생성 시점이 유일 방어선)
            skipped += 1
            continue
        rows_by_conf.setdefault(r['confer_num'], []).append({
            'speaker': r['speaker'], 'speaker_raw': r['speaker_raw'],
            'position': r['position'], 'party': None,
            'meeting_date': r['meeting_date'], 'confer_num': r['confer_num'],
            'chunk_seq': r['chunk_seq'], 'agenda': r['agenda'],
            'topic': r['topic'], 'summary': s[:250], 'source_url': r['source_url'],
        })

    sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    tot_del = tot_ins = 0
    for cn, rows in sorted(rows_by_conf.items()):
        old = (sb.table('assembly_speeches').select('id', count='exact')
               .eq('confer_num', cn).execute())
        n_old = old.count or 0
        print('  %-16s 기존 %3d → 신규 %3d' % (cn, n_old, len(rows)), flush=True)
        tot_del += n_old
        tot_ins += len(rows)
        if a.dry_run:
            continue
        sb.table('assembly_speeches').delete().eq('confer_num', cn).execute()
        for i in range(0, len(rows), 100):
            sb.table('assembly_speeches').insert(rows[i:i + 100]).execute()
    print('[%s] 회의 %d건 · 삭제 %d · 삽입 %d · 요약없음/검증실패 제외 %d'
          % ('DRY' if a.dry_run else '적재', len(rows_by_conf), tot_del, tot_ins, skipped))


if __name__ == '__main__':
    main()
