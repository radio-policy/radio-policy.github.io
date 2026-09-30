# -*- coding: utf-8 -*-
"""과방위 발언(assembly_speeches) — 상한에 잘린 발언 점검·소급 (2026-09-30, #262).

배경: 회의당 판정 후보 상한(40·국감 80)과 수록 상한(30·국감 50)이 발언을 잘랐다.
  ① 자사(SK텔레콤) 언급 — 우선권만 있어 자사 블록이 상한보다 많은 회의(2025-04-30 유심 해킹 현안질의 176블록)는 30개만 남았다.
  ② SK 밖 관련 발언 — 큰 회의일수록 잘려 인물별 발언 수·주제 비율·'SK 언급 / 전체' 비율이 틀어졌다.
수집 경로는 assembly_minutes(cap_speech_indices, MAX_SPEECH_ROWS)로 고쳤고, 이 도구는 이미 적재된 회의를 맞춘다.
speeches_exist가 참이면 run()은 발언 적재를 건너뛰므로 별도 경로가 필요하다.

원칙:
  - 기존 행은 지우지도 바꾸지도 않는다(칩 보정의 topic 덧붙임만 예외). 빠진 (confer_num, chunk_seq)만 upsert.
  - 원문 블록과 기존 행의 **정렬 검사**(모든 행의 chunk_seq 위치 발언자 == speaker)를 통과한 회의만 다룬다 —
    어긋나면 chunk_seq가 가리키는 블록이 다르다(뷰어가 다시 받은 본문이 달라진 회차). 그 회의는 보고만 한다.
  - 판정·요지는 세션이 쓴다(운영자 규칙 #120 — 일회성 AI 작업에 API를 쓰지 않는다). 이 파일은 AI를 부르지 않는다.
  - --related 후보는 키워드 1차 선별일 뿐이라 **세션이 관련성을 판정**한다(keep false = 적재 안 함). 이미 판정해
    탈락시킨 블록(minutes_work의 *.judged.json rejected, --summaries의 keep false)은 다시 묻지 않는다.

원문 출처(앞에서부터): --blocks-dir(여러 번) → SPEECH_RAW_DIR(발언 분야 원문, 22대) → ../minutes_work/{연도}/*.blocks.json
(20·21대 오프라인 적재분) → ../minutes_work/sk_cache → --fetch면 국회 뷰어(캐시에 저장). 원문은 모두 저장소 밖에 둔다.

사용:
  py -3.12 tools_minutes_speech_backfill.py                     # 점검만(읽기 전용) — 자사 누락·칩 누락·정렬 불일치
  py -3.12 tools_minutes_speech_backfill.py --related [--summaries GLOB]   # SK 밖 관련 후보 중 미판정 블록 수
  py -3.12 tools_minutes_speech_backfill.py [--related] --export DIR/x.jsonl   # 대상 블록 원문·메타(세션 입력)
  py -3.12 tools_minutes_speech_backfill.py --load DIR/x.jsonl --summaries "DIR/*.out.jsonl" [--dry-run]
  py -3.12 tools_minutes_speech_backfill.py --fix-chips [--dry-run]   # 원문에 자사 언급이 있는데 칩이 없는 행에 칩 덧붙임
세션 출력(jsonl): {"confer_num": "54606", "chunk_seq": 123, "keep": true, "summary": "…"} — keep 생략 = true.
적재 뒤 인물 발언 수는 17시 체인의 tools_people_refresh.py가 다시 센다(수동: py -3.12 tools_people_refresh.py).
"""
import argparse, glob, io, json, os, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')
for _p in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
    os.environ.pop(_p, None)          # 세션 셸이 주입하는 사내 프록시는 SSL을 깬다(지침)
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
import assembly_minutes as am
import speech_fields
from press_ingest import load_press_keywords
from sb_client import make_client

REPO = os.path.dirname(os.path.abspath(__file__))
MINUTES_WORK = os.path.join(os.path.dirname(REPO), 'minutes_work')
DEFAULT_CACHE = os.path.join(MINUTES_WORK, 'sk_cache')


def load_jsonl(p):
    # 서브에이전트가 Write 도구로 남긴 파일에 BOM이 붙는다 — utf-8-sig로 읽는다
    return [json.loads(l) for l in io.open(p, encoding='utf-8-sig') if l.strip()]


def _read_blocks(path):
    with open(path, encoding='utf-8') as fp:
        d = json.load(fp)
    return (d.get('meeting') or {}), d['blocks'], d.get('src') or ''


