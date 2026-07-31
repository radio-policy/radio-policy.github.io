#!/usr/bin/env python3
"""
ITU-R 권고 개정 감시 (판 번호 대조)

지식베이스에 등재된 ITU-R 권고 PDF의 판 번호(예: M.1036-8 의 "8")를 ITU 공식 페이지의
현행판(In force)과 대조해, 개정되었으면 텔레그램으로 알린다.

※ PDF를 자동으로 내려받지 않는다 — 의도적 제약.
  ITU 원문에는 "All rights reserved. No part of this publication may be reproduced ...
  without written permission of ITU" 가 명시돼 있어, 법령(공공누리)처럼 자동 수집·재배포할 수 없다.
  따라서 이 스크립트는 '개정 감지와 알림'까지만 하고, 실제 PDF 확보와 지식베이스 교체는
  운영자가 수동으로(대시보드 업로드) 처리한다.

GitHub Actions에서 매월 1일 실행 (itu_watch.yml). 권고 개정은 드물어 월 1회로 충분하다.
"""

import os
import re
import sys
import time
import argparse
import requests
from datetime import datetime, timezone, timedelta

# Windows 스케줄러/cp949 콘솔에서 이모지·특수문자 print 크래시 방지 (배경역사 #19)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from supabase import Client
from sb_client import make_client

# ── 환경변수 ──────────────────────────────────────────────
SUPABASE_URL       = os.environ['SUPABASE_URL']
SUPABASE_KEY       = os.environ['SUPABASE_SERVICE_KEY']
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID   = os.environ.get('TELEGRAM_CHAT_ID', '')

sb: Client = make_client(SUPABASE_URL, SUPABASE_KEY)
KST = timezone(timedelta(hours=9))

# ── ITU 조회 설정 ─────────────────────────────────────────
ITU_REC_URL = 'https://www.itu.int/rec/R-REC-{rec}/en'

# 정직한 식별 UA를 쓴다 — 브라우저 UA 위장 금지.
# ITU 앞단 WAF(F5) 실측 결과:
#   · 'Mozilla/5.0' 같은 짧은 봇 시그니처 → HTTP 200인데 본문이 "Request Rejected"
#   · 완전한 Chrome UA 문자열          → 연결 자체를 블랙홀(ReadTimeout, 재시도 전부 실패)
#   · python-requests 기본 UA / curl / 아래 같은 정직한 UA → 정상 200 (1초대 응답)
# 위장할수록 오히려 막힌다. 예의상으로도 신원을 밝히는 편이 맞다.
USER_AGENT = 'radio-policy-ai-itu-watch/1.0 (+https://github.com/youjinwoong/radio-policy-ai)'

REQ_TIMEOUT   = 20
REQ_INTERVAL  = 1.5   # 요청 간 간격(초) — 예의상 텀. ITU 사이트는 응답이 들쭉날쭉하다.

# 파일명 예: R-REC-M.1036-8-202602-I!!PDF-E.pdf → 시리즈번호 'M.1036', 보유 판 '8'
# 시리즈는 1~3글자(M, SM, SNG 등)라 {1,3}으로 둔다.
REC_NAME_RE = re.compile(r'^R-REC-([A-Z]{1,3}\.\d+)-(\d+)-', re.I)

ROW_RE = re.compile(r'<tr\b.*?</tr>', re.S | re.I)
TAG_RE = re.compile(r'<[^>]+>')


# ══════════════════════════════════════════════════════════
#  감시 대상 수집 (DB에서 읽는다 — 하드코딩 금지)
# ══════════════════════════════════════════════════════════

def fetch_targets():
    """document_chunks의 ITU-R 문서명을 훑어 (시리즈번호, 보유판, 파일명) 목록을 만든다.

    반환: (targets, skipped_report, skipped_format)
    같은 권고가 여러 chunk로 쪼개져 있으므로 시리즈번호 기준으로 1건으로 합친다.
    """
    rows, start, PAGE = [], 0, 1000
    while True:
        # chunk 수가 1000을 넘으면 기본 limit에 잘려 감시 대상이 조용히 누락되므로 페이지네이션한다.
        res = (sb.table('document_chunks')
                 .select('doc_name')
                 .eq('doc_category', 'ITU-R')
                 .range(start, start + PAGE - 1)
                 .execute())
        batch = res.data or []
        rows += batch
        if len(batch) < PAGE:
            break
        start += PAGE

    names = sorted({r['doc_name'] for r in rows if r.get('doc_name')})

    targets, skipped_report, skipped_format = {}, [], []
    for name in names:
        # Report(R-REP-)는 권고와 URL 체계가 달라(/rec/ 경로에 없다) 이 스크립트로 감시할 수 없다.
        if name.upper().startswith('R-REP-'):
            skipped_report.append(name)
            continue
        m = REC_NAME_RE.match(name)
        if not m:
            # 보도자료 .md 등 권고 PDF 파일명 형식이 아닌 것
            skipped_format.append(name)
            continue
        rec, held = m.group(1).upper(), int(m.group(2))
        # 같은 권고의 chunk가 여러 개면 판 번호가 가장 높은 것을 보유본으로 본다.
        if rec not in targets or held > targets[rec]['held']:
            targets[rec] = {'rec': rec, 'held': held, 'doc_name': name}

    return [targets[k] for k in sorted(targets)], skipped_report, skipped_format


