# 07. 보안·정책·준수 경계

## 현재 확인된 정책 근거

최종 재확인일은 2026-09-06 KST다. 티스토리는 공식 Open API 종료를 공지했고(CL-001), 공식 대체 쓰기 API는 확인되지 않았다. Google은 AI 보조 자체보다 사람 대상 가치와 scaled low-value 조작 여부를 기준으로 판단한다(CL-003). Naver는 독창성과 실제 경험·관점을 더한 콘텐츠를 권고한다(CL-004). AdSense는 genuine user interest, 인위 상호작용 금지, 비기만 배치를 요구한다(CL-005). 경제적 이해관계와 AI 가상인물 추천은 현행 KFTC 표시 지침을 적용한다(CL-006/012). Tistory 공지에서 직접 확인된 금지 광고 형식은 anchor와 offerwall이며, 다른 형식은 별도 공식 근거 없이 이 allowlist gate에 추가하지 않는다(CL-010).

## fail-closed gate

| gate | 통과 조건 | 실패 처리 |
|---|---|---|
| Source/Claim | 핵심 주장에 출처·확인일·연결 | 주장 축소 또는 차단 |
| Owner experience | 실제 경험 표시에 owner evidence | `OWNER_EVIDENCE_REQUIRED` |
| Originality | 복제·스피닝·도어웨이 아님 | 게시 후보 제외 |
| Disclosure | 광고·제휴·협찬·AI persona 조건별 고지 | `DISCLOSURE_REQUIRED` |
| Media rights | 라이선스·출처·alt 기록 | 자산 제외/차단 |
| Platform ads | anchor/offerwall 없음 | `PROHIBITED_AD_FORMAT` |
| Privacy | controller·목적·vendor·보존·이전 판단 승인 | live collection 차단 |
| Publish authority | 지원 경로·현행 약관·owner 승인 | offline handoff에서 정지 |

## 비밀과 계정

비밀번호, cookie, API key는 채팅·로그·source·fixture에 저장하지 않는다. `.env.example`은 이름만 포함할 수 있고 실제 값은 환경 변수 또는 승인된 secret store로 주입한다. CAPTCHA, MFA, 로그인 보호를 우회하지 않는다. 현재 Milestone 2는 credential을 요청하거나 읽지 않으며 네트워크 import와 외부 쓰기 adapter를 포함하지 않는다.

## 게시·복구 통제

초기 상태는 `approval_required`다. 실제 게시, 예약, 기존 글 수정, 비공개 전환, 삭제는 명시 승인 전 금지한다. 미래 브라우저 보조가 검토되더라도 사용자가 직접 로그인한 세션, draft 우선, 속도·재시도 제한, idempotency key, DOM/스크린샷 검증, 실패 즉시 중단, 사후 실제 URL·제목·공개 상태·본문 hash·이미지·링크·카테고리·태그 재검증이 필요하다. 삭제, 대량 수정, 광고·결제·법적 고지는 항상 별도 승인이다.

## 개인정보와 관측

Search Console, GA4, Naver Search Advisor, 광고/제휴 데이터는 owner 승인과 property scope가 확인되기 전 수집하지 않는다. Naver 보고서는 전체·실시간 트래픽으로 표현하지 않고 surface, 기간, update 기준일, 수집일, top-30 truncation, 최대 90일 보존을 기록한다. 실제 controller·processor 관계가 미확정이므로 법률 결론을 자동 생성하지 않고 `OWNER_DECISION_REQUIRED`로 둔다.
