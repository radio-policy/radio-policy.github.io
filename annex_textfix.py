"""
법제처 API 별표 본문의 잃은 글자('?') 되찾기 (#257, 2026-09-29).

법제처 DRF가 주는 별표·별지·붙임 본문(별표내용)은 서버에서 옛 한글 코드(KS X 1001)를 거치며 그 코드에 없는
글자를 '?'로 바꿔 버린다 — 표 글머리 「‧」(U+2027)·「․」(U+2024), 흐름도 화살표 등. 「집적정보 통신시설
보호지침」 별표는 API '?' 53개 = PDF 「‧」 47 + 「․」 6이었다(2026-09-29 실측, 자문 37d2d5c3에서 발견).
같은 별표의 PDF(별표서식PDF파일링크)에는 원래 글자가 살아 있으므로, '?' 하나마다 **같은 칸 안의 앞뒤 글자**를
PDF 텍스트에서 찾아 그 사이 한 글자를 되찾는다.

규칙(틀리게 바꾸느니 '?'로 둔다):
  - 앞뒤 문맥은 같은 표 칸(줄바꿈·괘선 문자에서 끊음) 안의 글자만, 공백은 빼고 본다.
  - 긴 문맥부터 짧은 문맥 순으로 찾고, PDF에서 나온 후보 글자가 **하나로 모일 때만** 바꾼다.
  - 후보가 '?'면 진짜 물음표(시험 문항 「몇도입니까?」·주소 「?flSeq=」)라 그대로 둔다.
  - 되찾은 글자는 문장부호·기호만 받는다(한글·라틴 문자·사용자 정의 영역은 PDF 배치·글꼴 찌꺼기라 '?'로 둔다).
  - 한 글자 → 한 글자라 길이가 같다 — 조각 경계(청크)가 바뀌지 않는다.
네트워크·AI 없음(fix_lost_chars). PDF 받기·추출은 fetch_pdf_text(pdftotext, 없으면 '' → 복구 안 함).
"""

import os
import re
import shutil
import subprocess
import tempfile
import unicodedata

LAW_HOST = 'https://www.law.go.kr'

_BOX_RE = re.compile(r'[\u2500-\u257F]')   # 괘선 문자 — 표 칸 경계


def _is_boundary(ch: str) -> bool:
    return ch == '\n' or bool(_BOX_RE.match(ch))


def _context(text: str, i: int, step: int, limit: int) -> str:
    """text[i]('?')에서 step(+1 오른쪽/-1 왼쪽) 방향으로 같은 칸 안의 글자를 공백 빼고 limit자까지.
    다른 '?'(아직 모름)나 칸 경계에서 멈춘다."""
    out = []
    j = i + step
    while 0 <= j < len(text) and len(out) < limit:
        ch = text[j]
        if _is_boundary(ch) or ch == '?':
            break
        if not ch.isspace():
            out.append(ch)
        j += step
    return ''.join(out if step > 0 else reversed(out))


def _norm_pdf(pdf_text: str) -> str:
    return re.sub(r'\s+', '', _BOX_RE.sub('', pdf_text or ''))


# (왼쪽, 오른쪽) 문맥 길이 — 긴 것부터(짧은 문맥은 같은 문구가 여러 곳에 있어 후보가 갈린다 — 보호지침
# '시설보호계획및업무연속성' 12자는 두 곳, 30자면 한 곳). 합이 4자 미만인 문맥은 쓰지 않는다
_TRIES = ((30, 30), (12, 12), (0, 30), (30, 0), (8, 8), (0, 12), (12, 0), (6, 6), (4, 4), (0, 6), (6, 0), (3, 3), (2, 2))
_MIN_CTX = 4


def _candidates(pn: str, left: str, right: str):
    """pn에서 left + X + right의 X 후보 집합. 후보가 둘이 되면 더 찾지 않는다(모름). 문자열 찾기 — 정규식 전방탐색은
    PDF가 큰 문서(무선국 운용 규정 '?' 2,991개)에서 '?'마다 전체를 훑어 수 분씩 걸렸다."""
    if len(left) + len(right) < _MIN_CTX:
        return None
    found = set()
    if right:
        j = pn.find(right)
        while j >= 0 and len(found) < 2:
            x = j - 1 - len(left)
            if x >= 0 and (not left or pn[x:j - 1] == left):
                found.add(pn[j - 1])
            j = pn.find(right, j + 1)
    else:
        j = pn.find(left)
        while j >= 0 and len(found) < 2:
            k = j + len(left)
            if k < len(pn):
                found.add(pn[k])
            j = pn.find(left, j + 1)
    return found or None


def _acceptable(x: str) -> bool:
    """되찾은 글자로 받을 수 있는가 — 유니코드 문장부호(P*)·기호(S*)만. 사용자 정의 영역(Co)·문자·숫자·공백은 아니다."""
    return unicodedata.category(x)[0] in ('P', 'S')


