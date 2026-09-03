#!/usr/bin/env python3
"""
과방위 회의록 오프라인(무API) 백필·재요약 파이프라인

왜 무API인가 — 운영자 규칙(2026-09-03): **일회성 AI 작업은 세션에서, API 호출 금지.**
회의록 백필·재요약은 한 번 돌리고 끝나는 작업이라 유료 API(Haiku/Sonnet)를 태울 이유가 없다.
그래서 이 스크립트는 AI 판정·요약을 **직접 하지 않는다.** 파이썬은 원문 수집·키워드 선별·
파일 입출력·DB 등재만 맡고, 판정·요약은 Claude *세션*(서브에이전트)이 내보낸 JSON을 읽고
판정 JSON을 써서 되돌려 준다. 이 파일 어디에도 anthropic 클라이언트가 없다.

두 파이프라인:

A. 20·21대 상임위 회의록 신규 백필
   1) --export-candidates --year YYYY --out DIR
      회의 목록(am.fetch_meetings) → 뷰어 원문(best-of-N, PDF 폴백) → **뷰어 본문 교차 검증**
      (am.looks_foreign_committee + am.verify_blocks_against_pdf: 뷰어가 다른 회의의 본문을 돌려준 실측
      2017/41948·42378, 2018/43150 — 불일치면 PDF 블록으로 교체 src='PDF(뷰어 불일치)', PDF 도 없으면
      _index.json 에 skipped='viewer_mismatch_no_pdf') → 키워드 후보 선별(am.candidate_blocks)
      → DIR/{year}/{confer_num}.blocks.json + .cand.json 저장(meeting.verify 에 판정 기록).
      DIR/_criteria.txt(관련성 기준문, app_config 원본) + DIR/_rules.md(세션 판정 규칙) 1회 생성.
   1') --verify-exported --in DIR [--year Y] [--fix]
      이미 내보낸 blocks.json 을 PDF 와 재대조해 표로 출력 + DIR/{year}/_verify.json.
      --fix 는 불일치 회의를 PDF 블록으로 다시 쓰고(blocks/cand/_index) 그 회의의 .judged.json 을 지운다.
   2) 세션이 .cand.json 을 읽고 DIR/{year}/{confer_num}.judged.json 을 쓴다.
   3) --import-judged --in DIR
      .judged.json + .blocks.json 으로 섹션 본문·발언 행을 만들어 등재(run() 과 같은 dedupe).
      meeting.verify 가 불일치인데 src 가 'PDF…' 가 아니면(미복구) 거부한다.

B. 기존 섹션(~238건, 2016~2026) 요약·개요 재작성
   1) --export-resummary --out DIR
      DB 의 회의록 섹션을 읽어 DIR/resum/{year}/{ymd6}_{confer_num}.json 으로 내보낸다(DB 무변경).
   2) 세션이 {ymd6}_{confer_num}.judged.json 을 쓴다.
   3) --import-resummary --in DIR
      **문서 단위 재구성(doc-level rebuild)** — 실측(2026-09-03) 2024·2025·2026 문서는 섹션 헤더가
      청크 중간에 있어(105/250 섹션) 섹션 단위 drop+register 가 이웃 섹션을 지운다. 그래서 문서 전체를
      읽어 판정 JSON 이 있는 섹션만 '요약:'·'개요:' 를 갈아 끼우고(나머지는 바이트 동일), 섹션마다
      새 청크에서 시작하도록 통째로 재청크한 뒤 `{doc_name}.rebuild` 임시 이름으로 넣고 검증 → 실문서
      삭제 → 이름 교체 순으로 바꾼다. 임시 사본 검증 전에는 실문서를 절대 지우지 않는다.
      새 청크는 embedding NULL → backfill_embeddings.py 가 재임베딩(건수 출력).
      발언 행(assembly_speeches)에는 SK텔레콤 언급 칩만 소급한다(--no-refetch 로 생략).
      진행 기록: resum/_done.json(칩 완료 confer_num), resum/_rebuilt_docs.json(문서·시각·청크 수).

JSON 계약(정확한 스키마는 _rules.md 에도 같은 내용으로 적힌다):

  minutes-blocks/1     {"schema","meeting":{…fetch_meetings 필드 + viewer_id,is_audit,dae_num,comm_name,src,
                        verify:{foreign,pdf_ok,detail[,fixed,fixed_at,viewer_blocks]}},
                        "detail":{…VCONFDETAIL},"blocks":[{"name","pos","text"}…]}
  minutes-candidates/1 {"schema","meeting":{confer_num,viewer_id,title,conf_date,dgr,agenda,n_blocks,max_excerpts,src},
                        "candidates":[{"idx","name","pos","always_keep","kw":[…],"score","text"}…]}
  minutes-judged/1     {"schema","confer_num","meeting_summary","meeting_overview":[{"topic","text"}…],
                        "kept":[{"idx","summary"}…],"rejected":[idx…],"judged_by"}
  minutes-resum/1      {"schema","confer_num","doc_name","ymd6","title","year","is_audit","viewer_id",
                        "current_summary","skt_flag","agenda":[…],"excerpt"}
  minutes-resum-judged/1 {"schema","confer_num","meeting_summary","meeting_overview":[{"topic","text"}…]}

원칙: 무음 실패 금지(모든 스킵에 사유 출력), 재실행 안전(dedupe·_done.json), subscriber_notify 미사용,
어떤 큐에도 넣지 않음. DB 클라이언트는 sb_client.make_client(HTTP/1.1 강제) 로만 만든다.
"""

import os
import re
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

# Windows 스케줄러/cp949 콘솔에서 이모지·특수문자 print 크래시 방지 (배경역사 #19)
try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from sb_client import make_client
import assembly_minutes as am
from press_ingest import (
    register_kb_section, section_exists, load_press_keywords, load_press_criteria,
    _chunk_text,
)

SCHEMA_BLOCKS = 'minutes-blocks/1'
SCHEMA_CAND = 'minutes-candidates/1'
SCHEMA_JUDGED = 'minutes-judged/1'
SCHEMA_RESUM = 'minutes-resum/1'
SCHEMA_RESUM_JUDGED = 'minutes-resum-judged/1'

QA_MARK = '질의·응답:'
MIN_BODY_LEN = 200                  # 재구성 본문이 이보다 짧으면 잘못 잡은 섹션으로 보고 거부
SUMMARY_MIN_LEN = 10                # 회의 요약 채택 최소 길이(run()의 summarize_meeting 과 동일)
SPEECH_SUMMARY_MIN_LEN = 8          # 발언 요지 채택 최소 길이(is_valid_summary 기본값과 동일)

# 섹션 전체 텍스트 분해: [프리앰블]## YYMMDD 제목 \n\n 본문 \n\n (원문: url)
SECTION_RE = re.compile(
    r'\A(?P<pre>.*?)^## (?P<ymd>\d{6}) (?P<title>[^\n]*)\n\n'
    r'(?P<body>.*?)\n\n\(원문:\s*(?P<url>[^)\n]+)\)\s*\Z',
    re.S | re.M)
SUMMARY_LINE_RE = re.compile(r'(?m)^요약:\s*(.*)$')
OVERVIEW_BLOCK_RE = re.compile(r'(?ms)^개요:\n.*?(?=\n\n|\Z)')
QA_LINE_RE = re.compile(r'(?m)^질의·응답:')
VIEWER_ID_RE = re.compile(r'\(원문:\s*\S*?id=(\d+)')


# ═══════════════════════════════════════════════════════════
#  공통 유틸
# ═══════════════════════════════════════════════════════════

def _doc_name(year: int) -> str:
    return '과방위_회의록_%d.md' % year


def _doc_header(year: int) -> str:
    """run() 과 글자 단위로 같은 프리앰블 — 문서가 처음 생길 때만 앞에 붙는다."""
    return ('# 과방위 회의록 %d년\n\n'
            '> 출처: 국회 과학기술정보방송통신위원회 회의록 자동 수집 '
            '(열린국회정보 Open API + 국회회의록시스템)\n\n---\n\n' % year)


def _read_json(path: Path, default=None):
    if not path.exists():
        return default
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _year_dirs(root: Path, year: int) -> list:
    """root/{YYYY}/ 목록. --year 가 있으면 그 하나만."""
    if year:
        d = root / str(year)
        return [d] if d.is_dir() else []
    return sorted(p for p in root.iterdir() if p.is_dir() and re.fullmatch(r'\d{4}', p.name))


def _require_contract(names: list) -> None:
    """assembly_minutes 인터페이스(동시 작업 중) 미반영 시 조용히 깨지지 않게 먼저 확인."""
    missing = [n for n in names if not hasattr(am, n)]
    if missing:
        print('[중단] assembly_minutes 에 아직 없는 이름: %s — 인터페이스 반영 후 다시 실행'
              % ', '.join(missing))
        sys.exit(2)


def _ymd6(conf_date: str) -> str:
    return (conf_date or '').replace('-', '')[2:]


def _sec_prefix(m: dict) -> str:
    """run() 의 dedupe 접두와 동일: 국감은 피감기관 포함 제목, 상임위는 '제N차 '."""
    return am._section_title(m) if m.get('is_audit') else '제%s차 ' % m['dgr']


# ═══════════════════════════════════════════════════════════
#  세션 판정 규칙 (DIR/_rules.md)
# ═══════════════════════════════════════════════════════════

