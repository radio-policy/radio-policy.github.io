"""자문 검색 회귀 스냅샷 비교 (#201, 2026-09-24 B-2)

사용: python tests/rag_regress_diff.py A.json B.json [--fields rag,extra,added,citing,annex,pending,kb,news]

두 스냅샷(브라우저 하네스 window.ragRegress.last를 저장한 파일 / Deno 하네스 출력)을 질문 id로 맞춰
단계별 id 목록이 **순서까지** 같은지 대조하고, 다르면 집합 차이(양쪽에만 있는 것)와 순서만 다른지를 적는다.
소요 시간은 질문별·합계로 나란히 보여 준다. 네트워크·AI 없음.
"""
import json
import sys

# Windows 콘솔(cp949)에서 한글 출력이 깨지지 않게 — PC 스크립트 공통 규칙(#19)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


def load(path):
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    return {r['id']: r for r in d.get('results', [])}, d


def main():
    argv = sys.argv[1:]
    fields = 'rag,extra,added,citing,annex,pending,kb,news'
    if '--fields' in argv:
        # 값까지 떼어 낸 뒤 파일 인자를 센다 — 종전엔 값('a,b')이 세 번째 파일로 잡혀 사용법만 출력됐다
        i = argv.index('--fields')
        fields = argv[i + 1] if i + 1 < len(argv) else ''
        del argv[i:i + 2]
    args = [a for a in argv if not a.startswith('--')]
    fields = [f for f in fields.split(',') if f]
    if len(args) != 2 or not fields:
        print(__doc__)
        sys.exit(2)
    a, da = load(args[0])
    b, db = load(args[1])
    print(f'A = {args[0]} (tag={da.get("tag")}, {len(a)}건, 총 {da.get("totalMs")}ms)')
    print(f'B = {args[1]} (tag={db.get("tag")}, {len(b)}건, 총 {db.get("totalMs")}ms)')
    same = diff = 0
    for qid in sorted(set(a) | set(b)):
        ra, rb = a.get(qid), b.get(qid)
        if not ra or not rb:
            print(f'{qid}: 한쪽에만 있음')
            diff += 1
            continue
        lines = []
        for f in fields:
            va, vb = ra.get(f), rb.get(f)
            if va is None and vb is None:
                continue
            if va == vb:
                continue
            la, lb = list(va or []), list(vb or [])
            if sorted(map(str, la)) == sorted(map(str, lb)):
                lines.append(f'  {f}: 순서만 다름 A={la} B={lb}')
            else:
                only_a = [x for x in la if x not in lb]
                only_b = [x for x in lb if x not in la]
                lines.append(f'  {f}: A에만 {only_a} / B에만 {only_b} (A {len(la)}개, B {len(lb)}개)')
        err = ''
        if ra.get('error') or rb.get('error'):
            err = f'  error A={ra.get("error")} B={rb.get("error")}'
        # RPC 기록이 있으면(하네스 계측) 검색 RPC의 행수·오류를 나란히 — trgm 타임아웃(57014)이 차이의 원인인지 바로 보인다
        def rpc_summary(r):
            out = []
            for x in r.get('rpc') or []:
                fn = str(x.get('fn', ''))
                short = fn.replace('search_chunks_trgm', 'trgm').replace('match_chunks_semantic', 'sem') \
                          .replace('match_law_articles_semantic', 'lawsem').replace('search_kb_chunks_trgm', 'kbtrgm') \
                          .replace('match_kb_chunks_semantic', 'kbsem')
                out.append(f"{short}={x.get('rows')}{'!' + str(x.get('error')) if x.get('error') else ''}({x.get('ms')}ms)")
            return ' '.join(out)
        if (ra.get('rpc') or rb.get('rpc')) and lines:
            lines.append(f'  rpc A: {rpc_summary(ra)}')
            lines.append(f'  rpc B: {rpc_summary(rb)}')
        if lines or err:
            diff += 1
            print(f'{qid}: 다름  ({ra.get("ms")}ms → {rb.get("ms")}ms)')
            for ln in lines:
                print(ln)
            if err:
                print(err)
        else:
            same += 1
            print(f'{qid}: 동일  ({ra.get("ms")}ms → {rb.get("ms")}ms)')
    print(f'\n동일 {same} / 다름 {diff}  |  총 소요 {da.get("totalMs")}ms → {db.get("totalMs")}ms')
    sys.exit(1 if diff else 0)


if __name__ == '__main__':
    main()
