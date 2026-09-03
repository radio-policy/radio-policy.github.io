"""
법령 일괄 신규 적재 — 딥리서치+전수점검으로 확정된 목록을 순차 등재.

law_sync.py / law_watch.py의 기존 함수를 그대로 재사용한다(중복 구현 금지).
sync_one과 다른 점은 "기존 문서의 갱신"이 아니라 "KB에 전혀 없던 법령의 신규 추가"라는 것뿐 —
검색·조문취득·청킹·문서명·삽입검증·law_watch 등록 로직은 동일하게 따른다.

사용법:
  python add_laws_batch.py --dry-run   # 검색·조문취득까지만, DB 미변경
  python add_laws_batch.py             # 실제 적재(순차, 병렬 금지)
  python add_laws_batch.py --only "위치정보"   # 이름에 해당 문자열 포함된 항목만
"""
import os
import sys
import time
import argparse
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import sb_client
from law_watch import drf_law_search, pick_exact, row_fields, alias_variants, norm_name
from law_sync import (fetch_law_articles, fetch_admrul_articles, chunk_articles,
                       build_doc_name, _law_type_label)

SB_URL = os.getenv("SUPABASE_URL")
SB_KEY = os.getenv("SUPABASE_SERVICE_KEY")

# (검색명, doc_category, target 힌트 or None=자동판별)
# target 힌트: 'law'(법률/시행령/시행규칙) / 'admrul'(고시/훈령/예규/공고) / None(law 먼저 시도 후 admrul)
TARGETS = [
    # ── A. 위치정보/개인정보/통신비밀/기반보호/방미통위설치법 (법률·시행령·시행규칙) ──
    ("위치정보의 보호 및 이용 등에 관한 법률", "위치정보보호법", "law"),
    ("위치정보의 보호 및 이용 등에 관한 법률 시행령", "위치정보보호법_시행령", "law"),
    ("통신비밀보호법", "통신비밀보호법", "law"),
    ("통신비밀보호법 시행령", "통신비밀보호법_시행령", "law"),
    ("개인정보 보호법", "개인정보보호법", "law"),
    ("개인정보 보호법 시행령", "개인정보보호법_시행령", "law"),
    ("정보통신기반 보호법", "정보통신기반보호법", "law"),
    ("정보통신기반 보호법 시행령", "정보통신기반보호법_시행령", "law"),
    ("정보통신기반 보호법 시행규칙", "정보통신기반보호법_시행규칙", "law"),
    ("방송미디어통신위원회의 설치 및 운영에 관한 법률", "방미통위설치법", "law"),
    ("방송미디어통신위원회의 설치 및 운영에 관한 법률 시행령", "방미통위설치법_시행령", "law"),
    ("전기통신사업 회계정리 및 보고에 관한 규정", "전기통신사업법_시행령", "law"),

    # ── A. 고시·행정규칙 18건 ──
    ("위치정보의 관리적ㆍ기술적 보호조치 기준", "위치정보보호법", "admrul"),
    ("개인정보의 안전성 확보조치 기준", "개인정보보호법", "admrul"),
    ("주요정보통신기반시설 취약점 분석ㆍ평가 기준", "정보통신기반보호법", "admrul"),
    ("전기통신설비의 상호접속기준", "전기통신사업법", "admrul"),
    ("설비등의 제공조건 및 대가산정기준", "전기통신사업법", "admrul"),
    ("전기통신번호관리세칙", "전기통신사업법", "admrul"),
    ("이동전화망번호관리기준", "전기통신사업법", "admrul"),
    ("이동전화서비스 번호이동성 시행 등에 관한 기준", "전기통신사업법", "admrul"),
    ("전기통신사업 회계분리기준", "전기통신사업법", "admrul"),
    ("보편적역무손실보전금 산정방법 등에 관한 기준", "전기통신사업법", "admrul"),
    ("도매제공의무사업자의 도매제공의무서비스 대상과 도매제공의 조건ㆍ절차ㆍ방법 및 대가의 산정에 관한 기준", "전기통신사업법", "admrul"),
    ("방송통신사업 금지행위 등에 대한 업무처리규정", "전기통신사업법", "admrul"),
    ("금지행위 위반에 대한 과징금 부과 세부기준", "전기통신사업법", "admrul"),
    ("결합판매의 금지행위 세부 유형 및 심사기준", "전기통신사업법", "admrul"),
    ("이용약관 인가대상 기간통신서비스와 기간통신사업자", "전기통신사업법", "admrul"),
    ("전기통신사업용 무선설비의 기술기준", "기술기준", "admrul"),
    ("정보통신망을 이용한 이동통신단말장치의 지원금 제시행위 시 사전승낙서 게시 기준", "전기통신사업법", "admrul"),
    ("이동통신사업자 등의 자료제출 방법 등에 대한 고시", "전기통신사업법", "admrul"),
    ("본인확인기관 지정 등에 관한 기준", "전기통신사업법", "admrul"),

    # ── B. 운영자 지시 승격 ──
    ("재난문자방송 기준 및 운영규정", "재난통신", "admrul"),

    # ── C. 상향식 전수 점검 발견 16건 ──
    ("방송통신발전기금 분담금 산정 및 부과에 관한 세부사항", "방송통신발전기본법", "admrul"),
    ("방송통신발전기금 분담금 징수 및 부과 등에 관한 사항", "방송통신발전기본법", "admrul"),
    ("전기통신설비의 상호접속ㆍ공동사용 및 정보제공 협정의 인가대상 기간통신사업자", "전기통신사업법", "admrul"),
    ("전기통신설비 의무제공대상 기간통신사업자", "전기통신사업법", "admrul"),
    ("전기통신설비의 공동사용 등의 기준", "전기통신사업법", "admrul"),
    ("중요한 전기통신설비", "전기통신사업법", "admrul"),
    ("주요통신사업자의 통신시설 등급 지정 및 관리 기준", "전기통신사업법", "admrul"),
    ("전기통신설비의 정보제공기준", "전기통신사업법", "admrul"),
    ("전기통신사업자간 불합리하거나 차별적인 조건ㆍ제한 부과의 부당한 행위 세부기준", "전기통신사업법", "admrul"),
    ("위치정보보호 법규 위반에 대한 과징금 부과기준", "위치정보보호법", "admrul"),
    ("긴급구조를 위한 소방기관의 위치정보 이용ㆍ관리 지침", "재난통신", "admrul"),
    ("재난피해자등의 개인 및 위치정보 요청ㆍ제공ㆍ이용지침", "재난통신", "admrul"),
    ("기간통신사업의 양수ㆍ합병 인가 등의 심사기준 및 절차", "전기통신사업법", "admrul"),
    ("공익성심사의 대상이 되는 기간통신사업자의 범위", "전기통신사업법", "admrul"),
    ("기반시설에 해당하는 전기통신설비", "전기통신사업법", "admrul"),
    ("경고문구의 표기 내용 및 방법", "전기통신사업법", "admrul"),

    # ── D. Fable 재검증 추가 3건 ──
    ("요금한도 초과 등의 고지에 관한 기준", "전기통신사업법", "admrul"),
    ("거짓으로 표시된 전화번호로 인한 이용자의 피해 예방 등에 관한 고시", "전기통신사업법", "admrul"),
    ("방송통신위원회 재정 및 알선 등에 관한 규정", "전기통신사업법", "admrul"),

    # ── E. 경계선 3건 ──
    ("국제전화요금 정산계약에 관한 신고방식 및 절차", "전기통신사업법", "admrul"),
    ("재난안전통신망 표준운영절차의 관리와 활용에 관한 규정", "재난통신", "admrul"),
    ("재난방송 및 민방위경보방송의 실시에 관한 기준", "재난통신", "admrul"),

    # ── F. AI 기본법 계열 (2026-08-03) ──
    # 과기정통부 소관 국내 AI 규제 기본법. 시행규칙은 법제처 검색 totalCnt=0(미존재).
    # 고시는 admrul 'AI' 전수 23건 중 아래 1건만 AI 기본법 위임(시행령 §15⑤ 확인 절차);
    # 나머지는 타 부처 조직 훈령·추진단 설치 규정이라 업무 무관으로 제외.
    ("인공지능 발전과 신뢰 기반 조성 등에 관한 기본법", "인공지능기본법", "law"),
    ("인공지능 발전과 신뢰 기반 조성 등에 관한 기본법 시행령", "인공지능기본법_시행령", "law"),
    ("인공지능제품ㆍ서비스 확인 절차 운영에 관한 고시", "인공지능기본법", "admrul"),

    # ── G. AI 인접 도메인 — 지능정보화·데이터·클라우드 (2026-08-03, 전부 과기정통부 소관) ──
    # 지능정보화 기본법: AI 기본법이 기본계획·데이터센터·비상정지 등을 계속 참조하는 체계 모법.
    ("지능정보화 기본법", "지능정보화기본법", "law"),
    ("지능정보화 기본법 시행령", "지능정보화기본법_시행령", "law"),
    ("지능정보화 기본법 시행규칙", "지능정보화기본법_시행규칙", "law"),
    # 데이터산업법: AI 기본법 제2조제5호가 "데이터" 정의를 이 법에서 차용.
    ("데이터 산업진흥 및 이용촉진에 관한 기본법", "데이터산업법", "law"),
    ("데이터 산업진흥 및 이용촉진에 관한 기본법 시행령", "데이터산업법_시행령", "law"),
    ("데이터 산업진흥 및 이용촉진에 관한 기본법 시행규칙", "데이터산업법_시행규칙", "law"),
    # 클라우드컴퓨팅법 + 과기정통부 고시 2건(CSAP 보안인증·품질성능). 행안부 고시는 타 부처라 제외.
    ("클라우드컴퓨팅 발전 및 이용자 보호에 관한 법률", "클라우드컴퓨팅법", "law"),
    ("클라우드컴퓨팅 발전 및 이용자 보호에 관한 법률 시행령", "클라우드컴퓨팅법_시행령", "law"),
    ("클라우드컴퓨팅 발전 및 이용자 보호에 관한 법률 시행규칙", "클라우드컴퓨팅법_시행규칙", "law"),
    ("클라우드컴퓨팅서비스 보안인증에 관한 고시", "클라우드컴퓨팅법", "admrul"),
    ("클라우드컴퓨팅서비스 품질·성능에 관한 기준", "클라우드컴퓨팅법", "admrul"),

    # ── H. 정보통신망법 하위 보안 고시 3건 (2026-08-03, 운영자 지시) ──
    # 이미 등재된 정보통신망법 본법·시행령·시행규칙(family network-act)의 하위 고시.
    # 셋 다 법제처 target=admrul. ISMS-P는 개보위·과기정통부 공동 고시.
    # 집적정보통신시설 보호지침은 법제처 정식명이 "집적정보 통신시설"(띄어쓰기 포함)이라
    # 정식명 그대로 둔다 — build_doc_name이 이 문자열을 doc_name에 그대로 쓴다.
    ("정보보호 및 개인정보보호 관리체계 인증 등에 관한 고시", "정보통신망법", "admrul"),
    ("정보보호 공시에 관한 고시", "정보통신망법", "admrul"),
    ("집적정보 통신시설 보호지침", "정보통신망법", "admrul"),

    # ── I. 공정위 소관 3법 계열 (2026-08-03, 운영자 지시) ──
    # 지금까지 후보를 "과기정통부·방통위가 만든 법"에서만 뽑아 KB에 공정위 소관이 0건이었다.
    # 같은 행위(단말·요금제 온라인 판매 / 광고 표시 / 이용약관)를 다른 부처가 규제하는 축.
    # doc_category는 계열별 신설이 아니라 부처축 1개('공정거래')로 묶는다 — 신설 목적이
    # "다음 점검에서 이 축이 보이게" 하는 것이라, 계열별로 쪼개면 목적을 잃는다.
    # 표시ㆍ광고법 시행규칙은 법제처 검색 결과 없음(미존재) — 이 법은 총리령을 두지 않는다.
    # 법령명 중 'ㆍ'는 법제처 정본 표기 그대로(build_doc_name이 doc_name에 그대로 쓴다).
    ("전자상거래 등에서의 소비자보호에 관한 법률", "공정거래", "law"),
    ("전자상거래 등에서의 소비자보호에 관한 법률 시행령", "공정거래", "law"),
    ("전자상거래 등에서의 소비자보호에 관한 법률 시행규칙", "공정거래", "law"),
    ("표시ㆍ광고의 공정화에 관한 법률", "공정거래", "law"),
    ("표시ㆍ광고의 공정화에 관한 법률 시행령", "공정거래", "law"),
    ("약관의 규제에 관한 법률", "공정거래", "law"),
    ("약관의 규제에 관한 법률 시행령", "공정거래", "law"),
    # 하위 고시·예규 — 공정위 admrul 전수(전자상거래/표시광고/약관 키워드) 중 SKT 실무 접점 3개
    # (단말·요금제 온라인 판매 / "5G 최고속도" 광고 표시 / 이용약관 불공정조항 심사)에
    # 직접 걸리는 것만 채택. 금융상품·부동산·부동산중개 등 타 업종 심사지침 6건은 제외.
    ("전자상거래 등에서의 소비자보호 지침", "공정거래", "admrul"),
    ("전자상거래 등에서의 상품 등의 정보제공에 관한 고시", "공정거래", "admrul"),
    ("중요한 표시·광고사항 고시", "공정거래", "admrul"),
    ("부당한 표시·광고행위의 유형 및 기준 지정고시", "공정거래", "admrul"),
    ("기만적인 표시·광고 심사지침", "공정거래", "admrul"),
    ("주된 표시·광고에 딸린 제한사항의 효과적 전달에 관한 가이드라인", "공정거래", "admrul"),
    ("약관심사지침", "공정거래", "admrul"),

    # ── 위임 대응표(law_delegations, #80)가 드러낸 공백 (2026-08-03) ──
    # 3단비교 정본에서 **전파법이 16개 조문을 무선설비규칙에 위임**하는데 본문이 KB에 없어
    # 그 16건이 전부 끊긴 링크였다. 문서명 추측(family)으로는 계열이 달라 찾을 수 없던 것 —
    # 위임 대응표를 만들고 나서야 드러났다. 전파 분야 핵심 기술기준이므로 등재한다.
    ("무선설비규칙", "전파법", "law"),

    # ── J. 통신사기피해환급법 계열 (2026-08-05, 운영자 지시) ──
    # 전기통신사업자가 직접 수범자인 법(보이스피싱 대응 — 전화번호 이용중지, 지급정지 협조 등)인데
    # KB에 없어서 "KB 등재 법령만 DIFF 분석" 규칙에서 통째로 빠지던 공백.
    # 시행규칙은 법제처 검색 totalCnt=0(미존재) — 이 법은 부령을 두지 않는다.
    # 하위 고시 3건(금융위 「전기통신금융사기 피해 방지에 관한 규정」 등)은 금융위·금감원·경찰청
    # 소관이라 이번 범위에서 제외(운영자 지시 대상은 법률·시행령·시행규칙).
    ("전기통신금융사기 피해 방지 및 피해금 환급에 관한 특별법", "통신사기피해환급법", "law"),
    ("전기통신금융사기 피해 방지 및 피해금 환급에 관한 특별법 시행령", "통신사기피해환급법_시행령", "law"),
    # ── C. 2026-09-04 소급: 과기정통부·방미통위 소관 통신 법령·고시 전수 대조로 빠진 것 (#121) ──
    ("디지털포용법", "디지털포용법", "law"),
    ("디지털포용법 시행령", "디지털포용법_시행령", "law"),
    ("무선설비규칙", "전파법_시행규칙", "law"),
    ("소프트웨어 진흥법", "소프트웨어진흥법", "law"),
    ("소프트웨어 진흥법 시행령", "소프트웨어진흥법_시행령", "law"),
    ("소프트웨어 진흥법 시행규칙", "소프트웨어진흥법_시행규칙", "law"),
    ("인터넷주소자원에 관한 법률", "인터넷주소자원법", "law"),
    ("인터넷주소자원에 관한 법률 시행령", "인터넷주소자원법_시행령", "law"),
    ("전기통신기본법", "전기통신기본법", "law"),
    ("전기통신기본법 시행령", "전기통신기본법_시행령", "law"),
    ("전자문서 및 전자거래 기본법", "전자문서법", "law"),
    ("전자문서 및 전자거래 기본법 시행령", "전자문서법_시행령", "law"),
    ("전자문서 및 전자거래 기본법 시행규칙", "전자문서법_시행규칙", "law"),
    ("전자서명법", "전자서명법", "law"),
    ("전자서명법 시행령", "전자서명법_시행령", "law"),
    ("전자서명법 시행규칙", "전자서명법_시행규칙", "law"),
    ("정보보호산업의 진흥에 관한 법률", "정보보호산업법", "law"),
    ("정보보호산업의 진흥에 관한 법률 시행령", "정보보호산업법_시행령", "law"),
    ("정보보호산업의 진흥에 관한 법률 시행규칙", "정보보호산업법_시행규칙", "law"),
    ("정보통신공사업법", "정보통신공사업법", "law"),
    ("정보통신공사업법 시행령", "정보통신공사업법_시행령", "law"),
    ("정보통신공사업법 시행규칙", "정보통신공사업법_시행규칙", "law"),
    ("정보통신 진흥 및 융합 활성화 등에 관한 특별법", "정보통신융합특별법", "law"),
    ("정보통신 진흥 및 융합 활성화 등에 관한 특별법 시행령", "정보통신융합특별법_시행령", "law"),
    ("정보통신 진흥 및 융합 활성화 등에 관한 특별법 시행규칙", "정보통신융합특별법_시행규칙", "law"),
    ("공인전자문서중계자 설비에 관한 규정", "전자문서법", "admrul"),
    ("기간통신역무가 아닌 전기통신서비스", "전기통신사업법", "admrul"),
    ("대한민국 과학기술정보통신부와 인도네시아 통신디지털부 (舊 통신정보부) 간의 방송통신기자재등의 적합성평가에 대한 상호인정협정", "적합성평가", "admrul"),
    ("대한민국 과학기술정보통신부와 캐나다 혁신과학경제개발부간의 방송통신기자재등에 대한 상호인정협정", "적합성평가", "admrul"),
    ("대한민국 방송통신위원회와 베트남 정보통신부간의 방송통신기자재등에 대한 상호인정협정", "적합성평가", "admrul"),
    ("대한민국 방송통신위원회와 칠레공화국 통신청간의 전기통신기기에 대한 상호인정 협정", "적합성평가", "admrul"),
    ("데이터 가치평가기관 지정 및 운영 등에 관한 고시", "데이터산업법", "admrul"),
    ("데이터산업 기반 조성 및 산업육성 지원 전문기관 지정 고시", "데이터산업법", "admrul"),
    ("데이터안심구역의 지정 및 운영 등에 관한 고시", "데이터산업법", "admrul"),
    ("방송통신표준", "기술기준", "admrul"),
    ("방송통신표준화지침", "기술기준", "admrul"),
    ("번호안내서비스를 제공하지 않아도 되는 경미한 사업", "전기통신사업법", "admrul"),
    ("부가통신서비스 요금신고 대상에서 제외되는 전기통신사업자", "전기통신사업법", "admrul"),
    ("소프트웨어프로세스 품질인증 운영에 관한 지침", "고시", "admrul"),
    ("수출하고자 하는 중고 이동통신단말장치의 분실ㆍ도난 단말장치 여부 확인방법 등에 관한 고시", "전기통신사업법", "admrul"),
    ("시내전화서비스 등 번호이동성 시행에 관한 기준", "전기통신사업법", "admrul"),
    ("신호점번호관리기준", "전기통신사업법", "admrul"),
    ("이동통신단말장치 고유식별번호 공유 전문기관 지정 등에 관한 고시", "전기통신사업법", "admrul"),
    ("자가전기통신설비 목적외 사용의 특례 범위", "전기통신사업법", "admrul"),
    ("전기통신사업자의 통계보고 등에 관한 고시", "전기통신사업법", "admrul"),
    ("전기통신설비 공동구축을 위한 협의회 구성·운영 및 전담기관 지정 등에 관한 고시", "전기통신사업법", "admrul"),
    ("전자파흡수율 측정기준", "전자파", "admrul"),
    ("접근성 품질인증 및 시험평가 등에 관한 고시", "지능정보화기본법", "admrul"),
    ("접지설비·구내통신설비·선로설비 및 통신공동구등에 대한 기술기준", "기술기준", "admrul"),
    ("정보보호 관리등급 부여에 관한 고시", "정보통신망법", "admrul"),
    ("정보보호 사전점검에 관한 고시", "정보통신망법", "admrul"),
    ("정보보호시스템 평가·인증 등에 관한 고시", "정보통신망법", "admrul"),
    ("정보보호 전문서비스 기업 지정 등에 관한 고시", "정보통신망법", "admrul"),
    ("정보보호제품 성능평가 운영지침", "정보통신망법", "admrul"),
    ("정보보호조치에 관한 지침", "정보통신망법", "admrul"),
    ("정보보호 취약점 신고자에 대한 포상업무 위탁 고시", "정보통신망법", "admrul"),
    ("정보통신망연결기기등 정보보호인증에 관한 고시", "정보통신망법", "admrul"),
    ("정보통신설비 유지보수·관리기준", "방송통신설비", "admrul"),
    ("정보통신융합 기술·서비스 등의 품질인증기관 지정", "정보통신융합특별법", "admrul"),
    ("정보통신융합 기술·서비스 등의 품질인증기준", "정보통신융합특별법", "admrul"),
    ("정보통신융합등 기술ㆍ서비스에 대한 신속처리ㆍ임시허가ㆍ실증특례 운영규정", "정보통신융합특별법", "admrul"),
    ("정보통신표준 개발·운영 지침", "기술기준", "admrul"),
    ("중고 이동통신단말장치 안심거래 사업자 인증기준 등에 관한 고시", "전기통신사업법", "admrul"),
    ("통신과금서비스 운영에 관한 고시", "정보통신망법", "admrul"),
    ("통신구 성능개선기준", "방송통신설비", "admrul"),
    ("통신구 최소유지관리기준", "방송통신설비", "admrul"),
    ("통신망 종합관리 지침", "전기통신사업법", "admrul"),
    ("통신설비를 이용한 중계서비스 제공 등에 관한 기준", "방송통신설비", "admrul"),
    ("개인위치정보사업등록 세부심사기준별 평가방법", "위치정보보호법", "admrul"),
    ("개인위치정보사업 양수 및 법인의 합병 등의 인가 세부심사기준별 평가방법", "위치정보보호법", "admrul"),
    ("경제적 이익 등 제공의 부당한 이용자 차별행위에 관한 세부기준", "전기통신사업법", "admrul"),
]