RULES_MD = '''# 과방위 회의록 세션 판정 규칙 (minutes_offline)

이 폴더의 JSON 은 `minutes_offline.py` 가 내보낸 것이다. 세션(서브에이전트)은 **API 를 부르지 않고**
아래 규칙대로 직접 읽고 판정·요약해 `.judged.json` 을 쓴다. 파이썬은 그 결과만 DB 에 등재한다.

## 1. 관련성 판정 (파이프라인 A — `{confer_num}.cand.json`)

- 관련성 기준은 같은 폴더의 `_criteria.txt`(app_config.press_relevance_criteria 원본) 를 따른다.
  통신·전파·주파수·5G/6G·AI·방송통신 정책, 통신사 규제·요금·망·단말·개인정보 등 기준문이 "관련"으로
  보는 내용만 채택한다.
- `always_keep: true` 후보(SK텔레콤 언급)는 **판정 없이 무조건 채택**한다 — 주제가 무관해 보여도 자료다.
- 절차·의례 발언(개의·산회 선포, 증인 선서, 인사말, 간부 소개, 사회 진행 멘트, "예/알겠습니다" 류
  맞장구)은 탈락시킨다. 정책 낱말이 스쳐 지나가도 질의·답변이 아니면 탈락이다.
- 후보 `text` 는 앞부분만 잘라 보낸 것이다(`--cand-chars`). 잘린 부분을 상상해 채우지 말고 보이는
  내용으로만 판단한다.
- `rejected` 에는 탈락한 후보의 `idx` 를 넣는다. `kept` + `rejected` 가 후보 전체를 덮어야 한다.

## 2. 발언 요지 (`kept[].summary`)

- 1~2문장, **120자 이내**, 한국어.
- 발언에서 **실제로 말한 내용·요구·질의만** 기술한다. 없는 내용을 보태지 않는다.
- 발언자의 성향·정파성·의도를 단정하는 평가어(친기업/반기업/강경/온건/옹호/편향/정치적 등) **금지**.
- 촉구/질의/지적/요청/제안/우려 표명/반대/찬성 입장 표명 같은 **행위 동사는 허용**한다.
- 머리기호·따옴표·발언자명 없이 요지 문장만 쓴다.
- 영어 메타응답("I appreciate…"), 한국어 메타응답("제공하신 회의록에는…") 은 절대 쓰지 않는다 —
  요약할 내용이 없으면 그 후보를 `rejected` 로 보낸다. (파이썬은 요지가 부적합한 파일을 통째로 거부한다.)

## 3. 회의 한 줄 요약 (`meeting_summary`)

- 통신·전파·AI 와 관련해 **무엇이 논의됐는지** 1~2문장, **130자 이내**.
- 특정 기업 관점(SK텔레콤 관점 등) 금지 — 사실만. 국회 측 질의와 정부 측 답변을 균형 있게.
- 관련 논의가 전혀 없으면 빈 문자열 `""` 로 둔다(파이썬이 규칙 요약으로 대체한다).

## 4. 회의 개요 (`meeting_overview`)

- 주제별 문단 **2~5개**, 합계 **300~600자**. 각 항목은 `{"topic": "주파수·5G", "text": "…"}`.
- `text` 는 그 주제에서 의원들이 무엇을 묻고 지적했는지 + **정부(장관·기관장) 답변**을 함께 담는다.
- SK텔레콤이 언급된 발언이 있으면 **그 문단 안에 명시**한다(예: "SK텔레콤의 … 에 대해 …").
- `topic` 은 짧은 명사구(2~12자). 평가어 금지 규칙은 여기에도 적용된다.
- 관련 논의가 없으면 빈 배열 `[]`.

## 5. 판정 JSON 스키마 — 파이프라인 A (`{confer_num}.judged.json`, .cand.json 과 같은 폴더)

```json
{"schema": "minutes-judged/1", "confer_num": "56419",
 "meeting_summary": "…", "meeting_overview": [{"topic": "…", "text": "…"}],
 "kept": [{"idx": 57, "summary": "…"}], "rejected": [12, 34], "judged_by": "session 2026-09-04"}
```

- `confer_num` 은 파일명·cand.json 과 같아야 한다(문자열).
- `idx` 는 cand.json 의 `candidates[].idx`(= blocks.json 의 블록 번호) 그대로.
- `kept` 의 모든 항목에 유효한 `summary` 가 있어야 한다. 하나라도 비면 파일 전체가 거부된다.

## 6. 판정 JSON 스키마 — 파이프라인 B (`resum/{year}/{ymd6}_{confer_num}.judged.json`)

입력 `{ymd6}_{confer_num}.json` 의 `excerpt`(기존 섹션의 질의·응답 발췌)와 `current_summary` 를 읽고,
3·4절 규칙대로 새 요약·개요를 쓴다. 발췌 자체는 바꾸지 않는다(파이썬이 요약·개요 줄만 갈아 끼운다).

```json
{"schema": "minutes-resum-judged/1", "confer_num": "audit-51996",
 "meeting_summary": "…", "meeting_overview": [{"topic": "…", "text": "…"}]}
```

- 기존 `current_summary` 가 "주요 쟁점: … (질의 N건 · 의원 M명)" 꼴 규칙 요약이면 반드시 새로 쓴다.
- `skt_flag: true` 면 개요 어딘가에 SK텔레콤 관련 내용이 들어가야 한다(요약 끝의 "(SK텔레콤 언급)" 접미는
  파이썬이 붙이므로 요약문 안에는 쓰지 않는다).
'''


# ═══════════════════════════════════════════════════════════
#  A-1. 후보 내보내기
# ═══════════════════════════════════════════════════════════

SRC_PDF_MISMATCH = 'PDF(뷰어 불일치)'   # 뷰어 본문이 다른 회의로 판정돼 PDF 로 갈아탄 원문 표시
SKIP_VIEWER_MISMATCH = 'viewer_mismatch_no_pdf'


def _verify_viewer(blocks: list, m: dict):
    """뷰어 블록 교차 검증(2026-09-03 실측: 뷰어가 다른 회의 본문을 돌려줌 — 41948·42378·43150).
    반환 (verify dict, pdf=(텍스트, 오류)). 국감·pdf_url 없음이면 PDF 대조는 None(판정 불가).
    verify = {'foreign': 타 부처명|None, 'pdf_ok': True|False|None, 'detail': str}"""
    foreign = am.looks_foreign_committee(blocks)
    pdf_url = (m.get('pdf_url') or '') if not m.get('is_audit') else ''
    if not pdf_url:
        return ({'foreign': foreign, 'pdf_ok': None,
                 'detail': '국감(검증 제외)' if m.get('is_audit') else 'pdf_url 없음'}, ('', 'pdf_url 없음'))
    pdf = am.fetch_pdf_text(pdf_url)
    ok, detail = am.verify_blocks_against_pdf(blocks, pdf_url, pdf=pdf)
    return {'foreign': foreign, 'pdf_ok': ok, 'detail': detail}, pdf



def _skt_in_body(sec_text: str) -> bool:
    """자사 언급 표시 근거 — 섹션에서 **요약 줄·개요 블록·제목 줄을 뺀 발췌 원문**에 ALWAYS_KEEP_TERMS 가 있는가.
    요약문까지 보면 "SK텔레콤이 직접 언급되지 않았습니다" 같은 옛 요약이 표시를 켠다(2026-09-03 실측 29건)."""
    s = re.sub(r'(?m)^요약: .*$', '', sec_text or '')
    s = re.sub(r'(?ms)^개요:\n.*?(?=\n\n|\Z)', '', s)
    s = re.sub(r'(?m)^## .*$', '', s)
    return any(t in s for t in am.ALWAYS_KEEP_TERMS)

def _is_mismatch(verify: dict) -> bool:
    return bool((verify or {}).get('foreign')) or (verify or {}).get('pdf_ok') is False


def _candidates_of(blocks: list, keywords: list, max_cand: int, cand_chars: int):
    """키워드 후보 목록(cand.json 의 candidates 모양). 반환 (cands, always)."""
    always, matched = am.candidate_blocks(blocks, keywords, max_cand)
    always_set = set(always)
    cands = []
    for i in sorted(set(always) | set(matched)):
        b = blocks[i]
        cands.append({
            'idx':         i,
            'name':        b['name'],
            'pos':         b.get('pos') or '',
            'always_keep': i in always_set,
            'kw':          am.matched_keywords(b['text'], keywords),
            'score':       am.relevance_score(b['text'], keywords),
            'text':        b['text'][:cand_chars],
        })
    return cands, always


def _write_meeting_files(ydir: Path, m: dict, detail: dict, blocks: list, cands: list,
                         src: str, verify: dict):
    """{cn}.blocks.json + {cn}.cand.json 저장 — 내보내기와 --verify-exported --fix 가 같은 모양을 쓴다."""
    cn = str(m['confer_num'])
    viewer_id = m.get('viewer_id') or cn
    meeting_out = dict(m)
    meeting_out['src'] = src
    meeting_out['verify'] = verify
    blocks_path = ydir / ('%s.blocks.json' % cn)
    cand_path = ydir / ('%s.cand.json' % cn)
    _write_json(blocks_path, {
        'schema': SCHEMA_BLOCKS, 'meeting': meeting_out, 'detail': detail or {},
        'blocks': [{'name': b['name'], 'pos': b.get('pos') or '', 'text': b['text']}
                   for b in blocks],
    })
    _write_json(cand_path, {
        'schema': SCHEMA_CAND,
        'meeting': {
            'confer_num': cn, 'viewer_id': str(viewer_id), 'title': m['title'],
            'conf_date': m['conf_date'], 'dgr': m.get('dgr') or '',
            'agenda': list(m.get('agenda') or []), 'n_blocks': len(blocks),
            'max_excerpts': am.AUDIT_MAX_EXCERPTS if m.get('is_audit') else am.MAX_EXCERPTS,
            'src': src,
        },
        'candidates': cands,
    })
    return blocks_path, cand_path


