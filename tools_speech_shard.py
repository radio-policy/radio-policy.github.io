# -*- coding: utf-8 -*-
"""발언 재수집 2단계 보조 — 덤프를 서브에이전트용 샤드로 분할한다(요약은 세션이 수행)."""
import argparse, io, json, os, sys
sys.stdout.reconfigure(encoding='utf-8')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default='speech_rebuild/raw_speeches.jsonl')
    ap.add_argument('--size', type=int, default=60)
    ap.add_argument('--only-confer', default='')
    ap.add_argument('--prefix', default='shard')
    a = ap.parse_args()
    rows = [json.loads(l) for l in io.open(a.src, encoding='utf-8')]
    if a.only_confer:
        rows = [r for r in rows if r['confer_num'] == a.only_confer]
    d = os.path.dirname(a.src) or '.'
    n = 0
    for i in range(0, len(rows), a.size):
        n += 1
        p = os.path.join(d, '%s_%03d.jsonl' % (a.prefix, n))
        with io.open(p, 'w', encoding='utf-8') as f:
            for r in rows[i:i + a.size]:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        print('%s  %d행' % (p, len(rows[i:i + a.size])))
    print('[샤드] %d개 · 총 %d행' % (n, len(rows)))

if __name__ == '__main__':
    main()