def already_have(sb, law_name):
    """이미 정확히 같은 법령명(괄호 앞부분 완전일치)의 현행 문서가 있으면 반환.

    앞 N자 부분일치는 쓰지 않는다 — "법"과 "법 시행령", "상호접속기준"과
    "상호접속·공동사용 및 정보제공 협정의 인가대상 기간통신사업자"처럼 접두어가 같은
    별개 문서를 같다고 오판해 5건을 잘못 건너뛴 사고가 실제로 있었다.
    """
    key = norm_name(law_name).replace(' ', '')
    r = (sb.table('document_chunks').select('doc_name')
         .eq('status', 'current').ilike('doc_name', f'{law_name}(%').limit(5).execute())
    for row in (r.data or []):
        head = row['doc_name'].split('(')[0]
        if norm_name(head).replace(' ', '') == key:
            return row['doc_name']
    return None


def search_with_fallback(law_name, target_hint):
    targets = [target_hint] if target_hint else ['law', 'admrul']
    for target in targets:
        rows = drf_law_search(law_name, target)
        hit = pick_exact(rows, law_name)
        if hit:
            return target, hit
        for alt in alias_variants(law_name):
            rows = drf_law_search(alt, target)
            hit = pick_exact(rows, alt)
            if hit:
                return target, hit
    return None, None