def export_candidates(sb, api_key: str, year: int, out_dir: str, max_cand: int,
                      cand_chars: int, limit: int, force: bool) -> dict:
    _require_contract(['fetch_meetings', 'candidate_blocks', 'fetch_speech_blocks',
                       'pdf_fallback_blocks', 'fetch_detail', 'relevance_score',
                       'matched_keywords', 'speeches_exist', 'MAX_EXCERPTS',
                       'looks_foreign_committee', 'verify_blocks_against_pdf', 'fetch_pdf_text'])
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    keywords = load_press_keywords(sb)

    crit_path = out / '_criteria.txt'
    if crit_path.exists():
        print('[기준문] %s 이미 있음 — 유지' % crit_path)
    else:
        crit_path.write_text(load_press_criteria(sb), encoding='utf-8')
        print('[기준문] %s 생성 (app_config.press_relevance_criteria)' % crit_path)
    rules_path = out / '_rules.md'
    if rules_path.exists():
        print('[규칙] %s 이미 있음 — 유지' % rules_path)
    else:
        rules_path.write_text(RULES_MD, encoding='utf-8')
        print('[규칙] %s 생성' % rules_path)

    ydir = out / str(year)
    ydir.mkdir(parents=True, exist_ok=True)
    index_path = ydir / '_index.json'
    index = {str(e['confer_num']): e for e in (_read_json(index_path, []) or [])}

    meetings = am.fetch_meetings(api_key, year)
    for m in meetings:                       # run() 과 같은 보강
        m.setdefault('viewer_id', m['confer_num'])
        m.setdefault('is_audit', False)
    print('[후보 내보내기] %d년 상임위 회의 %d건, 키워드 %d개, 후보 상한 %d, 후보 본문 %d자'
          % (year, len(meetings), len(keywords), max_cand, cand_chars))
    doc_name = _doc_name(year)
    stats = {'exported': 0, 'skip_db': 0, 'skip_file': 0, 'fail': 0, 'n_cand': 0,
             'mismatch_fixed': 0, 'mismatch_skip': 0}

    for m in meetings:
        if limit and stats['exported'] >= limit:
            print('  [상한] --limit %d 도달' % limit)
            break
        if not m.get('conf_date') or (not m.get('dgr') and not m.get('is_audit')):
            print('  [스킵·날짜/회차 없음] %s' % (m.get('title') or '')[:60])
            continue
        cn = str(m['confer_num'])
        viewer_id = m.get('viewer_id') or cn
        ymd6 = _ymd6(m['conf_date'])
        blocks_path = ydir / ('%s.blocks.json' % cn)
        cand_path = ydir / ('%s.cand.json' % cn)
        if blocks_path.exists() and cand_path.exists() and not force:
            print('  [스킵·이미 내보냄] %s %s' % (ymd6, m['title'][:50]))
            stats['skip_file'] += 1
            continue
        if not force and section_exists(sb, doc_name, ymd6, _sec_prefix(m)) \
                and am.speeches_exist(sb, cn):
            print('  [스킵·DB에 섹션+발언 모두 있음] %s %s' % (ymd6, m['title'][:50]))
            stats['skip_db'] += 1
            continue

        # 원문: 뷰어(best-of-N) → 예외·빈 결과 모두 PDF 폴백까지 간다(run() 과 동일)
        blocks, src, viewer_err = [], '뷰어', None
        try:
            blocks = am.fetch_speech_blocks(viewer_id)
        except Exception as e:
            viewer_err = str(e)[:80]
        if not blocks:
            try:
                blocks = am.pdf_fallback_blocks(m.get('pdf_url') or '')
                src = 'PDF폴백'
            except Exception as e:
                print('  [원문 실패] %s: 뷰어=%s / PDF=%s'
                      % (m['title'][:50], viewer_err or '빈결과', str(e)[:60]))
                stats['fail'] += 1
                time.sleep(1)
                continue
            if blocks and viewer_err:
                print('  [뷰어 실패→PDF 폴백] %s (%s)' % (m['title'][:44], viewer_err[:40]))
        if not blocks:
            print('  [원문 없음·스킵] %s' % m['title'][:60])
            stats['fail'] += 1
            time.sleep(1)
            continue

        # 뷰어 본문 교차 검증 — 뷰어가 다른 회의 본문을 돌려준 실측(2017/41948·42378, 2018/43150).
        # 타 상임위 직함이 보이거나 PDF 표본 대조가 불일치면 뷰어 블록을 버리고 PDF 블록으로 간다.
        verify = {'foreign': None, 'pdf_ok': None, 'detail': '뷰어 아님(검증 생략)'}
        if src == '뷰어':
            verify, pdf = _verify_viewer(blocks, m)
            if _is_mismatch(verify):
                why = ('타 상임위 직함 %s' % verify['foreign']) if verify['foreign'] else verify['detail']
                try:
                    fixed = am.pdf_fallback_blocks(m.get('pdf_url') or '', pdf_text=pdf[0])
                except Exception as e:
                    fixed = []
                    why += ' / PDF 폴백 예외 %s' % str(e)[:50]
                if not fixed:
                    print('  [!!뷰어 불일치·PDF 폴백 없음→스킵] %s %s (%s) — 잘못된 본문은 내보내지 않는다'
                          % (ymd6, m['title'][:50], why))
                    index[cn] = {
                        'confer_num': cn, 'conf_date': m['conf_date'], 'title': m['title'],
                        'n_candidates': 0, 'cand_file': '', 'skipped': SKIP_VIEWER_MISMATCH,
                        'verify': verify,
                    }
                    _write_json(index_path, sorted(index.values(),
                                                   key=lambda e: (e['conf_date'], e['confer_num'])))
                    stats['mismatch_skip'] += 1
                    time.sleep(1)
                    continue
                print('  [뷰어 불일치→PDF 폴백] %s %s (%s) 뷰어 %d블록 → PDF %d블록'
                      % (ymd6, m['title'][:44], why, len(blocks), len(fixed)))
                blocks, src = fixed, SRC_PDF_MISMATCH
                stats['mismatch_fixed'] += 1
            elif verify['pdf_ok'] is None:
                print('  [뷰어 검증 불가·뷰어 사용] %s %s (%s)' % (ymd6, m['title'][:44], verify['detail']))

        detail = am.fetch_detail(api_key, m.get('conf_id') or '') or {}
        cands, always = _candidates_of(blocks, keywords, max_cand, cand_chars)
        blocks_path, cand_path = _write_meeting_files(ydir, m, detail, blocks, cands, src, verify)
        index[cn] = {
            'confer_num': cn, 'conf_date': m['conf_date'], 'title': m['title'],
            'n_candidates': len(cands), 'cand_file': cand_path.name, 'src': src, 'verify': verify,
        }
        _write_json(index_path, sorted(index.values(),
                                       key=lambda e: (e['conf_date'], e['confer_num'])))
        print('  [내보냄] %s %s | 원문=%s 블록 %d, 후보 %d(자사 %d) → %s'
              % (ymd6, m['title'][:44], src, len(blocks), len(cands), len(always),
                 cand_path.name))
        stats['exported'] += 1
        stats['n_cand'] += len(cands)
        time.sleep(1)

    print('[후보 내보내기 완료] year=%d 내보냄=%d(후보 %d) DB중복=%d 파일중복=%d 실패=%d '
          '뷰어불일치→PDF=%d 뷰어불일치·스킵=%d → %s'
          % (year, stats['exported'], stats['n_cand'], stats['skip_db'],
             stats['skip_file'], stats['fail'], stats['mismatch_fixed'],
             stats['mismatch_skip'], ydir))
    return stats


# ═══════════════════════════════════════════════════════════
#  A-1'. 내보낸 원문 재검증 (--verify-exported)
# ═══════════════════════════════════════════════════════════

