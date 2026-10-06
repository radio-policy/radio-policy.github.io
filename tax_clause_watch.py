# -*- coding: utf-8 -*-
"""
무선국 등록면허세 근거 조문 감시 (#287, 2026-10-06) — 세율·종별·감면 글이 바뀐 날만 운영자에게 한 줄. AI 0회.

왜: 무선국 1국당 등록면허세는 세 곳의 글로 정해진다 — ⓐ 지방세법 제34조 세율표(종별·시군별 정액) ⓑ 지방세법 시행령
별표 1의 무선국 행(지금 <제3종> 제128호) ⓒ 지방세특례제한법의 무선국·이동통신 감면(제49조의2 5G 무선국 50% 경감 —
2023-12-31 일몰, 현행본에 그대로 남아 있다). ⓐⓑ는 KB에 있어 law_sync가 새 판으로 바꿔 넣지만 그 숫자가 바뀌었는지는
아무도 알려 주지 않고, ⓒ는 KB에 없다(넣지 않기로 함 — 10-06 운영자 결정 ④ 보류). 그래서 셋의 글자 지문을 app_config 한 행에
두고 달라진 날만 운영자 봇에 알린다.

  ⓐ ⓑ document_chunks 현행본(11:00 체인 앞 단계 law_sync가 이미 교체) — 조각을 이어 붙여 그 조·그 행만
  ⓒ 법제처 DRF(lawSearch → 현행 MST·시행일 → lawService eflaw)에서 「무선국|이동통신|기지국」이 든 조문단위 전부(부칙·별표 제외)

지문 = 정규화한 글(공백·<img> 태그 제거 — 같은 표도 판마다 그림 번호가 바뀐다)의 sha256 앞 16자리. 판 번호·시행일은 지문에
넣지 않는다(글이 같으면 판이 바뀌어도 조용히). 첫 실행은 저장만. 조회 실패한 갈래는 지난 값을 그대로 두고 연속 실패 수만 센다 —
FAIL_ALERT_RUNS번째에 한 번 「감시 못 함」을 알린다(조용한 고장 방지). 새 표는 만들지 않는다(app_config 한 행, value는 JSON 글).

  py -3.12 tax_clause_watch.py --dry-run   # 지금 지문·지난 지문 대조만 출력(DB·알림 없음)
  py -3.12 tax_clause_watch.py             # 대조 → 저장 → 달라진 것만 운영자 봇(11:00 law_crawl.yml 끝 스텝)
필요 .env: SUPABASE_URL, SUPABASE_SERVICE_KEY, LAW_OC_KEY (+ 알림 시 TELEGRAM_BOT_TOKEN/CHAT_ID).
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

KST = timezone(timedelta(hours=9))
CONFIG_KEY = 'tax_clause_watch'
FAIL_ALERT_RUNS = 3
WORDS_RE = re.compile(r'무선국|이동통신|기지국')
SPTL_NAME = '지방세특례제한법'
HEAD_PREFIX_RE = re.compile(r'^〔[^〕\n]{1,12}〕\n')            # law_sync.chunk_articles가 붙인 별표 구간 머리(#287)
SECTION_RE = re.compile(r'(?m)^[ \t]*<[ \t]*(제[ \t]*\d+[ \t]*[종류군급])[ \t]*>[ \t]*$')
ITEM_RE = re.compile(r'(?m)^(\d+)\.\s')


# ── 순수 함수(시험 대상) ───────────────────────────────────────

def norm(text):
    """지문용 정규화 — <img …>·</img> 태그와 모든 공백을 뺀다(같은 세율표도 판마다 그림 번호 flSeq가 바뀐다)."""
    t = re.sub(r'</?img[^>]*>', '', text or '')
    return re.sub(r'\s+', '', t)


def fingerprint(text):
    return hashlib.sha256(norm(text).encode('utf-8')).hexdigest()[:16]


def merge_chunks(parts):
    """같은 조·별표의 조각(chunk_index 순)을 원문으로 — 별표 구간 머리 접두를 떼고 앞뒤 겹침(≈100자)을 한 번만 남긴다."""
    out = ''
    for p in parts:
        t = HEAD_PREFIX_RE.sub('', p or '', count=1)
        if not t:
            continue
        if not out:
            out = t
            continue
        k = 0
        for n in range(min(400, len(out), len(t)), 19, -1):
            if out[-n:] == t[:n]:
                k = n
                break
        out += t[k:] if k else '\n' + t
    return out


def annex_items(text, words=WORDS_RE):
    """별표 본문 → 낱말이 든 항목 [(key, label 꼬리, 저장 글)] — 항목 = 「N. 」 줄부터 다음 항목·구간 머리 전까지, 구간(<제3종>)은
    번호가 구간마다 다시 1부터라 열쇠에 넣는다."""
    marks = sorted([(m.start(), 'S', re.sub(r'\s', '', m.group(1))) for m in SECTION_RE.finditer(text)]
                   + [(m.start(), 'I', m.group(1)) for m in ITEM_RE.finditer(text)])
    out, sec = [], ''
    for i, (pos, kind, val) in enumerate(marks):
        if kind == 'S':
            sec = val
            continue
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        body = text[pos:end].strip()
        if words.search(body):
            out.append((f'{sec}|{val}', f'{sec} 제{val}호' if sec else f'제{val}호', f'〔{sec}〕 {body}' if sec else body))
    return out


def first_diff(old, new, width=24):
    """두 글(정규화)이 처음 갈리는 곳 앞뒤 — 알림 한 줄에 「…옛…」→「…새…」로."""
    a, b = norm(old), norm(new)
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    s = max(0, i - 8)
    return a[s:i + width], b[s:i + width]


def compare(state, fresh, ok_groups, today):
    """state(지난 저장) + fresh({key: item}) → (새 state, 알림 줄 목록). 첫 실행(state 없음)은 저장만.
    ok_groups: 이번에 조회에 성공한 갈래(a·b·c) — 실패한 갈래의 지난 항목은 그대로 두고 연속 실패 수만 올린다."""
    first = not state or not state.get('items')
    old = dict((state or {}).get('items') or {})
    fails = dict((state or {}).get('fails') or {})
    lines = []
    items = {k: v for k, v in old.items() if v.get('group') not in ok_groups}   # 실패한 갈래는 지난 값 유지
    for g in ('a', 'b', 'c'):
        if g in ok_groups:
            fails[g] = 0
            continue
        fails[g] = int(fails.get(g, 0)) + 1
        if fails[g] == FAIL_ALERT_RUNS and not first:
            lines.append(f"⚠ {GROUP_NAME[g]} 감시 못 함 — {FAIL_ALERT_RUNS}회 연속 조회 실패")
    for k, v in fresh.items():
        items[k] = dict(v, checked=today)
        o = old.get(k)
        if first:
            continue
        if not o:
            lines.append(f"🆕 {v['label']} — 새로 걸림 ({v['src']})")
        elif o.get('hash') != v['hash']:
            a, b = first_diff(o.get('text', ''), v['text'])
            lines.append(f"✏️ {v['label']} — 글 바뀜 ({o.get('src')} → {v['src']}) 「…{a}…」→「…{b}…」")
    for k, o in old.items():
        if o.get('group') in ok_groups and k not in fresh and not first:
            lines.append(f"🗑 {o.get('label')} — 사라짐 (지난 {o.get('src')})")
    return {'v': 1, 'items': items, 'fails': fails, 'updated_at': today}, lines


GROUP_NAME = {'a': '지방세법 제34조 세율표', 'b': '지방세법 시행령 별표 1 무선국 행', 'c': '지방세특례제한법 무선국 감면'}


# ── 조회 ──────────────────────────────────────────────────────

def _current_doc(sb, prefix):
    """그 법령의 현행 문서명 — 문서명 목록은 kb_store.list_docs(RPC)로(#218), 둘이면 시행일이 늦은 쪽."""
    import kb_store
    names = sorted((d for d in kb_store.list_docs(sb, status='current') if d.startswith(prefix)),
                   key=lambda d: (re.findall(r'\((\d{8})\)\s*$', d) or [''])[0])
    if not names:
        raise RuntimeError(f'현행 문서 없음: {prefix}')
    return names[-1]


def _chunks(sb, doc, art_like):
    rows = (sb.table('document_chunks').select('id,chunk_index,article_no,content').eq('doc_name', doc)
            .like('article_no', art_like).order('chunk_index').order('id').limit(1000).execute().data) or []
    if len(rows) >= 1000:
        raise RuntimeError(f'조각 1,000개 이상 — 페이지 조회가 필요: {doc} {art_like}')
    return rows


def fetch_a(sb):
    doc = _current_doc(sb, '지방세법(법률)(')
    rows = _chunks(sb, doc, '34조(%')
    if not rows:
        return {}
    text = merge_chunks([r['content'] for r in rows])
    label = '지방세법 제' + rows[0]['article_no']
    return {'a|34조': {'group': 'a', 'label': label, 'src': _short(doc), 'hash': fingerprint(text), 'text': text}}


def fetch_b(sb):
    doc = _current_doc(sb, '지방세법 시행령(대통령령)(')
    rows = _chunks(sb, doc, '별표 1(%')
    if not rows:
        return {}
    text = merge_chunks([r['content'] for r in rows])
    return {f'b|{k}': {'group': 'b', 'label': f'지방세법 시행령 별표 1 {lab}', 'src': _short(doc),
                       'hash': fingerprint(body), 'text': body} for k, lab, body in annex_items(text)}


def fetch_c():
    import requests
    import law_sync
    from law_watch import drf_law_search, pick_exact, row_fields
    rows = drf_law_search(SPTL_NAME, 'law')
    hit = pick_exact(rows or [], SPTL_NAME)
    if not hit:
        raise RuntimeError('법제처 검색 실패·현행본 없음')
    mst, law_no, enf = row_fields(hit, 'law')
    r = requests.get(law_sync.DRF_SERVICE, params={'OC': law_sync.OC_KEY, 'type': 'JSON', 'target': 'eflaw',
                                                   'MST': mst, 'efYd': enf}, timeout=60)
    r.raise_for_status()
    arts = law_sync.law_articles(r.json()['법령'])
    if len(arts) < 50:                       # 빈·잘린 응답을 「전부 사라짐」으로 읽지 않게
        raise RuntimeError(f'조문 {len(arts)}개 — 응답이 비었거나 잘림')
    src = f'제{law_no}호({enf})'
    out = {}
    for art_no, text in arts:
        if WORDS_RE.search(text):
            key = art_no.split('(')[0]
            out[f'c|{key}'] = {'group': 'c', 'label': f'{SPTL_NAME} 제{art_no}', 'src': src,
                               'hash': fingerprint(text), 'text': text}
    return out


def _short(doc):
    m = re.search(r'\((제[^()]*호)\)\((\d{8})\)\s*$', doc)
    return f'{m.group(1)}({m.group(2)})' if m else doc[-24:]


# ── 실행 ──────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='대조만 출력(저장·알림 없음)')
    args = ap.parse_args()
    for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):   # 세션 프록시는 법제처 SSL을 깨뜨린다
        os.environ.pop(k, None)
    from dotenv import load_dotenv
    load_dotenv()
    import sb_client
    import notify
    sb = sb_client.make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    today = datetime.now(KST).strftime('%Y-%m-%d')

    fresh, ok = {}, set()
    for g, fn in (('a', lambda: fetch_a(sb)), ('b', lambda: fetch_b(sb)), ('c', fetch_c)):
        try:
            got = fn()
            fresh.update(got)
            ok.add(g)
            print(f"[{g}] {GROUP_NAME[g]}: {len(got)}개 — " + ', '.join(f"{v['label'][:40]}={v['hash'][:8]}" for v in got.values()))
        except Exception as e:
            print(f"[{g}] {GROUP_NAME[g]}: 조회 실패 — {str(e)[:120]}")

    row = (sb.table('app_config').select('value').eq('key', CONFIG_KEY).limit(1).execute().data) or []
    state = json.loads(row[0]['value']) if row and row[0].get('value') else None
    new_state, lines = compare(state, fresh, ok, today)
    if state is None:
        print('첫 실행 — 지문만 저장(알림 없음)')
    for ln in lines:
        print('  ' + ln)
    if not lines and state is not None:
        print('바뀐 것 없음')
    if args.dry_run:
        print('[dry-run] 저장·알림 없음')
        return 0
    sb.table('app_config').upsert({'key': CONFIG_KEY, 'value': json.dumps(new_state, ensure_ascii=False)},
                                  on_conflict='key').execute()
    if lines:
        notify.send_telegram('🧾 무선국 등록면허세 근거 조문 감시 (#287)\n' + '\n'.join(lines), disable_web_page_preview=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