def fix_lost_chars(api_text: str, pdf_text: str, passes: int = 3):
    """api_text의 '?'를 pdf_text에서 되찾는다 → (고친 글, 바꾼 수, 남은 '?' 수, 진짜 물음표 수).
    pdf_text가 비면 그대로 돌려준다."""
    text = api_text or ''
    if '?' not in text or not pdf_text:
        return text, 0, text.count('?'), 0
    pn = _norm_pdf(pdf_text)
    chars = list(text)
    fixed = 0
    genuine = set()
    for _ in range(passes):
        changed = False
        cur = ''.join(chars)
        for i, ch in enumerate(chars):
            if ch != '?' or i in genuine:
                continue
            for ln, rn in _TRIES:
                left = _context(cur, i, -1, ln) if ln else ''
                right = _context(cur, i, +1, rn) if rn else ''
                # 문맥이 요청 길이보다 짧게 끊겼으면(칸 경계) 있는 만큼만 — 같은 시도를 되풀이하지 않게 그대로 둔다
                cands = _candidates(pn, left, right)
                if not cands:
                    continue
                if len(cands) == 1:
                    x = next(iter(cands))
                    if x == '?':
                        genuine.add(i)
                    elif not _acceptable(x):
                        # 문장부호·기호만 받는다(KB 전수 미리보기 2026-09-29: 받은 글자 3,625개가 전부 ․ — – ‧ • ｢｣ ∙ ≦ 등).
                        # 받지 않는 것 — 한글·숫자: PDF 배치에서 옆 칸 글자가 붙어 나온다(보호지침 칸 첫머리 '?'가 옆 칸 「…계획」의 「획」이 됐다).
                        # 라틴 문자: 가운뎃점을 PDF 글꼴이 「ž」「ż」로 옮긴다(적합성평가 고시 「냉장ž냉동」 82건).
                        # 사용자 정의 영역(U+E000~F8FF): 기호 글꼴 찌꺼기라 화면에 네모로 나온다(항행안전무선시설 기준 등 93건)
                        pass
                    else:
                        chars[i] = x
                        fixed += 1
                        changed = True
                break   # 후보가 나왔으면(하나든 여럿이든) 더 짧은 문맥으로 내려가지 않는다 — 여럿이면 모름
        if not changed:
            break
    out = ''.join(chars)
    return out, fixed, out.count('?') - len(genuine), len(genuine)


def _find_pdftotext() -> str:
    """press_ingest·law_diff_gen과 같은 탐색 순서."""
    p = shutil.which('pdftotext')
    if p:
        return p
    for cand in (
        os.environ.get('PDFTOTEXT', ''),
        r'C:\Program Files\poppler\Library\bin\pdftotext.exe',
        r'C:\Program Files\poppler-24.08.0\Library\bin\pdftotext.exe',
        r'C:\tools\poppler\Library\bin\pdftotext.exe',
        r'C:\Program Files\Git\mingw64\bin\pdftotext.exe',
    ):
        if cand and os.path.exists(cand):
            return cand
    return ''


_PDFTOTEXT = None


def pdf_to_text(data: bytes) -> str:
    """pdftotext -layout(표 칸의 한 줄이 이어진 채 나온다). 실패·미설치면 ''."""
    global _PDFTOTEXT
    if _PDFTOTEXT is None:
        _PDFTOTEXT = _find_pdftotext()
    if not _PDFTOTEXT or not data:
        return ''
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix='.pdf')
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        out = subprocess.run([_PDFTOTEXT, '-enc', 'UTF-8', '-layout', tmp, '-'],
                             capture_output=True, timeout=90)
        return out.stdout.decode('utf-8', errors='replace') if out.returncode == 0 else ''
    except Exception:
        return ''
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass


def fetch_pdf_text(link: str, session=None, timeout: int = 60) -> str:
    """별표 단위의 '별표서식PDF파일링크'(/LSW/flDownload.do?flSeq=…) → PDF 텍스트. 실패면 ''."""
    if not link:
        return ''
    try:
        import requests
        get = (session or requests).get
        r = get(link if link.startswith('http') else LAW_HOST + link, timeout=timeout)
        if r.status_code != 200 or not r.content[:5].startswith(b'%PDF'):
            return ''
        return pdf_to_text(r.content)
    except Exception:
        return ''


def repair_unit_text(text: str, unit: dict, session=None):
    """별표 단위(dict) 본문의 '?'를 그 PDF로 되찾는다 → (글, 바꾼 수, 남은 수). 실패·해당 없음은 (text, 0, n)."""
    if '?' not in (text or ''):
        return text, 0, 0
    link = unit.get('별표서식PDF파일링크') if isinstance(unit, dict) else None
    pdf = fetch_pdf_text(link, session=session) if link else ''
    if not pdf:
        return text, 0, text.count('?')
    out, n, left, _genuine = fix_lost_chars(text, pdf)
    return out, n, left