def verify_exported(sb, in_dir: str, year: int, fix: bool, max_cand: int, cand_chars: int) -> dict:
    """이미 내보낸 {year}/{cn}.blocks.json 의 블록을 PDF 와 다시 대조한다(국감 제외).
    --fix: 불일치 회의는 PDF 블록으로 blocks/cand 를 다시 쓰고, 잘못된 본문으로 만든 .judged.json 은 지운다."""
    _require_contract(['looks_foreign_committee', 'verify_blocks_against_pdf', 'fetch_pdf_text',
                       'pdf_fallback_blocks', 'candidate_blocks', 'relevance_score',
                       'matched_keywords', 'MAX_EXCERPTS', 'AUDIT_MAX_EXCERPTS'])
    root = Path(in_dir)
    if not root.is_dir():
        print('[오류] 입력 폴더 없음: %s' % root)
        return {}
    keywords = load_press_keywords(sb) if fix else []
    stats = {'checked': 0, 'ok': 0, 'mismatch': 0, 'unverifiable': 0, 'skipped': 0,
             'fixed': 0, 'fix_failed': 0, 'judged_deleted': 0}
    print('[내보낸 원문 재검증%s] %s%s' % (' --fix' if fix else '', root,
                                         (' (%d년)' % year) if year else ''))
    for d in _year_dirs(root, year):
        results = []
        index_path = d / '_index.json'
        index = {str(e['confer_num']): e for e in (_read_json(index_path, []) or [])}
        files = sorted(d.glob('*.blocks.json'), key=lambda p: p.name)
        print('  %s: blocks.json %d건' % (d.name, len(files)))
        print('  %-8s %-10s %7s %-10s %-6s %s' % ('confer', 'date', 'blocks', 'foreign', 'pdf_ok', 'detail'))
        for bpath in files:
            cn = bpath.name[:-len('.blocks.json')]
            try:
                b = _read_json(bpath)
            except Exception as e:
                print('  %-8s JSON 파싱 실패: %s' % (cn, str(e)[:60]))
                stats['skipped'] += 1
                continue
            m = b.get('meeting') or {}
            blocks = b.get('blocks') or []
            date = m.get('conf_date') or ''
            if m.get('is_audit'):
                stats['skipped'] += 1
                continue
            pdf_url = m.get('pdf_url') or ''
            if not pdf_url:
                print('  %-8s %-10s %7d %-10s %-6s %s' % (cn, date, len(blocks), '-', '-', 'pdf_url 없음·스킵'))
                stats['skipped'] += 1
                continue
            stats['checked'] += 1
            verify, pdf = _verify_viewer(blocks, m)
            mismatch = _is_mismatch(verify)
            row = {'confer_num': cn, 'conf_date': date, 'title': m.get('title') or '',
                   'n_blocks': len(blocks), 'src': m.get('src') or '', 'mismatch': mismatch,
                   'fixed': False, **verify}
            print('  %-8s %-10s %7d %-10s %-6s %s' % (
                cn, date, len(blocks), verify['foreign'] or '-',
                {True: 'ok', False: 'FAIL', None: '?'}[verify['pdf_ok']],
                verify['detail'] + (' ← 불일치' if mismatch else '')))
            if mismatch:
                stats['mismatch'] += 1
            elif verify['pdf_ok'] is None:
                stats['unverifiable'] += 1
            else:
                stats['ok'] += 1
            if mismatch and fix:
                try:
                    fixed = am.pdf_fallback_blocks(pdf_url, pdf_text=pdf[0])
                except Exception as e:
                    fixed = []
                    print('    [fix 실패] PDF 폴백 예외: %s' % str(e)[:60])
                if not fixed:
                    print('    [fix 실패] %s PDF 블록 0건 — blocks.json 그대로 둠(등재 시 거부됨)' % cn)
                    stats['fix_failed'] += 1
                else:
                    cands, always = _candidates_of(fixed, keywords, max_cand, cand_chars)
                    vfix = dict(verify)
                    vfix['fixed'] = True
                    vfix['fixed_at'] = datetime.now(am.KST).isoformat(timespec='seconds')
                    vfix['viewer_blocks'] = len(blocks)
                    _write_meeting_files(d, m, b.get('detail') or {}, fixed, cands,
                                         SRC_PDF_MISMATCH, vfix)
                    jpath = d / ('%s.judged.json' % cn)
                    if jpath.exists():
                        jpath.unlink()
                        stats['judged_deleted'] += 1
                        print('    [판정 삭제] %s — 잘못된 본문으로 판정된 파일' % jpath.name)
                    entry = index.get(cn) or {'confer_num': cn, 'conf_date': date,
                                              'title': m.get('title') or ''}
                    entry.update({'n_candidates': len(cands), 'cand_file': '%s.cand.json' % cn,
                                  'src': SRC_PDF_MISMATCH, 'verify': vfix})
                    entry.pop('skipped', None)
                    index[cn] = entry
                    row.update({'fixed': True, 'n_blocks_fixed': len(fixed), 'n_candidates': len(cands)})
                    stats['fixed'] += 1
                    print('    [fix] %s 뷰어 %d블록 → PDF %d블록, 후보 %d(자사 %d) — 재판정 필요'
                          % (cn, len(blocks), len(fixed), len(cands), len(always)))
            results.append(row)
            time.sleep(1)
        if fix and index:
            _write_json(index_path, sorted(index.values(),
                                           key=lambda e: (e.get('conf_date') or '', e['confer_num'])))
        _write_json(d / '_verify.json', {
            'checked_at': datetime.now(am.KST).isoformat(timespec='seconds'), 'fix': fix,
            'results': results,
        })
    print('[재검증 완료] checked=%d ok=%d mismatch=%d unverifiable=%d skipped=%d fixed=%d fix_failed=%d judged_deleted=%d'
          % (stats['checked'], stats['ok'], stats['mismatch'], stats['unverifiable'],
             stats['skipped'], stats['fixed'], stats['fix_failed'], stats['judged_deleted']))
    if stats['mismatch'] and not fix:
        print('  ※ 불일치 %d건 — `--verify-exported --fix` 로 PDF 원문으로 갈아끼우고 판정 파일을 지운 뒤 재판정'
              % stats['mismatch'])
    return stats


# ═══════════════════════════════════════════════════════════
#  A-2. 판정 결과 등재
# ═══════════════════════════════════════════════════════════

def _validate_judged(j: dict, b: dict, cn: str) -> list:
    """세션 판정 JSON 의 형식 오류 목록(비면 정상). 요지가 부적합한 kept 는 파일 전체 거부 —
    presummarized 에 구멍이 나면 build_speech_rows 가 API 폴백/누락으로 갈 수 있기 때문."""
    errs = []
    if j.get('schema') != SCHEMA_JUDGED:
        errs.append('schema 가 %s 아님: %r' % (SCHEMA_JUDGED, j.get('schema')))
    if str(j.get('confer_num')) != cn:
        errs.append('confer_num 불일치: 파일=%s json=%r' % (cn, j.get('confer_num')))
    if b.get('schema') != SCHEMA_BLOCKS:
        errs.append('blocks.json schema 가 %s 아님' % SCHEMA_BLOCKS)
    n = len(b.get('blocks') or [])
    kept = j.get('kept')
    if not isinstance(kept, list):
        errs.append('kept 가 배열이 아님')
        kept = []
    seen = set()
    for k in kept:
        if not isinstance(k, dict) or not isinstance(k.get('idx'), int):
            errs.append('kept 항목 형식 오류: %r' % (k,))
            continue
        i = k['idx']
        if not (0 <= i < n):
            errs.append('kept idx %d 범위 밖(0~%d)' % (i, n - 1))
        if i in seen:
            errs.append('kept idx %d 중복' % i)
        seen.add(i)
        if not am.is_valid_summary(k.get('summary') or '', SPEECH_SUMMARY_MIN_LEN):
            errs.append('kept idx %d 요지 부적합: %r' % (i, (k.get('summary') or '')[:50]))
    rej = j.get('rejected', [])
    if not isinstance(rej, list) or any(not isinstance(r, int) for r in rej):
        errs.append('rejected 가 정수 배열이 아님')
    else:
        both = seen & set(rej)
        if both:
            errs.append('kept 와 rejected 에 동시에 있는 idx: %s' % sorted(both))
    if not isinstance(j.get('meeting_summary', ''), str):
        errs.append('meeting_summary 가 문자열이 아님')
    ov = j.get('meeting_overview', [])
    if not isinstance(ov, (list, str)):
        errs.append('meeting_overview 가 배열/문자열이 아님')
    return errs


