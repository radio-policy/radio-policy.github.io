# -*- coding: utf-8 -*-
"""과방위 발언(assembly_speeches) 안건 칸 블록별 보정 (2026-10-15, #310) — AI 호출 0회.

배경: build_speech_rows 가 회의의 첫 안건(열린국회정보 목록 순서) 하나를 그 회의 모든 발언 행의 agenda 에 적었다.
2025-12-09 회의(55942)는 제1~8항 인사청문·청문회 절차 안건 뒤 제9항 AI 입법 공청회가 열렸는데 발언 98행이 전부
「…인사청문회 자료제출 요구의 건」으로 적혀 자문 답변이 공청회 질의를 인사청문회 발언으로 소개했다.
수집 경로는 assembly_minutes.agenda_labels(위원장 상정·진행 발언으로 블록마다 안건)로 고쳤고, 이 도구는 이미 적재된 행을 맞춘다.

원칙:
  - agenda 칸만 바꾼다. 행 추가·삭제·다른 칸 변경 없음. 요지(summary)는 그대로 둔다(요지 생성 때 넣은 「안건:」 줄은 참고용이었다).
  - 원문 블록과 기존 행의 **정렬 검사**(모든 행의 chunk_seq 위치 발언자 == speaker)를 통과한 원문만 쓴다 — 후보 원문을
    차례로 보고 처음 맞는 것을 고른다. 하나도 맞지 않으면 보고만 한다(--fetch면 뷰어를 다시 받아 한 번 더 본다).
  - 번호 안건이 둘 미만인 회의(국정감사·단일 안건)는 건드리지 않는다.
  - --apply 전 행별 전후 값을 저장소 밖(../minutes_work/agenda_fix/)에 남긴다 — 되돌리기는 --revert <그 파일>.
  - 16:30~17:30(KST)에는 --apply·--revert 를 거부한다(회사 PC 16:30 정부 체인이 회의록을 적재하는 시간, #265).

원문 출처(앞에서부터, 정렬 맞는 첫 것): SPEECH_RAW_DIR(발언 분야 원문, 22대) → ../minutes_work/{연도}/*.blocks.json
(20·21대 오프라인 적재분) → ../minutes_work/sk_cache → ../minutes_work/agenda_fix/cache → --fetch면 국회 뷰어(캐시에 저장).
뷰어 재수신은 안건 목록을 로컬 원문 메타에서 가져온다(없으면 그 회의는 건너뜀).

사용:
  py -3.12 tools_minutes_agenda_fix.py                         # 점검만(읽기 전용) — 바뀔 행 수·회의별 분포
  py -3.12 tools_minutes_agenda_fix.py --confer 55942 --show    # 한 회의의 사건(상정·넘어가기·되돌리기)과 행별 전후
  py -3.12 tools_minutes_agenda_fix.py --fetch                  # 정렬 불일치 회의만 뷰어 재수신해 다시 대조(AI 0, 국회 사이트만)
  py -3.12 tools_minutes_agenda_fix.py --apply [--fetch]        # 보정 적용(전후 기록 파일을 먼저 쓴다)
  py -3.12 tools_minutes_agenda_fix.py --revert ../minutes_work/agenda_fix/applied_YYMMDD_HHMM.json
"""
import argparse, json, os, sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
sys.stdout.reconfigure(encoding='utf-8')
for _p in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
    os.environ.pop(_p, None)          # 세션 셸이 주입하는 사내 프록시는 SSL을 깬다(지침)
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
import assembly_minutes as am
import speech_fields
from sb_client import make_client

REPO = os.path.dirname(os.path.abspath(__file__))
MINUTES_WORK = os.path.join(os.path.dirname(REPO), 'minutes_work')
OUT_DIR = os.path.join(MINUTES_WORK, 'agenda_fix')
CACHE_DIR = os.path.join(OUT_DIR, 'cache')
KST = timezone(timedelta(hours=9))


def _read(path):
    with open(path, encoding='utf-8') as fp:
        d = json.load(fp)
    return (d.get('meeting') or {}), d['blocks']


def misaligned(rows, blocks):
    return [r['chunk_seq'] for r in rows
            if not isinstance(r['chunk_seq'], int) or not 0 <= r['chunk_seq'] < len(blocks)
            or am.normalize_speaker(blocks[r['chunk_seq']]['name']) != r['speaker']]


