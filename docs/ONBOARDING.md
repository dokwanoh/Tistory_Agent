# 처음 설정하기

Python 3.11–3.14와 macOS가 필요합니다. 이미지 변환과 브라우저 전달에서 macOS `sips`를 사용합니다. Windows와 Linux의 완전한 실행은 지원하지 않습니다. 오프라인 핵심 검증은 표준 라이브러리만 사용합니다.

Codex에서 저장소를 열고 `$tistory-onboarding 처음 설정을 도와줘`라고 요청하세요. 스킬이 자동 인식되지 않으면 `.agents/skills/tistory-onboarding/SKILL.md`를 직접 읽도록 요청할 수 있습니다. 스킬 형식 안내: [OpenAI 공식 문서](https://developers.openai.com/codex/skills).

에이전트 없이도 저장소 루트에서 실행할 수 있습니다.

```sh
PYTHONPATH=src python -m tistory_growth_os.onboarding
```

블로그 주소, 네 가지 범위 내 주제, 독자·문체, 사용 가능한 모델, 희망 빈도·예산을 묻습니다. 비밀번호·이메일·API 키는 받지 않습니다. 모델을 비워도 오프라인 데모는 가능합니다. 기본 게시 빈도와 비용 상한은 0입니다.

설정은 `.local/profile.json`에 저장되고 Git에서 제외됩니다. 재실행은 기존 파일을 덮어쓰지 않습니다. Unix에서는 파일 권한 0600을 사용합니다. `.env.example`은 설명용 이름 목록이며 자동 로드하지 않습니다. 임시 환경변수 `TISTORY_BLOG_HOST`, `TISTORY_MODEL`은 로컬 설정보다 우선하므로 다중 블로그 작업 전 확인하세요.

## 첫 로컬 결과

```sh
PYTHONPATH=src python -m tistory_growth_os validate-contracts
PYTHONPATH=src python -m tistory_growth_os prepare-review --fixture tests/fixtures/topic_supported.json --output .artifacts/first-review --dry-run
```

출력은 합성 사례의 검토용 자료입니다. 실제 계정에 접속하거나 게시하지 않습니다. 완성 패키지를 게시할 수 있다는 승인이 아니며, 실제 글은 새 출처와 독립 검토가 필요합니다. 같은 출력 경로를 반복할 때는 기존 결과를 보존하고 새 이름을 쓰세요.

## 실사용으로 넘어가기

모델 호출은 별도의 `TISTORY_ALLOW_MODEL_EXECUTION=1` 승인 환경변수가 없으면 차단됩니다. 비용 범위를 확인하고 해당 실행에서만 설정하세요. 단계별 모델은 `TISTORY_MODEL_WRITING`처럼 단계 이름을 붙인 환경변수로 선택할 수 있습니다. 설정 인터뷰는 이 승인 변수를 만들지 않습니다.

온보딩의 주제·독자·문체·빈도·예산은 에이전트가 읽는 편집 계획입니다. 블로그 주소는 게시/관측 경계에서, 모델은 준비 provider에서 실제 사용됩니다. 빈도는 스케줄러가 아니고 예산은 결제사의 강제 한도가 아닙니다. 무인 비용 집행은 제공하지 않습니다.

실행 전에 사용자가 비용·대상·내용을 승인하고, 현재 Tistory 정책과 연결 도구 지원 여부를 확인해야 합니다. 브라우저 어댑터는 별도 선택 의존성(`requirements-browser.txt`)과 자신의 로그인 세션이 필요하며 새 계정에서의 실게시를 보증하지 않습니다. 이전 사용자의 로그인·검수·게시 권한은 제공하지 않습니다. STOP 해제나 새로운 글 저장은 초기 설정에 포함되지 않습니다.
