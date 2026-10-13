# -*- coding: utf-8 -*-
"""텔레그램 주요 뉴스 2문장 요약 지시문 실측 (#298, 2026-10-13 운영자 결정 5) — 실제 호출(운영 모델), DB 쓰기 없음(api_usage 기록 제외).

실제로 구독자에게 긴급(주요 뉴스)으로 나간 기사(subscriber_queue topic 'urgent', 최신순·기사당 한 번)를 고르고, 그 기사 원문을
**지금 다시 받아**(crawler.fetch_article_body — 운영과 같은 추출기, 자르지 않은 전문) 운영과 같은 요청(news_summary.request_kwargs —
모델·max_tokens·지시문·입력 앞 8,000자)으로 요약시킨다. 결과를 운영자가 원문과 대조한다(부풀림·단정·주체) → 고정.
  자동 표시(참고용 — 판정은 사람): 원문에 없는 범위·확정 낱말, 원문에 없는 숫자, 문장 수 ≠ 2, 120자 기준 길이, 잘림·버림.

  py -3.12 tools_news_summary_probe.py --dry-run                 # 고른 기사·본문 길이·어림 비용(API 0회, 기사 사이트만 읽음)
  py -3.12 tools_news_summary_probe.py --count-tokens            # count_tokens로 정확한 입력 토큰(무료 API, 생성 0)
  py -3.12 tools_news_summary_probe.py --allow-api [--n 10]      # 실제 요약(Sonnet 5 ≈$0.007/건) → local_docs/텔레그램요약_시험_261013/
  py -3.12 tools_news_summary_probe.py --allow-api --from-snapshot <json>   # 같은 본문으로 다시(지시문을 고친 뒤 비교)
  py -3.12 tools_news_summary_probe.py --report <json>           # 저장한 결과로 보고서만 다시(API 0회)
세션에서 돌릴 때는 HTTP(S)_PROXY를 비운다(도구가 비운다). api_usage에는 이 도구의 함수 이름(probe_summary_call)으로 기록된다
— 운영 라벨(news_summary.py:news_tg_summary)과 섞이지 않게. 요청 모양은 운영과 같다(tests/test_news_summary.py가 대조).
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
for _k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
    os.environ.pop(_k, None)

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, 'local_docs', '텔레그램요약_시험_261013')
PRICE_IN, PRICE_OUT = 2.0, 10.0         # $ / 100만 토큰 — main이 모델(--model 또는 운영 모델)로 다시 정한다
PRICES = {'claude-haiku-4-5-20251001': (1.0, 5.0), 'claude-sonnet-5': (2.0, 10.0), 'claude-sonnet-5-5': (2.0, 10.0)}
KST = timezone(timedelta(hours=9))
# 자동 표시 — 요약에 있는데 원문에 없으면 표시(결정 방어 ①의 낱말 + 흔한 부풀림 낱말). 판정은 운영자가 한다.
RISK_WORDS = ('전국', '전면', '모든', '확정', '전체', '일제히', '대폭', '전격', '최초', '사상')


def _env():
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, '.env'))
    except Exception:
        pass


def pick_articles(sb, n: int, days: int = 14) -> list:
    """최근 나간 긴급(공통 urgent 큐 행) 기사 — 최신순, 기사당 한 번. news_feed에서 제목·출처·저장 본문을 붙인다."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    q = (sb.table('subscriber_queue').select('news_url,created_at').eq('topic', 'urgent')
         .gte('created_at', since).order('created_at', desc=True).limit(400).execute().data or [])
    urls, seen = [], set()
    for r in q:
        u = (r.get('news_url') or '').strip()
        if u and u not in seen:
            seen.add(u)
            urls.append((u, r.get('created_at')))
    rows = {}
    for i in range(0, len(urls), 20):
        part = [u for u, _ in urls[i:i + 20]]
        for r in sb.table('news_feed').select('id,url,title,source,content,urgency,published_at').in_('url', part) \
                .execute().data or []:
            rows[r['url']] = r
    out = []
    for u, at in urls:
        if u in rows:
            out.append(dict(rows[u], queued_at=at))
        if len(out) >= n * 3:                    # 본문을 못 받는 기사가 있어 넉넉히
            break
    return out


