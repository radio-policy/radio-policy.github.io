-- 20260915063900 assembly_notice_reject_5_offtopic_20260915

-- 2026-09-15 운영자 판단: 밀린 입법예고 5건 중 통신사업자 의무가 걸리는 것이 없어 알림 차단(#171).
--  · 청소년복지 지원법      모바일 청소년증 — 발급 주체가 사회보장정보시스템, 통신사 의무 없음
--  · 전기통신금융사기 특별법 내용은 검찰청법 폐지에 따른 수사권 조정 조문 정비
--  · 농업·농촌 기본법 / 스마트농업 육성법 / 농어업인 삶의 질 특별법
--      제안이유의 'AI·IoT·정보통신기술' 낱말만 걸렸고 통신·ICT 법령 개정이 아님
-- 판정기는 같은 입력에 5건/4건으로 흔들렸다(연속 실행 실측) — 안정화는 별건 과제.
update app_config
   set value = (
         value::jsonb
         || jsonb_build_object(
              'PRC_U2V6T0S9S0A3B1Z2A1Y3X5X3F4G7E4', '260915',
              'PRC_M2L6J0J9H1J1Q1R6P1O6O4M4N4V2V0', '260915',
              'PRC_F2F6B0C8A1B9Z0X9Y4G4H3F1F5E1C5', '260915',
              'PRC_Y2Z6X0N8N1M9M0K9L4K3K2S9S9R1P2', '260915',
              'PRC_K2S6R0R8P1Q9P0P9X4V5W2U5V4T2U0', '260915'
            )
       )::text
 where key = 'assembly_notice_rejected';;