# ══════════════════════════════════════════════════════════
#  ITU 페이지 조회·파싱
# ══════════════════════════════════════════════════════════

def _row_text(html_row: str) -> str:
    return re.sub(r'\s+', ' ', TAG_RE.sub(' ', html_row)).strip()


def fetch_current_edition(rec: str):
    """ITU 권고 페이지에서 'In force' 판 번호를 뽑는다. 실패 시 (None, 사유).

    페이지 구조(실측): 판마다 <tr>, 첫 칸에 'M.1036-8 (02/2026)', 상태 칸에
    'In force (Main)' 또는 'Superseded'. 구판 표(Previous versions)도 같은 구조라
    'In force' 인 행만 골라야 한다.
    """
    url = ITU_REC_URL.format(rec=rec)
    resp = requests.get(url, timeout=REQ_TIMEOUT, headers={'User-Agent': USER_AGENT})

    # status_code를 믿으면 안 된다 — WAF 거부가 HTTP 200 + "Request Rejected" 본문으로 온다.
    # 이걸 성공으로 세면 차단당한 실행이 "전건 조회 성공 / 개정 0건"으로 멀쩡해 보인다.
    html = resp.content.decode('iso-8859-1', 'replace')  # 페이지 선언 charset. 숫자만 뽑으므로 안전.
    if 'Request Rejected' in html:
        return None, 'WAF 거부(Request Rejected, HTTP %d)' % resp.status_code
    if resp.status_code != 200:
        return None, 'HTTP %d' % resp.status_code

    editions = []
    for row in ROW_RE.findall(html):
        text = _row_text(row)
        if 'In force' not in text:
            continue
        m = re.match(re.escape(rec) + r'-(\d+)\s*\(', text)
        if m:
            editions.append(int(m.group(1)))

    if not editions:
        # 페이지는 받았는데 현행판을 못 찾음 = 폐지됐거나 페이지 구조가 바뀐 것.
        # 0건으로 조용히 넘기지 말고 '조회 실패'로 집계해 파서 고장을 드러낸다.
        return None, '현행판(In force) 행 없음 — 폐지 또는 페이지 구조 변경 의심'
    return max(editions), None


# ══════════════════════════════════════════════════════════
#  텔레그램 알림
# ══════════════════════════════════════════════════════════

