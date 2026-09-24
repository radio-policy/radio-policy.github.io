# -*- coding: utf-8 -*-
"""
OKF 요약 자동 갱신 (2026-09-24 신설, #198 — 운영자 결정 ⓓ '완전 자동').

조문(document_chunks)이 새 판으로 교체·승격됐는데 OKF 요약(kb_documents)이 옛 판이면
(okf_drift_check.find_drift), Sonnet이 **새 판 전문 + 구판 요약(구조·실무 메모 참고)**으로
요약을 전면 재작성해 현행 요약으로 적재한다. 구판 요약 행은 superseded로 보존하므로 되돌릴 수 있다.

왜 전면 재작성인가(운영자 결정): 바뀐 문장만 고치는 방식은 옛 문장이 섞여 남고 DIFF가 못 보는
별표 개정을 놓친다(#116-보론). 전문을 통째로 읽으면 둘 다 자연히 해결된다. 비용은 Sonnet 5 기준
법령 하나 $0.2~0.4(전문 평균 4.6만 자), 월 8~10건 → 월 $3~5.

왜 무인인가: 웹 업로드 승인 훅은 2026-07-29부터 Haiku로 검토 없이 OKF를 자동 생성해 왔다(선례).
그보다 좋은 모델로, 구판 보존 + 무엇이 바뀌었는지 텔레그램 통지를 붙이면 사후 검토로 충분하다.

흐름(11:00 체인, law_sync --all-outdated 뒤 · okf_drift_check 앞):
  ① 어긋남 목록 → ② 구판 요약 행 + 새 판 전문 + (있으면) 직전 판과의 조문 차이 →
  ③ Sonnet 전면 재작성 → ④ 검증(프론트매터·섹션·분량·완결) → ⑤ 새 path로 kb_documents/kb_chunks
  적재(voyage-law-2), 구판 행 superseded → ⑥ 텔레그램 통지 + api_usage 기록.

DB 우선(번들 파일은 안 쓴다): Actions는 저장소에 커밋하지 않는다. 웹 생성 OKF와 같은 방식으로
`sync_kb_to_bundle.py`가 DB 행을 번들 md + manifest로 역동기화한다(기존 주기 작업).

사용:
  python okf_refresh.py --dry-run            # 대상·입력 토큰 수·예상 비용만(API 호출 0, DB 무변경)
  python okf_refresh.py --only 금지행위       # 특정 법령만(제목 조각)
  python okf_refresh.py                      # 실행. 한 번에 --limit(기본 5)건까지 — 나머지는 다음 실행
  python okf_refresh.py --limit 20 --allow-api   # 상한을 넘겨 돌릴 때(수동, 비용 확인 후)
필요 .env: SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY, VOYAGE_API_KEY (+ TELEGRAM_*)
"""

import os
import re
import sys
import time
import argparse
from datetime import datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import sb_client
import api_usage
import notify as tg_notify
import okf_drift_check
import import_regulatory_kb as ikb
from law_watch import parse_doc_name

api_usage.install()

KST = timezone(timedelta(hours=9))
MODEL = 'claude-sonnet-5'
MAX_OUTPUT_TOKENS = 32000          # 요약 본문 최대 3.4만 자 실측 → 여유. 스트리밍이라 timeout 무관
MAX_INPUT_TOKENS = 600_000         # 이 위는 무인 처리 안 함(세션 처리) — 100만 자짜리 법령 1건이 이 근처
PRICE_IN, PRICE_OUT = 2.0, 10.0    # Sonnet 5 $/백만 토큰 (2026-09-24 기준, 통지 문구의 추정치에만 씀)
DEFAULT_LIMIT = 5                  # 한 실행의 무인 상한(비용 상한 ≈ $2~3). 넘는 건 다음 실행이 이어서
DIFF_MAX_CHARS = 60_000            # 직전 판과의 조문 차이 블록 상한
DIFF_OLD_EXCERPT = 2_500           # 개정 조문의 구판 원문 발췌 상한(조문당)
SITE = 'okf_refresh.py:rewrite'

