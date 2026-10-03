# 05. 기능 아키텍처

## 선택

Milestone 2는 Python 3.11 표준 라이브러리 기반 단일 패키지와 로컬 파일 artifact만 사용한다. 설치 승인이 없는 `uv`, Pydantic, jsonschema, ruff 또는 외부 SaaS를 추가하지 않는다. 공개 데이터 계약은 체크인된 JSON Schema로, 런타임 불변 조건은 frozen/slotted dataclass와 결정론적 boundary parser로 보호한다. 한 언어, 한 실행 표면, 구조화된 감사 로그, `dry_run` 고정이 현재 복잡성에 맞는다.

```mermaid
flowchart TB
  CLI[CLI / commands] --> APP[Pipeline orchestrator]
  APP --> DOMAIN[Domain core & state machine]
  APP --> POLICY[Policy / quality gates]
  APP --> RENDER[Renderer / preview package]
  APP --> STORE[Local atomic artifact store]
  CONTRACTS[JSON Schema & typed decoder] --> CLI
  CONTRACTS --> DOMAIN
  AUDIT[Audit JSONL] <-- APP
  MODEL[Future model adapter] -. replaceable .-> APP
  SEARCH[Future search/analytics connectors] -. authorization .-> APP
  TISTORY[Future Tistory adapter] -. explicit approval .-> APP
```

## capability 경계

Offline vertical slice는 Existing Blog Auditor의 로컬 계약 검사, Topic Portfolio Planner의 fixture 입력, Research & Source Pack Builder, Brief Builder, Article Composer, Claim/Fact Checker, Originality/Cannibalization 규칙, Brand/Readability/Accessibility 검사, SEO/Internal Link 계획, Media manifest, Tistory Renderer/Previewer, local artifact store를 관통한다. Telemetry Collector, 실제 Publish Adapter, Experiment Manager, Refresh/Merge/Retire Engine, Self-Evolution Controller는 schema와 명시적 seam만 남기고 실행하지 않는다.

Existing Blog Auditor의 첫 실행 가능한 slice는 `classify-public-inventory`다. 외부에서 읽기 전용으로 확보한 strict metadata snapshot을 typed value로 파싱하고, 제목·게시일·카테고리·canonical만으로 intent hint, freshness, risk, action candidate를 결정론적으로 분류한다. 본문·description은 계약에서 허용하지 않으며 `style_analysis_performed=false`를 출력한다. Python runtime에는 HTTP client가 없고 remote fetch도 하지 않는다.

도메인 코어는 모델 이름, Codex/OMO 명령, 브라우저 selector, 계정 세션을 모른다. LLM adapter는 이후 구조화 출력·비용·지연·재시도 계약 뒤에만 연결한다. Tistory adapter는 공식 지원 경로가 확인되기 전 offline export 구현 하나뿐이다. 저장소는 성공 시 원자적 bundle, 실패 시 diagnostics를 분리하고 동일 idempotency key의 재실행에서 새 콘텐츠 정체성을 만들지 않는다.

Blocked 진단에는 `article-draft.json`이 포함되어 실제 평가한 조합 원고를 읽을 수 있다(ADR-019). `quality_status=blocked`를 유지하며 HTML·manifest·승인 bundle은 없다. 잘못된 입력에는 원고가 생성되지 않는다. Markdown 초안과 조합 원고는 별도 표현물이므로 하나의 검수 결과를 다른 표현물의 승인으로 재사용하지 않는다. 진단 원고 역시 비밀·개인정보를 입력하지 않는 로컬 자료 경계를 따른다.

## 의존성 방향과 보안 경계

`commands → pipeline → domain` 방향만 허용하고 domain이 command, filesystem, 모델 또는 웹을 import하지 않게 한다. 외부 입력은 boundary에서 중복 JSON 키, 비표준 수, unknown field, 경로 이탈을 거부한 뒤 typed value로 바꾼다. output root 바깥 쓰기, symlink 대상, remote URL fetch, secret 읽기는 Milestone 2에 없다. 로컬 artifact write는 외부 쓰기가 아니지만 감사 로그에 `external_write_count=0`을 남긴다.

## 향후 확장 조건

실제 병목 측정 없이 마이크로서비스, queue, vector DB, 다중 agent 런타임을 도입하지 않는다. 모델·검색·분석·이미지·게시 adapter는 contract test와 failure injection을 먼저 만든 뒤 추가한다. 게시 adapter는 지원성·약관·승인·멱등성·사후 검증이 모두 준비되기 전에는 `published` 상태를 만들 수 없다. 아키텍처 변경은 DECISIONS.md에 대안·비용·가드레일을 기록한다.
