#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
구독자 봇용 랜덤 시크릿 생성 → .env에 기록 + Supabase에 넣을 값 출력 (1회 실행)

왜 스크립트로 만드나:
  webhook 검증용/cron 검증용 시크릿은 값 자체가 비밀이라 대화·문서·저장소에 남기면 안 된다.
  로컬에서 생성해 .env에만 쓰고, 화면에 한 번만 보여줘 Supabase 콘솔에 옮겨 적게 한다.

동작:
  - .env에 TELEGRAM_WEBHOOK_SECRET / CRON_SECRET 이 이미 있으면 건드리지 않는다(재실행 안전).
  - 없으면 생성해 .env 끝에 추가한다.
  - SUBSCRIBER_BOT_TOKEN은 BotFather 값이라 자동 생성 불가 — 직접 넣어야 한다고 안내만 한다.

사용:  python init_subscriber_secrets.py              (안내를 화면에 출력)
       python init_subscriber_secrets.py --out 파일경로 (안내를 파일로 저장 — 화면에 값이 안 남음)
"""
import re
import secrets
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')   # 스케줄러 cp949 캡처 대비(지침 #19)

ENV = Path(__file__).parent / '.env'
KEYS = ['TELEGRAM_WEBHOOK_SECRET', 'CRON_SECRET']


def read_env() -> str:
    return ENV.read_text(encoding='utf-8') if ENV.exists() else ''


def get_val(text: str, key: str) -> str:
    m = re.search(rf'^{key}\s*=\s*(.*)$', text, re.M)
    return m.group(1).strip() if m else ''


def main() -> int:
    text = read_env()
    added, values = [], {}

    for key in KEYS:
        cur = get_val(text, key)
        if cur:
            values[key] = cur
            print(f'[유지] {key} — .env에 이미 있음')
        else:
            values[key] = secrets.token_urlsafe(32)
            added.append(f'{key}={values[key]}')

    if added:
        with ENV.open('a', encoding='utf-8') as f:
            if text and not text.endswith('\n'):
                f.write('\n')
            f.write('\n# 구독자 봇 (telegram-webhook / send-subscriber-briefing)\n')
            f.write('\n'.join(added) + '\n')
        print(f'[생성] {len(added)}개 시크릿을 .env에 추가했습니다.')

    token = get_val(text, 'SUBSCRIBER_BOT_TOKEN')
    anthropic_key = get_val(text, 'ANTHROPIC_API_KEY')

    guide = f"""{'=' * 66}
 ① Edge Function Secrets — 아래 5줄을 통째로 복사해 Name 칸에 붙여넣기
    (Supabase가 key=value 다중 붙여넣기를 지원 → 5개가 한 번에 채워짐)
{'=' * 66}

SUBSCRIBER_BOT_TOKEN={token or '(.env에 아직 없음)'}
TELEGRAM_WEBHOOK_SECRET={values['TELEGRAM_WEBHOOK_SECRET']}
CRON_SECRET={values['CRON_SECRET']}
ANTHROPIC_API_KEY={anthropic_key or '(기존 Anthropic 키)'}
OPERATOR_CHAT_ID=344506450

  → 붙여넣은 뒤 Save 클릭. (칸이 안 채워지면 Add another로 5칸 만들어 하나씩 입력)

{'=' * 66}
 ② Supabase → SQL Editor 에서 아래 한 줄 실행 (cron이 읽는 Vault 시크릿)
{'=' * 66}

select vault.create_secret('{values['CRON_SECRET']}', 'subscriber_cron_secret');

{'=' * 66}
 ③ 끝나면 실행:  python setup_subscriber_bot.py
{'=' * 66}

 ※ 이 파일에는 비밀값이 들어 있습니다. 등록을 마치면 삭제하세요.
"""

    out_path = None
    if '--out' in sys.argv:
        out_path = Path(sys.argv[sys.argv.index('--out') + 1])
        out_path.write_text(guide, encoding='utf-8')
        print(f'[안내] 등록용 값을 파일로 저장했습니다 (화면 출력 생략): {out_path}')
    else:
        print(guide)

    if not token:
        print('⚠️  .env에 SUBSCRIBER_BOT_TOKEN이 아직 없습니다.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