SYSTEM_PROMPT = (
    "너는 대한민국 전파·통신 규제 전문가이자 SK텔레콤 기술정책팀 지식베이스(OKF)의 편집자다. "
    "법령이 새 판으로 개정되어, 그 법령의 OKF 요약 문서를 새 판 기준으로 전면 재작성한다.\n"
    "출력은 마크다운 문서 하나뿐이다 — 머리말·설명·코드펜스(```)를 붙이지 말 것.\n\n"
    "규칙:\n"
    "1. 문서 맨 앞에 --- 로 감싼 YAML frontmatter를 둔다. 키는 구판과 같게(type, title, description, resource, "
    "tags, timestamp, law_type, law_number, enforcement_date, competent_authority, status, source_path) 하되 "
    "law_number·enforcement_date·resource·timestamp는 [메타]의 새 값으로, status는 current로 쓴다. "
    "description은 한 문장으로 새 판을 설명한다.\n"
    "2. 섹션 구조('# 요약' '# 적용 범위' '# 주요 내용' '# 실무 체크리스트' '# Citations' 등)는 구판을 따르되, "
    "내용은 [새 판 전문]을 기준으로 다시 쓴다. 구판 문장을 그대로 두지 말고 새 판 조문과 하나하나 대조해 "
    "조문 번호·항·호·수치·기한·시행일을 새 판에 맞춘다. 별표·부칙도 전문에 있으면 반영한다.\n"
    "3. 구판의 SK텔레콤 실무 관점, 실무 체크리스트, 별표 해설, 다른 문서로의 링크([…](….md))는 새 판에서도 "
    "유효하면 유지한다. 폐지·변경된 것은 고치거나 뺀다.\n"
    "4. '# 요약' 안에 **제N호(YYYY-MM-DD 시행) 개정 요지** 문단을 두고, 직전 판 대비 무엇이 바뀌었는지 조문 "
    "번호와 함께 적는다. [직전 판과의 조문 차이]에 없는 변경을 지어내지 말 것. 차이 목록이 비어 있거나 "
    "제공되지 않았으면 '조문 본문의 실질 변경은 확인되지 않음(별표·부칙 확인 필요)'처럼 사실대로 쓴다.\n"
    "5. [새 판 전문]에 없는 내용은 쓰지 않는다. 확실하지 않으면 쓰지 않는다. 과장 없이 사실만.\n"
    "6. 분량은 구판 요약과 비슷하게(±30%). '# Citations'로 끝낸다.\n"
    "7. 입력 블록 이름([메타]·[구판 요약 문서 전문]·[직전 판과의 조문 차이]·[새 판 전문])을 본문에 쓰지 않는다 — "
    "독자는 그 블록을 보지 못한다. '새 판 조문에 따르면', '직전 판 대비'처럼 풀어 쓴다.\n"
)


# ── 순수 함수(스모크 테스트 대상) ─────────────────────────

def kb_law_number(api_no: str) -> str:
    """law_watch(API) 호수 → kb 관례 표기. '제00156호'→'제156호', '제2026-26호' 그대로."""
    core = okf_drift_check.norm_no(api_no)
    return f"제{core}호" if core else (api_no or '')


def ymd_dash(d8: str) -> str:
    d = re.sub(r'[^0-9]', '', d8 or '')
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else (d8 or '')


def new_doc_path(old_path: str, new_no: str) -> str:
    """구판 path → 신판 path. 꼬리의 판 표시(_36121·_2026_10)를 떼고 새 호수를 붙인다(판별 파일 관례)."""
    p = (old_path or '').replace('\\', '/')
    stem, ext = (p[:-3], '.md') if p.endswith('.md') else (p, '.md')
    stem = re.sub(r'_\d{1,6}(_\d{1,6})?$', '', stem)         # _36121 / _2026_10 / _156
    tag = okf_drift_check.norm_no(new_no).replace('-', '_')
    out = f"{stem}_{tag}{ext}"
    if out == p:                                             # 같은 이름이면 충돌 방지
        out = f"{stem}_{tag}_r{ext}"
    return out


def retitle(title: str, old_no: str, new_no: str) -> str:
    """제목에 호수가 박힌 고시('… 고시 (과기정통부고시 제2026-10호)')는 호수만 새것으로."""
    if old_no and old_no in (title or ''):
        return title.replace(old_no, new_no)
    return title or ''


def group_articles(chunks):
    """[(article_no, content)] → {article_no: 본문}(청크 순서 유지). article_no 없는 청크는 '(본문 N)'."""
    out, n = {}, 0
    for art, content in chunks:
        key = art or ''
        if not key:
            n += 1
            key = f'(본문 {n})'
        out[key] = (out.get(key, '') + ('\n' if key in out else '') + (content or ''))
    return out


