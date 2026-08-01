#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
최근 브리핑을 텔레그램 + 이메일로 즉시 재발송

사용법:
  python resend_briefing.py           # 가장 최근 브리핑
  python resend_briefing.py 2026-06-07  # 특정 날짜
"""

import sys
import os
from dotenv import load_dotenv
load_dotenv()

import requests
from sb_client import make_client

SUPABASE_URL       = os.environ['SUPABASE_URL']
SUPABASE_KEY       = os.environ['SUPABASE_SERVICE_KEY']
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID   = os.environ.get('TELEGRAM_CHAT_ID', '')
RESEND_API_KEY     = os.environ.get('RESEND_API_KEY', '')

sb = make_client(SUPABASE_URL, SUPABASE_KEY)

# ── 환경변수 확인 ──
print("── 환경변수 확인 ──")
print(f"  TELEGRAM_BOT_TOKEN : {'✅ 설정됨' if TELEGRAM_BOT_TOKEN else '❌ 없음'}")
print(f"  TELEGRAM_CHAT_ID   : {'✅ ' + TELEGRAM_CHAT_ID if TELEGRAM_CHAT_ID else '❌ 없음'}")
print(f"  RESEND_API_KEY     : {'✅ 설정됨' if RESEND_API_KEY else '❌ 없음'}")
print()

# ── 브리핑 조회 ──
target_date = sys.argv[1] if len(sys.argv) > 1 else None
if target_date:
    resp = sb.table('daily_briefings').select('*').eq('briefing_date', target_date).execute()
else:
    resp = sb.table('daily_briefings').select('*').order('briefing_date', desc=True).limit(1).execute()

if not resp.data:
    print("❌ 브리핑 없음")
    sys.exit(1)

row = resp.data[0]
briefing_date = row['briefing_date']
briefing_text = row['content']
news_count    = row.get('news_count', 0)
print(f"📋 브리핑: {briefing_date} ({news_count}건 기사)")
print()

# ── 텔레그램 발송 ──
print("── 텔레그램 발송 ──")
if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    print("  ❌ 환경변수 미설정 — 건너뜀")
else:
    # 포맷은 정규 발송과 동일 규칙을 재사용 (제목=하이퍼링크, 별도 🔗 줄 없음)
    from morning_briefing import _briefing_to_telegram_html
    html_text = _briefing_to_telegram_html(briefing_text)
    text = f"<b>[재발송: {briefing_date}]</b>\n\n" + html_text[:3900]
    if len(html_text) > 3900:
        text = text[:text.rfind('\n')]          # 태그 중간 절단 방지
        text += '\n\n...(전문은 대시보드 참조)'
    text += '\n\n📊 <a href="https://youjinwoong.github.io/radio-policy-ai/">대시보드</a>'
    api = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    try:
        r = requests.post(api, json={'chat_id': TELEGRAM_CHAT_ID, 'text': text,
                                     'parse_mode': 'HTML', 'disable_web_page_preview': True}, timeout=15)
        if r.status_code == 400:
            import re as _re
            print(f"  ⚠️ HTML 400 → 평문 재시도: {r.text[:150]}")
            r = requests.post(api, json={'chat_id': TELEGRAM_CHAT_ID, 'text': _re.sub(r'<[^>]+>', '', text),
                                         'disable_web_page_preview': True}, timeout=15)
        if r.status_code == 200:
            print(f"  ✅ 발송 완료")
        else:
            print(f"  ❌ HTTP {r.status_code}: {r.text[:300]}")
    except Exception as e:
        print(f"  ❌ 오류: {e}")
print()

# ── 이메일 발송 (Resend) ──
print("── 이메일 발송 (Resend) ──")
if not RESEND_API_KEY:
    print("  ❌ RESEND_API_KEY 미설정 — 건너뜀")
else:
    subject = f"[재발송] 전파정책 AI 모닝 브리핑 — {briefing_date}"
    lines = briefing_text.split('\n')
    html_lines = []
    for line in lines:
        if line.startswith('# '):
            html_lines.append(f'<h2 style="color:#1a73e8">{line[2:]}</h2>')
        elif line.startswith('## '):
            html_lines.append(f'<h3>{line[3:]}</h3>')
        elif line.startswith('🔴'):
            html_lines.append(f'<p style="color:#c53030;font-weight:bold">{line}</p>')
        elif line == '':
            html_lines.append('<br>')
        else:
            html_lines.append(f'<p style="margin:2px 0">{line}</p>')
    body_html = f"""<html><body style="font-family:sans-serif;max-width:700px;margin:auto;padding:20px">
<p style="color:#888;font-size:12px">재발송 | {briefing_date}</p>
{''.join(html_lines)}
<hr><p style="font-size:11px;color:#aaa">
<a href="https://youjinwoong.github.io/radio-policy-ai/">대시보드 바로가기</a></p>
</body></html>"""
    try:
        r = requests.post(
            'https://api.resend.com/emails',
            headers={'Authorization': f'Bearer {RESEND_API_KEY}', 'Content-Type': 'application/json'},
            json={'from': '전파정책 AI <onboarding@resend.dev>',
                  'to': ['you.jinwoong@gmail.com'],
                  'subject': subject,
                  'html': body_html},
            timeout=15
        )
        if r.status_code in (200, 201):
            print(f"  ✅ 발송 완료 (id: {r.json().get('id','')})")
        else:
            print(f"  ❌ HTTP {r.status_code}: {r.text[:300]}")
    except Exception as e:
        print(f"  ❌ 오류: {e}")
