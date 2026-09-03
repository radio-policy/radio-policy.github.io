# -*- coding: utf-8 -*-
"""
국회 법안 진행단계 파생 (2026-09-04, 배경역사 #122) — 순수 함수, DB·네트워크 없음.

열린국회정보 API(nzmimeepazxkubdpn) 행의 PROC_RESULT는 본회의 처리 결과만 담고, 계류 중이면
비어 있다. 종전 크롤러는 그 경우를 무조건 '접수'로 저장해 회부·상정·법사위·위원회 의결(본회의
대기)을 구분하지 못했다. API가 이미 주는 날짜·결과 필드로 단계를 판정한다.

- 실제 순서: 발의·접수 → 소관위 회부 → (국회 입법예고: 회부 직후 거의 모든 법안) → 소관위 상정
  → 소위 심사 → 위원회 의결 → 법사위 회부·심사 → 본회의 → 공포.
- API에 '소위' 필드는 없다. 상정일(CMT_PRESENT_DT)이 심사 착수의 대리 지표.
- 자문 근거는 확정 법령만이다(운영자 결정). 이 라벨은 '법안 동향'(목록·알림·자문 각주)의
  정확성을 위한 것이지, 어떤 단계도 법안을 지식베이스 근거로 올리지 않는다.
"""

# 위원회 처리결과 중 위원회 단계에서 법안이 완전히 끝나는 값. 가결·수정가결·원안가결은
# 법사위·본회의로 이어지므로 종결이 아니라 '위원회 의결'이다.
COMMITTEE_TERMINAL_CODES = {'대안반영폐기', '부결', '철회', '폐기'}
COMMITTEE_PASS_CODES = {'가결', '수정가결', '원안가결'}

# derive_stage()가 만들어내는 "계류 중(생존)" 라벨의 닫힌 집합. 이 밖의 값은 전부 API 원본
# 처리결과가 그대로 통과된 것이므로 종결로 본다(화이트리스트 — 미지의 결과코드는 안전 쪽으로).
ALIVE_LABELS = {'접수', '소관위 회부', '소관위 심사중', '위원회 의결', '법사위 회부', '법사위 심사중'}

# assembly_bills에 저장하는 단계 원본 컬럼 ← API 필드
STAGE_FIELDS = {
    'committee_dt':    'COMMITTEE_DT',
    'cmt_present_dt':  'CMT_PRESENT_DT',
    'cmt_proc_dt':     'CMT_PROC_DT',
    'cmt_proc_result': 'CMT_PROC_RESULT_CD',
    'law_submit_dt':   'LAW_SUBMIT_DT',
    'law_present_dt':  'LAW_PRESENT_DT',
    'law_proc_dt':     'LAW_PROC_DT',
}


def _s(v) -> str:
    return (v or '').strip() if isinstance(v, str) else ('' if v is None else str(v).strip())


def derive_stage(bill: dict) -> str:
    """API 원본 행(대문자 키) → assembly_bills.proc_result 저장값."""
    raw = _s(bill.get('PROC_RESULT'))
    if raw:
        return raw                                    # 본회의 처리 결과 = 항상 종결
    cmt = _s(bill.get('CMT_PROC_RESULT_CD'))
    if cmt in COMMITTEE_TERMINAL_CODES:
        return cmt
    if cmt in COMMITTEE_PASS_CODES:
        return '위원회 의결'
    if _s(bill.get('LAW_PRESENT_DT')):
        return '법사위 심사중'
    if _s(bill.get('LAW_SUBMIT_DT')):
        return '법사위 회부'
    if _s(bill.get('CMT_PRESENT_DT')):
        return '소관위 심사중'
    if _s(bill.get('COMMITTEE_DT')):
        return '소관위 회부'
    return '접수'


def stage_columns(bill: dict) -> dict:
    """API 원본 행 → 단계 컬럼 dict(빈값은 None)."""
    return {col: (_s(bill.get(api)) or None) for col, api in STAGE_FIELDS.items()}


def is_terminal_label(proc_result: str) -> bool:
    """저장된 proc_result가 종결(가결·폐기·철회·부결…)인가 — ALIVE_LABELS 밖이면 종결."""
    return _s(proc_result) not in ALIVE_LABELS