def article_diff(old_chunks, new_chunks):
    """직전 판 ↔ 새 판 조문 대조 → (신설, 삭제, 개정) 조문 번호 목록 + 프롬프트 블록."""
    old, new = group_articles(old_chunks), group_articles(new_chunks)
    norm = lambda t: re.sub(r'\s+', ' ', t or '').strip()
    added = [a for a in new if a not in old]
    removed = [a for a in old if a not in new]
    changed = [a for a in new if a in old and norm(old[a]) != norm(new[a])]
    lines = [f"신설 {len(added)}개 · 삭제 {len(removed)}개 · 개정 {len(changed)}개"]
    if added:
        lines.append("[신설] " + ", ".join(added[:60]) + (" …" if len(added) > 60 else ""))
    if removed:
        lines.append("[삭제] " + ", ".join(removed[:60]) + (" …" if len(removed) > 60 else ""))
        for a in removed[:15]:
            lines.append(f"--- 삭제된 {a} (구판 원문) ---\n{old[a][:DIFF_OLD_EXCERPT]}")
    for a in changed:
        lines.append(f"--- 개정된 {a} (구판 원문 — 새 판은 [새 판 전문] 참조) ---\n{old[a][:DIFF_OLD_EXCERPT]}")
    text = "\n".join(lines)
    if len(text) > DIFF_MAX_CHARS:
        text = text[:DIFF_MAX_CHARS] + "\n… (차이 블록 상한 초과 — 나머지는 [새 판 전문]과 대조)"
    return {'added': added, 'removed': removed, 'changed': changed, 'text': text}


def build_user_prompt(kb_row, meta, old_body_md, new_chunks, diff):
    parts = [
        "[메타]",
        f"title={meta['title']} / law_type={kb_row.get('law_type') or ''} / concept_type={kb_row.get('concept_type') or ''}",
        f"구판: law_number={kb_row.get('law_number')} enforcement_date={kb_row.get('enforcement_date')}",
        f"새 판: law_number={meta['new_no']} enforcement_date={meta['new_enf']} resource={meta['doc_name']}",
        f"competent_authority={kb_row.get('competent_authority') or ''} / timestamp={meta['today']}T00:00:00Z / "
        f"source_path=법제처 DRF API(law_sync.py) 취득 — 조문 원문은 document_chunks 참조",
        f"개정 요지 문단 제목은 정확히 '**{meta['new_no']}({meta['new_enf']} 시행) 개정 요지**'로 쓴다(제N호 같은 자리표시 금지).",
        "",
        "[구판 요약 문서 전문 — 구조·실무 메모 참고용, 내용은 새 판 기준으로 다시 쓴다]",
        old_body_md or '(구판 본문 없음)',
        "",
        "[직전 판과의 조문 차이]",
        diff['text'] if diff else "(직전 판 조문을 구할 수 없어 대조하지 못함 — 개정 요지는 지어내지 말 것)",
        "",
        "[새 판 전문]",
    ]
    for art, content in new_chunks:
        parts.append(f"## {art}\n{content}" if art else content)
    return "\n".join(parts)


def strip_fence(md: str) -> str:
    md = (md or '').strip()
    md = re.sub(r'^```(?:markdown|md)?\s*\n', '', md)
    md = re.sub(r'\n```\s*$', '', md)
    return md.strip()