def import_judged(sb, in_dir: str, year: int, limit: int, dry: bool) -> dict:
    _require_contract(['with_context', 'cap_indices', 'skt_mentioned', 'with_skt_suffix',
                       'format_overview', 'build_section_body', 'build_speech_rows',
                       'is_valid_summary', 'rule_summary', 'clip_sentence',
                       'shell_section_range', 'drop_section', 'renumber_doc',
                       'speeches_exist', 'upsert_speeches', 'VIEWER_URL', 'DOC_CATEGORY',
                       'MAX_EXCERPTS', 'AUDIT_MAX_EXCERPTS', 'SHELL_BODY_MARK'])
    root = Path(in_dir)
    if not root.is_dir():
        print('[오류] 입력 폴더 없음: %s' % root)
        return {}
    keywords = load_press_keywords(sb)
    files = []
    for d in _year_dirs(root, year):
        files.extend(sorted(d.glob('*.judged.json')))
    print('[판정 등재%s] %s 판정 파일 %d건, 키워드 %d개'
          % (' dry-run' if dry else '', root, len(files), len(keywords)))
    stats = {'new': 0, 'dup': 0, 'sp': 0, 'invalid': 0, 'proc': 0, 'no_blocks': 0}
    renum_docs = set()

    for jpath in files:
        if limit and stats['proc'] >= limit:
            print('  [상한] --limit %d 도달' % limit)
            break
        cn = jpath.name[:-len('.judged.json')]
        bpath = jpath.with_name('%s.blocks.json' % cn)
        if not bpath.exists():
            print('  [스킵·blocks.json 없음] %s' % jpath.name)
            stats['no_blocks'] += 1
            continue
        try:
            j = _read_json(jpath)
            b = _read_json(bpath)
        except Exception as e:
            print('  [스킵·JSON 파싱 실패] %s: %s' % (jpath.name, str(e)[:80]))
            stats['invalid'] += 1
            continue
        errs = _validate_judged(j, b, cn)
        if errs:
            print('  [거부] %s' % jpath.name)
            for e in errs[:10]:
                print('      - %s' % e)
            stats['invalid'] += 1
            continue

        m = b['meeting']
        # 뷰어 본문 불일치로 표시된 회의는 PDF 로 갈아끼운(src 가 'PDF…') 경우에만 등재한다 —
        # 다른 회의의 본문으로 만든 판정을 DB 에 넣지 않기 위해(2026-09-03, --verify-exported --fix 로 복구).
        v = m.get('verify') or {}
        if _is_mismatch(v) and not (m.get('src') or '').startswith('PDF'):
            print('  [거부·뷰어 본문 불일치] %s — foreign=%s pdf_ok=%s (%s) src=%s → '
                  '`--verify-exported --fix` 후 재판정'
                  % (jpath.name, v.get('foreign'), v.get('pdf_ok'), v.get('detail'), m.get('src')))
            stats['invalid'] += 1
            continue
        detail = b.get('detail') or {}
        blocks = b['blocks']
        kept = j['kept']
        is_audit = bool(m.get('is_audit'))
        viewer_id = m.get('viewer_id') or cn
        yr = int((m.get('conf_date') or '0000')[:4]) or int(jpath.parent.name)
        doc_name = _doc_name(yr)
        ymd6 = _ymd6(m['conf_date'])
        max_exc = am.AUDIT_MAX_EXCERPTS if is_audit else am.MAX_EXCERPTS
        title = am._section_title(m)
        sec_prefix = _sec_prefix(m)

        # dedupe — run() 과 동일: 섹션/발언 독립 확인, 껍데기 섹션은 dup 아님
        sec_exists = section_exists(sb, doc_name, ymd6, sec_prefix)
        shell = am.shell_section_range(sb, doc_name, ymd6, sec_prefix) if sec_exists else None
        if shell:
            # 껍데기 범위가 정말 섹션 하나인지 확인 — 헤더가 청크 중간에 있는 문서에서는
            # section_range 가 이웃 섹션까지 한 범위로 돌려준다(실측 2026-09-03). 그 경우 지우지 않는다.
            _txt, why = _load_section_range(sb, doc_name, shell[0], shell[1])
            if _txt is None:
                print('  [껍데기 교체 보류·안전장치] %s %s — %s' % (ymd6, title[:30], why))
                shell = None            # 섹션은 '있음'으로 두고 발언 적재만 진행
            else:
                sec_exists = False
        sp_exists = am.speeches_exist(sb, cn)
        if sec_exists and sp_exists:
            print('  [중복·섹션+발언 모두 있음] %s %s' % (ymd6, title[:50]))
            stats['dup'] += 1
            continue

        confirmed = sorted({int(k['idx']) for k in kept})
        picked = am.with_context(confirmed, blocks)
        capped = am.cap_indices(picked, blocks, max_exc, keywords)
        skt_flag = am.skt_mentioned(blocks, picked)
        ms = (j.get('meeting_summary') or '').replace('\n', ' ').strip()
        if am.is_valid_summary(ms, SUMMARY_MIN_LEN):
            summary = ms
            sum_src = '세션'
        else:
            summary = am.rule_summary(m, blocks, capped, keywords)
            sum_src = '규칙 폴백'
            if ms:
                print('  [요약 부적합 — 규칙 폴백] %s' % ms[:60])
        summary = am.with_skt_suffix(am.clip_sentence(summary, 250), skt_flag)
        overview = am.format_overview(j.get('meeting_overview') or [])
        body = am.build_section_body(m, detail, blocks, picked, summary,
                                     max_excerpts=max_exc, keywords=keywords,
                                     overview=overview)
        url = am.VIEWER_URL % viewer_id
        presum = {int(k['idx']): k['summary'].strip() for k in kept}
        rows = [] if sp_exists else am.build_speech_rows(
            m, blocks, confirmed, keywords, url, dry=dry, max_excerpts=max_exc,
            presummarized=presum)

        if dry:
            speakers = sorted({r['speaker'] for r in rows})
            print('  [dry-run] ## %s %s | 블록 %d, 확정 %d, 발췌 %d, 요약=%s, 개요 %d자, %d자'
                  % (ymd6, title, len(blocks), len(confirmed), len(picked), sum_src,
                     len(overview), len(body)))
            print('  섹션: %s / 발언 행 %d건(발언자 %d명: %s)%s'
                  % ('이미 있음' if sec_exists else ('껍데기 교체' if shell else '신규'),
                     len(rows), len(speakers), ', '.join(speakers)[:120],
                     ' / 발언 이미 있음' if sp_exists else ''))
            print('  ----- 섹션 미리보기 -----')
            print('\n'.join('  | ' + ln for ln in body.split('\n')[:40]))
            print('  -------------------------')
            stats['proc'] += 1
            continue

        did_work = False
        if sec_exists:
            pass
        elif shell and am.SHELL_BODY_MARK in body:
            print('  [껍데기 유지] %s %s — 다시 만들어도 관련 발언 없음' % (ymd6, title[:40]))
            stats['dup'] += 1
        else:
            if shell:
                n_del = am.drop_section(sb, doc_name, shell[0], shell[1])
                renum_docs.add(doc_name)
                print('  [껍데기 섹션 제거] %s %s (청크 %d개, %d~%d) — 재등재'
                      % (ymd6, title, n_del, shell[0], shell[1]))
            if register_kb_section(sb, doc_name, am.DOC_CATEGORY, ymd6, title, body, url,
                                   _doc_header(yr)):
                print('  [등재] %s %s (요약=%s, 발췌 %d, 개요 %d자)'
                      % (ymd6, title, sum_src, len(picked), len(overview)))
                stats['new'] += 1
                did_work = True
            else:
                print('  [등재 안 됨·이미 있음] %s %s' % (ymd6, title[:50]))
                stats['dup'] += 1
        if not sp_exists:
            n_sp = am.upsert_speeches(sb, rows)
            if n_sp:
                print('  [발언 적재] %s 발언 %d건 (요지=세션)' % (ymd6, n_sp))
                stats['sp'] += n_sp
                did_work = True
            else:
                print('  [발언 적재 0건] %s — 행 %d건 구성됐으나 적재되지 않음'
                      % (ymd6, len(rows)))
        if did_work:
            stats['proc'] += 1

    for dn in sorted(renum_docs):
        n_fix = am.renumber_doc(sb, dn)
        if n_fix:
            print('  [결번 정리] %s 청크 %d개 재번호' % (dn, n_fix))
    print('[판정 등재 완료] new=%d dup=%d sp=%d invalid=%d no_blocks=%d proc=%d'
          % (stats['new'], stats['dup'], stats['sp'], stats['invalid'],
             stats['no_blocks'], stats['proc']))
    return stats


# ═══════════════════════════════════════════════════════════
#  B-1. 기존 섹션 내보내기 (재요약용)
# ═══════════════════════════════════════════════════════════

def _split_section(text: str):
    """섹션 전체 텍스트 → dict(pre, ymd, title, body, url). 형식이 다르면 None."""
    mm = SECTION_RE.match(text)
    if not mm:
        return None
    return {'pre': mm.group('pre'), 'ymd': mm.group('ymd'), 'title': mm.group('title'),
            'body': mm.group('body'), 'url': mm.group('url')}


def _load_section_range(sb, doc_name: str, start: int, end: int):
    """chunk_index [start, end] 를 읽어 **정확히 섹션 하나**인지 확인한 뒤 (텍스트, 사유) 반환.

    section_range() 는 "다음 섹션 헤더는 반드시 청크 맨 앞에 온다"를 전제한다. 그런데 실측
    (2026-09-03, 과방위_회의록_2026.md) 에서 헤더가 청크 **중간**에 있는 문서가 있었다 — 문서를
    통째로 재청크한 흔적. 그 문서에서 section_range 는 (0, 29) 처럼 섹션 세 개를 한 범위로 돌려주고,
    그대로 drop_section 하면 이웃 섹션까지 지워진다(2026-08-14 사고와 같은 꼴). 헤더 1개·원문 표시
    1개·첫 청크가 헤더(또는 '# ' 프리앰블)로 시작 — 셋 다 맞을 때만 텍스트를 돌려준다."""
    chunks = sb.table('document_chunks').select('chunk_index,content') \
        .eq('doc_name', doc_name).gte('chunk_index', start).lte('chunk_index', end) \
        .order('chunk_index').execute().data or []
    if not chunks:
        return None, '청크 없음'
    text = ''.join(c['content'] or '' for c in chunks)
    heads = re.findall(r'(?m)^## (\d{6}) ', text)
    n_src = len(re.findall(r'(?m)^\(원문:', text))
    first = (chunks[0]['content'] or '')
    if len(heads) != 1 or n_src != 1:
        return None, ('범위 %d~%d 에 섹션 헤더 %d개(%s)·원문표시 %d개 — 헤더가 청크 중간에 있는 문서. '
                      '문서 재청크(섹션 단위) 후 재시도' % (start, end, len(heads), ','.join(heads), n_src))
    if not (first.startswith('## ') or first.startswith('# ')):
        return None, ('청크 %d 가 헤더로 시작하지 않음: %r' % (start, first[:40]))
    return text, ''


def _confer_num_of(title: str, sec_text: str):
    """섹션 텍스트 → (viewer_id, confer_num, is_audit). 내보내기·재등재가 **같은 함수**로 키를 만든다.
    국감 섹션은 assembly_speeches 네임스페이스와 같게 'audit-' 접두. viewer id 가 없으면 confer_num=''."""
    vm = VIEWER_ID_RE.search(sec_text)
    viewer_id = vm.group(1) if vm else ''
    is_audit = title.strip().startswith('국정감사')
    if not viewer_id:
        return '', '', is_audit
    return viewer_id, (('audit-' + viewer_id) if is_audit else viewer_id), is_audit


def _agenda_lines(body: str) -> list:
    """'- 안건:' 아래 들여쓴 줄들."""
    out, on = [], False
    for ln in body.split('\n'):
        if ln.startswith('- 안건:'):
            on = True
            continue
        if on:
            if ln.startswith('  ') and ln.strip():
                out.append(ln.strip())
            else:
                break
    return out


def _parse_section_record(doc_name: str, sec_text: str, excerpt_chars: int):
    parts = _split_section(sec_text)
    if not parts:
        hm = re.match(r'## (\d{6}) ([^\n]*)', sec_text)
        if not hm:
            return None
        parts = {'pre': '', 'ymd': hm.group(1), 'title': hm.group(2),
                 'body': sec_text[hm.end():].strip(), 'url': ''}
    ymd6, title, body, url = parts['ymd'], parts['title'].strip(), parts['body'], parts['url']
    ym = re.search(r'_(\d{4})\.md$', doc_name)
    year = int(ym.group(1)) if ym else 0
    sm = SUMMARY_LINE_RE.search(body)
    current_summary = sm.group(1).strip() if sm else ''
    qa = QA_LINE_RE.search(body)
    excerpt = body[qa.end():].strip() if qa else body
    if len(excerpt) > excerpt_chars:
        excerpt = excerpt[:excerpt_chars].rstrip() + '…'
    skt_flag = _skt_in_body(sec_text)
    viewer_id, confer_num, is_audit = _confer_num_of(title, sec_text)
    return {
        'schema': SCHEMA_RESUM, 'confer_num': confer_num, 'doc_name': doc_name,
        'ymd6': ymd6, 'title': title, 'year': year, 'is_audit': is_audit,
        'viewer_id': viewer_id, 'current_summary': current_summary, 'skt_flag': skt_flag,
        'agenda': _agenda_lines(body), 'excerpt': excerpt,
    }


