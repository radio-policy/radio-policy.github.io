#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
system_prompt.js → Supabase app_config('system_prompt') 업로드

왜 DB에 올리는가:
  루트 system_prompt.js는 브라우저용 전역 선언(`const SYSTEM_PROMPT = "..."`)이라 export가 없어
  Edge Function(Deno)에서 그대로 import할 수 없다. 루트 파일을 고치면 대시보드가 로드하는 파일이
  바뀌어(캐시버스터 갱신 필요 + 자문 경로 회귀 위험) 손해가 크다.
  그래서 원본은 손대지 않고, 문자열만 뽑아 app_config에 저장한다.
  → 텔레그램 봇(telegram-webhook)이 이 값을 읽어 자문 시스템 프롬프트로 사용.
  → 프롬프트를 고쳐도 Edge Function 재배포가 필요 없다(이 스크립트만 재실행).

주의:
  프롬프트 내용 수정은 반드시 루트 system_prompt.js에서 한다(대시보드와 봇의 단일 원본).
  수정 후 이 스크립트를 실행해야 텔레그램 봇에 반영된다.

사용:  python sync_system_prompt.py
"""
import os
import sys
import json
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')   # 스케줄러 cp949 캡처 대비(지침 #19)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from sb_client import make_client

ROOT = Path(__file__).parent
SRC = ROOT / 'system_prompt.js'


def extract_prompt(js: str) -> str:
    """`const SYSTEM_PROMPT = "...";` 의 문자열 리터럴을 JSON으로 파싱해 실제 값을 얻는다."""
    start = js.index('"')
    end = js.rindex('"')
    return json.loads(js[start:end + 1])


def main() -> int:
    if not SRC.exists():
        print(f'[오류] 원본 없음: {SRC}')
        return 1
    prompt = extract_prompt(SRC.read_text(encoding='utf-8'))
    if len(prompt) < 1000:
        print(f'[중단] 추출 결과가 비정상적으로 짧음({len(prompt)}자) — 원본 형식 확인 필요')
        return 1

    sb = make_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    sb.table('app_config').upsert({'key': 'system_prompt', 'value': prompt}, on_conflict='key').execute()
    print(f'[업로드] app_config.system_prompt 갱신 완료 ({len(prompt):,}자)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