def find_blocks(cn, year, extra_dirs, cache_dir, fetch):
    """(meeting_meta, blocks, 출처) — 없으면 (None, None, 이유)."""
    cands = []
    for d in extra_dirs:
        cands += [os.path.join(d, cn + '.json'), os.path.join(d, cn + '.blocks.json')]
    raw = speech_fields.default_raw_dir()
    cands += [os.path.join(raw, year, cn + '.json'),
              os.path.join(MINUTES_WORK, year, cn + '.blocks.json'),
              os.path.join(cache_dir, cn + '.json')]
    for p in cands:
        if os.path.exists(p):
            meta, blocks, _src = _read_blocks(p)
            return meta, blocks, p
    if not fetch:
        return None, None, '로컬 원문 없음(--fetch로 수신)'
    is_audit = cn.startswith(am.AUDIT_CONFER_PREFIX)
    vid = cn[len(am.AUDIT_CONFER_PREFIX):] if is_audit else cn
    m = {'confer_num': cn, 'viewer_id': vid, 'is_audit': is_audit, 'title': cn, 'conf_date': '',
         'pdf_url': (am.AUDIT_PDF_URL % vid) if is_audit else None}
    blocks, src = am.fetch_verified_blocks(m)
    if not blocks:
        return None, None, '수신 실패(%s)' % src
    os.makedirs(cache_dir, exist_ok=True)
    p = os.path.join(cache_dir, cn + '.json')
    with open(p, 'w', encoding='utf-8') as fp:
        json.dump({'meeting': m, 'src': src, 'blocks': blocks}, fp, ensure_ascii=False)
    return m, blocks, p


def prior_rejected(cn, year):
    """이미 세션이 판정해 탈락시킨 블록 번호 — 오프라인 파이프라인(#120) judged.json + 이 도구의 keep false."""
    out = set()
    p = os.path.join(MINUTES_WORK, year, cn + '.judged.json')
    if os.path.exists(p):
        with io.open(p, encoding='utf-8-sig') as fp:
            out |= {int(i) for i in (json.load(fp).get('rejected') or [])}
    return out | _REJECTED.get(cn, set())


_REJECTED = defaultdict(set)


def _load_rejected(summaries_glob):
    for p in glob.glob(summaries_glob or ''):
        for r in load_jsonl(p):
            if r.get('keep') is False:
                _REJECTED[str(r['confer_num'])].add(int(r['chunk_seq']))


def misaligned(rows, blocks):
    bad = []
    for r in rows:
        cs = r['chunk_seq']
        if not isinstance(cs, int) or cs < 0 or cs >= len(blocks) \
                or am.normalize_speaker(blocks[cs]['name']) != r['speaker']:
            bad.append(cs)
    return bad


def _new_targets(blocks, rows, want):
    """want(block) 가 참인 블록 중 적재 안 된 것 — 절차·잡음(build_speech_rows가 버리는 사회·호명)·같은 글 중복
    (이미 적재된 행과 같은 글 포함) 제외."""
    have = {r['chunk_seq'] for r in rows}
    seen = {blocks[cs]['text'].strip() for cs in have if 0 <= cs < len(blocks)}
    out = []
    for i, b in enumerate(blocks):
        if not want(b) or am.is_procedural(b) or am.is_noise_speech(b['text']):
            continue
        t = b['text'].strip()
        if i in have or t in seen:
            continue
        seen.add(t)
        out.append(i)
    return out


def sk_targets(blocks, rows):
    """적재돼 있어야 할 자사 블록 중 빠진 인덱스(기준 = run()의 always − 잡음 − 같은 글)."""
    return _new_targets(blocks, rows, lambda b: am.is_always_keep(b['text']))


def related_targets(blocks, rows, keywords, rejected):
    """SK 밖 키워드 후보(candidate_blocks의 matched, 상한 없이) 중 적재도 판정 탈락도 아닌 블록."""
    return [i for i in _new_targets(
        blocks, rows, lambda b: not am.is_always_keep(b['text'])
        and any(am.kw_hit(b['text'], k) for k in keywords)) if i not in rejected]


def chip_targets(blocks, rows):
    return [r for r in rows if am.is_always_keep(blocks[r['chunk_seq']]['text'])
            and am.SKT_CHIP not in (r.get('topic') or '')]