def export_resummary(sb, out_dir: str, year: int, limit: int, excerpt_chars: int) -> dict:
    _require_contract(['_fetch_all', 'ALWAYS_KEEP_TERMS', 'DOC_CATEGORY'])
    rdir = Path(out_dir) / 'resum'
    rdir.mkdir(parents=True, exist_ok=True)
    index_path = rdir / '_index.json'
    index = {str(e['confer_num']): e for e in (_read_json(index_path, []) or [])}

    q = sb.table('document_chunks').select('id,doc_name,chunk_index,content') \
        .eq('doc_category', am.DOC_CATEGORY)
    if year:
        q = q.eq('doc_name', _doc_name(year))
    q = q.order('doc_name').order('chunk_index')
    rows = am._fetch_all(q)
    by_doc: dict = {}
    for r in rows:
        by_doc.setdefault(r['doc_name'], []).append(r)
    print('[재요약 내보내기] 회의록 청크 %d개, 문서 %d건%s'
          % (len(rows), len(by_doc), (' (%d년)' % year) if year else ''))
    stats = {'exported': 0, 'no_id': 0, 'bad': 0}
    for doc_name in sorted(by_doc):
        chunks = sorted(by_doc[doc_name], key=lambda r: r['chunk_index'])
        text = ''.join(c['content'] or '' for c in chunks)
        parts = re.split(r'(?m)^(?=## \d{6} )', text)
        n_doc = 0
        for part in parts:
            if limit and stats['exported'] >= limit:
                break
            if not part.startswith('## '):
                continue                              # 프리앰블
            rec = _parse_section_record(doc_name, part, excerpt_chars)
            if not rec:
                stats['bad'] += 1
                print('  [형식 불명·스킵] %s: %s' % (doc_name, part[:60].replace('\n', ' ')))
                continue
            if not rec['confer_num']:
                stats['no_id'] += 1
                print('  [원문 id 없음·스킵] %s ## %s %s' % (doc_name, rec['ymd6'], rec['title'][:40]))
                continue
            fname = '%s_%s.json' % (rec['ymd6'], rec['confer_num'])
            path = rdir / str(rec['year']) / fname
            _write_json(path, rec)
            index[rec['confer_num']] = {
                'confer_num': rec['confer_num'], 'doc_name': doc_name, 'ymd6': rec['ymd6'],
                'title': rec['title'], 'year': rec['year'], 'is_audit': rec['is_audit'],
                'has_summary': bool(rec['current_summary']), 'skt_flag': rec['skt_flag'],
                'excerpt_chars': len(rec['excerpt']), 'file': '%d/%s' % (rec['year'], fname),
            }
            stats['exported'] += 1
            n_doc += 1
        print('  %s: 섹션 %d건 내보냄' % (doc_name, n_doc))
        if limit and stats['exported'] >= limit:
            print('  [상한] --limit %d 도달' % limit)
            break
    _write_json(index_path, sorted(index.values(),
                                   key=lambda e: (e['year'], e['ymd6'], e['confer_num'])))
    print('[재요약 내보내기 완료] 내보냄=%d id없음=%d 형식불명=%d → %s'
          % (stats['exported'], stats['no_id'], stats['bad'], rdir))
    return stats


# ═══════════════════════════════════════════════════════════
#  B-2. 재요약 등재
# ═══════════════════════════════════════════════════════════

def _apply_resummary(body: str, meeting_summary: str, overview_items, skt_flag: bool):
    """본문의 '요약:' 줄과 '개요:' 블록만 교체. 반환 (새 본문, 정보 dict)."""
    info = {'old_summary': '', 'new_summary': '', 'summary_replaced': False,
            'overview_len': 0, 'had_overview': False}
    sm = SUMMARY_LINE_RE.search(body)
    info['old_summary'] = sm.group(1).strip() if sm else ''
    ms = (meeting_summary or '').replace('\n', ' ').strip()
    if am.is_valid_summary(ms, SUMMARY_MIN_LEN):
        new_sum = am.with_skt_suffix(am.clip_sentence(ms, 250), skt_flag)
        line = '요약: ' + new_sum
        if sm:
            body = body[:sm.start()] + line + body[sm.end():]
        else:                                  # 요약 줄이 없던 섹션(과거 국감) — 제목 줄 뒤에 삽입
            first, _, rest = body.partition('\n')
            body = first + '\n' + line + ('\n' + rest if rest else '')
        info['new_summary'] = new_sum
        info['summary_replaced'] = True
    overview = am.format_overview(overview_items or [])
    info['overview_len'] = len(overview)
    if OVERVIEW_BLOCK_RE.search(body):
        info['had_overview'] = True
        body = OVERVIEW_BLOCK_RE.sub('', body)
    body = re.sub(r'\n{3,}', '\n\n', body).strip()
    if overview:
        qa = QA_LINE_RE.search(body)
        if qa:
            body = body[:qa.start()].rstrip('\n') + '\n\n' + overview + '\n\n' + body[qa.start():]
        else:
            body = body.rstrip('\n') + '\n\n' + overview
    return am._clean_text(body), info


def _backfill_skt_chips(sb, base: dict, dry: bool) -> int:
    """assembly_speeches.topic 에 'SK텔레콤 언급' 칩 소급. 원문을 다시 받아 chunk_seq 정렬을
    확인하고, 한 행이라도 어긋나면(뷰어가 덜 보낸 회차 등) 이 회의는 통째로 건너뛴다."""
    cn = base['confer_num']
    viewer_id = base.get('viewer_id') or ''
    if not viewer_id:
        print('    [칩 스킵] viewer_id 없음')
        return 0
    try:
        blocks = am.fetch_speech_blocks(viewer_id)
    except Exception as e:
        print('    [칩 스킵] 뷰어 실패: %s' % str(e)[:60])
        return 0
    if not blocks:
        print('    [칩 스킵] 뷰어 원문 0블록')
        return 0
    rows = am._fetch_all(sb.table('assembly_speeches').select('id,speaker,chunk_seq,topic')
                         .eq('confer_num', cn).order('chunk_seq'))
    if not rows:
        print('    [칩 스킵] assembly_speeches 행 없음 (%s)' % cn)
        return 0
    bad = []
    for r in rows:
        cs = r.get('chunk_seq')
        if not isinstance(cs, int) or cs >= len(blocks) or cs < 0:
            bad.append('%s#%s(범위 밖, 블록 %d)' % (r['speaker'], cs, len(blocks)))
        elif am.normalize_speaker(blocks[cs]['name']) != r['speaker']:
            bad.append('%s#%d≠%s' % (r['speaker'], cs, am.normalize_speaker(blocks[cs]['name'])))
    if bad:
        print('    [칩 스킵] 발언 행과 원문 블록 정렬 불일치 %d건: %s'
              % (len(bad), '; '.join(bad[:3])))
        return 0
    cands = [r for r in rows
             if am.is_always_keep(blocks[r['chunk_seq']]['text'])
             and am.SKT_CHIP not in (r.get('topic') or '')]
    if not cands:
        print('    [칩] 행 %d건 정렬 확인, 추가할 칩 없음' % len(rows))
        return 0
    if dry:
        print('    [칩 dry-run] 행 %d건 중 후보 %d건: %s'
              % (len(rows), len(cands),
                 ', '.join('%s#%d' % (r['speaker'], r['chunk_seq']) for r in cands)[:150]))
        return len(cands)
    n = 0
    for r in cands:
        topic = (r.get('topic') or '').strip()
        new_topic = (topic + ', ' if topic else '') + am.SKT_CHIP
        try:
            sb.table('assembly_speeches').update({'topic': new_topic}).eq('id', r['id']).execute()
            n += 1
        except Exception as e:
            print('    [칩 갱신 실패] id=%s: %s' % (r['id'], str(e)[:60]))
    print('    [칩] 행 %d건 중 %d건에 "%s" 추가' % (len(rows), n, am.SKT_CHIP))
    return n


# ── 문서 단위 재구성 (2026-09-03 결정) ─────────────────────────
# section_range/drop_section 은 "헤더는 청크 맨 앞" 전제인데 실측 2024·2025·2026 문서는 105/250 섹션의
# 헤더가 청크 중간에 있다. 섹션 단위로 지우고 넣으면 이웃 섹션이 유실된다(2026-08-14 사고와 같은 꼴).
# 그래서 재요약 등재는 **문서 전체를 읽어 다시 청크하는 한 가지 경로만** 둔다 — 코드 두 벌 금지.
REBUILD_SUFFIX = '.rebuild'          # 임시 사본 doc_name 접미. 검증 후 실문서 이름으로 교체
INSERT_BATCH = 200
HEADER_SPLIT_RE = re.compile(r'(?m)(?=^## \d{6} )')
HEADER_RE = re.compile(r'(?m)^## (\d{6}) ([^\n]*)')
SRC_LINE_RE = re.compile(r'(?m)^\(원문:')


def _split_doc(full: str):
    """문서 전체 텍스트 → (프리앰블, [섹션 텍스트…]). 프리앰블 = 첫 헤더 앞 텍스트(없으면 '')."""
    parts = HEADER_SPLIT_RE.split(full)
    if parts and not parts[0].startswith('## '):
        preamble, sections = parts[0], parts[1:]
    else:
        preamble, sections = '', parts
    return preamble, [s for s in sections if s]


def _doc_sanity(full: str, preamble: str, sections: list) -> list:
    """문서 분할이 정확히 '헤더 수 == 섹션 수, 섹션마다 원문 표시 1개' 인지. 오류 목록(비면 정상)."""
    errs = []
    n_heads = len(HEADER_RE.findall(full))
    if n_heads != len(sections):
        errs.append('헤더 %d개 ≠ 섹션 %d개' % (n_heads, len(sections)))
    if SRC_LINE_RE.search(preamble):
        errs.append('프리앰블에 원문 표시가 있음')
    if preamble and not preamble.startswith('# '):
        errs.append('프리앰블이 "# " 로 시작하지 않음: %r' % preamble[:40])
    for i, s in enumerate(sections):
        n_src = len(SRC_LINE_RE.findall(s))
        if n_src != 1:
            errs.append('섹션 %d(%s) 원문 표시 %d개' % (i, s[:36].replace('\n', ' '), n_src))
        if len(HEADER_RE.findall(s)) != 1:
            errs.append('섹션 %d(%s) 헤더 %d개' % (i, s[:36].replace('\n', ' '), len(HEADER_RE.findall(s))))
    if preamble + ''.join(sections) != full:
        errs.append('분할 재결합이 원문과 다름')
    return errs