def fetch_bodies(cands: list, n: int) -> list:
    import crawler
    import news_summary as ns
    got = []
    for a in cands:
        full, _d = crawler.fetch_article_body(a['url'], a.get('source') or '')
        full = full or ''
        ok = ns.usable_body(full)
        print(f"  {'○' if ok else '×'} {len(full):>6}자 저장 {len(a.get('content') or ''):>5}자  {a['title'][:50]}")
        if ok:
            got.append(dict(a, full=full[:ns.SUMMARY_INPUT_MAX], full_len=len(full)))
        if len(got) >= n:
            break
    return got


def probe_kwargs(a: dict, model: str = '') -> dict:
    """운영 요청(news_summary.request_kwargs) 그대로 — model을 주면 모델만 바꾼다(비교 실측, 모델별 인자도 운영 함수가 붙인다)."""
    import news_summary as ns
    return ns.request_kwargs(a['title'], a.get('source'), a['full'], model=model)


def probe_summary_call(client, a: dict, model: str = '') -> dict:
    """운영과 같은 요청 한 번 — 결과 판정도 운영 함수(news_summary.accept). 이 함수 이름이 api_usage 라벨이다."""
    import news_summary as ns
    try:
        resp = client.messages.create(**probe_kwargs(a, model))
    except Exception as e:
        return {'summary': '', 'why': f'실패: {str(e)[:80]}', 'raw': '', 'stop': '', 'in': 0, 'out': 0}
    raw = ''.join(getattr(b, 'text', '') or '' for b in resp.content if getattr(b, 'type', '') == 'text')
    stop = str(resp.stop_reason or '')
    s = ns.accept(raw, stop)
    u = resp.usage
    return {'summary': s, 'why': '' if s else '버림', 'raw': raw, 'stop': stop,
            'in': int(getattr(u, 'input_tokens', 0) or 0), 'out': int(getattr(u, 'output_tokens', 0) or 0)}


def flags(a: dict) -> list:
    s, body = a.get('summary') or a.get('raw') or '', re.sub(r'\s+', ' ', a.get('full') or '')
    out = []
    for w in RISK_WORDS:
        if w in s and w not in body:
            out.append(f'원문에 없는 「{w}」')
    for num in re.findall(r'\d[\d,.]*\d|\d', s):
        n0 = num.replace(',', '')
        if num not in body and n0 not in body.replace(',', ''):
            out.append(f'원문에 없는 숫자 「{num}」')
    k = len(re.findall(r'다\.', s))
    if k != 2:
        out.append(f'문장 {k}개')
    if a.get('why'):
        out.append(f"요약 없음({a['why']}, stop={a.get('stop')})")
    return out