def validate_output(md: str, old_body: str, new_path: str, meta):
    """(fm, body) 또는 ValueError. 잘린 문서·형식 이탈·분량 급변을 적재 전에 막는다."""
    md = strip_fence(md)
    if not md.startswith('---'):
        raise ValueError('frontmatter 없음')
    fm, body = ikb.split_frontmatter(md)
    body = body.strip()
    if '# 요약' not in body:
        raise ValueError("'# 요약' 섹션 없음")
    ok, why = ikb.check_body_complete(new_path, body)
    if not ok:
        raise ValueError(why)
    # 입력 블록 이름의 '언급'은 표현만 바꾼다(첫 체인 실행에서 국가재정법 시행령이 이걸로 기각돼 $0.38이 버려졌다, #198-보론).
    # 기각은 블록이 통째로 섞인 경우([메타] 머리와 그 값 줄)만.
    if re.search(r'\[메타\]\s*\n\s*title=', body):
        raise ValueError('프롬프트 블록이 본문에 통째로 섞임')
    for label, plain in (('[새 판 전문]', '새 판 조문'), ('[직전 판과의 조문 차이]', '직전 판과의 조문 차이')):
        body = body.replace(label, plain)
    body = re.sub(r'\[구판 요약 문서 전문[^\]\n]*\]', '구판 요약', body)
    # 시험 실행(2026-09-24)에서 규칙문의 '제N호'를 그대로 베낀 사례 — 자리표시가 남으면 실제 호수로
    body = body.replace('제N호(', meta['new_no'] + '(').replace('제N호 ', meta['new_no'] + ' ')
    lo, hi = len(old_body or '') * 0.5, max(len(old_body or '') * 2.5, 3000)
    if old_body and not (lo <= len(body) <= hi):
        raise ValueError(f'분량 급변: 구판 {len(old_body)}자 → {len(body)}자')
    if meta['new_no'] not in (fm.get('law_number') or '') and meta['new_no'] not in body[:4000]:
        raise ValueError(f"새 호수 {meta['new_no']}가 문서에 없음")
    return fm, body


def est_cost(usage) -> float:
    g = lambda k: int(getattr(usage, k, 0) or 0)
    return (g('input_tokens') + g('cache_read_input_tokens') + g('cache_creation_input_tokens')) / 1e6 * PRICE_IN \
        + g('output_tokens') / 1e6 * PRICE_OUT


def format_refresh_report(done, fails, skipped, now=None):
    now = now or datetime.now(KST).strftime('%m/%d %H:%M')
    lines = []
    if done:
        cost = sum(d.get('cost') or 0 for d in done)
        lines.append(f"✍️ <b>OKF 요약 자동 갱신 {len(done)}건</b> ({now}) · 약 ${cost:.2f}")
        for d in done:
            lines.append(f"· {d['title']}: {d['old_no']} → <b>{d['new_no']}</b>({d['new_enf']}) · 본문 {d['old_len']}→{d['new_len']}자 · 청크 {d['chunks']}")
            df = d.get('diff') or {}
            if df:
                lines.append(f"  <i>조문 차이 신설 {len(df.get('added', []))}·삭제 {len(df.get('removed', []))}·개정 {len(df.get('changed', []))}</i>")
            else:
                lines.append("  <i>직전 판 조문 없음 — 개정 요지는 새 판 전문만으로</i>")
        lines.append("<i>구판 요약은 superseded로 보존. 대시보드 '실무 안내' 탭에서 확인 — 잘못됐으면 세션에서 되돌리기(status 교환).</i>")
    if fails:
        lines.append(f"❌ <b>자동 갱신 실패 {len(fails)}건</b>" + ("" if done else f" ({now})") + " — 세션 처리 필요")
        for t, why in fails:
            lines.append(f"· {t}: {why}")
    if skipped:
        lines.append(f"⏭ 보류 {len(skipped)}건: " + ", ".join(f"{t}({why})" for t, why in skipped))
    return "\n".join(lines)


# ── DB ─────────────────────────────────────────────────────

def fetch_chunks(sb, doc_name, status=None):
    rows, start = [], 0
    while True:
        q = (sb.table('document_chunks').select('chunk_index, article_no, content')
             .eq('doc_name', doc_name).order('chunk_index').range(start, start + 999))
        if status:
            q = q.eq('status', status)
        batch = q.execute().data or []
        rows.extend(batch)
        if len(batch) < 1000:
            break
        start += 1000
    return [(r.get('article_no') or '', r.get('content') or '') for r in rows]


def find_prev_doc(sb, law_id, new_doc, kb_enf8):
    """같은 law_id의 superseded 판 중 요약이 설명하던 판(시행일 일치) 우선, 없으면 가장 최근 구판."""
    if not law_id:
        return None
    rows = (sb.table('document_chunks').select('doc_name').eq('law_id', law_id)
            .eq('status', 'superseded').neq('doc_name', new_doc).limit(3000).execute().data) or []
    cands = {}
    for r in rows:
        m = parse_doc_name(r['doc_name'])
        if m and m.get('enf_date'):
            cands[r['doc_name']] = m['enf_date']
    if not cands:
        return None
    exact = [d for d, e in cands.items() if e == kb_enf8]
    return exact[0] if exact else max(cands, key=cands.get)


def load_kb_row(sb, path):
    r = sb.table('kb_documents').select('*').eq('path', path).eq('status', 'current').limit(1).execute()
    return (r.data or [None])[0]