def _chunk_exact(text: str) -> list:
    """press_ingest._chunk_text 와 같은 모양으로 자르되 **글자 손실 0** 을 보장한다.
    _chunk_text 는 공백뿐인 꼬리 청크를 버린다 — 섹션 꼬리 '\\n\\n' 이 빠지면 다음 섹션 헤더가
    줄 첫머리가 아니게 돼 대시보드·내보내기의 `^## ` 분할이 깨진다. 잘린 꼬리는 마지막 청크에 되붙인다."""
    pieces = _chunk_text(text)
    joined = ''.join(pieces)
    if joined == text:
        return pieces
    if text.startswith(joined) and not text[len(joined):].strip():
        tail = text[len(joined):]
        if pieces:
            pieces[-1] += tail
        else:
            pieces = [text]
        return pieces
    raise ValueError('재청크 결과가 원문과 다름 (%d자 ≠ %d자)' % (len(joined), len(text)))


def _load_resum_judged(rdir: Path, year: int):
    """resum/{year}/*.judged.json 을 읽어 {'{ymd6}_{confer_num}': {base, judged, path, used}} 로.
    형식 오류는 (파일명, 사유) 목록으로 따로 돌려준다."""
    out, invalid = {}, []
    for d in _year_dirs(rdir, year):
        for jpath in sorted(d.glob('*.judged.json')):
            stem = jpath.name[:-len('.judged.json')]
            bpath = jpath.with_name(stem + '.json')
            if not bpath.exists():
                invalid.append((jpath.name, '원본 JSON 없음'))
                continue
            try:
                base, j = _read_json(bpath), _read_json(jpath)
            except Exception as e:
                invalid.append((jpath.name, 'JSON 파싱 실패: %s' % str(e)[:60]))
                continue
            cn = str(base.get('confer_num') or '')
            if base.get('schema') != SCHEMA_RESUM or not cn:
                invalid.append((jpath.name, '원본 schema/confer_num 오류'))
                continue
            if j.get('schema') != SCHEMA_RESUM_JUDGED or str(j.get('confer_num')) != cn:
                invalid.append((jpath.name, 'schema %r / confer_num %r ≠ %s'
                                % (j.get('schema'), j.get('confer_num'), cn)))
                continue
            if not isinstance(j.get('meeting_summary', ''), str) \
                    or not isinstance(j.get('meeting_overview', []), (list, str)):
                invalid.append((jpath.name, 'meeting_summary/meeting_overview 형식 오류'))
                continue
            key = '%s_%s' % (base.get('ymd6'), cn)
            if key != stem:
                invalid.append((jpath.name, '파일명이 %s 와 다름' % key))
                continue
            out[key] = {'base': base, 'judged': j, 'path': jpath, 'used': False}
    return out, invalid


def _swap_doc(sb, doc_name: str, rows: list, new_full: str) -> bool:
    """임시 사본 삽입 → 검증 → 실문서 삭제 → 이름 교체. **임시 사본이 검증되기 전에는 실문서를 지우지 않는다.**
    실패하면 임시 사본을 남기고(다음 실행이 잔존을 감지해 멈춘다) False."""
    tmp = doc_name + REBUILD_SUFFIX
    try:
        for i in range(0, len(rows), INSERT_BATCH):
            sb.table('document_chunks').insert(rows[i:i + INSERT_BATCH]).execute()
    except Exception as e:
        print('  [중단] 임시 사본 삽입 실패: %s\n         실문서 %s 는 그대로. doc_name=%s 잔존 행을 수동 삭제 후 재실행'
              % (str(e)[:100], doc_name, tmp))
        return False
    got = am._fetch_all(sb.table('document_chunks').select('chunk_index,content')
                        .eq('doc_name', tmp).order('chunk_index'))
    idx_ok = [g['chunk_index'] for g in got] == list(range(len(rows)))
    text_ok = ''.join(g['content'] or '' for g in got) == new_full
    if len(got) != len(rows) or not idx_ok or not text_ok:
        print('  [중단] 임시 사본 검증 실패 (행 %d/%d, 번호 %s, 본문 %s) — 실문서 %s 는 그대로. '
              'doc_name=%s 행을 수동 점검·삭제 후 재실행'
              % (len(got), len(rows), '정상' if idx_ok else '불일치',
                 '일치' if text_ok else '불일치', doc_name, tmp))
        return False
    try:
        sb.table('document_chunks').delete().eq('doc_name', doc_name).execute()
    except Exception as e:
        print('  [중단] 실문서 삭제 실패: %s — 임시 사본 %s 잔존, 실문서 상태를 확인할 것' % (str(e)[:100], tmp))
        return False
    left = sb.table('document_chunks').select('id').eq('doc_name', doc_name).limit(1).execute().data
    if left:
        print('  [중단] 삭제 후에도 %s 행이 남아 있음 — 임시 사본 %s 잔존. 수동 점검' % (doc_name, tmp))
        return False
    try:
        sb.table('document_chunks').update({'doc_name': doc_name}).eq('doc_name', tmp).execute()
    except Exception as e:
        print('  [중단·긴급] 이름 교체 실패: %s\n         실문서는 삭제됐고 내용은 doc_name=%s 에 있음. 즉시 수동으로 '
              'UPDATE document_chunks SET doc_name=%r WHERE doc_name=%r' % (str(e)[:100], tmp, doc_name, tmp))
        return False
    n_final = len(am._fetch_all(sb.table('document_chunks').select('id').eq('doc_name', doc_name)))
    if n_final != len(rows):
        print('  [중단·긴급] 교체 후 %s 행 수 %d ≠ %d — 즉시 수동 점검' % (doc_name, n_final, len(rows)))
        return False
    return True