def report(res: list, path_md: str) -> None:
    import subscriber_notify as sn
    n_ok = sum(1 for a in res if a.get('summary'))
    tin, tout = sum(a.get('in', 0) for a in res), sum(a.get('out', 0) for a in res)
    lens = [len(a['summary']) for a in res if a.get('summary')]
    lines = [f'# 텔레그램 주요 뉴스 2문장 요약 — 지시문 실측 ({datetime.now(KST):%Y-%m-%d %H:%M} KST)', '',
             f'- 기사 {len(res)}건(최근 구독자 긴급 알림으로 나간 기사, 최신순) · 요약 붙음 {n_ok}건',
             f'- 토큰 입력 {tin:,} · 출력 {tout:,} → 실비 ${tin * PRICE_IN / 1e6 + tout * PRICE_OUT / 1e6:.4f}'
             f' (출력 최대 {max([a.get("out", 0) for a in res] or [0])} / 상한 {__import__("news_summary").SUMMARY_MAX_TOKENS})',
             f'- 요약 길이(자) {min(lens or [0])}~{max(lens or [0])}, 평균 {sum(lens) / max(1, len(lens)):.0f}', '',
             '대조할 것(운영자): ① 부풀림(원문에 없는 범위·정도) ② 단정(추진·검토를 확정처럼) ③ 주체(누가 말했나·누가 하나). '
             '자동 표시는 참고용이다.', '']
    for i, a in enumerate(res, 1):
        fl = flags(a)
        lines += [f'## {i}. {a["title"]}', '',
                  f'- 출처 {a.get("source")} · 원문 {a.get("full_len")}자(요약 입력 {len(a.get("full") or "")}자) · '
                  f'출력 {a.get("out", 0)}토큰 · stop={a.get("stop")}',
                  f'- {a["url"]}', '',
                  f'**요약**: {a.get("summary") or "(없음 — 제목만)"}', '']
        if not a.get('summary') and a.get('raw'):
            lines += [f'(버린 응답: {a["raw"]})', '']
        lines += [f'자동 표시: {", ".join(fl) if fl else "없음"}', '',
                  '텔레그램 모양:', '```', sn.format_news_item(dict(a, _summary=a.get('summary') or '')), '```', '',
                  '<details><summary>요약에 넣은 원문</summary>', '', a.get('full') or '', '', '</details>', '']
    os.makedirs(os.path.dirname(path_md), exist_ok=True)
    with open(path_md, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'[보고서] {path_md}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='기본 — API 0회')
    ap.add_argument('--count-tokens', action='store_true')
    ap.add_argument('--allow-api', action='store_true')
    ap.add_argument('--n', type=int, default=10)
    ap.add_argument('--from-snapshot')
    ap.add_argument('--report')
    ap.add_argument('--model', default='', help='비교 실측용 — 운영 모델 대신(예: claude-sonnet-5). 지시문·입력은 운영 그대로')
    args = ap.parse_args()
    _env()
    global PRICE_IN, PRICE_OUT
    import news_summary as _ns
    _model = args.model or _ns.SUMMARY_MODEL
    PRICE_IN, PRICE_OUT = PRICES.get(_model, (PRICE_IN, PRICE_OUT))
    print(f'[모델] {_model}' + ('' if args.model else '(운영)') + f' — 단가 ${PRICE_IN}/${PRICE_OUT} (100만 토큰)')

    if args.report:
        res = json.load(open(args.report, encoding='utf-8'))
        report(res, os.path.splitext(args.report)[0] + '.md')
        return

    if args.from_snapshot:
        arts = json.load(open(args.from_snapshot, encoding='utf-8'))
        arts = [{k: a[k] for k in ('id', 'url', 'title', 'source', 'content', 'urgency', 'published_at', 'queued_at',
                                   'full', 'full_len') if k in a} for a in arts]
        print(f'[스냅샷] {len(arts)}건 — 같은 본문으로')
    else:
        from sb_client import make_client
        sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
        cands = pick_articles(sb, args.n)
        print(f'[후보] 최근 구독자 긴급 기사 {len(cands)}건 — 본문을 다시 받는다')
        arts = fetch_bodies(cands, args.n)
    chars = sum(len(a['full']) for a in arts)
    print(f'[세트] {len(arts)}건 · 입력 본문 {chars:,}자 · 어림 비용 ≈ ${chars * 0.9 * PRICE_IN / 1e6 + len(arts) * 150 * PRICE_OUT / 1e6:.3f}'
          ' (한글 1자 ≈ 0.9토큰 어림)')

    if args.count_tokens or args.allow_api:
        import anthropic
        import news_summary as ns
        client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'], timeout=ns.SUMMARY_TIMEOUT_S, max_retries=1)
    if args.count_tokens:
        tot = 0
        for a in arts:
            kw = ns.request_kwargs(a['title'], a.get('source'), a['full'])
            kw.pop('max_tokens')
            tot += client.messages.count_tokens(**kw).input_tokens
        print(f'[count_tokens] 입력 {tot:,}토큰 → 입력 비용 ${tot * PRICE_IN / 1e6:.4f} (+ 출력 ≈ ${len(arts) * 150 * PRICE_OUT / 1e6:.4f})')
    if not args.allow_api:
        print('[dry-run] API 호출 없음 — 실제 요약은 --allow-api')
        return

    res = []
    for i, a in enumerate(arts, 1):
        r = probe_summary_call(client, a, args.model)
        res.append(dict(a, **r))
        print(f'  {i:>2}. {r["out"]:>3}토큰 {len(r["summary"]):>3}자 {r["summary"] or "(없음: " + r["why"] + ")"}')
    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = datetime.now(KST).strftime('%m%d_%H%M') + (('_' + args.model) if args.model else '')
    path = os.path.join(OUT_DIR, f'probe_{stamp}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(f'[저장] {path}')
    report(res, os.path.splitext(path)[0] + '.md')


if __name__ == '__main__':
    main()