def call_model(client, user_prompt, dry_run=False):
    """스트리밍(긴 출력) → 최종 메시지. usage는 api_usage에 명시 기록(스트림은 래퍼가 못 잡는다)."""
    kwargs = dict(model=MODEL, max_tokens=MAX_OUTPUT_TOKENS, system=SYSTEM_PROMPT,
                  thinking={'type': 'disabled'},
                  messages=[{'role': 'user', 'content': user_prompt}])
    n_in = client.messages.count_tokens(model=MODEL, system=SYSTEM_PROMPT,
                                        messages=kwargs['messages']).input_tokens
    if n_in > MAX_INPUT_TOKENS:
        raise ValueError(f'입력 {n_in:,} 토큰 > 상한 {MAX_INPUT_TOKENS:,} — 세션 처리')
    if dry_run:
        return None, n_in, None
    with client.messages.stream(**kwargs) as s:
        msg = s.get_final_message()
    api_usage.record_usage(SITE, msg.usage, MODEL)
    text = ''.join(b.text for b in msg.content if getattr(b, 'type', '') == 'text')
    if msg.stop_reason == 'max_tokens':
        raise ValueError('출력이 max_tokens에서 잘림')
    return text, n_in, msg.usage


def write_kb(sb, kb_row, fm, body, meta, path):
    entry = {
        'dedup_key': retitle(kb_row.get('dedup_key') or '', kb_row.get('law_number') or '', meta['new_no']) or None,
        'title': meta['title'], 'concept_type': kb_row.get('concept_type'),
        'law_type': kb_row.get('law_type'), 'law_number': meta['new_no'],
        'enforcement_date': meta['new_enf'], 'status': 'current', 'path': path,
    }
    row = ikb.build_doc_row(entry, fm, body)
    row['competent_authority'] = row.get('competent_authority') or kb_row.get('competent_authority')
    ikb.sb_delete_doc(path)                                  # 앞선 실패 실행의 잔재 제거(idempotent)
    doc_id = ikb.sb_insert_doc(row)
    chunks = ikb.chunk_body(body, meta['title'])
    embs = []
    for i in range(0, len(chunks), ikb.VOYAGE_BATCH):
        embs.extend(ikb.voyage_embed(chunks[i:i + ikb.VOYAGE_BATCH]))
    ikb.sb_insert_chunks(doc_id, chunks, embs)
    got = (sb.table('kb_chunks').select('id', count='exact').eq('doc_id', doc_id).limit(1).execute()).count or 0
    if got != len(chunks):
        raise RuntimeError(f'kb_chunks 삽입 검증 실패: {len(chunks)} 중 {got}')
    # 구판 → superseded (되돌리려면 두 행의 status를 맞바꾼다)
    sb.table('kb_documents').update({'status': 'superseded', 'superseded_by': meta['new_no']}) \
        .eq('id', kb_row['id']).execute()
    return doc_id, len(chunks)


