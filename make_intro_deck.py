# -*- coding: utf-8 -*-
"""사내 공유용 소개 PPT 생성 (2026-09-13).

내용의 원본은 docs/사내공유_메일_20260913.md 이고, 이 스크립트는 **그 메일과 같은 순서·같은 말**로
슬라이드를 만든다(메일 1~5항 → 본문 13장 + 부록 2장). 메일과 자료가 다른 이야기를 하면 안 된다.
시스템이 바뀌면 메일 원본 → 이 스크립트 순으로 고친다. AI 호출 없음.

실행: C:/Users/SKTelecom/AppData/Local/Programs/Python/Python312/python.exe make_intro_deck.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

W, H   = Inches(13.333), Inches(7.5)
INK    = RGBColor(0x1A, 0x1A, 0x1A)
MUTED  = RGBColor(0x5F, 0x66, 0x73)
ACCENT = RGBColor(0xEA, 0x00, 0x2C)      # SKT 레드
NAVY   = RGBColor(0x0F, 0x1B, 0x2E)
PANEL  = RGBColor(0xF4, 0xF5, 0xF7)
LINE   = RGBColor(0xDF, 0xE3, 0xE9)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
DIM    = RGBColor(0xB0, 0xB8, 0xC4)
FONT   = '맑은 고딕'

MARGIN = Inches(0.75)
BODY_W = W - 2 * MARGIN


def blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def rect(slide, x, y, w, h, fill=None, line=None, round_=True):
    shape = MSO_SHAPE.ROUNDED_RECTANGLE if round_ else MSO_SHAPE.RECTANGLE
    sh = slide.shapes.add_shape(shape, x, y, w, h)
    if round_:
        sh.adjustments[0] = 0.035
    if fill is None:
        sh.fill.background()
    else:
        sh.fill.solid(); sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line; sh.line.width = Pt(1)
    sh.shadow.inherit = False
    return sh


def bar(slide, x, y, w, h, fill):
    return rect(slide, x, y, w, h, fill, None, round_=False)


def text(slide, x, y, w, h, runs, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
         space_after=Pt(4), line_spacing=1.2):
    """runs: [(문자열, pt, 굵게, 색)] — 항목 하나가 문단 하나."""
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, (s, size, bold, color) in enumerate(runs):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = align
        para.space_after = space_after
        para.line_spacing = line_spacing
        r = para.add_run(); r.text = s
        r.font.size = Pt(size); r.font.bold = bold
        r.font.color.rgb = color; r.font.name = FONT
    return tb


def head(slide, title, sub=None, idx=None, tag=None):
    # tag: 오른쪽 위 꼬리표. 종전 '메일 N항' 표시에 썼다가 뺐다(2026-09-14) —
    # 첨부는 메일과 떨어져 혼자 돌아다니므로 읽는 사람이 무슨 말인지 알 수 없다.
    bar(slide, MARGIN, Inches(0.6), Inches(0.085), Inches(0.44), ACCENT)
    text(slide, MARGIN + Inches(0.22), Inches(0.56), Inches(9.5), Inches(0.5),
         [(title, 26, True, INK)])
    if tag:
        text(slide, W - MARGIN - Inches(3.0), Inches(0.66), Inches(3.0), Inches(0.3),
             [(tag, 11, False, DIM)], align=PP_ALIGN.RIGHT)
    if sub:
        text(slide, MARGIN + Inches(0.22), Inches(1.11), BODY_W - Inches(0.5), Inches(0.4),
             [(sub, 12.5, False, MUTED)])
    if idx is not None:
        text(slide, W - MARGIN - Inches(1.0), H - Inches(0.6), Inches(1.0), Inches(0.3),
             [(str(idx), 10, False, DIM)], align=PP_ALIGN.RIGHT)


def cards(slide, items, top, cols=3, card_h=Inches(2.0), gap=Inches(0.22),
          head_size=14.5, body_size=11.5):
    """items: [(제목, 본문)] 또는 [(번호, 제목, 본문)]"""
    cw = (BODY_W - gap * (cols - 1)) / cols
    for i, it in enumerate(items):
        row, col = divmod(i, cols)
        x = MARGIN + col * (cw + gap)
        y = top + row * (card_h + gap)
        rect(slide, x, y, cw, card_h, PANEL, LINE)
        pad = Inches(0.26)
        if len(it) == 3:
            num, title, body = it
            text(slide, x + pad, y + Inches(0.2), cw - 2 * pad, Inches(0.3),
                 [(num, 13, True, ACCENT)])
            hy = y + Inches(0.55)
        else:
            title, body = it
            hy = y + Inches(0.24)
        text(slide, x + pad, hy, cw - 2 * pad, Inches(0.4), [(title, head_size, True, INK)])
        text(slide, x + pad, hy + Inches(0.4), cw - 2 * pad, card_h - Inches(1.0),
             [(body, body_size, False, MUTED)], line_spacing=1.32)


def rows(slide, data, top, left_w=Inches(2.6), row_h=Inches(0.62),
         left_size=12, right_size=11.5):
    y = top
    for i, (a, b) in enumerate(data):
        if i % 2 == 0:
            bar(slide, MARGIN, y, BODY_W, row_h, PANEL)
        text(slide, MARGIN + Inches(0.24), y + Inches(0.13), left_w - Inches(0.32), row_h,
             [(a, left_size, True, INK)], line_spacing=1.2)
        text(slide, MARGIN + left_w, y + Inches(0.13), BODY_W - left_w - Inches(0.3), row_h,
             [(b, right_size, False, MUTED)], line_spacing=1.28)
        y += row_h
    return y


def note(slide, s, y=None):
    y = y or (H - Inches(1.02))
    bar(slide, MARGIN, y, Inches(0.05), Inches(0.4), ACCENT)
    text(slide, MARGIN + Inches(0.18), y + Inches(0.04), BODY_W - Inches(0.4), Inches(0.4),
         [(s, 11.5, False, INK)], line_spacing=1.25)


def fake_sidebar(slide, x, y, w, groups):
    """실제 사이드바를 그대로 옮겨 그린다. 캡처 대신 그리는 이유 — 화면이 바뀌면
    캡처는 낡지만 이 목록은 코드와 함께 고치면 되고, 인쇄·확대에서도 또렷하다.
    상자 높이는 항목 수에서 계산한다 — 고정값으로 두면 항목이 늘 때 밖으로 넘친다."""
    LBL, ROW, GAP, PAD = Inches(0.24), Inches(0.27), Inches(0.09), Inches(0.2)
    need = PAD * 2 + sum(LBL + ROW * len(items) + GAP for _, items in groups)
    rect(slide, x, y, w, need, RGBColor(0xFA, 0xFB, 0xFC), LINE)
    cy = y + PAD
    for label, items in groups:
        text(slide, x + Inches(0.24), cy, w - Inches(0.4), LBL,
             [(label, 9.5, True, DIM)])
        cy += LBL
        for it in items:
            text(slide, x + Inches(0.4), cy, w - Inches(0.55), ROW,
                 [(it, 11.5, False, INK)])
            cy += ROW
        cy += GAP
    return y + need


def side_cards(slide, items, x, y, w, card_h, gap=Inches(0.2)):
    """오른쪽 칼럼 전용 세로 카드 — cards()는 전폭을 써서 사이드바를 덮는다."""
    for i, (title, body) in enumerate(items):
        cy = y + i * (card_h + gap)
        rect(slide, x, cy, w, card_h, PANEL, LINE)
        pad = Inches(0.26)
        text(slide, x + pad, cy + Inches(0.2), w - 2 * pad, Inches(0.3),
             [(title, 13, True, INK)])
        text(slide, x + pad, cy + Inches(0.58), w - 2 * pad, card_h - Inches(0.75),
             [(body, 11.5, False, MUTED)], line_spacing=1.3)

def shot_slide(prs, title, sub, idx, img, caption):
    """화면 캡처 한 장을 꽉 차게 놓는다. 캡처는 tools_deck_shots.py 가 같은 구도로 다시 뜬다 —
    화면을 고치면 그 스크립트를 다시 돌릴 것(손으로 뜨면 구도·배율이 매번 달라진다)."""
    import os
    from PIL import Image
    sl = blank(prs); head(sl, title, sub, idx)
    path = os.path.join('docs', 'shots', img)
    if not os.path.exists(path):
        text(sl, MARGIN, Inches(3.0), BODY_W, Inches(0.4),
             [('(캡처 없음 — tools_deck_shots.py 를 실행하십시오)', 12, False, MUTED)])
        return sl
    iw, ih = Image.open(path).size
    top, bot = Inches(1.5), H - Inches(0.95)
    scale = min(BODY_W / iw, (bot - top) / ih)
    w, h = int(iw * scale), int(ih * scale)
    sl.shapes.add_picture(path, int(MARGIN + (BODY_W - w) / 2), int(top), width=w, height=h)
    note(sl, caption)
    return sl



# ══════════════════════════════════════════════════════════════
def build():
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H

    # ── 01 표지 ───────────────────────────────────────────────
    s = blank(prs)
    bar(s, 0, 0, W, H, NAVY)
    bar(s, MARGIN, Inches(2.5), Inches(0.5), Inches(0.07), ACCENT)
    text(s, MARGIN, Inches(2.8), Inches(11.0), Inches(1.2),
         [('전파·통신 정책 모니터링 · AI 자문 시스템', 38, True, WHITE)])
    text(s, MARGIN, Inches(3.9), Inches(11.0), Inches(0.9),
         [('법령 관계도 · 자동 수집 · 근거를 대조하는 AI 자문', 15, False, DIM)])
    text(s, MARGIN, Inches(5.85), Inches(11.0), Inches(1.0),
         [('SKT Comm.센터 기술정책팀   ·   2026. 9.', 12.5, False, RGBColor(0x7E, 0x88, 0x99)),
          ('radio-policy.gitlab.io      ·      t.me/radio_policy_law_ai_bot', 12.5, True, WHITE)],
         space_after=Pt(7))

    # ── 02 Agent 개요 (메일 1항) ──────────────────────────────
    s = blank(prs); head(s, 'Agent 개요', None, 2)
    rect(s, MARGIN, Inches(1.35), BODY_W, Inches(1.25), PANEL, LINE)
    text(s, MARGIN + Inches(0.32), Inches(1.58), BODY_W - Inches(0.64), Inches(0.9),
         [('대외 업무를 하다 보면 법률과 관련해 검토할 일이 생깁니다.', 14, True, INK),
          ('AI에 맡기면 없는 조문을 지어냅니다. 직접 찾으면 시행령·시행규칙·고시·별표로 갈래가 이어져 '
           '어디까지 봐야 다 본 것인지 알 수 없고, 빠뜨려도 빠뜨린 줄 모릅니다. '
           '이 두 가지를 풀려고 만들었습니다.', 12.5, False, MUTED)],
         space_after=Pt(6), line_spacing=1.3)
    cards(s, [
        ('01', '법령 관계도',
         '법률에서 시행령·시행규칙·고시·별표로 이어지는 위임 관계와 조문 사이 인용 관계를 '
         '자동으로 추출해 지도로 보여 줍니다.'),
        ('02', '자동 수집',
         '정부 보도자료, 국내외 규제기관 동향, 국회 회의록과 법안, 정책 뉴스를 매일 모으고, '
         '법령이 개정되면 바뀐 조문을 비교해 알려 줍니다.'),
        ('03', 'AI 자문',
         '관련 법령·고시 원문에서 근거를 찾아 답하고, 인용한 조문이 원문과 맞는지 기계가 대조해 '
         '[원문 확인됨]을 붙입니다.'),
    ], Inches(2.95), cols=3, card_h=Inches(2.15))
    note(s, '설치할 것이 없습니다 — 웹 주소와 텔레그램 링크가 전부입니다.')

    # ── 03 법령 관계도 ────────────────────────────────────────
    s = blank(prs); head(s, '① 법령 관계도', '조문 하나가 어디에 물려 있는지 지도로 봅니다', 3)
    rows(s, [
        ('무엇이 문제였나',
         '전파법 조문 하나를 확인하려면 시행령 → 시행규칙 → 고시 → 별표까지 타고 내려가야 하고,\n'
         '어디까지 봐야 다 본 것인지 알 수 없습니다'),
        ('위임 관계',
         '법제처 3단비교 정본에서 법률↔시행령·시행규칙 조문 대응을 가져오고,\n'
         '고시는 제1조(목적)에 적힌 근거 법령을 거꾸로 짚어 상위 법령에 잇습니다'),
        ('인용 관계',
         '조문이 다른 조문을 인용한 선을 그려, 벌칙·검사 조항처럼 검색어로는 닿지 않는 곳까지 보여 줍니다'),
        ('주제별 보기',
         '「주파수 재할당」을 고르면 전파법 → 시행령 → 시행규칙 → 「주파수할당대가의 산정 및 부과에 관한\n'
         '세부사항」 고시까지, 그 주제에 걸린 것만 모아 봅니다.' + chr(10) +
         '조문 단위로도 펼쳐 볼 수 있고, 지도에서 법령을 누르면 그 조문 원문이 열립니다'),
    ], Inches(1.9), left_w=Inches(2.5), row_h=Inches(1.02))
    note(s, 'AI가 새로 제안한 연결은 바로 반영하지 않고, 운영자가 원문을 확인해 승인한 것만 지도에 올립니다.')

    # ── 04 법령 관계도 화면 ───────────────────────────────────
    shot_slide(prs, '① 법령 관계도 — 실제 화면', '주제 「주파수 재할당」을 고른 모습', 4, 'lawmap.png',
               '전파법을 가운데 두고 시행령·시행규칙·고시가 어떻게 물려 있는지 한눈에 보입니다 — 선 굵기는 근거 조문 수, 노드를 누르면 원문으로 갑니다.')

    # ── 05 자동 수집 ──────────────────────────────────────────
    s = blank(prs); head(s, '② 자동 수집', '시스템이 모으고 만드는 시각입니다 — 받아 보는 시각은 따로 고르실 수 있습니다', 6)
    cards(s, [
        ('매시간', '정책 뉴스 수집 →\n관련성 판정 → 중요도 분류'),
        ('06:00', '모닝 브리핑 생성\n(어제~오늘 핵심 + 업무 영향)'),
        ('10:00', '국회 법안·입법예고 수집\n(발의·처리 단계 추적)'),
        ('11:00', '법령·고시 개정 감지\n(현행·시행예정 변경)'),
        ('17:00', '부처 입법예고·정부 공고,\n법령 신·구 대조,\n과방위 회의록 등재·요약'),
    ], Inches(1.9), cols=5, card_h=Inches(1.6), head_size=14, body_size=10.5)
    text(s, MARGIN, Inches(3.62), BODY_W, Inches(0.35), [('어디에서 모으나', 13.5, True, INK)])
    rows(s, [
        ('정부', '과학기술정보통신부 · 국립전파연구원 · 중앙전파관리소 · 방송미디어통신위원회 · ETRI · KISDI'),
        ('법령 · 국회', '법제처 국가법령정보 · 열린국회정보(법안·국회 입법예고) · 국민참여입법센터(부처 입법예고) · 국회 회의록시스템'),
        ('해외 규제기관', 'FCC(미국) · Ofcom(영국) · BEREC(EU) · 총무성(일본) · ITU — 매일 05:30'),
        ('뉴스', '네이버 검색 API(1순위) · Google 뉴스 RSS(차단 시 대체) · 선별된 기사는 언론사 원문에서 본문 수집 (키워드는 부록 A)'),
    ], Inches(4.05), left_w=Inches(2.3), row_h=Inches(0.58), left_size=11.5, right_size=11)
    # ⚠️ '실행이 이중화돼 있다'고 쓰지 말 것 — 주(pg_cron 디스패치)·보조(GitHub schedule) 둘 다
    # 종착지가 GitHub Actions라 같은 고장 영역이다(2026-08-01 계정 정지 때 함께 멈췄다).
    # 진짜 이중화는 감시 쪽이다 — GitHub 워치독(Supabase 독립)과 Supabase 워치독이 서로를 덮는다.
    note(s, '수집이 조용히 멈추는 일이 없도록, 멈추면 운영자에게 자동으로 경보가 갑니다.')

    # ── 05 AI 자문 ────────────────────────────────────────────
    s = blank(prs); head(s, '③ AI 자문', '답보다 근거가 먼저입니다', 7)
    cards(s, [
        ('근거를 찾아 답합니다',
         '질문에 맞는 법령·고시 조문, 정부 보도자료, 수집한 뉴스를 함께 찾아 근거로 삼습니다.\n\n'
         '조문이 구체적인 수치·기준을 별표에 맡겨 두었으면, 그 별표까지 함께 읽어 옵니다.'),
        ('붙인 표시를 따로 검사합니다',
         '표시는 답을 쓴 AI가 붙이지만, 시스템이 그대로 내보내지 않습니다.\n\n'
         '답변이 끝난 뒤 검증 단계가 따로 돌아, 인용한 법령명·조·항·호를 하나씩 떼어 내 그 원문이 '
         '검색 결과에 실제로 있었는지 대조하고, 있었다면 원문과 답변 문장이 어긋나지 않는지 '
         '다른 AI가 한 번 더 봅니다. 검사에 걸리면 표시가 경고로 바뀝니다.'),
    ], Inches(1.95), cols=2, card_h=Inches(2.05), head_size=16)
    text(s, MARGIN, Inches(4.12), BODY_W, Inches(0.3),
         [('답변에 붙는 표시는 네 가지입니다', 13, True, INK)])
    rows(s, [
        ('[원문 확인됨: 전파법 제21조]', '인용한 조문이 실제로 있고, 설명도 원문과 어긋나지 않습니다'),
        ('[학습 데이터 기반 — 원문 확인 권장]', '검색 결과에 없어 AI가 기억으로 쓴 부분입니다 — 원문을 꼭 확인하십시오'),
        ('[⚠️ 원문 미확인 — 검색 결과에 해당 조문 없음]', '인용한 조문을 찾지 못했습니다 — 그대로 믿지 마십시오'),
        ('[⚠️ 원문과 다르게 설명됨 — 확인 필요]', '조문은 있으나 원문과 다르게 옮겼습니다'),
    ], Inches(4.5), left_w=Inches(4.3), row_h=Inches(0.48), left_size=11, right_size=10.5)
    note(s, '[원문 확인됨]은 인용이 맞다는 뜻이지 결론이 맞다는 보증은 아닙니다 — 대외로 나가는 문서는 원문을 한 번 더 확인하십시오.')

    # ── 06 대시보드 지도 (메일 2항) ───────────────────────────
    s = blank(prs); head(s, '대시보드 — 열람은 로그인 없이',
                         'radio-policy.gitlab.io  ·  PC와 휴대폰 모두 지원', 6)
    rows(s, [
        ('법령', '법령·고시 원문을 조문 단위로 검색 · 법령 관계도 · 개정 시 바뀐 조문 자동 비교 · 법적·기술 용어'),
        ('모니터링', '정책 뉴스(중요도 자동 분류, 60일 보관) · 매일 아침 브리핑 · 정부·해외 규제기관 공지와 보도자료'),
        ('이슈맵', 'AI가 중요한 흐름을 이슈로 제안하고, 운영자가 승인하면 관련 뉴스·보도자료·법령·이해관계자를 연대기로 정리'),
        ('국회', '법안 발의·처리 경과와 입법예고 · 과방위 회의록(2016년 20대 국회부터) · 인물 243명의 발언 이력과 쟁점별 입장 요약'),
        ('AI 자문', '질문을 입력하면 근거 조문과 함께 답변이 나옵니다 — AI가 그 자리에서 새로 만드는 기능은 로그인·승인이 필요합니다'),
    ], Inches(1.95), left_w=Inches(2.0), row_h=Inches(0.85), left_size=13.5)
    note(s, '쌓여 있는 것을 읽는 일은 전부 로그인 없이 됩니다 — 로그인은 AI가 그 자리에서 답·요약을 새로 만들 때만 필요합니다.')

    # ── 07 메뉴 지도 ──────────────────────────────────────────
    s = blank(prs); head(s, '어디를 누르면 무엇이 나오나',
                         '왼쪽이 실제 사이드바입니다 — 대부분은 이름이 곧 설명입니다', 7)
    fake_sidebar(s, MARGIN, Inches(1.72), Inches(3.0), [
        ('모니터링', ['통합 모니터링', '이슈맵', 'Daily Briefing', '법적·기술 용어']),
        ('AI 도우미', ['AI 자문', '법령 관계도']),
        ('법안 동향', ['국회 법안', '과방위 회의록', '인물', '법령 개정 추적']),
        ('지식베이스', ['지식베이스']),
    ])
    RX = MARGIN + Inches(3.3)
    RW = W - RX - MARGIN
    text(s, RX, Inches(1.72), RW, Inches(0.3),
         [('처음 오시면 여기서 헷갈립니다 — 세 가지만 짚어 드립니다', 13.5, True, INK)])
    side_cards(s, [
        ('정부 보도자료 · 해외 동향은 사이드바에 없습니다',
         '「통합 모니터링」을 누른 뒤 화면 위쪽 탭에서 고르십시오. '
         '과기정통부·전파연구원·방미통위 공고와 FCC·Ofcom·ITU 동향이 거기 있습니다.'),
        ('회의록에서 발언을 찾으려면 맨 위 검색창',
         '「과방위 회의록」을 열면 첫 화면 맨 위에 검색창이 있습니다. 거기에 말하듯 쓰면 됩니다 — '
         '아래 목록은 회의를 둘러볼 때 씁니다.'),
        ('법령 관계도는 로그인 없이 열립니다',
         '「AI 도우미」 묶음에 있어 승인이 필요해 보이지만 그냥 열립니다. '
         '관계도를 새로 만드는 것만 관리자 몫이고, 보는 것은 누구나 됩니다.'),
    ], RX, Inches(2.18), RW, Inches(1.26), gap=Inches(0.17))
    note(s, '국회 법안·인물·용어는 눌러 보시면 바로 아실 수 있습니다.')

    # ── 08 법령 탭 ────────────────────────────────────────────
    s = blank(prs); head(s, '대시보드 ① 법령', '원문이 정답인 자리에는 AI 해설을 붙이지 않습니다', 10)
    rows(s, [
        ('조문 검색', '지식베이스에서 법령·고시를 찾아 열면 전체 조문이 나오고, 그 안에서 조문을 검색합니다.\n'
                      '문서 가로질러 조문을 한 번에 찾는 것은 AI 자문과 텔레그램 /law가 맡습니다'),
        ('개정 비교', '법이 바뀌면 어느 조문이 어떻게 바뀌었는지 신·구 대조로 보여 줍니다.\n'
                      '시행예정 법령도 미리 비교해 둡니다'),
        ('법적 용어', '조문에 정의된 용어를 원문 그대로 보여 줍니다. '
                      '출처(법령명·조·호·시행일)도 함께 붙습니다'),
        ('기술 용어', '뉴스에서 새 기술 용어를 자동으로 뽑아 풀이합니다'),
    ], Inches(1.9), left_w=Inches(2.2), row_h=Inches(1.0))

    # ── 09 모니터링 탭 ────────────────────────────────────────
    s = blank(prs); head(s, '대시보드 ② 모니터링', '매시간 모으고, 아침에 한 통으로 정리합니다', 12)
    rows(s, [
        ('정책 뉴스', '중요도 3단계 자동 분류 — 🔴 중요 / 🟡 보통 / 🟢 참고.\n'
                      '60일간 보관하고, 운영자가 표시해 둔 기사는 그 뒤에도 남습니다'),
        ('모닝 브리핑', '매일 06:00 발송. 어제~오늘 핵심 + 업무 영향 분석 + 새로 나온 용어 풀이.\n'
                        '지난 브리핑이 날짜별로 전부 남아 있어 되짚어 볼 수 있습니다'),
        ('정부 공지', '과기정통부 · 국립전파연구원 · 중앙전파관리소 · 방미통위(구 방통위) · ETRI · KISDI의 공고와 보도자료'),
        ('해외 동향', 'FCC·Ofcom·BEREC·일본 총무성·ITU의 규제 동향'),
    ], Inches(1.9), left_w=Inches(2.2), row_h=Inches(1.0))
    # 장 번호로 가리키지 말 것 — 장을 하나 끼워 넣으면 번호가 밀려 엉뚱한 곳을 가리킨다
    # (실제로 7장을 넣은 뒤 이 줄이 텔레그램 장을 가리키고 있었다). 제목으로 가리킨다.
    note(s, '무엇을 중요하게 볼지는 팀마다 다릅니다 — 「다른 팀에서 쓰시려면」 장에 적었습니다.')

    # ── 11 통합 모니터링 화면 ─────────────────────────────────
    shot_slide(prs, '통합 모니터링 — 실제 화면', '수집한 정책 뉴스가 등급별로 쌓입니다', 11, 'monitor.png',
               '화면 위쪽 탭에서 정부 보도자료·공지와 해외 규제동향으로 건너갑니다 — 사이드바에는 없는 화면입니다.')

    # ── 12 이슈맵 탭 ──────────────────────────────────────────
    s = blank(prs); head(s, '대시보드 ③ 이슈맵', '흩어진 자료를 하나의 흐름으로 묶습니다', 13)
    cards(s, [
        ('1. AI가 제안합니다',
         '쌓인 뉴스·보도자료에서 "이건 하나의 흐름 같다"는 것을 이슈로 제안합니다.'),
        ('2. 운영자가 승인합니다',
         '제안을 그대로 쓰지 않습니다. 운영자가 확인해 승인한 것만 이슈가 됩니다.'),
        ('3. 연대기로 정리됩니다',
         '시간 순으로 한 화면에 모입니다.'),
    ], Inches(1.95), cols=3, card_h=Inches(1.95), head_size=14.5)
    text(s, MARGIN, Inches(3.98), BODY_W, Inches(0.3),
         [('하나의 이슈에 모이는 것', 13, True, INK)])
    rows(s, [
        ('정부 보도자료 · 공고', '그 사안을 소관 부처가 어떻게 발표했는지'),
        ('정책 뉴스', '언제 무엇이 보도됐는지, 시간 순으로'),
        ('법령', '그 사안에 걸린 조문과 고시'),
        ('이해관계자', '누가 어느 자리에서 무슨 말을 했는지'),
    ], Inches(4.35), left_w=Inches(2.8), row_h=Inches(0.5), left_size=11.5, right_size=11)
    note(s, '"그 건 어떻게 흘러왔더라"를 다시 찾지 않으려고 만든 자리입니다.')

    # ── 11 국회 탭 ────────────────────────────────────────────
    s = blank(prs); head(s, '대시보드 ④ 국회', '법안·회의록을 사람 축으로도 봅니다', 14)
    rows(s, [
        ('법안', '발의 → 소관위 회부 → 상정 → 위원회 의결 → 법사위 → 본회의.\n'
                 '위원회를 통과하거나 폐기되면 구독자에게 알립니다(중간 단계는 대시보드에서 봅니다)'),
        ('입법예고', '국회·부처 입법예고를 모아 의견 마감일과 남은 일수(D-n)를 배지로 표시합니다.'
                    ' 신·구 조문 대비표가 붙은 개정안은 조문을 나란히 갈라 보여 줍니다'),
        ('과방위 회의록', '국회 과학기술정보방송통신위원회(과방위) 상임위·국정감사 전문, 2016년 20대 국회부터.\n'
                          '첫 화면 맨 위 검색창에 말하듯 쓰면 발언을 찾아 줍니다'),
        ('인물', '의원·정부 인사·기업 증인 243명.\n'
                 '쟁점별로 어떤 입장이었는지 발언 날짜를 근거로 붙여 정리합니다'),
    ], Inches(1.9), left_w=Inches(2.3), row_h=Inches(1.0))
    note(s, '입장 요약은 "질의했다·지적했다·답변했다"처럼 실제 행위로 씁니다 — 질의 한 번을 그 사람의 소신으로 단정하지 않습니다.')

    # ── 13 회의록 검색 화면 ───────────────────────────────────
    shot_slide(prs, '과방위 회의록 — 발언 검색', '첫 화면 맨 위 검색창에 「주파수 재할당」을 넣은 결과', 14, 'minutes_search.png',
               '정리해 둔 발언에서 먼저 찾고, 이어서 국회 회의록 원문에서 찾습니다 — 발언자·날짜·원문 링크가 함께 나옵니다.')

    # ── 14 텔레그램 받기 ───────────────────────────
    s = blank(prs); head(s, '텔레그램 — 받아 보기',
                         't.me/radio_policy_law_ai_bot  (정책 AI도우미)', 12)
    cards(s, [
        ('① 링크 열기', '휴대폰에 텔레그램이 있으면\n링크를 누르는 것만으로 시작됩니다'),
        ('② /start', '받을 항목과 수신 시간대를 고르면 끝.\n설정은 /settings로 언제든 변경'),
    ], Inches(1.85), cols=2, card_h=Inches(1.3), head_size=15, body_size=11.5)
    text(s, MARGIN, Inches(3.4), BODY_W, Inches(0.35), [('받을 항목', 13.5, True, INK)])
    rows(s, [
        ('📡  모닝 브리핑', '정하신 수신 시간대의 시작 시각에 하루 한 번'),
        ('📡  주요 뉴스', '관심 분야 선택 가능'),
        ('🏛️  국회·법률 동향', '법안 발의·처리 경과, 국회·부처 입법예고, 과방위 회의록 요약'),
        ('📺  방미통위 동향', '방송미디어통신위원회(구 방통위) 회의 의사일정·위원회 결과·관련 보도자료'),
    ], Inches(3.85), left_w=Inches(2.9), row_h=Inches(0.62))
    note(s, '브리핑을 제외한 항목은 정해 두신 수신 시간대 안에서 새로 생기는 대로 전달됩니다.')

    # ── 16 텔레그램 설정 화면 ─────────────────────────────────
    # 세로로 긴 캡처(비율 1.13)라 shot_slide의 전폭 배치는 양옆이 크게 빈다 — 왼쪽 그림 + 오른쪽 설명.
    import os as _os
    from PIL import Image as _Image
    s = blank(prs); head(s, '텔레그램 — 설정 화면', '/start 를 누르면 이 화면이 나옵니다', 16)
    _tg = _os.path.join('docs', 'shots', 'telegram_start.png')
    if _os.path.exists(_tg):
        _iw, _ih = _Image.open(_tg).size
        _top, _bot = Inches(1.6), H - Inches(0.75)
        _h = _bot - _top
        _w = int(_iw * (_h / _ih))
        s.shapes.add_picture(_tg, int(MARGIN), int(_top), width=_w, height=int(_h))
        _RX = MARGIN + _w + Inches(0.45)
    else:
        _RX = MARGIN
    _RW = W - _RX - MARGIN
    text(s, _RX, Inches(1.6), _RW, Inches(0.3),
         [('무엇을 고르나', 13.5, True, INK)])
    _y = Inches(2.05)
    for _lab, _desc in [
        ('받을 항목 4가지', '모닝 브리핑 · 주요 뉴스 · 국회·법률 동향 · 방미통위 동향 — 각각 켜고 끕니다'),
        ('관심분야 5가지', '주파수·네트워크 / 요금·시장 / 규제·제재 / 보안·개인정보 / AI 정책\n주요 뉴스에만 적용됩니다'),
        ('요일', '매일 받기 · 평일만'),
        ('받기 시작 시각', '06 · 07 · 08 · 09 · 10시 — 모닝 브리핑이 이 시각에 옵니다'),
        ('받기 종료 시각', '18 · 19 · 20 · 21 · 22시 — 이후 들어온 소식은 다음 날 시작 시각에 모아서 옵니다'),
    ]:
        rect(s, _RX, _y, _RW, Inches(0.86), PANEL, LINE)
        text(s, _RX + Inches(0.22), _y + Inches(0.13), _RW - Inches(0.44), Inches(0.26),
             [(_lab, 12, True, INK)])
        text(s, _RX + Inches(0.22), _y + Inches(0.42), _RW - Inches(0.44), Inches(0.4),
             [(_desc, 10.5, False, MUTED)], line_spacing=1.25)
        _y += Inches(0.98)
    text(s, _RX, _y + Inches(0.05), _RW, Inches(0.4),
         [('설정은 언제든 /settings 로 바꾸실 수 있고, 항목을 모두 끄면 알림이 오지 않습니다.',
           11, False, INK)], line_spacing=1.3)

    # ── 17 텔레그램 물어보기 ──────────────────────────────────
    s = blank(prs); head(s, '텔레그램 — 물어보기',
                         '대화창에 /를 입력하면 명령어 목록이 뜹니다', 13)
    cards(s, [
        ('/assem',
         '2023년 공공와이파이 관련 발언 찾아줘\n\n'
         '2016년부터 쌓인 과방위 발언에서 어느 의원이 언제 무슨 말을 했는지 원문 링크까지 찾아 줍니다.\n\n'
         '별도 승인 없이 바로 이용 가능'),
        ('/law',
         '전기통신사업법 19조\n\n'
         '조문 원문을 그대로 보여 드립니다.\n원문을 옮기는 것이라 AI가 지어낼 여지가 없습니다.\n\n'
         '별도 승인 없이 바로 이용 가능'),
    ], Inches(1.95), cols=2, card_h=Inches(2.85), head_size=17)
    rect(s, MARGIN, Inches(5.15), BODY_W, Inches(0.95), PANEL, LINE)
    text(s, MARGIN + Inches(0.32), Inches(5.38), BODY_W - Inches(0.64), Inches(0.6),
         [('주제로 묻는 법령 검색(/law 3G 종료 관련 법령)과 AI 자문(/ask)은 '
           '최초 1회 승인 후 이용하실 수 있습니다.', 12.5, False, INK)], line_spacing=1.3)

    # ── 14 다른 팀 + 계정 (메일 4·5항) ────────────────────────
    s = blank(prs); head(s, '다른 팀에서 쓰시려면', '현재 범위와 계획', 18)
    text(s, MARGIN, Inches(1.68), BODY_W, Inches(0.6),
         [('이 시스템의 구조는 분야를 가리지 않습니다. 관심 키워드와 소관 법령, 담당 기관 목록만 바꾸면 '
           '어느 조직에서든 쓸 수 있습니다. 다만 지금은 그 목록이 전파·전기통신에 맞춰져 있습니다.',
           12.5, False, INK)], line_spacing=1.35)
    cards(s, [
        ('지금의 한계',
         '소관 법령이 다른 팀에서는 AI 자문과 뉴스 중요도 분류가 기대에 못 미칠 수 있습니다.\n\n'
         '뉴스 중요도는 모든 이용자에게 같은 기준이 적용되는 구조라 지금은 조정을 제한해 두었습니다.'),
        ('어떻게 나눌지 정리 중입니다',
         '팀마다 소관 법령과 상임위, 중요하게 보는 뉴스가 다릅니다. 어디까지 공통으로 두고 어디부터 팀별로 나눌지는 지금 정리하고 있습니다.\n\n'
         '정해지는 대로 순차적으로 열어 드리고, 먼저 써 보실 팀은 소수 인원 파일럿으로 함께 맞춰 가겠습니다.'),
        ('사내 환경도 준비합니다',
         '지금 시스템에는 공개된 자료만 담겨 있어 사내 문서를 근거로 하는 검토는 할 수 없습니다.\n\n'
         '사내 문서까지 근거로 삼을 수 있는 사내 환경 구축을 별도로 준비하고 있습니다.'),
    ], Inches(2.5), cols=3, card_h=Inches(2.9), head_size=15)

    # ── 15 계정과 이용 안내 ───────────────────────────────────
    s = blank(prs); head(s, '계정과 이용 안내', '읽는 일에는 계정이 필요 없습니다', 19)
    rows(s, [
        ('계정 없이', '대시보드 열람 · 텔레그램 알림 · /assem 발언검색 · /law 조문 조회'),
        ('승인이 필요한 것', 'AI 자문(대시보드·/ask), 주제로 묻는 법령 검색, 뉴스를 열 때의 요약·업무영향 분석.\n'
                            '대시보드에서 가입 신청하시면 파일럿 팀부터 순차적으로 승인해 드립니다'),
        ('승인제인 이유', 'AI 자문은 질문 한 건마다 비용이 발생해 현재 기술정책팀 예산으로 부담하고 있습니다.\n'
                          '그 밖의 열람·알림·발언검색·조문조회는 추가 비용이 들지 않으니 마음껏 쓰십시오'),
        ('올리지 마실 것', '담긴 자료는 법령·정부 공고·국회 기록·언론 보도 등 공개된 것뿐입니다.\n'
                          '사내 문서·대외비는 올리지도, 자문 질문에 넣지도 말아 주십시오'),
    ], Inches(1.95), left_w=Inches(2.4), row_h=Inches(0.95), left_size=12.5)
    note(s, '틀린 답이나 빠진 자료를 보시면 알려 주십시오 — AI 자문 답변 아래 👍👎로 남기시거나 저에게 말씀해 주시면 됩니다.')

    # ── 부록 A ────────────────────────────────────────────────
    s = blank(prs); head(s, '부록 A. 수집 기준', '뉴스는 이 범위로 매시간, 법안은 매일 한 번 검색합니다', None)
    text(s, MARGIN, Inches(1.72), BODY_W, Inches(0.3), [('정책 뉴스 수집 키워드', 13, True, INK)])
    rect(s, MARGIN, Inches(2.1), BODY_W, Inches(1.95), PANEL, LINE)
    text(s, MARGIN + Inches(0.3), Inches(2.35), BODY_W - Inches(0.6), Inches(1.5),
         [('주파수 · 5G/6G 주파수 · 전파정책 · 전파법 · 전파사용료 · 전자파 · 무선국 · 무선설비 · '
           '적합성평가 · 방송통신기자재 · WRC-27 · 6GHz · ITU · 위성통신', 11.5, False, INK),
          ('이동통신 · 기지국 · LTE · 3G · 이동통신 품질 · 통신품질 · 통신장애 · 이동통신 장비 · '
           '공공와이파이 · 지하철 와이파이', 11.5, False, INK),
          ('전기통신사업법 · 정보통신망법 · 위치정보법 · 통신정책 · 통신요금 · 알뜰폰 · 번호이동 · '
           '단말기유통 · 이용자보호 · 스팸문자 · 재난문자', 11.5, False, INK),
          ('사이버보안 · AI 기본법 · AI 규제 · 과기정통부 · 부처 인사이동(과기정통부 · 방미통위)',
           11.5, False, INK)], space_after=Pt(7), line_spacing=1.35)
    text(s, MARGIN, Inches(4.3), BODY_W, Inches(0.3), [('국회 법안 수집 키워드', 13, True, INK)])
    rect(s, MARGIN, Inches(4.68), BODY_W, Inches(1.15), PANEL, LINE)
    text(s, MARGIN + Inches(0.3), Inches(4.9), BODY_W - Inches(0.6), Inches(0.8),
         [('전파법 · 전기통신사업법 · 방송통신발전 · 정보통신망 · 주파수 · 전자파 · 무선국 · '
           '방송통신설비 · 적합성평가 · 이동통신단말 · 위성통신 · 기간통신 · 전파간섭', 11.5, False, INK),
          ('개인정보 · 인공지능 · 플랫폼 · 데이터 · 클라우드 · 메타버스   '
           '← 다른 팀 업무와 겹치는 주제도 이미 상당 부분 들어와 있습니다', 11.5, True, INK)],
         space_after=Pt(7), line_spacing=1.35)
    note(s, '키워드는 넓게 잡아 모으고 관련 없는 것은 저장하지 않습니다 — 빠뜨리는 쪽보다 넉넉히 보는 쪽을 택했습니다.')

    # ── 부록 B ────────────────────────────────────────────────
    s = blank(prs); head(s, '부록 B. 지금 담고 있는 것', '2026년 9월 기준', None)
    rows(s, [
        ('과방위 회의록', '2016년 6월부터 393회 · 발언 6,741건 (상임위 · 국정감사 전문)'),
        ('인물', '243명 — 의원 124명 · 정부 인사와 기업 증인 119명. 공개된 회의록 발언에 한합니다'),
        ('국회 법안', '669건 — 발의부터 처리까지 단계 추적'),
        ('정책 뉴스', '현재 1만 1천여 건 보관 · 매시간 수집 · 60일 경과분은 정리'),
        ('법적 용어', '조문에 정의된 법률 용어 1,370개 — 원문 그대로'),
        ('법령 관계도', '법령·고시 1,230여 건 + 주제 72개, 그 사이의 위임·인용 관계 (전파·전기통신 분야)'),
    ], Inches(1.9), left_w=Inches(2.6), row_h=Inches(0.68))
    rect(s, MARGIN, Inches(5.95), BODY_W, Inches(0.95), PANEL, LINE)
    text(s, MARGIN + Inches(0.35), Inches(6.15), BODY_W - Inches(0.7), Inches(0.6),
         [('문의 · 기능 요청 · 자료 추가', 12.5, True, INK),
          ('SKT Comm.센터 기술정책팀   ·   radio-policy.gitlab.io   ·   '
           't.me/radio_policy_law_ai_bot', 11.5, False, MUTED)], space_after=Pt(5))

    out = '전파정책AI_소개_20260913.pptx'
    prs.save(out)
    print('저장: %s (%d장)' % (out, len(prs.slides._sldIdLst)))


if __name__ == '__main__':
    build()
