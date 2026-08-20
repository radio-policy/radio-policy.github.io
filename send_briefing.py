#!/usr/bin/env python3
"""
전파정책 AI — 모닝 브리핑 발송 스크립트
morning-telecom-news SKILL.md STEP 10에서 호출
Supabase daily_briefings에서 오늘 브리핑을 읽어 이메일 + 텔레그램 발송
"""

import os, smtplib
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests
from sb_client import make_client
import notify   # 텔레그램 전송 공용 유틸 (개선⑪) — 전송부만 위임

# ── 환경변수 ─────────────────────────────────────────
SUPABASE_URL  = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY  = os.environ.get('SUPABASE_SERVICE_KEY', '')
EMAIL_FROM    = os.environ.get('EMAIL_FROM', '')
EMAIL_PASS    = os.environ.get('EMAIL_PASSWORD', '')
EMAIL_TO      = os.environ.get('EMAIL_TO', '')
BOT_TOKEN     = os.environ.get('TELEGRAM_BOT_TOKEN', '')
CHAT_ID       = os.environ.get('TELEGRAM_CHAT_ID', '')

KST = timezone(timedelta(hours=9))


def get_today_briefing() -> str:
    """Supabase daily_briefings에서 오늘 브리핑 조회"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print('[오류] SUPABASE_URL / SUPABASE_SERVICE_KEY 환경변수 미설정')
        return ''
    sb = make_client(SUPABASE_URL, SUPABASE_KEY)
    today = datetime.now(KST).strftime('%Y-%m-%d')
    try:
        resp = sb.table('daily_briefings').select('content').eq('briefing_date', today).execute()
        if resp.data:
            return resp.data[0]['content'] or ''
        print(f'[브리핑] {today} 브리핑 없음 — SKILL.md STEP 8이 완료되었는지 확인하세요')
        return ''
    except Exception as e:
        print(f'[브리핑 조회 오류] {e}')
        return ''


def briefing_to_html(text: str) -> str:
    """브리핑 텍스트 → HTML 변환"""
    import html as html_lib
    lines = text.split('\n')
    html_lines = []
    in_box = False
    for line in lines:
        e = html_lib.escape(line)
        is_urgent = '🔴' in line
        if in_box and not is_urgent and (e.startswith('[') or '📡' in line or e == ''):
            html_lines.append('</div>')
            in_box = False
        if is_urgent:
            if not in_box:
                html_lines.append('<div style="border:2px solid #c53030;border-radius:6px;background:#fff5f5;padding:10px 14px;margin:10px 0">')
                in_box = True
            html_lines.append(f'<p style="margin:3px 0">{e}</p>')
        elif '📡' in line:
            html_lines.append(f'<h2 style="color:#534AB7;margin-bottom:4px">{e}</h2>')
        elif e.startswith('[') and e.endswith(']'):
            html_lines.append(f'<h3 style="color:#1a1a1a;margin:18px 0 6px;border-bottom:1px solid #eee;padding-bottom:4px">{e}</h3>')
        elif e.startswith('•') or '🟡' in line or '🟢' in line:
            html_lines.append(f'<p style="margin:4px 0 4px 12px">{e}</p>')
        elif e.startswith('  →'):
            html_lines.append(f'<p style="margin:2px 0 2px 24px;color:#555;font-size:13px">{e}</p>')
        elif e.startswith('  🔗'):
            url = line.strip()[2:].strip()
            html_lines.append(f'<p style="margin:2px 0 8px 24px;font-size:12px"><a href="{url}" style="color:#534AB7">{url}</a></p>')
        elif e == '':
            html_lines.append('<br>')
        else:
            html_lines.append(f'<p style="margin:4px 0">{e}</p>')
    if in_box:
        html_lines.append('</div>')
    return '\n'.join(html_lines)


def send_email(briefing_text: str):
    """이메일 발송"""
    if not all([EMAIL_FROM, EMAIL_PASS, EMAIL_TO]):
        print('[이메일] 환경변수 미설정 — 건너뜀')
        return
    today = datetime.now(KST).strftime('%Y.%m.%d')
    subject = f'☀️ [전파정책 AI] {today} 모닝 브리핑'
    body_html = f'''
<html><body style="font-family:sans-serif;max-width:640px;margin:auto;padding:20px">
{briefing_to_html(briefing_text)}
<hr style="margin-top:24px">
<p style="color:#999;font-size:11px">
이 메일은 자동 발송됩니다. SKT Comm센터 기술정책팀<br>
대시보드: <a href="https://radio-policy.gitlab.io/">https://radio-policy.gitlab.io/</a>
</p>
</body></html>'''
    extra_to = 'lampman@sktelecom.com'
    all_to = list({a.strip() for a in (EMAIL_TO + ',' + extra_to).split(',') if a.strip()})
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From']    = f'전파정책 AI <{EMAIL_FROM}>'
    msg['To']      = ', '.join(all_to)
    msg.attach(MIMEText(body_html, 'html', 'utf-8'))
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30) as smtp:
            smtp.login(EMAIL_FROM, EMAIL_PASS)
            smtp.sendmail(EMAIL_FROM, all_to, msg.as_string())
        print(f'[이메일] {", ".join(all_to)} 발송 완료')
    except Exception as e:
        print(f'[이메일 오류] {e}')


def send_telegram(briefing_text: str):
    """텔레그램 발송 — 4000자 절단 가공은 여기, 전송부는 notify 위임 (개선⑪)"""
    if not BOT_TOKEN or not CHAT_ID:
        print('[텔레그램] 환경변수 미설정 — 건너뜀')
        return
    text = briefing_text[:4000]
    if len(briefing_text) > 4000:
        text += '\n\n...(전문은 대시보드 참조)'
    text += '\n\n📊 https://radio-policy.gitlab.io/'
    if notify.send_telegram(text, chat_id=CHAT_ID, disable_web_page_preview=True):
        print('[텔레그램] 발송 완료')


if __name__ == '__main__':
    print('=== 브리핑 발송 시작 ===')
    briefing = get_today_briefing()
    if not briefing:
        print('[종료] 오늘 브리핑 없음')
    else:
        print(f'[브리핑] {len(briefing)}자 로드 완료')
        send_email(briefing)
        send_telegram(briefing)
    print('=== 완료 ===')