def scan(sb, args, keywords=None):
    q = sb.table('assembly_speeches').select(
        'id,confer_num,speaker,chunk_seq,topic,meeting_date,agenda,source_url').order('id')
    rows = am._fetch_all(q)
    by_cn = defaultdict(list)
    for r in rows:
        by_cn[r['confer_num']].append(r)
    only = set(x.strip() for x in args.confer.split(',') if x.strip())
    if args.related:
        _load_rejected(args.summaries)
    res = []
    for cn, rs in sorted(by_cn.items(), key=lambda kv: min(r['meeting_date'] or '' for r in kv[1])):
        if only and cn not in only:
            continue
        year = (min(r['meeting_date'] or '' for r in rs) or '0000')[:4]
        meta, blocks, where = find_blocks(cn, year, args.blocks_dir, args.cache_dir, args.fetch)
        item = {'cn': cn, 'date': min(r['meeting_date'] or '' for r in rs), 'rows': rs,
                'meta': meta, 'blocks': blocks, 'where': where}
        if blocks is not None:
            item['bad'] = misaligned(rs, blocks)
            if not item['bad']:
                item['missing'] = sk_targets(blocks, rs)
                item['chips'] = chip_targets(blocks, rs)
                if args.related:
                    item['related'] = related_targets(blocks, rs, keywords,
                                                      prior_rejected(cn, year))
        res.append(item)
    return res


def report(res, related):
    nosrc = [x for x in res if x['blocks'] is None]
    bad = [x for x in res if x.get('bad')]
    ok = [x for x in res if x['blocks'] is not None and not x.get('bad')]
    print('[점검] 회의 %d — 정렬 확인 %d · 정렬 불일치 %d · 원문 없음 %d' % (len(res), len(ok), len(bad), len(nosrc)))
    for x in ok:
        if x['missing'] or x['chips'] or (related and x['related']):
            print('  %-12s %s 행 %3d · 자사 누락 %3d · 칩 누락 %2d%s'
                  % (x['cn'], x['date'], len(x['rows']), len(x['missing']), len(x['chips']),
                     (' · 관련 미판정 %3d' % len(x['related'])) if related else ''))
    for x in bad:
        n_sk = sum(1 for b in x['blocks'] if am.is_always_keep(b['text']))
        print('  [정렬 불일치·건너뜀] %-12s %s 행 %d 중 %d 불일치 (원문 자사 블록 %d)'
              % (x['cn'], x['date'], len(x['rows']), len(x['bad']), n_sk))
    for x in nosrc:
        print('  [원문 없음] %-12s %s — %s' % (x['cn'], x['date'], x['where']))
    print('[합계] 자사 누락 %d블록(회의 %d) · 칩 누락 %d행(회의 %d)%s'
          % (sum(len(x['missing']) for x in ok), sum(1 for x in ok if x['missing']),
             sum(len(x['chips']) for x in ok), sum(1 for x in ok if x['chips']),
             (' · 관련 미판정 %d블록(회의 %d)' % (sum(len(x['related']) for x in ok),
                                          sum(1 for x in ok if x['related']))) if related else ''))


def export(res, keywords, path, related):
    n = 0
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        for x in res:
            if x.get('bad'):
                continue
            targets = x.get('related') if related else x.get('missing')
            if not targets:
                continue
            base = x['rows'][0]                  # 회의 공통 메타는 기존 행을 따른다(화면 조인 키 source_url 일치)
            title = (x['meta'] or {}).get('title') or ''
            if title == x['cn']:
                title = ''
            for i in targets:
                b = x['blocks'][i]
                kws = am.matched_keywords(b['text'], keywords)[:5]
                if am.is_always_keep(b['text']) and am.SKT_CHIP not in kws:
                    kws.append(am.SKT_CHIP)
                f.write(json.dumps({
                    'confer_num': x['cn'], 'chunk_seq': i, 'meeting_title': title,
                    'meeting_date': base['meeting_date'], 'agenda': base['agenda'],
                    'speaker': am.normalize_speaker(b['name']), 'speaker_raw': b['name'],
                    'position': b['pos'] or None, 'topic': ', '.join(kws), 'judge': bool(related),
                    'source_url': base['source_url'], 'raw_text': (b['text'] or '')[:2000],
                }, ensure_ascii=False) + '\n')
                n += 1
    print('[내보내기] %d블록 → %s' % (n, path))