def refresh_one(sb, client, d, args):
    kb_row = load_kb_row(sb, d['path'])
    if not kb_row:
        raise ValueError('구판 kb_documents 행을 못 찾음(이미 처리됨?)')
    meta = {
        'title': retitle(kb_row['title'], kb_row.get('law_number') or '', kb_law_number(d['cur_no'])),
        'new_no': kb_law_number(d['cur_no']), 'new_enf': ymd_dash(d['cur_enf']),
        'doc_name': d['doc_name'], 'today': datetime.now(KST).strftime('%Y-%m-%d'),
    }
    new_chunks = fetch_chunks(sb, d['doc_name'], status='current')
    if not new_chunks:
        raise ValueError('새 판 조문이 비어 있음')
    w = (sb.table('law_watch').select('law_id').eq('doc_name', d['doc_name']).limit(1).execute().data or [{}])[0]
    prev_doc = find_prev_doc(sb, w.get('law_id'), d['doc_name'], d['kb_enf'])
    diff = article_diff(fetch_chunks(sb, prev_doc), new_chunks) if prev_doc else None
    old_body = kb_row.get('body_md') or ''
    prompt = build_user_prompt(kb_row, meta, old_body, new_chunks, diff)
    path = new_doc_path(kb_row['path'], meta['new_no'])
    print(f"\n■ {meta['title']}: {kb_row.get('law_number')} → {meta['new_no']}({meta['new_enf']})")
    print(f"  새 판 {len(new_chunks)}청크 · 구판 요약 {len(old_body):,}자 · 직전 판 {'있음' if prev_doc else '없음'}"
          + (f" (신설 {len(diff['added'])}·삭제 {len(diff['removed'])}·개정 {len(diff['changed'])})" if diff else ''))
    text, n_in, usage = call_model(client, prompt, dry_run=args.dry_run)
    print(f"  입력 {n_in:,} 토큰 (예상 ≈ ${n_in / 1e6 * PRICE_IN + 0.10:.2f}) → {path}")
    if args.dry_run:
        return None
    fm, body = validate_output(text, old_body, path, meta)
    doc_id, n_chunks = write_kb(sb, kb_row, fm, body, meta, path)
    cost = est_cost(usage)
    print(f"  ✓ 적재 doc_id={doc_id} 청크 {n_chunks} · 본문 {len(body):,}자 · 출력 {usage.output_tokens:,} 토큰 · ${cost:.2f}")
    return {'title': meta['title'], 'old_no': kb_row.get('law_number'), 'new_no': meta['new_no'],
            'new_enf': meta['new_enf'], 'old_len': len(old_body), 'new_len': len(body),
            'chunks': n_chunks, 'diff': diff, 'cost': cost, 'path': path}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='대상·토큰·예상 비용만(API 생성 호출 0, DB 무변경)')
    ap.add_argument('--only', help='제목 조각으로 대상 한정')
    ap.add_argument('--limit', type=int, default=DEFAULT_LIMIT, help=f'한 실행의 처리 상한(기본 {DEFAULT_LIMIT})')
    ap.add_argument('--allow-api', action='store_true', help='기본 상한을 넘겨 돌릴 때 필요')
    ap.add_argument('--no-notify', action='store_true')
    a = ap.parse_args()

    url, key = os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_KEY')
    if not (url and key and os.getenv('ANTHROPIC_API_KEY')):
        print("오류: .env에 SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY 필요")
        sys.exit(1)
    if a.limit > DEFAULT_LIMIT and not a.allow_api:
        print(f"오류: --limit {a.limit} > 기본 {DEFAULT_LIMIT} — --allow-api 필요(비용 확인 후)")
        sys.exit(1)
    sb = sb_client.make_client(url, key)
    import anthropic
    client = anthropic.Anthropic()

    drift, n_kb, n_watch = okf_drift_check.run_check(sb)
    if a.only:
        drift = [d for d in drift if a.only in d['title']]
    print(f"어긋남 {len(drift)}건 (kb {n_kb} · 감시 {n_watch}) · 상한 {a.limit} · dry-run={a.dry_run}")
    targets, deferred = drift[:a.limit], drift[a.limit:]
    done, fails, skipped = [], [], [(d['title'], '상한 초과 — 다음 실행') for d in deferred]
    for d in targets:
        try:
            r = refresh_one(sb, client, d, a)
            if r:
                done.append(r)
        except Exception as e:
            why = str(e)[:140]
            print(f"  ! 실패({d['title'][:40]}): {why}")
            (skipped if '세션 처리' in why else fails).append((d['title'], why))
        time.sleep(0.5)

    print(f"\n=== 완료 {len(done)} · 실패 {len(fails)} · 보류 {len(skipped)} ===")
    if a.dry_run:
        return
    sb_client.heartbeat(sb, 'last_okf_refresh_run',
                        f'targets={len(targets)} done={len(done)} fail={len(fails)} skip={len(skipped)}')
    if (done or fails) and not a.no_notify:
        ok = tg_notify.send_telegram(format_refresh_report(done, fails, skipped),
                                     parse_mode='HTML', disable_web_page_preview=True)
        print("  ✓ 통지" if ok else "  ! 통지 실패")
    if done:
        # 갱신 뒤의 어긋남 집합으로 서명을 갱신 — 뒤따르는 okf_drift_check --notify가 남은 것만 알린다
        try:
            rest, _, _ = okf_drift_check.run_check(sb)
            sb_client.heartbeat(sb, okf_drift_check.HEALTH_KEY,
                                f'drift={len(rest)} sig={okf_drift_check.drift_signature(rest)}')
        except Exception as e:
            print(f"  (어긋남 재대조 실패 — 다음 실행이 알림) {str(e)[:80]}")


if __name__ == '__main__':
    main()
