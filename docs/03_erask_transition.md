# 03. ERASK+C 전환과 추적성

## 고정 어휘

- **E — Erase**: 가치가 없거나 위험한 단계를 제거한다.
- **R — Replace**: 취약한 수작업/도구를 더 안전한 계약·자동화로 대체한다.
- **A — Assist**: 인간 판단을 유지하고 조사·비교·검증을 보조한다.
- **S — reStruct**: 순서, 병렬성, 핸드오프, batch, 승인 지점을 재구성한다.
- **K — Keep**: 차별화·책임·고위험 판단을 인간 중심으로 유지한다.
- **C — Create**: AS-IS에 없지만 목표·BDW·통제상 필요한 블록을 만든다.

아래 12개 AS-IS 블록은 각각 정확히 한 개의 주 전환과 한 개의 TO-BE 블록으로 매핑된다. 보조 전환은 주 전환을 대체하지 않는다. `Create`는 기존 AS-IS가 없는 신설 블록이라 별도 표에 둔다.

## 완전 추적성 matrix

| AS-IS ID | 문제/기회 | BDW 근거 | ERASK(+C) | TO-BE ID | 자동화 수준 | 인간 책임 | 테스트 | KPI | 위험/통제 |
|---|---|---|---|---|---|---|---|---|---|
| ASIS-001 | 비구조 아이디어 | 기록·도구 미확인 | S 주, A 보조 | TOBE-001 | assisted | 경험 범위 승인 | TopicCandidate 계약 | 유효 후보 전환율 | owner 사실 추정 금지 |
| ASIS-002 | 일관된 기회 비교 부재 | 기준 미확인 | A 주, S 보조 | TOBE-002 | assisted | 포트폴리오 승인 | 점수 unknown 처리 | 선정 적중률 | 검색량 단독 최적화 금지 |
| ASIS-003 | 주장·출처 연결 부재 | ledger 없음 | R 주, A 보조 | TOBE-003 | assisted | 출처 적합성 확인 | 무근거 주장 차단 | evidence coverage | 확인일·충돌 기록 |
| ASIS-004 | brief와 작성 혼합 | 초안 이력 없음 | A 주, S 보조 | TOBE-004 | assisted | 독창 관점·경험 | golden draft | first-pass 통과율 | 허위 체험 차단 |
| ASIS-005 | QA 기준·흔적 부재 | QA 로그 없음 | S 주, A/K 보조 | TOBE-005 | hybrid | 고위험·최종 승인 | 품질·정책 게이트 | 재작업률 | 실패 시 stop |
| ASIS-006 | 미디어 권리·alt 미확정 | inventory 없음 | A 주, S 보조 | TOBE-006 | assisted | 권리·표현 승인 | asset manifest 검사 | 미디어 결함률 | 무단 자산 금지 |
| ASIS-007 | 잠식·링크 맥락 불명 | blog inventory 없음 | A 주, S 보조 | TOBE-007 | assisted | 제목·링크 승인 | 중복 intent 검사 | 잠식 탐지율 | stuffing 금지 |
| ASIS-008 | 입력 결함·공식 API 부재 | CL-001/002 | R 주, S 보조 | TOBE-008 | offline automated | 실제 입력 승인 | dry-run bundle | 패키징 결함률 | 외부 쓰기 0 |
| ASIS-009 | 육안 검수 왕복 | preview 로그 없음 | S 주, A/K 보조 | TOBE-009 | hybrid | 시각 승인 | 브라우저 렌더 QA | 렌더 결함률 | 실패 시 승인 불가 |
| ASIS-010 | 자동 게시 경로 미확인 | CL-001/002 | K 주 | TOBE-010 | manual | 로그인·게시 | published 상태 도달 불가 | 중복·rollback률 | 명시 승인 |
| ASIS-011 | 부분·지연 지표 | CL-007/011 | S 주, A 보조 | TOBE-011 | authorization blocked | 접근·보존 승인 | unknown≠0 | 데이터 품질 | 무승인 수집 금지 |
| ASIS-012 | 갱신 학습 부재 | 로그·baseline 없음 | S 주, A/K 보조 | TOBE-012 | recommendation | 갱신·실험 승인 | 합격선 하향 차단 | refresh SLA | canary·rollback |

## Create 정당화

| 신설 ID | 블록 | BDW/목표 근거 | 책임·통제 |
|---|---|---|---|
| TOBE-C01 | 정책 근거 감시 | 정책의 시점 변경이 모든 게시 게이트에 영향 | 공식 출처·확인일·만료일, 불명확하면 stop |
| TOBE-C02 | claim ledger | ASIS-003의 근거 누락과 허위 체험 위험 | 핵심 주장↔evidence, owner experience 별도 증거 |
| TOBE-C03 | publish manifest·감사 로그 | ASIS-008/010의 재시도·중복·복구 위험 | idempotency key, body hash, 승인 상태, 외부 쓰기 수 |
| TOBE-C04 | incident·rollback | 테스트 실패를 다음 단계로 넘기지 않는 원칙 | 실패 기록, kill switch, rollback 자료, 회귀 테스트 |

## 제거(E) 판단

현재 확인된 실제 단계가 없어 기존 블록 자체를 Erase로 단정하지 않는다. 대신 미래 설계에서 근거 없는 주장 생성, 문장 치환형 대량 발행, 무단 스크래핑, 비공식 API 쓰기, 자동 댓글, 정책 우회를 명시적으로 제거한다. AS-IS 인터뷰에서 가치 없는 중복 입력이 확인되면 그때 E 매핑 변경을 의사결정 기록과 테스트로 남긴다.