def add_one(sb, law_name, category, target_hint, dry_run=False):
    existing = already_have(sb, law_name)
    if existing:
        return 'skip', f"이미 보유: {existing}"

    target, hit = search_with_fallback(law_name, target_hint)
    if not hit:
        return 'fail', "법제처 검색 결과 없음"

    mst, law_no, enf = row_fields(hit, target)
    try:
        if target == 'law':
            articles, basic = fetch_law_articles(mst)
            type_token = basic.get('법령구분명') or hit.get('법령구분명')
            org = None
            law_id = str(hit.get('법령ID') or '')
        else:
            articles, basic = fetch_admrul_articles(mst)
            type_token = basic.get('행정규칙종류') or hit.get('행정규칙종류') or '고시'
            org = basic.get('소관부처명') or hit.get('소관부처명') or ''
            law_id = str(hit.get('행정규칙ID') or '')
    except Exception as e:
        return 'fail', f"조문 취득 실패: {str(e)[:120]}"

    # 첨부파일 전용 문서 — 법제처가 조문 대신 "자세한 내용은 상단 메뉴 버튼을 이용" 안내만 준다
    # (지침 §재적재 불가 사례와 동일 유형 — 무선통신매뉴얼·전기안전 통합처리지침에서도 발생).
    # 그대로 넣으면 안내문 1청크가 유일 본문인 빈 문서가 생기므로 여기서 걸러낸다.
    if len(articles) == 1 and articles[0][0] is None and '상단 메뉴' in articles[0][1] and '버튼을 이용' in articles[0][1]:
        return 'fail', "첨부파일 전용 문서(조문 미제공) — 법제처 원문 첨부파일만 존재, API 재적재 불가"

    chunks = chunk_articles(articles)
    if not chunks:
        return 'fail', "조문 취득 결과가 비어 있음(첨부파일 전용 등)"

    new_doc = build_doc_name(law_name, type_token, law_no, enf, org, target)

    # 다른 검색어로 이미 들어간 경우 재확인(정확 문서명 기준)
    dup = (sb.table('document_chunks').select('id', count='exact')
           .eq('doc_name', new_doc).eq('status', 'current').limit(1).execute()).count or 0
    if dup:
        return 'skip', f"이미 보유(정확명): {new_doc}"

    print(f"    → {new_doc}  [{len(chunks)}청크, target={target}]")
    if dry_run:
        return 'ok', f"{new_doc} ({len(chunks)}청크, dry-run)"

    now = datetime.now(timezone.utc).isoformat()
    payload = [{
        'doc_name': new_doc, 'doc_category': category, 'chunk_index': i,
        'content': c['content'], 'article_no': c['article_no'],
        'effective_date': enf, 'notice_no': (law_no if target != 'law' else None),
        'law_id': law_id, 'law_mst': mst, 'status': 'current',
        'is_approved': True,
    } for i, c in enumerate(chunks)]
    for i in range(0, len(payload), 50):
        sb.table('document_chunks').insert(payload[i:i + 50]).execute()

    got = ((sb.table('document_chunks').select('id', count='exact')
            .eq('doc_name', new_doc).limit(1).execute()).count) or 0
    if got != len(payload):
        return 'fail', f"삽입 검증 실패: {len(payload)}청크 중 {got}청크만 확인"

    sb.table('law_watch').upsert({
        'doc_name': new_doc, 'law_name': law_name,
        'law_type_token': type_token, 'api_target': target,
        'law_id': law_id, 'registered_mst': mst,
        'registered_law_no': law_no, 'registered_enf': enf,
        'latest_mst': mst, 'latest_law_no': law_no, 'latest_enf': enf,
        'watch_status': 'watching', 'sync_status': 'current',
        'last_checked_at': now, 'updated_at': now,
        'note': f'add_laws_batch 신규 적재 ({datetime.now():%Y-%m-%d})',
    }, on_conflict='doc_name').execute()

    return 'ok', f"{new_doc} ({len(payload)}청크)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--only', default=None, help='검색명에 이 문자열이 포함된 항목만')
    args = ap.parse_args()

    sb = sb_client.make_client(SB_URL, SB_KEY)
    targets = TARGETS
    if args.only:
        targets = [t for t in targets if args.only in t[0]]
        print(f"--only 필터: {len(targets)}건")

    results = {'ok': [], 'skip': [], 'fail': []}
    for idx, (law_name, category, target_hint) in enumerate(targets, 1):
        print(f"\n[{idx}/{len(targets)}] {law_name}")
        try:
            status, msg = add_one(sb, law_name, category, target_hint, dry_run=args.dry_run)
        except Exception as e:
            status, msg = 'fail', f"예외: {str(e)[:150]}"
        results[status].append((law_name, msg))
        print(f"  [{status}] {msg}")
        time.sleep(0.5)

    print("\n" + "=" * 60)
    print(f"완료: 성공 {len(results['ok'])} / 스킵 {len(results['skip'])} / 실패 {len(results['fail'])}")
    if results['fail']:
        print("\n실패 목록:")
        for name, msg in results['fail']:
            print(f"  - {name}: {msg}")
    if results['skip']:
        print("\n스킵 목록:")
        for name, msg in results['skip']:
            print(f"  - {name}: {msg}")


if __name__ == '__main__':
    main()
