# Tistory Agent

한국어 티스토리 콘텐츠를 근거 수집 → 작성 → 검토 → 로컬 미리보기로 준비하는 배포용 프로젝트입니다. 기존 운영자의 글, 성과자료, 계정·브라우저 정보, 게시 승인과 운영 이력을 포함하지 않습니다.

## Codex에서 바로 시작하기

저장소를 Codex에서 연 뒤 아래 문구를 그대로 입력하면 신규 사용자 온보딩 인터뷰가 시작됩니다.

> `$tistory-onboarding 처음 설정을 도와줘`

스킬이 자동으로 인식되지 않으면 `.agents/skills/tistory-onboarding/SKILL.md`를 읽고 온보딩을 진행해 달라고 요청하세요.

## 처음 시작하기

1. 이 저장소를 내려받고 Codex에서 폴더를 엽니다.
2. 위 문구를 입력해 블로그 주소, 주제, 독자·문체, 모델, 빈도·예산 인터뷰에 답합니다. 로그인 비밀번호나 API 키는 묻지 않습니다.
3. 합성 사례로 로컬 검토 자료를 만들어 확인합니다.

Python 3.11–3.14와 macOS가 필요합니다. 브라우저·이미지 전달 경로가 macOS `sips`를 사용합니다. 초기 설정과 오프라인 핵심 검증은 표준 라이브러리만으로 실행됩니다.

```sh
PYTHONPATH=src python -m tistory_growth_os.onboarding
PYTHONPATH=src python -m tistory_growth_os validate-contracts
PYTHONPATH=src python -m tistory_growth_os prepare-review --fixture tests/fixtures/topic_supported.json --output .artifacts/first-review --dry-run
```

[온보딩 상세](docs/ONBOARDING.md) · [보안·배포 점검](docs/DISTRIBUTION.md)

## 제공 범위

- 근거·주장·ArticleSpec 계약, 품질 게이트, HTML 렌더링, 검토 패키지, 중복 방지와 상태 추적
- 선택적 Codex 준비 어댑터와 Tistory 브라우저 전달 코드. 모델·블로그 주소는 사용자 설정으로 분리
- 자동 설정 인터뷰 스킬, 개인 설정 Git 제외, 배포 내용 검사와 CI
- 주제 범위: 금융/보험, 법률, 부동산, IT/소프트웨어

초기 상태는 **드라이런**입니다. 설치나 인터뷰만으로 실제 글이 게시되거나 예약되지 않습니다. 온라인 준비는 비용 승인이 필요하며, 실제 전달은 현행 정책 확인·사용자 로그인·독립 검토·개별 승인을 별도로 거칩니다. 새 계정에서의 실게시 및 모든 운영체제 호환성을 보증하지 않습니다.

## 개발 검증

기존 개발 환경에 pytest와 선택적 브라우저 의존성이 있어야 전체 테스트를 수집할 수 있습니다. 새 환경에서는 설치 범위를 먼저 확인하세요.

```sh
uv venv
uv pip install pytest basedpyright -r requirements-browser.txt
PYTHONPATH=src uv run --no-project python -m pytest -q
PYTHONPATH=src uv run --no-project python -m tistory_growth_os.release_audit
```

실계정 접속 없이 테스트합니다. `browser_tests/`는 별도의 로컬 UI fixture 테스트이며 Chrome/Playwright 환경이 필요합니다. 기존 운영 조직의 개인 메모·디자인 상태를 검사하던 테스트는 배포하지 않으며, 실행 코드의 회귀 테스트는 유지합니다.

재배포 라이선스는 아직 지정하지 않았습니다. 제3자의 수정·상업적 재배포 권한은 별도 라이선스 결정이 필요합니다.