def load(sb, args):
    raw = load_jsonl(args.load)
    summ = {}
    for p in glob.glob(args.summaries):
        for r in load_jsonl(p):
            summ[(str(r['confer_num']), int(r['chunk_seq']))] = r
    print('[입력] 원문 %d행 · 판정·요지 %d행' % (len(raw), len(summ)))
    by_cn = defaultdict(list)
    bad_sum, dropped, unjudged = [], 0, []
    for r in raw:
        j = summ.get((r['confer_num'], int(r['chunk_seq'])))
        if j is None:
            unjudged.append('%s#%s' % (r['confer_num'], r['chunk_seq']))
            continue
        if j.get('keep') is False:               # 세션 판정 탈락(--related) — 적재 안 함
            dropped += 1
            continue
        s = (j.get('summary') or '').strip()
        if not s or not am.is_valid_summary(s):     # 검증 실패분은 적재하지 않는다(생성 시점이 유일 방어선, #99)
            bad_sum.append('%s#%s' % (r['confer_num'], r['chunk_seq']))
            continue
        by_cn[r['confer_num']].append({
            'speaker': r['speaker'], 'speaker_raw': r['speaker_raw'], 'position': r['position'],
            'party': None, 'meeting_date': r['meeting_date'], 'confer_num': r['confer_num'],
            'chunk_seq': int(r['chunk_seq']), 'agenda': r['agenda'], 'topic': r['topic'] or None,
            'summary': am.clip_sentence(s, 250), 'source_url': r['source_url'],
        })
    tot = 0
    for cn, rows in sorted(by_cn.items()):
        have = {x['chunk_seq'] for x in am._fetch_all(
            sb.table('assembly_speeches').select('chunk_seq').eq('confer_num', cn))}
        new = [x for x in rows if x['chunk_seq'] not in have]
        print('  %-12s 기존 %3d → 추가 %3d (이미 있음 %d)' % (cn, len(have), len(new), len(rows) - len(new)))
        if args.dry_run or not new:
            tot += len(new)
            continue
        for k in range(0, len(new), 100):
            sb.table('assembly_speeches').upsert(new[k:k + 100],
                                                 on_conflict='confer_num,speaker,chunk_seq').execute()
        tot += len(new)
    print('[%s] 추가 %d행 · 판정 탈락 %d · 판정 없음 %d · 요지 검증 실패 %d%s'
          % ('DRY' if args.dry_run else '적재', tot, dropped, len(unjudged), len(bad_sum),
             (' (%s)' % ', '.join((bad_sum + unjudged)[:10])) if bad_sum or unjudged else ''))


def fix_chips(sb, res, dry):
    n = 0
    for x in res:
        for r in x.get('chips') or []:
            topic = (r.get('topic') or '').strip()
            new_topic = (topic + ', ' if topic else '') + am.SKT_CHIP
            print('  %-12s #%-5d %s: %s → %s' % (x['cn'], r['chunk_seq'], r['speaker'], topic or '(없음)', new_topic))
            if not dry:
                sb.table('assembly_speeches').update({'topic': new_topic}).eq('id', r['id']).execute()
            n += 1
    print('[%s] 칩 보정 %d행' % ('DRY' if dry else '적용', n))


def main():
    ap = argparse.ArgumentParser(description='assembly_speeches 상한에 잘린 발언 점검·소급 (#262)')
    ap.add_argument('--confer', default='', help='대상 confer_num(쉼표 구분, 기본 전체)')
    ap.add_argument('--related', action='store_true', help='자사 대신 SK 밖 관련 후보(세션 판정 대상)')
    ap.add_argument('--blocks-dir', action='append', default=[], help='원문 JSON 폴더 추가(여러 번)')
    ap.add_argument('--cache-dir', default=DEFAULT_CACHE)
    ap.add_argument('--fetch', action='store_true', help='로컬 원문이 없으면 국회 뷰어에서 받는다(AI 0)')
    ap.add_argument('--export', default='', help='대상 블록 jsonl 경로(저장소 밖)')
    ap.add_argument('--load', default='', help='--export 파일(세션 판정·요지와 합쳐 적재)')
    ap.add_argument('--summaries', default='', help='세션 출력 jsonl glob(점검 때는 keep false 제외용)')
    ap.add_argument('--fix-chips', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    if args.load:
        if not args.summaries:
            ap.error('--load 에는 --summaries 가 필요하다')
        load(sb, args)
        return
    keywords = load_press_keywords(sb)
    res = scan(sb, args, keywords)
    report(res, args.related)
    if args.export:
        if os.path.abspath(args.export).startswith(REPO + os.sep):
            ap.error('원문 파일은 저장소 밖에 둔다(저장소는 공개)')
        export(res, keywords, args.export, args.related)
    if args.fix_chips:
        fix_chips(sb, res, args.dry_run)


if __name__ == '__main__':
    main()