def candidates(cn, year):
    raw = speech_fields.default_raw_dir()
    return [os.path.join(raw, year, cn + '.json'),
            os.path.join(MINUTES_WORK, year, cn + '.blocks.json'),
            os.path.join(MINUTES_WORK, 'sk_cache', cn + '.json'),
            os.path.join(CACHE_DIR, cn + '.json')]


def find_aligned(cn, year, rows, fetch):
    """(meta, blocks, 출처) — 정렬 맞는 원문이 없으면 (meta 또는 None, None, 이유)."""
    meta_any = None
    for p in candidates(cn, year):
        if not os.path.exists(p):
            continue
        meta, blocks = _read(p)
        if meta.get('agenda') and meta_any is None:
            meta_any = meta
        if not misaligned(rows, blocks):
            if not meta.get('agenda') and meta_any:
                meta = dict(meta, agenda=meta_any['agenda'])
            return meta, blocks, p
    if not fetch:
        return meta_any, None, '정렬 맞는 로컬 원문 없음(--fetch로 재수신)'
    if not meta_any:
        return None, None, '안건 목록 있는 로컬 원문 없음'
    meta_any = dict(meta_any, pdf_url=meta_any.get('pdf_url') or '', title=meta_any.get('title') or cn)
    tried = []
    for how in ('뷰어', '검증', 'PDF'):
        try:
            if how == '뷰어':
                blocks = am.fetch_speech_blocks(meta_any.get('viewer_id') or cn)
            elif how == '검증':
                blocks, _src = am.fetch_verified_blocks(meta_any)
            else:                                   # 적재 당시 뷰어가 비어 PDF 폴백으로 만든 행
                blocks = am.pdf_fallback_blocks(meta_any['pdf_url']) if meta_any['pdf_url'] else []
        except Exception as e:
            tried.append('%s 실패(%s)' % (how, str(e)[:40]))
            continue
        if blocks and not misaligned(rows, blocks):
            os.makedirs(CACHE_DIR, exist_ok=True)
            p = os.path.join(CACHE_DIR, cn + '.json')
            with open(p, 'w', encoding='utf-8') as fp:
                json.dump({'meeting': meta_any, 'src': how, 'blocks': blocks}, fp, ensure_ascii=False)
            return meta_any, blocks, p + '(재수신)'
        tried.append('%s %d블록 불일치' % (how, len(blocks or [])))
    return meta_any, None, '재수신도 불일치: ' + ', '.join(tried)


def plan(sb, args):
    rows = am._fetch_all(sb.table('assembly_speeches').select(
        'id,confer_num,chunk_seq,speaker,meeting_date,agenda').order('id'))
    by_cn = defaultdict(list)
    for r in rows:
        by_cn[r['confer_num']].append(r)
    only = set(x.strip() for x in (args.confer or '').split(',') if x.strip())
    changes, stat, notes = [], Counter(), []
    for cn, rs in sorted(by_cn.items(), key=lambda kv: min(r['meeting_date'] or '' for r in kv[1])):
        if only and cn not in only:
            continue
        year = (min(r['meeting_date'] or '' for r in rs) or '0000')[:4]
        stat['meetings'] += 1
        meta, blocks, where = find_aligned(cn, year, rs, args.fetch)
        items = am.agenda_items((meta or {}).get('agenda'))[0]
        if len(items) < 2:
            stat['skip_single'] += 1          # 국정감사·단일 안건 — 그대로
            continue
        if blocks is None:
            stat['skip_misaligned'] += 1
            stat['skip_misaligned_rows'] += len(rs)
            notes.append('  [정렬 불일치·건너뜀] %-12s %s 행 %d — %s' % (cn, year, len(rs), where))
            continue
        trace = []
        labels = am.agenda_labels(meta, blocks, trace=trace)
        how = 'blocks'
        if labels is None:
            how = 'meeting'
            stat['no_open'] += 1
        stat['meetings_multi'] += 1
        per = Counter()
        for r in rs:
            new = labels[r['chunk_seq']] if labels else am.meeting_agenda_label(meta)
            per[new] += 1
            if new != r['agenda']:
                changes.append({'id': r['id'], 'confer_num': cn, 'chunk_seq': r['chunk_seq'],
                                'before': r['agenda'], 'after': new})
        n_ch = sum(1 for c in changes if c['confer_num'] == cn)
        if n_ch:
            stat['meetings_changed'] += 1
        if args.show or (n_ch and args.verbose):
            print('  %-12s %s 행 %3d 바뀜 %3d (%s, %s)' % (cn, year, len(rs), n_ch, how, os.path.basename(where)))
            for lab, k in per.most_common():
                print('      %3d × %s' % (k, lab[:90]))
        if args.show:
            for e in trace:
                print('      사건 [%d] %-9s %s %s' % (e[0], e[1], ','.join(map(str, e[2])), e[3]))
            for c in changes:
                if c['confer_num'] == cn:
                    print('      #%d %s → %s' % (c['chunk_seq'], (c['before'] or '')[:40], c['after'][:60]))
    stat['rows_changed'] = len(changes)
    return changes, stat, notes


