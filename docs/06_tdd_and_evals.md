# 06. TDD와 평가 전략

## 실패 우선 계약

중요 동작은 Red → Green → Refactor 순서로 개발한다. 테스트는 자연어 문구를 고정하지 않고 상태, ID, schema field, error code, hash, 파일 존재/부재처럼 기계가 소비하는 계약을 검증한다. 각 마일스톤 전 test, typecheck, compile, audit, dry-run을 실행하고 결과와 artifact path를 STATUS.md에 남긴다.

| 계층 | 우선 검증 |
|---|---|
| Unit | opportunity 점수의 unknown 처리, 상태 전이, slug/날짜, retry/stop, idempotency |
| Schema | TopicCandidate부터 EvolutionProposal까지 입출력·버전·unknown field |
| Contract | 모델·검색·분석·이미지·Tistory adapter 오류 envelope; 미구현 adapter는 호출 불가 |
| Golden | evidence, brief, draft, HTML의 구조와 invariant; 산문 전체 snapshot은 금지 |
| Model eval | 근거율, claim-source 일치, 의도, 독창성, 브랜드, 정책, 비용·지연 |
| Integration | fixture topic → evidence → brief → draft → QA → package dry-run |
| E2E | CLI의 happy, unsupported claim, owner experience, malformed, replay |
| Failure injection | JSON 파손, 부분 결과, 정책 evidence 만료, 이미지 실패, idempotency 충돌 |
| Regression | 운영 incident와 발견된 결함을 영구 재현 |

## 핵심 불변 조건

1. `dry_run=true`에서 외부 쓰기는 0이다.
2. quality gate 실패 콘텐츠는 bundle/publish manifest를 만들 수 없다.
3. 동일 idempotency key 재실행은 새 글이나 다른 body hash를 만들지 않는다.
4. 핵심 사실 주장은 유효 SourceEvidence 없이 통과하지 않는다.
5. 실제 경험 표시는 owner evidence 없이는 차단한다.
6. 중복 의도는 update/merge/differentiate 결정 없이 통과하지 않는다.
7. 게시 성공은 클릭 완료가 아니라 공개 상태·본문 hash·링크·이미지 재검증으로 정의한다.
8. 평가 합격선·정책·권한을 낮추는 EvolutionProposal은 자동 승격하지 않는다.
9. 검토용 candidate JSON 생성은 승인 기록이나 승인 패키지를 만들지 않는다. 정상 run은 원본 요청으로 재생성하고 별도 검수와의 일치를 확인한다.

## Milestone 2 acceptance 시나리오

- 지원 fixture와 일치하는 유효한 별도 검수가 있을 때만 `READY_FOR_APPROVAL`, `approval_required`, `external_write_count=0`인 완전한 editor-ready bundle을 만든다. 합성 검수는 임시 테스트 프로젝트에만 둔다.
- evidence 없는 핵심 주장은 `CLAIM_EVIDENCE_REQUIRED`, owner 증거 없는 체험은 `OWNER_EVIDENCE_REQUIRED`로 종료하고 bundle을 만들지 않는다.
- malformed fixture는 `CONTRACT_INVALID`로 fail closed하고 diagnostics 외의 산출물이 없다.
- 같은 key를 두 번 실행하면 manifest와 body hash가 같고 두 번째 audit event는 replay를 나타낸다.
- 생성된 HTML은 실제 loopback browser에서 제목, 목차, 출처 링크, alt가 있는 placeholder를 보이며 서버 종료 후 포트가 닫힌다.

## 의미 평가의 통제

LLM만으로 LLM을 신뢰하지 않는다. 날짜·URL·필수 필드·evidence coverage·링크·alt·금지 광고 형식은 결정론적으로 검사한다. 검색 의도 충족, 독창성, 브랜드 같은 의미 판단은 독립 rubric grader와 표본 인간 검수를 결합하고 disagreement를 기록한다. 모델 출력 parse 실패율, 재시도 횟수, 비용, 지연을 관측하며 같은 품질이면 더 단순하고 저렴한 구성을 택한다.

## 다음 로컬 증분: 원고별 검수와 최신성 결합

이 배포본의 실제 테스트 결과는 새 환경에서 재실행해야 합니다. 기존 운영자의 합격 기록·접근성 검사 제외 지침·게시 승인을 포함하지 않습니다. 온보딩과 배포 개인정보 회귀 테스트도 실행하세요.