def import_resummary(sb, in_dir: str, year: int, limit: int, dry: bool,
                     no_refetch: bool, force: bool) -> dict:
    _require_contract(['format_overview', 'with_skt_suffix', 'clip_sentence', 'is_valid_summary',
                       'normalize_speaker', 'is_always_keep', 'fetch_speech_blocks',
                       '_fetch_all', '_clean_text', 'SKT_CHIP', 'ALWAYS_KEEP_TERMS',
                       'DOC_CATEGORY', 'KST'])
    rdir = Path(in_dir) / 'resum'
    if not rdir.is_dir():
        print('[오류] 입력 폴더 없음: %s' % rdir)
        return {}
    done_path, rebuilt_path = rdir / '_done.json', rdir / '_rebuilt_docs.json'
    done = [str(x) for x in (_read_json(done_path, []) or [])]
    done_set = set(done)
    rebuilt = _read_json(rebuilt_path, []) or []
    judged, invalid = _load_resum_judged(rdir, year)
    for name, why in invalid:
        print('  [판정 파일 거부] %s — %s' % (name, why))

    # 대상 문서: 판정 JSON 이 있는 문서. dry-run 에서는 연도 필터에 맞는 모든 회의록 문서를 점검한다.
    doc_names = {v['base']['doc_name'] for v in judged.values()}
    if dry:
        for r in am._fetch_all(sb.table('document_chunks').select('doc_name')
                               .eq('doc_category', am.DOC_CATEGORY).order('doc_name')):
            dn = r['doc_name'] or ''
            if dn.endswith(REBUILD_SUFFIX) or (year and dn != _doc_name(year)):
                continue
            doc_names.add(dn)
    doc_names = sorted(doc_names)
    print('[재요약 등재%s — 문서 단위 재구성] %s 판정 %d건(거부 %d), 대상 문서 %d건, 칩 완료 기록 %d건%s'
          % (' dry-run' if dry else '', rdir, len(judged), len(invalid), len(doc_names),
             len(done_set), ' (--force: 칩 완료 기록 무시)' if force else ''))
    stats = {'docs': 0, 'rebuilt': 0, 'unchanged': 0, 'refused': 0, 'sections_changed': 0,
             'invalid': len(invalid), 'chips': 0, 'reembed': 0}

    for doc_name in doc_names:
        if limit and stats['docs'] >= limit:
            print('  [상한] --limit %d 문서 도달' % limit)
            break
        stats['docs'] += 1
        tmp = doc_name + REBUILD_SUFFIX
        left = sb.table('document_chunks').select('id').eq('doc_name', tmp).limit(1).execute().data
        if left:
            print('  [중단·임시 사본 잔존] doc_name=%s 행이 있음 — 이전 실행이 검증 단계에서 멈춘 흔적. '
                  '실문서와 대조해 수동으로 삭제(또는 이름 교체)한 뒤 재실행' % tmp)
            stats['refused'] += 1
            continue
        chunks = am._fetch_all(sb.table('document_chunks').select('id,chunk_index,content')
                               .eq('doc_name', doc_name).order('chunk_index'))
        if not chunks:
            print('  [스킵·문서 없음] %s' % doc_name)
            stats['refused'] += 1
            continue
        full = ''.join(c['content'] or '' for c in chunks)
        preamble, sections = _split_doc(full)
        errs = _doc_sanity(full, preamble, sections)
        if errs:
            print('  [거부·문서 분할 이상] %s (청크 %d, %d자) — 쓰지 않음' % (doc_name, len(chunks), len(full)))
            for e in errs[:8]:
                print('      - %s' % e)
            stats['refused'] += 1
            continue

        # 섹션별: 판정 JSON 이 있으면 요약·개요만 교체, 없으면 바이트 동일
        new_sections, changed, previews, n_found = [], [], [], 0
        for sec in sections:
            hm = HEADER_RE.match(sec)
            ymd6, title = hm.group(1), hm.group(2).strip()
            _vid, cn, _aud = _confer_num_of(title, sec)
            item = judged.get('%s_%s' % (ymd6, cn)) if cn else None
            if not item:
                new_sections.append(sec)
                continue
            n_found += 1
            item['used'] = True
            base, j = item['base'], item['judged']
            parts = _split_section(sec)
            if not parts or parts['pre']:
                print('    [유지·섹션 형식 불명] %s %s' % (ymd6, title[:40]))
                new_sections.append(sec)
                continue
            if parts['title'].strip() != (base.get('title') or '').strip():
                print('    [유지·제목 불일치] DB=%r ≠ JSON=%r' % (parts['title'][:40], (base.get('title') or '')[:40]))
                new_sections.append(sec)
                continue
            if len(parts['body']) < MIN_BODY_LEN:
                print('    [유지·본문 %d자 < %d] %s %s' % (len(parts['body']), MIN_BODY_LEN, ymd6, title[:40]))
                new_sections.append(sec)
                continue
            skt_flag = _skt_in_body(sec)     # 요약·개요 줄은 빼고 발췌 원문만 본다(2026-09-03 실측: 옛 요약문의 'SK텔레콤이 언급되지 않았습니다'가 표시를 켰다)
            new_body, info = _apply_resummary(parts['body'], j.get('meeting_summary') or '',
                                              j.get('meeting_overview') or [], skt_flag)
            if not info['summary_replaced']:
                print('    [요약 유지] %s %s — 세션 요약 부적합/비어 있음: %r'
                      % (ymd6, title[:30], (j.get('meeting_summary') or '')[:50]))
            if not info['overview_len']:
                print('    [개요 없음] %s %s — meeting_overview 가 비었거나 부적합' % (ymd6, title[:30]))
            new_sec = '## %s %s\n\n%s\n\n(원문: %s)\n\n' % (ymd6, parts['title'], new_body, parts['url'])
            if new_sec == sec:
                print('    [이미 반영됨] %s %s' % (ymd6, title[:40]))
                new_sections.append(sec)
                continue
            new_sections.append(new_sec)
            changed.append((cn, base))
            if len(previews) < 3:
                previews.append((ymd6, title, info, new_body))
        new_full = preamble + ''.join(new_sections)

        # 재청크: 첫 섹션은 프리앰블과 함께, 이후 섹션은 각각 새 청크에서 시작 (register_kb_section 과 같은 모양)
        try:
            pieces = []
            for i, sec in enumerate(new_sections):
                pieces.extend(_chunk_exact((preamble + sec) if i == 0 else sec))
            if ''.join(pieces) != new_full:
                raise ValueError('청크 결합이 새 본문과 다름')
        except ValueError as e:
            print('  [거부·재청크 검증 실패] %s — %s' % (doc_name, e))
            stats['refused'] += 1
            continue
        rows = [{'doc_name': tmp, 'doc_category': am.DOC_CATEGORY, 'chunk_index': i,
                 'content': p, 'is_approved': True, 'status': 'current'}
                for i, p in enumerate(pieces)]
        print('  %s%s: 섹션 %d(판정 있음 %d, 변경 %d) | 청크 %d → %d | 프리앰블 %d자 | 분할 점검 통과'
              % ('[dry-run] ' if dry else '', doc_name, len(sections), n_found, len(changed),
                 len(chunks), len(rows), len(preamble)))
        for ymd6, title, info, new_body in previews:
            print('    ## %s %s' % (ymd6, title[:50]))
            print('       요약(구): %s' % (info['old_summary'][:120] or '(없음)'))
            print('       요약(신): %s' % (info['new_summary'][:120] if info['summary_replaced'] else '(유지)'))
            om = OVERVIEW_BLOCK_RE.search(new_body)
            print('       ' + (om.group(0).replace('\n', '\n       ') if om else '개요: (없음)'))
        if not changed:
            print('    [변경 없음] 쓰지 않음')
            stats['unchanged'] += 1
            continue
        if dry:
            print('    재임베딩 예정 청크 %d개 (backfill_embeddings.py)' % len(rows))
            if not no_refetch:
                for cn, base in changed:
                    if cn in done_set and not force:
                        print('    [칩 스킵·완료 기록] %s' % cn)
                        continue
                    stats['chips'] += _backfill_skt_chips(sb, base, dry=True)
                    time.sleep(1)
            continue

        if not _swap_doc(sb, doc_name, rows, new_full):
            stats['refused'] += 1
            print('[중단] %s 교체 실패 — 이후 문서는 처리하지 않는다. 위 안내대로 수동 점검' % doc_name)
            break
        stats['rebuilt'] += 1
        stats['sections_changed'] += len(changed)
        stats['reembed'] += len(rows)
        rebuilt.append({'doc_name': doc_name, 'at': datetime.now(am.KST).isoformat(timespec='seconds'),
                        'chunks': len(rows), 'old_chunks': len(chunks), 'sections_changed': len(changed)})
        _write_json(rebuilt_path, rebuilt)
        print('  [재구성 완료] %s 청크 %d → %d, 섹션 %d건 갱신 — 재임베딩 대상 %d개 (backfill_embeddings.py)'
              % (doc_name, len(chunks), len(rows), len(changed), len(rows)))
        if not no_refetch:
            for cn, base in changed:
                if cn in done_set and not force:
                    print('    [칩 스킵·완료 기록] %s' % cn)
                    continue
                stats['chips'] += _backfill_skt_chips(sb, base, dry=False)
                done.append(cn)
                done_set.add(cn)
                _write_json(done_path, done)
                time.sleep(1)

    unused = [v['path'].name for v in judged.values() if not v['used']]
    if unused:
        print('  [판정 파일 %d건이 어느 섹션과도 맞지 않음] %s%s'
              % (len(unused), ', '.join(unused[:5]), ' …' if len(unused) > 5 else ''))
    print('[재요약 등재 완료] docs=%d rebuilt=%d unchanged=%d refused=%d sections=%d invalid=%d chips=%d reembed=%d'
          % (stats['docs'], stats['rebuilt'], stats['unchanged'], stats['refused'],
             stats['sections_changed'], stats['invalid'], stats['chips'], stats['reembed']))
    if stats['reembed']:
        print('  ※ 새 청크 %d개는 embedding NULL — `python backfill_embeddings.py` 실행 필요' % stats['reembed'])
    return stats


# ═══════════════════════════════════════════════════════════
#  메인
# ═══════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description='과방위 회의록 오프라인(무API) 백필·재요약 — 판정·요약은 Claude 세션이 JSON 으로')
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument('--export-candidates', action='store_true',
                      help='A-1. 연도의 상임위 회의 원문·키워드 후보를 --out 폴더에 내보냄 (ASSEMBLY_API_KEY 필요)')
    mode.add_argument('--import-judged', action='store_true',
                      help='A-2. --in 폴더의 *.judged.json 을 섹션·발언으로 등재')
    mode.add_argument('--export-resummary', action='store_true',
                      help='B-1. DB 의 기존 회의록 섹션을 --out/resum 에 내보냄 (DB 무변경)')
    mode.add_argument('--import-resummary', action='store_true',
                      help='B-2. --in/resum 의 *.judged.json 으로 요약·개요 갈아끼움 + SKT 칩 소급')
    mode.add_argument('--verify-exported', action='store_true',
                      help="A-1'. --in 폴더의 blocks.json 을 PDF 와 재대조(뷰어 불일치 탐지). --fix 로 PDF 원문으로 교체")
    ap.add_argument('--fix', action='store_true',
                    help='verify-exported: 불일치 회의를 PDF 블록으로 다시 쓰고 .judged.json 삭제')
    ap.add_argument('--year', type=int, default=0, help='대상 연도 (export-candidates 필수, 나머지는 필터)')
    ap.add_argument('--out', help='내보내기 폴더')
    ap.add_argument('--in', dest='in_dir', help='가져오기 폴더')
    ap.add_argument('--limit', type=int, default=0, help='처리 상한 (0=무제한) — export/import-judged 는 회의 수, import-resummary 는 문서 수')
    ap.add_argument('--max-candidates', type=int, default=am.MAX_JUDGE_BLOCKS,
                    help='회의당 키워드 후보 상한 (기본 %d, 자사 언급은 별도)' % am.MAX_JUDGE_BLOCKS)
    ap.add_argument('--cand-chars', type=int, default=2000, help='후보 발언 본문 절단 자수 (기본 2000)')
    ap.add_argument('--excerpt-chars', type=int, default=8000,
                    help='재요약용 질의·응답 발췌 절단 자수 (기본 8000)')
    ap.add_argument('--dry-run', action='store_true', help='DB 쓰기 없이 미리보기')
    ap.add_argument('--no-refetch', action='store_true',
                    help='재요약 등재 시 원문 재수집(SKT 칩 소급) 생략')
    ap.add_argument('--force', action='store_true',
                    help='export-candidates: DB/파일 중복 무시, import-resummary: 칩 완료 기록(_done.json) 무시')
    args = ap.parse_args()

    if args.export_candidates or args.export_resummary:
        if not args.out:
            ap.error('--out 폴더가 필요합니다')
    else:
        if not args.in_dir:
            ap.error('--in 폴더가 필요합니다')
    if args.export_candidates and not args.year:
        ap.error('--export-candidates 는 --year 가 필요합니다')

    sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    t0 = datetime.now()
    if args.export_candidates:
        api_key = os.environ.get('ASSEMBLY_API_KEY', '')
        if not api_key:
            print('[오류] ASSEMBLY_API_KEY 환경변수가 없습니다.')
            sys.exit(1)
        export_candidates(sb, api_key, args.year, args.out, args.max_candidates,
                          args.cand_chars, args.limit, args.force)
    elif args.import_judged:
        import_judged(sb, args.in_dir, args.year, args.limit, args.dry_run)
    elif args.export_resummary:
        export_resummary(sb, args.out, args.year, args.limit, args.excerpt_chars)
    elif args.import_resummary:
        import_resummary(sb, args.in_dir, args.year, args.limit, args.dry_run,
                         args.no_refetch, args.force)
    elif args.verify_exported:
        verify_exported(sb, args.in_dir, args.year, args.fix, args.max_candidates, args.cand_chars)
    print('[소요] %.0f초' % (datetime.now() - t0).total_seconds())


if __name__ == '__main__':
    main()