def _guard_time():
    now = datetime.now(KST)
    if (now.hour, now.minute) >= (16, 30) and (now.hour, now.minute) < (17, 30):
        sys.exit('16:30~17:30 KST에는 적용하지 않는다(회사 PC 정부 체인 시간, #265) — 지금 %s' % now.strftime('%H:%M'))


def apply(sb, changes):
    _guard_time()
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, 'applied_%s.json' % datetime.now(KST).strftime('%y%m%d_%H%M'))
    with open(path, 'w', encoding='utf-8') as fp:
        json.dump(changes, fp, ensure_ascii=False, indent=0)
    print('[전후 기록] %s (%d행)' % (path, len(changes)))
    groups = defaultdict(list)
    for c in changes:
        groups[(c['confer_num'], c['after'])].append(c['id'])
    done = 0
    for (cn, lab), ids in sorted(groups.items()):
        for k in range(0, len(ids), 100):
            part = ids[k:k + 100]
            sb.table('assembly_speeches').update({'agenda': lab}).in_('id', part).execute()
            done += len(part)
    print('[적용] %d행 · 묶음 %d' % (done, len(groups)))
    return path


def revert(sb, path):
    _guard_time()
    with open(path, encoding='utf-8') as fp:
        changes = json.load(fp)
    groups = defaultdict(list)
    for c in changes:
        groups[c['before']].append(c['id'])
    n = 0
    for lab, ids in groups.items():
        for k in range(0, len(ids), 100):
            sb.table('assembly_speeches').update({'agenda': lab}).in_('id', ids[k:k + 100]).execute()
            n += len(ids[k:k + 100])
    print('[되돌림] %d행' % n)


def verify(sb, changes):
    """적용 뒤 실DB 재조회 — after 값과 다른 행 수."""
    want = {c['id']: c['after'] for c in changes}
    bad = 0
    ids = list(want)
    for k in range(0, len(ids), 200):
        for r in sb.table('assembly_speeches').select('id,agenda').in_('id', ids[k:k + 200]).execute().data:
            if r['agenda'] != want[r['id']]:
                bad += 1
    print('[재조회] %d행 중 불일치 %d' % (len(ids), bad))
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--confer', default='', help='confer_num 쉼표 목록(없으면 전체)')
    ap.add_argument('--fetch', action='store_true', help='정렬 불일치 회의는 국회 뷰어를 다시 받아 대조(AI 0)')
    ap.add_argument('--show', action='store_true', help='회의별 사건·행별 전후 출력')
    ap.add_argument('--verbose', action='store_true', help='바뀌는 회의마다 꼬리표 분포 출력')
    ap.add_argument('--apply', action='store_true', help='DB에 적용(전후 기록 먼저)')
    ap.add_argument('--revert', default='', help='applied_*.json 으로 되돌리기')
    args = ap.parse_args()
    sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    if args.revert:
        revert(sb, args.revert)
        return
    changes, stat, notes = plan(sb, args)
    for n in notes:
        print(n)
    print('[점검] 회의 %(meetings)d — 다안건 %(meetings_multi)d(상정 못 찾음 %(no_open)d) · 단일 안건 건너뜀 %(skip_single)d · '
          '정렬 불일치 %(skip_misaligned)d(%(skip_misaligned_rows)d행)' % defaultdict(int, stat))
    print('[바뀔 행] %d행 · 회의 %d' % (stat['rows_changed'], stat['meetings_changed']))
    if args.apply and changes:
        apply(sb, changes)
        verify(sb, changes)


if __name__ == '__main__':
    main()
