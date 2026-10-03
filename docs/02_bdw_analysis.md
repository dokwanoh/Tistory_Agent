# 02. BDW 분석

## 계산 규칙과 데이터 한계

`priority_score = impact × frequency × delay_or_cost × confidence`를 사용한다. 현재 `impact`, `frequency`, `delay_or_cost`의 관측값이 없으므로 숫자 점수를 만들지 않는다. `confidence`도 low라는 서술 등급만 있으며 임의의 소수로 치환하지 않는다. 따라서 아래 우선순위는 정책·복구 관점의 선행 조사 순서이며 정량 랭킹이 아니다. 첫 4주 instrumentation으로 각 단계의 시작/종료, 대기 사유, 수정 횟수, defect code, 모델 비용, 외부 쓰기 수를 수집한 뒤 계산한다.

| AS-IS | B/D/W 가설 | 증거 | 근본 원인 가설 | 영향 KPI | 빠른 개선 | 장기 개선 | 측정 방법 |
|---|---|---|---|---|---|---|---|
| ASIS-001 | W: 아이디어 유실·중복 | 도구·기록 없음 | 구조화 intake 부재 | 후보→brief 전환율 | TopicCandidate 양식 | portfolio registry | 후보 수·중복률·queue age |
| ASIS-002 | B: owner 판단 의존, D: 반복 SERP 탐색 | 기준 미확인 | 조정 가능한 점수 계약 부재 | 선정 적중률, touch time | 점수 요인과 unknown 분리 | 성과 기반 가중치 보정 | 의사결정 시간·후속 성과 |
| ASIS-003 | D/W: 재탐색·미사용 자료 | source ledger 없음 | claim↔source 연결 부재 | evidence coverage | evidence pack 템플릿 | 정책 만료·출처 충돌 감시 | 자료별 사용 여부·확인일 |
| ASIS-004 | B: 단일 작성자, W: 근거 없는 재작성 | 초안 기록 없음 | brief·claim 상태 혼합 | first-pass 통과율 | brief 선행 | 구조화 composer/eval | 작성 시간·수정 사유 |
| ASIS-005 | B: 승인, D: 수정 왕복 | QA 기준·로그 없음 | 게이트와 stop condition 부재 | 결함률·재작업률 | 품질 체크리스트 | 결정론+독립 grader | gate별 실패·왕복 수 |
| ASIS-006 | D/W: 이미지 탐색·미사용 자산 | inventory 없음 | 라이선스·alt 계약 부재 | 미디어 결함률 | 자산 manifest | media manager | 자산당 시간·권리 누락 |
| ASIS-007 | W: 중복 주제·부자연 링크 | blog inventory 없음 | 내부 링크 그래프 부재 | 잠식 탐지율 | 기존 글 inventory | cluster graph | 중복 intent·링크 오류 |
| ASIS-008 | D/W: 복사·붙여넣기·재로그인 | CL-001 API 종료 | 공식 쓰기 adapter 부재 | 패키징 결함률 | offline bundle | 승인된 지원 경로 adapter | 입력 시간·렌더 diff |
| ASIS-009 | B/D: 육안 QA와 왕복 | preview 로그 없음 | 재현 가능한 렌더 QA 부재 | 렌더 결함률 | 로컬 HTML preview | 브라우저 QA+manifest | viewport별 defect code |
| ASIS-010 | B: owner 승인, 위험: 중복 게시 | 현재 권한 미확인 | idempotency·사후 검증 부재 | 중복·rollback률 | approval_required 유지 | 승인된 canary adapter | key 재실행·공개상태 확인 |
| ASIS-011 | D/W: 지연·부분 지표 오해 | CL-007·CL-011 | 출처·표면·기간 메타 부재 | 데이터 품질 | unknown≠0 계약 | authorized collector | freshness·coverage·truncation |
| ASIS-012 | W: 성과 미반영·노후 주장 방치 | refresh 로그 없음 | SLA·실험 기록 부재 | refresh SLA·증분 효과 | review date 기록 | governed evolution | overdue ratio·canary delta |

## 가장 먼저 계측할 BDW

안전 우선의 초기 관찰 대상은 ASIS-003/005/008/010이다. 근거 누락과 품질 게이트 실패는 독자 피해와 정책 위험을 만들고, 입력·게시의 비멱등성은 되돌리기 어려운 외부 상태를 만든다. 다만 실제 병목이라는 확정 표현은 쓰지 않는다. 최소 표본 10건 또는 4주 중 먼저 충족되는 시점까지 stage event를 기록하고, 소요시간 중앙값·상위 90백분위, 대기 사유, first-pass 결과, 재작업 원인을 비교한다.

## 새 사용자 자료로 검증

기존 글의 규모·주제·성과는 아직 모릅니다. 허가된 inventory를 확보한 뒤 노후 주장, 주제 중복, 갱신 필요성을 측정합니다. 다른 운영자의 수치나 사례를 추정 근거로 가져오지 않습니다.

## instrumentation 계약

이벤트는 `article_id`, `process_id`, `state_from`, `state_to`, `started_at`, `ended_at`, `actor`, `result_code`, `rework_count`, `external_write_count`, `evidence_ids`를 가진다. 비용 미승인 상태에서는 모델 비용을 발생시키지 않으며 `cost_status=unknown_not_incurred`처럼 0과 미관측을 구분한다. 사람 시간은 사용자가 타이머 또는 완료 시 입력할 수 있게 하고 감시형 추적을 기본값으로 두지 않는다.
