# 01. AS-IS 프로세스 복원 초안

## 증거 상태

이 문서는 배포용 운영 가설입니다. 새 사용자의 게시글 수, 과거 성과, 카테고리, 운영 방식과 작업 시간은 모두 unknown입니다. 기존 운영자의 자료나 승인을 포함하지 않습니다. 온보딩에서 설정을 수집한 뒤 실측 결과로 갱신합니다.

```mermaid
flowchart LR
  subgraph Owner
    A1[ASIS-001 아이디어 포착]
    A10[ASIS-010 게시]
    A12[ASIS-012 업데이트 결정]
  end
  subgraph Topic_Research[Topic / Research]
    A2[ASIS-002 키워드·경쟁 조사]
    A3[ASIS-003 자료·출처 수집]
  end
  subgraph Writing
    A4[ASIS-004 초안]
    A6[ASIS-006 이미지]
  end
  subgraph QA
    A5[ASIS-005 편집·사실 확인]
    A7[ASIS-007 SEO 메타·내부 링크]
    A9[ASIS-009 미리보기]
  end
  subgraph Tistory
    A8[ASIS-008 편집기 입력]
  end
  subgraph Distribution
    D[배포 흔적 UNKNOWN]
  end
  subgraph Analytics
    A11[ASIS-011 성과 확인]
  end
  A1 --> A2 --> A3 --> A4 --> A5
  A5 --> A6 --> A7 --> A8 --> A9
  A9 -->|수정| A4
  A9 -->|승인 가설| A10 --> D --> A11 --> A12
  A12 -->|갱신 가설| A2
```

## 프로세스 블록

각 블록의 실행 가능한 원본은 [`contracts/process-traceability.json`](../contracts/process-traceability.json)에 있다. 모든 블록은 요구된 `process_id`, `name`, `actor`, `trigger`, `inputs`, `action`, `outputs`, `system_or_tool`, `touch_time`, `wait_time`, `frequency`, `defect_or_rework_rate`, `handoffs`, `evidence`, `confidence` 필드를 가진다.

| ID | 이름 | actor | trigger | inputs → action → outputs | system/tool | 시간·빈도·결함 | handoffs | evidence | confidence |
|---|---|---|---|---|---|---|---|---|---|
| ASIS-001 | 아이디어 포착 | Owner | 독자 질문/소재 | 메모 → 후보 기록 가설 → 미구조화 후보 | UNKNOWN | 모두 unknown | Topic/Research | 장기 휴면 진술, CL-008 | low |
| ASIS-002 | 키워드·경쟁 조사 | Topic/Research | 후보 선택 | 후보 → 수요·경쟁 확인 가설 → 선택 주제 | UNKNOWN | 모두 unknown | Topic/Research | 직접 증거 없음 | low |
| ASIS-003 | 자료·출처 수집 | Topic/Research | 주제 확정 | 주제 → 자료 수집 가설 → 참고 자료 | UNKNOWN | 모두 unknown | Writing | source ledger 없음 | low |
| ASIS-004 | 초안 작성 | Writing | 자료 준비 | 주제·자료 → 작성 가설 → 초안 | UNKNOWN | 모두 unknown | QA | 과거 게시 경험 진술 | low |
| ASIS-005 | 편집·사실 확인 | QA | 초안 완료 | 초안·자료 → 검토 가설 → 편집본 | UNKNOWN | 모두 unknown | Writing/Tistory | QA 기록 없음 | low |
| ASIS-006 | 이미지 준비 | Writing | 편집본 준비 | 이미지 후보 → 준비 가설 → 이미지·alt 후보 | UNKNOWN | 모두 unknown | Tistory | 공개 표본에 이미지 존재; 제작·권리 절차는 unknown | low |
| ASIS-007 | SEO 메타·내부 링크 | QA | 편집본 준비 | 편집본·과거 글 → 메타 결정 가설 → 제목·태그·링크 | UNKNOWN | 모두 unknown | Tistory | 새 사용자 inventory 미수집; 선택 절차 unknown | low |
| ASIS-008 | 티스토리 입력 | Tistory | 패키지 준비 | 본문·미디어·메타 → 편집기 입력 가설 → 편집기 초안 | Tistory editor | 모두 unknown | QA | CL-001, CL-002 | low |
| ASIS-009 | 미리보기 확인 | QA | 편집기 초안 | 초안 → 시각 확인 가설 → 승인/수정 | Tistory preview | 모두 unknown | Writing/Tistory | preview 로그 없음 | low |
| ASIS-010 | 게시 | Owner | 미리보기 승인 | 승인 초안 → 공개 선택 가설 → 공개 URL | Tistory editor | 모두 unknown | Distribution/Analytics | 현재 권한 미확인 | low |
| ASIS-011 | 성과 확인 | Analytics | 게시 후 | URL·지표 → 성과 확인 가설 → 관찰 | UNKNOWN | 모두 unknown | Owner | CL-007, CL-011 | low |
| ASIS-012 | 업데이트 여부 | Owner | 성과/노후화 인지 | 관찰·주장 → 유지/갱신/통합 판단 가설 → 후보 | UNKNOWN | 모두 unknown | Research/Writing | 갱신 로그 없음 | low |

## 검증 계획

온보딩 뒤 사용자 소유의 공개 URL 및 허가된 분석 자료로 실제 절차를 확인합니다. 작업 시간과 병목은 계측 전 UNKNOWN이며 과거 운영자를 새 사용자로 오인하지 않습니다. 증거에 따라 블록을 삭제·분할하고 비공개 데이터 접근은 별도로 승인받습니다.
