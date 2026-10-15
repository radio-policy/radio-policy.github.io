"""이동통신 이용약관 .doc/.docx → 조·항 번호를 되살린 업로드용 TXT + 상호참조 어긋남 목록 (#312, 2026-10-15)

왜: 사업자 약관 Word 파일은 조·항·호 번호가 모두 Word 자동 번호라서 텍스트로 뽑으면 번호가 사라진다
(pandoc·복사 모두). 조 번호가 없으면 kb_store.chunk_pdf_text가 조 경계를 못 찾고(article_no 없음),
인용 검증기는 「제N조」를 맞출 수 없다. 이 도구는 docx의 numbering.xml을 읽어 Word가 화면에 그리는
번호(제N장·제N조·①·1.)를 그대로 다시 만든다. AI·DB·네트워크 호출 0.

  py -3.12 tools_yakgwan_txt.py <약관.doc|docx> --out <폴더> [--name 파일이름앞부분] [--head 첫 줄]
  예) py -3.12 tools_yakgwan_txt.py ../약관_원문/260826_5G_agree.doc --out ../약관_원문/out
          --name SKT_5G_이용약관_20260826 --head "SK텔레콤 5G 이용약관 (ver. 2026. 8)"
      → py -3.12 upload_law_pdf.py <그 txt> "SK텔레콤 5G 이용약관(약관)(2026.8)(20260826)" 약관 --unapproved

  · **.doc을 넣을 것** — LibreOffice(soffice --headless)로 docx를 만들되(새 임시 폴더), 본문 속 상호참조(REF 필드)의
    표시 글은 원본 .doc의 저장값으로 갈아 끼운다. LibreOffice는 그 값을 자기 번호 모형으로 다시 계산해 장마다 조를
    1부터 세므로 「제 17 조」가 「제 2 조」로 바뀐다(2026-08 5G 판 18개 모두). docx만 넣으면 그 틀린 값이 남는다.
  · 조 번호는 목차(Word가 그린 값)를 따른다 — 같은 까닭으로 numbering.xml만으로는 장마다 다시 센다. 본문 조 제목이
    목차와 순서대로 같지 않으면 멈춘다. 항(①…)·호(1.)·목(가.)은 조마다 따로 정의된 목록이라 numbering.xml로 센다.
  · 출력: <name>.txt(업로드용 — 머리 한 줄 + 장·조 본문, 목차·표지·부칙 제외 — 조 머리는 「제N조(제목)」 줄 머리라
          kb_store.chunk_pdf_text가 조 경계·article_no로 쓴다)
          <name>_상호참조.md(상호참조마다 원본 표시·LibreOffice 변환값·필드가 가리키는 조 대조)
  · 본문은 첫 「제1장」부터 첫 「[부칙]」 앞까지. 부칙(시행일 기록)·별표(이 파일에 본문 없음)는 넣지 않는다
    (운영자 결정 D2 「본문만」, local_docs/이용약관_등록_판정_261014.md §6).

검사: 조 개수·제목이 목차와 같은지, 조 번호가 1부터 빈틈없이 이어지는지, 원본 .doc의 REF 필드가 docx와 같은 순서·같은
책갈피로 짝지어지는지 확인하고 어긋나면 멈춘다.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from xml.etree import ElementTree as ET

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
SOFFICE = r"C:\Program Files\LibreOffice\program\soffice.exe"

_GANADA = '가나다라마바사아자차카타파하'


def circled(n: int) -> str:
    if 1 <= n <= 20:
        return chr(0x2460 + n - 1)
    if 21 <= n <= 35:
        return chr(0x3251 + n - 21)
    if 36 <= n <= 50:
        return chr(0x32B1 + n - 36)
    return '(%d)' % n


def fmt_num(n: int, fmt: str) -> str:
    if fmt == 'decimalEnclosedCircle':
        return circled(n)
    if fmt in ('ganada', 'koreanCounting') and 1 <= n <= len(_GANADA):
        return _GANADA[n - 1]
    if fmt == 'lowerLetter':
        return chr(ord('a') + n - 1)
    if fmt == 'upperLetter':
        return chr(ord('A') + n - 1)
    if fmt == 'lowerRoman':
        return ['i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x'][n - 1] if n <= 10 else str(n)
    if fmt == 'upperRoman':
        return ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X'][n - 1] if n <= 10 else str(n)
    return str(n)   # decimal 등


def to_docx(src: str) -> tuple:
    """.doc → 새 임시 폴더의 .docx. (docx 경로, 지울 폴더)"""
    if src.lower().endswith('.docx'):
        return src, None
    tmp = tempfile.mkdtemp(prefix='yakgwan_')
    r = subprocess.run([SOFFICE, '--headless', '--convert-to', 'docx', '--outdir', tmp, src],
                       capture_output=True, text=True, timeout=300)
    out = os.path.join(tmp, os.path.splitext(os.path.basename(src))[0] + '.docx')
    if r.returncode != 0 or not os.path.exists(out):
        raise SystemExit('soffice 변환 실패 (다른 soffice가 떠 있으면 끄고 다시): %s %s' % (r.stdout, r.stderr))
    return out, tmp


class Numbering:
    """numbering.xml·styles.xml → 단락별 번호 글자. 계수기는 abstractNum 단위(Word와 같음)."""

    def __init__(self, z):
        num = ET.fromstring(z.read('word/numbering.xml'))
        sty = ET.fromstring(z.read('word/styles.xml'))
        self.levels = {}
        for a in num.findall(W + 'abstractNum'):
            lv = {}
            for l in a.findall(W + 'lvl'):
                il = int(l.get(W + 'ilvl'))
                g = lambda tag: l.find(W + tag)
                lv[il] = {
                    'fmt': g('numFmt').get(W + 'val') if g('numFmt') is not None else 'decimal',
                    'text': g('lvlText').get(W + 'val') if g('lvlText') is not None else '',
                    'start': int(g('start').get(W + 'val')) if g('start') is not None else 1,
                    'restart': int(g('lvlRestart').get(W + 'val')) if g('lvlRestart') is not None else None,
                }
            self.levels[a.get(W + 'abstractNumId')] = lv
        self.nums = {}
        for n in num.findall(W + 'num'):
            ov = {}
            for o in n.findall(W + 'lvlOverride'):
                so = o.find(W + 'startOverride')
                if so is not None:
                    ov[int(o.get(W + 'ilvl'))] = int(so.get(W + 'val'))
            self.nums[n.get(W + 'numId')] = (n.find(W + 'abstractNumId').get(W + 'val'), ov)
        self.styles = {}
        for s in sty.findall(W + 'style'):
            ppr = s.find(W + 'pPr')
            npr = ppr.find(W + 'numPr') if ppr is not None else None
            based = s.find(W + 'basedOn')
            d = {'based': based.get(W + 'val') if based is not None else None, 'num': None}
            if npr is not None:
                ni, il = npr.find(W + 'numId'), npr.find(W + 'ilvl')
                d['num'] = (ni.get(W + 'val') if ni is not None else None,
                            int(il.get(W + 'val')) if il is not None else 0)
            self.styles[s.get(W + 'styleId')] = d
        self.count = {}        # abstractNumId → {ilvl: 값}
        self.used_num = set()  # startOverride는 그 num을 처음 쓸 때 한 번

    def _style_num(self, sid):
        for _ in range(10):
            d = self.styles.get(sid)
            if not d:
                return None
            if d['num']:
                return d['num']
            sid = d['based']
        return None

    def num_of(self, p):
        """단락의 (numId, ilvl) 또는 None."""
        ppr = p.find(W + 'pPr')
        sid = numid = ilvl = None
        if ppr is not None:
            ps = ppr.find(W + 'pStyle')
            sid = ps.get(W + 'val') if ps is not None else None
            npr = ppr.find(W + 'numPr')
            if npr is not None:
                ni, il = npr.find(W + 'numId'), npr.find(W + 'ilvl')
                numid = ni.get(W + 'val') if ni is not None else None
                ilvl = int(il.get(W + 'val')) if il is not None else None
        sn = self._style_num(sid)
        if numid is None and sn:
            numid = sn[0]
        if ilvl is None:
            ilvl = sn[1] if (sn and sn[0] == numid) else 0
        if not numid or numid == '0' or numid not in self.nums:
            return None
        return numid, ilvl

    def label(self, numid, ilvl):
        """계수기를 한 칸 올리고 이 단락의 번호 글자를 돌려준다. (글자, abstractNumId, 각 단계 값)"""
        aid, ov = self.nums[numid]
        lv = self.levels[aid]
        cnt = self.count.setdefault(aid, {})
        if numid not in self.used_num:
            self.used_num.add(numid)
            for k, v in ov.items():
                cnt[k] = v - 1
        if ilvl in cnt:
            cnt[ilvl] += 1
        else:
            cnt[ilvl] = lv.get(ilvl, {}).get('start', 1)
        for k in [k for k in cnt if k > ilvl]:
            rs = lv.get(k, {}).get('restart')
            if rs is None or (rs != 0 and rs - 1 <= ilvl):   # 기본: 위 단계가 나오면 다시 시작, 0이면 이어 감
                del cnt[k]
        text = lv.get(ilvl, {}).get('text', '')

        def sub(m):
            k = int(m.group(1)) - 1
            v = cnt.get(k, lv.get(k, {}).get('start', 1))
            return fmt_num(v, lv.get(k, {}).get('fmt', 'decimal'))
        return re.sub(r'%(\d)', sub, text), aid, dict(cnt)


def doc_ref_results(doc_path: str) -> list:
    """원본 .doc(Word 97) 본문 흐름에서 REF 필드의 저장값을 순서대로 [(책갈피, 표시 글)].

    LibreOffice는 .doc → docx 변환 때 REF 필드 결과를 자기 번호 모형으로 다시 계산한다. 이 약관은
    numbering.xml에 조 단계 lvlRestart가 없어 LibreOffice가 장마다 조를 1부터 세므로, 제17조를 가리키는
    필드가 「제 2 조」로 바뀐다(5G 판 18개 중 17개). 원본 .doc의 저장값(「제 17 조」「제3장 제 10 조」)은 맞다
    — 그래서 원본 값을 꺼내 docx 쪽 결과를 갈아 끼운다. 필드 표시: 0x13 명령 0x14 결과 0x15 (UTF-16 본문)."""
    b = open(doc_path, 'rb').read()
    s = b.decode('utf-16-le', errors='replace')
    return [(m.group(1), m.group(2)) for m in
            re.finditer(r'\x13\s*REF\s+(_Ref\d+)[^\x14\x15]*\x14([^\x13\x15]*)\x15', s)]


def para_text(p, refs, cur_para, override=None):
    """단락 글자 + 이 단락 안 REF 필드(표시값·책갈피) 수집. 삭제 글(delText)·필드 명령은 넣지 않는다.
    override: 원본 .doc의 REF 저장값 목록(문서 순서) — 있으면 docx 쪽 결과 글을 그것으로 바꾼다."""
    out = []
    fld_stack = []   # [{'instr': str, 'in_result': bool, 'at': out 위치}]
    for el in p.iter():
        tag = el.tag
        if tag == W + 'fldChar':
            t = el.get(W + 'fldCharType')
            if t == 'begin':
                fld_stack.append({'instr': '', 'in_result': False, 'at': None})
            elif t == 'separate' and fld_stack:
                fld_stack[-1]['in_result'] = True
                fld_stack[-1]['at'] = len(out)
            elif t == 'end' and fld_stack:
                f = fld_stack.pop()
                m = re.match(r'\s*REF\s+(\S+)', f['instr'])
                if m:
                    at = f['at'] if f['at'] is not None else len(out)
                    shown_docx = ''.join(out[at:])
                    shown = shown_docx
                    if override is not None:
                        if not override:
                            raise SystemExit('원본 .doc의 REF 필드가 docx보다 적음 — 대응 불가')
                        bm, orig = override.pop(0)
                        if bm != m.group(1):
                            raise SystemExit('REF 순서 어긋남: docx %s / doc %s' % (m.group(1), bm))
                        del out[at:]
                        out.append(orig)
                        shown = orig
                    refs.append({'para': cur_para, 'bookmark': m.group(1), 'shown': shown,
                                 'shown_docx': shown_docx, 'pos': len(''.join(out))})
        elif tag == W + 'instrText':
            if fld_stack:
                fld_stack[-1]['instr'] += el.text or ''
        elif tag == W + 't':
            out.append(el.text or '')
        elif tag == W + 'tab':
            out.append(' ')
        elif tag in (W + 'br', W + 'cr'):
            out.append('\n')
    return ''.join(out)


def norm_space(s: str) -> str:
    s = s.replace('\u00a0', ' ').replace('\u3000', ' ')
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r' *\n *', '\n', s)
    return s.strip()


def convert(docx_path: str, override=None):
    z = zipfile.ZipFile(docx_path)
    doc = ET.fromstring(z.read('word/document.xml'))
    nb = Numbering(z)
    body = doc.find(W + 'body')
    paras = list(body.iter(W + 'p'))

    # 책갈피 → 단락 번호
    bm_para = {}
    for i, p in enumerate(paras):
        for b in p.iter(W + 'bookmarkStart'):
            bm_para[b.get(W + 'name')] = i

    toc_articles = []
    rows = []      # 단락별 {'i','kind','label','text'}
    refs = []
    ptexts = {}
    for i, p in enumerate(paras):
        ppr = p.find(W + 'pPr')
        ps = ppr.find(W + 'pStyle') if ppr is not None else None
        sid = (ps.get(W + 'val') if ps is not None else '') or ''
        text = para_text(p, refs, i, override)
        ptexts[i] = text
        if sid.lower().startswith('toc') or sid.lower().startswith('목차'):
            m = re.match(r'\s*제\s*(\d+)\s*조\s*(\(.*\))', text)
            if m:
                toc_articles.append((int(m.group(1)), re.sub(r'\s', '', m.group(2))))
            rows.append({'i': i, 'kind': 'toc', 'label': '', 'text': text})
            continue
        n = nb.num_of(p)
        label = ''
        if n:
            label, _, _ = nb.label(*n)
        kind = 'p'
        if re.fullmatch(r'제\s*\d+\s*장\s*', label):
            kind = 'chapter'
        elif re.fullmatch(r'제\s*\d+\s*조\s*', label):
            kind = 'article'
        rows.append({'i': i, 'kind': kind, 'label': label, 'text': text})

    # 본문 범위: 첫 장 머리 ~ 첫 [부칙] 앞
    start = next((k for k, r in enumerate(rows) if r['kind'] == 'chapter'), None)
    if start is None:
        raise SystemExit('장 머리(제N장)를 못 찾음 — 번호 구조가 다른 파일')
    end = next((k for k in range(start, len(rows)) if rows[k]['text'].lstrip().startswith('[부칙]')), len(rows))
    addenda = [norm_space(r['text']) for r in rows[end:] if norm_space(r['text'])]

    lines = []
    art_of_para = {}   # 단락 번호 → (조 번호, 조 제목)
    label_of_para = {}
    cur = (None, '')
    art_nos = []
    for r in rows[start:end]:
        t = norm_space(r['text'])
        lab = r['label'].replace(' ', '')
        if r['kind'] == 'chapter':
            lines.append('%s %s' % (lab, t))
        elif r['kind'] == 'article':
            # 조 번호는 목차(Word가 그린 값)를 따른다 — docx로 바뀌며 장마다 조를 다시 세는 설정이 끼어든다
            # (5G 판: numbering.xml에 lvlRestart가 없어 장이 바뀌면 1로 돌아가지만 목차·원본은 1~63 연속).
            title = t if t.startswith('(') else '(%s)' % t
            k = len(art_nos)
            if toc_articles:
                if k >= len(toc_articles) or toc_articles[k][1] != re.sub(r'\s', '', title):
                    raise SystemExit('목차와 본문 조 제목이 어긋남: %d번째 조 %s' % (k + 1, title))
                no = toc_articles[k][0]
            else:
                no = int(re.search(r'\d+', lab).group())
            art_nos.append(no)
            cur = (no, title)
            lines.append('제%d조%s' % (no, title))
        else:
            if not t and not lab:
                continue
            lines.append(('%s %s' % (r['label'].strip(), t)).strip() if lab else t)
        art_of_para[r['i']] = cur
        # 조 머리는 목차 번호로 — 상호참조 저장값이 「장 안에서 센 번호」(제17조 → 「제 2 조」)인 곳을 잡으려면
        label_of_para[r['i']] = ('제 %d 조' % cur[0]) if r['kind'] == 'article' else r['label']

    # 검사
    if toc_articles and len(art_nos) != len(toc_articles):
        raise SystemExit('조 개수가 목차와 다름: 본문 %d개 / 목차 %d개' % (len(art_nos), len(toc_articles)))
    if art_nos != list(range(1, len(art_nos) + 1)):
        raise SystemExit('조 번호가 1부터 이어지지 않음: %s' % art_nos[:10])

    # 상호참조 대조
    xrefs = []
    for f in refs:
        if f['para'] not in art_of_para:
            continue
        tgt = bm_para.get(f['bookmark'])
        tgt_label = norm_space(label_of_para.get(tgt, '')) if tgt is not None else ''
        tgt_art = art_of_para.get(tgt, (None, ''))
        where = art_of_para[f['para']]
        shown = norm_space(f['shown'])
        # 「제3장 제 10 조」처럼 장이 붙은 표시(다른 장에서 가리킬 때 Word가 붙인다)는 조 번호만 견준다
        mm = re.search(r'제\s*(\d+)\s*조\s*$', shown)
        if tgt_label.replace(' ', '').startswith('제') and mm:
            same = int(mm.group(1)) == tgt_art[0]
        else:
            same = re.sub(r'\s', '', shown) == re.sub(r'\s', '', tgt_label)
        ptxt = norm_space(ptexts[f['para']])
        ctx = ptxt[max(0, f['pos'] - 40): f['pos'] + 25]
        xrefs.append({'where': where, 'shown': shown, 'shown_docx': norm_space(f['shown_docx']),
                      'target_label': tgt_label,
                      'target_art': tgt_art, 'same': same, 'ctx': ctx})
    return lines, art_nos, xrefs, addenda


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('--out', required=True)
    ap.add_argument('--name', default=None)
    ap.add_argument('--head', default=None, help='TXT 첫 줄(문서 설명). 없으면 파일 이름')
    a = ap.parse_args()
    override = doc_ref_results(a.src) if a.src.lower().endswith('.doc') else None
    n_override = len(override) if override is not None else 0
    docx, tmp = to_docx(a.src)
    try:
        lines, arts, xrefs, addenda = convert(docx, override)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    if override:
        raise SystemExit('원본 .doc의 REF 필드 %d개가 docx에서 짝을 못 찾음' % len(override))
    os.makedirs(a.out, exist_ok=True)
    name = a.name or os.path.splitext(os.path.basename(a.src))[0]
    head = a.head or name
    txt = head + '\n' + '\n'.join(lines) + '\n'
    with open(os.path.join(a.out, name + '.txt'), 'w', encoding='utf-8', newline='\n') as fp:
        fp.write(txt)

    bad = [x for x in xrefs if not x['same']]
    lo = [x for x in xrefs if x['shown'] != x['shown_docx']]
    md = ['# %s — 본문 속 상호참조(Word REF 필드) 대조' % name, '',
          '- 원본: `%s` · 상호참조 %d개' % (os.path.basename(a.src), len(xrefs)),
          '- 업로드 TXT의 표시는 **원본 .doc의 필드 저장값**이다(%s).' % (
              '원본에서 %d개를 읽어 LibreOffice 변환값을 갈아 끼움, 그중 값이 달랐던 것 %d개' % (n_override, len(lo))
              if override is not None else 'docx 입력이라 변환값 그대로 — .doc을 넣어야 원본 값'),
          '- 표시 조 번호 ≠ 필드가 실제 가리키는 조: %d개 (원문 그대로 둠 — 아래 「같음: 아니오」)' % len(bad),
          '', '「실제 가리키는 곳」은 필드가 연결된 책갈피 단락(조 머리면 그 조). 「변환값」은 LibreOffice가 다시 계산한 값으로,',
          '장마다 조를 1부터 세어 틀린다 — 2026-10-14 대조 문서(약관_대조_261014.md §2-5)의 「저장값이 대상과 어긋남」은 이 변환값을 본 것이었다.',
          '', '| 위치(조) | 원본 표시 | 변환값(LibreOffice) | 실제 가리키는 곳 | 같음 | 앞뒤 글 |', '|---|---|---|---|---|---|']
    for x in xrefs:
        w = '제%s조%s' % x['where'] if x['where'][0] else '-'
        ta = x['target_art']
        tgt = ('제%s조%s' % ta if ta[0] else '?') + ('' if x['target_label'].replace(' ', '').startswith('제') else ' ' + x['target_label'])
        md.append('| %s | %s | %s | %s | %s | …%s… |' % (w, x['shown'], x['shown_docx'], tgt,
                                                        '예' if x['same'] else '**아니오**', x['ctx'].replace('|', '/')))
    with open(os.path.join(a.out, name + '_상호참조.md'), 'w', encoding='utf-8', newline='\n') as fp:
        fp.write('\n'.join(md) + '\n')
    print('조 %d개(제%d~%d조), 줄 %d, 글자 %d / 상호참조 %d개(원본 값으로 바꾼 것 %d) 중 표시≠대상 %d / 뺀 부칙 줄 %d'
          % (len(arts), arts[0], arts[-1], len(lines), len(txt), len(xrefs), len(lo), len(bad), len(addenda)))


if __name__ == '__main__':
    main()
