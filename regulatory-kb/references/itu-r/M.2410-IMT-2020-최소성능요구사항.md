---
type: Guideline
title: ITU-R 보고서 M.2410 — IMT-2020(5G) 최소 성능 요구사항
description: 5G 후보 기술이 충족해야 할 국제 최소 성능 기준(최대 전송속도 20Gbps, 지연 1ms 등 13개 지표). 5G 성능을 국제 기준으로 논할 때의 근거. 한국어 요약이며 수치·산식은 영문 원문(R-REP-M.2410-0) 참조
resource: Report ITU-R M.2410-0 (2017-11) "Minimum requirements related to technical performance for IMT-2020 radio interface(s)"
competent_authority: ITU-R (국제전기통신연합 전파통신부문) SG5 WP5D
timestamp: 2026-08-01T00:00:00Z
---

# ITU-R M.2410 — IMT-2020(5G) 최소 성능 요구사항

## 이 문서가 무엇인가

**5G(IMT-2020) 후보 기술이 "5G라고 불릴 자격"을 얻으려면 넘어야 하는 최소 성능선**을 정한 국제 문서다. 2017년 11월 승인.

**권고(Recommendation)가 아니라 보고서(Report)다.** 규범이 아니라 평가 기준 문서라는 뜻인데, 실질적으로는 3GPP 5G NR이 이 기준을 충족했음을 입증해 IMT-2020으로 인정받았으므로 **사실상의 5G 성능 정의**로 통한다.

> **주의**: 대시보드에 한동안 `M.1544`가 "IMT 최소 성능 요구사항"으로 잘못 표기돼 있었다. 그 이름이 가리키는 실제 문서가 **이 M.2410**이다. M.1544는 아마추어무선 자격기준으로 전혀 다른 문서다.

**국문 용어 대응**: 최대 전송속도 = peak data rate, 체감 전송속도 = user experienced data rate, 스펙트럼 효율 = spectral efficiency, 면적당 트래픽 용량 = area traffic capacity, 사용자 평면 지연 = user plane latency, 제어 평면 지연 = control plane latency, 연결 밀도 = connection density, 이동성 = mobility, 신뢰성 = reliability

## 주요 최소 요구값 (원문 확인)

| 지표 | 최소 요구값 | 적용 시나리오 |
|---|---|---|
| **최대 전송속도** | 하향 **20 Gbit/s** / 상향 **10 Gbit/s** | eMBB |
| **사용자 평면 지연** | **4 ms** (eMBB) / **1 ms** (URLLC) | eMBB·URLLC |
| **제어 평면 지연** | **20 ms** (10 ms 권장) | eMBB·URLLC |
| **면적당 트래픽 용량** | 하향 **10 Mbit/s/m²** | 실내 핫스팟 eMBB |
| **연결 밀도** | km²당 다수 기기 (원문 값 확인 필요) | mMTC |

최대 전송속도는 대역을 여러 개 묶을 때 `R = Σ(Wi × SEpi)` 로 합산한다(반송파 집성).

## 5G 3대 이용 시나리오

M.2083(IMT Vision)이 정의한 세 가지에 대해 각각 요구값이 정해진다:

- **eMBB**(enhanced mobile broadband, 향상된 모바일 광대역) — 속도·용량
- **URLLC**(ultra-reliable and low-latency communications, 초고신뢰 저지연) — 지연·신뢰성
- **mMTC**(massive machine type communications, 대규모 사물통신) — 연결 밀도

## SKT 실무 관점에서 왜 중요한가

- **"5G 속도" 논쟁의 국제 기준선**이다. 20 Gbps는 *이론상 최대치이자 평가 조건*이지 실사용 속도가 아니다 — 5G 과장광고 사안에서 이 구분이 쟁점이 된다.
- **6G(IMT-2030) 목표와 비교할 때 출발점**이 된다. M.2160이 6G 능력을 정의하는데, "5G 대비 몇 배"를 말하려면 이 문서의 값이 기준이다.
- 기술 평가 절차는 **Report ITU-R M.2412**가 별도로 정한다(시험 환경·평가 방법).

## 참고

- **정확한 수치·산식·평가 조건은 영문 원문(R-REP-M.2410-0)에 있다.** 이 요약은 문서를 찾아가기 위한 것이며, 인용은 원문에서 할 것.
- 관련 문서: ITU-R M.2083(IMT Vision — 능력 정의), ITU-R M.2150(IMT-2020 상세 규격), ITU-R M.2160(IMT-2030 프레임워크), Report ITU-R M.2412(평가 방법론 — 미보유)