def send_telegram(msg: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    try:
        resp = requests.post(url, json={
            'chat_id': TELEGRAM_CHAT_ID,
            'text': msg,
            'parse_mode': 'HTML',
        }, timeout=10)
        if resp.status_code != 200:
            print(f'[텔레그램 오류] {resp.status_code}')
    except Exception as e:
        print(f'[텔레그램 오류] {e}')


def notify_revised(revised: list):
    lines = ['📡 <b>[ITU-R 권고 개정 감지]</b> %d건\n' % len(revised)]
    for r in revised:
        lines.append(
            '<b>%s</b>\n'
            '• 보유: -%d판 → 현행: <b>-%d판</b>\n'
            '• %s\n'
            % (r['rec'], r['held'], r['current'], ITU_REC_URL.format(rec=r['rec']))
        )
    # PDF 자동 수집은 ITU 저작권 때문에 못 한다 → 사람이 받아 올려야 함을 매번 명시.
    lines.append(
        '위 링크에서 <b>PDF를 직접 받아 대시보드에서 업로드</b>하세요.\n'
        '(ITU 저작권 정책상 자동 다운로드는 하지 않습니다)'
    )
    send_telegram('\n'.join(lines))


def notify_all_failed(targets: int, failures: list):
    """조회가 전량 실패했을 때의 경고.

    '개정 0건'과 '조회 실패'는 절대 같게 취급하면 안 된다 — 무성 실패를 정상으로 오인하는 사고가
    이 프로젝트에서 반복됐다. 전량 실패는 감시가 죽은 것이므로 반드시 사람에게 알린다.
    """
    detail = '\n'.join('• %s: %s' % (f['rec'], f['reason']) for f in failures[:10])
    send_telegram(
        '🚨 <b>[ITU 조회 전량 실패]</b>\n'
        '감시 대상 %d건 중 <b>조회 성공 0건</b> — 개정 여부를 알 수 없습니다.\n'
        'WAF 차단 또는 페이지 구조 변경 가능성이 있습니다.\n\n'
        '%s' % (targets, detail or '—')
    )


# ══════════════════════════════════════════════════════════
#  메인
# ══════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description='ITU-R 권고 개정 감시')
    ap.add_argument('--dry-run', action='store_true',
                    help='조회·비교만 하고 텔레그램 발송과 heartbeat 기록을 하지 않는다')
    args = ap.parse_args()

    now_str = datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')
    print('=' * 60)
    print('[ITU-R 권고 개정 감시 시작] ' + now_str + (' (DRY-RUN)' if args.dry_run else ''))
    print('=' * 60)

    targets, skipped_report, skipped_format = fetch_targets()

    for n in skipped_report:
        print('[제외] Report(권고와 URL 체계 다름): %s' % n)
    for n in skipped_format:
        print('[제외] 권고 파일명 형식 아님: %s' % n)
    if skipped_report or skipped_format:
        print('[제외 합계] %d건 (Report %d / 형식불일치 %d)'
              % (len(skipped_report) + len(skipped_format), len(skipped_report), len(skipped_format)))

    print('[감시 대상] %d건' % len(targets))

    results, failures, revised = [], [], []
    for i, t in enumerate(targets):
        if i:
            time.sleep(REQ_INTERVAL)
        try:
            current, reason = fetch_current_edition(t['rec'])
        except Exception as e:
            # 그 문서만 건너뛰고 계속 — 한 건의 타임아웃으로 전체 감시가 죽으면 안 된다.
            current, reason = None, '%s: %s' % (type(e).__name__, e)

        if current is None:
            failures.append({'rec': t['rec'], 'reason': reason})
            results.append({**t, 'current': None, 'reason': reason})
            print('  [실패] %-9s 보유 -%d판 / %s' % (t['rec'], t['held'], reason))
            continue

        row = {**t, 'current': current, 'reason': None}
        results.append(row)
        if current > t['held']:
            revised.append(row)
            print('  [개정] %-9s 보유 -%d판 → 현행 -%d판  ★' % (t['rec'], t['held'], current))
        else:
            print('  [최신] %-9s 보유 -%d판 = 현행 -%d판' % (t['rec'], t['held'], current))

    ok = len(results) - len(failures)

    # 0건이 '정상(개정 없음)'인지 '파서 고장/차단'인지 구분하려면 이 세 숫자가 함께 찍혀야 한다.
    print('-' * 60)
    print('[요약] 감시 대상 %d건 / 조회 성공 %d건 / 개정 %d건 (조회 실패 %d건)'
          % (len(targets), ok, len(revised), len(failures)))

    if args.dry_run:
        print('-' * 60)
        print('%-10s %-8s %-8s %s' % ('권고', '보유', '현행', '판정'))
        print('-' * 60)
        for r in results:
            if r['current'] is None:
                verdict = '조회실패 — %s' % r['reason']
                cur = '—'
            else:
                verdict = '개정됨 ★' if r['current'] > r['held'] else '최신'
                cur = '-%d' % r['current']
            print('%-10s %-8s %-8s %s' % (r['rec'], '-%d' % r['held'], cur, verdict))
        print('-' * 60)
        print('[DRY-RUN] 텔레그램 발송·heartbeat 기록 생략')
        print('=' * 60)
        return

    # ── 알림 ──
    if targets and ok == 0:
        # 전량 실패: 감시가 죽은 상태. '개정 0건'으로 조용히 넘기지 않는다.
        print('[경고] 조회 전량 실패 — 텔레그램 경고 발송')
        notify_all_failed(len(targets), failures)
    elif revised:
        notify_revised(revised)
        print('[알림] 개정 %d건 텔레그램 발송' % len(revised))
    else:
        # 개정 0건이면 조용히 종료(알림 없음). 돌았다는 증거는 heartbeat가 남긴다.
        print('[알림] 개정 0건 — 텔레그램 발송 안 함')

    # ── heartbeat ── ('돌긴 했는데 변화 없음'과 '안 돌았음'을 구분). 실패해도 무시.
    note = 'targets=%d ok=%d revised=%d failed=%d' % (len(targets), ok, len(revised), len(failures))
    if targets and ok == 0:
        note = 'FAILED all fetch — ' + note   # 운영 상태 탭에서 전량 실패가 눈에 띄도록
    try:
        sb.table('system_health').upsert(
            {'key': 'last_itu_watch_run',
             'updated_at': datetime.now(timezone.utc).isoformat(),
             'note': note},
            on_conflict='key'
        ).execute()
        print('[heartbeat] system_health.last_itu_watch_run 갱신 (%s)' % note)
    except Exception as e:
        print('[heartbeat 오류] %s' % e)

    print('=' * 60)


if __name__ == '__main__':
    main()
