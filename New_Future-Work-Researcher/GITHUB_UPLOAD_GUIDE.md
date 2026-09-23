# CoT1~CoT5 GitHub 업로드 파일 가이드

공개 목적은 **CoT1 → CoT2 → CoT3 → Future Work → CoT4(실현가능성) → CoT5(신규성)의 전체 실험 코드와 실행 방법을 제공하는 것**이다.
단, **CoT5에서 사용하는 로컬 문헌 DB와 파생 데이터는 공개하지 않는다.** 따라서 저장소를 내려받는 것만으로 DB 연동 신규성 실험까지 실행할 수는 없으며, 사용자가 호환 DB와 API 키 등 실행 환경을 직접 준비해야 한다. CoT5 실행·검색 코드는 그대로 제공한다.

아래는 업로드 기준을 디렉토리별로 정리한 것이다. 현재 존재하는 파일 목록만을 뜻하지 않으며, 추가 작성할 항목도 표시했다. 분류는 **올릴 것 / 안 올릴 것** 두 가지이며, 소스 디렉토리 안에 있더라도 실제 DB·비밀정보·실험 산출물은 제외한다.

## 올릴 것

```text
Future-Work-Researcher/
├── CoT1.py                          # 목표 분해
├── CoT2.py                          # 한계 추출
├── CoT3.py                          # 교차 비교
├── CoT4.py                          # 실현가능성 검사
├── CoT5.py                          # 신규성 검사: DB 연결·검색 코드 포함
├── run_future_work.py               # Future Work 제안 생성
├── run_cot4_then_cot5.py             # CoT4 통과 후 CoT5 실행
├── global_state.py
│
├── requirements.txt                 # 추가 작성 필요: CoT1~3 및 Future Work 의존성
├── requirements-cot4.txt
├── requirements-cot5.txt
├── config.cot5.yml.example           # 실제 키·개인 경로 없이 제공
├── .env.example                     # 추가 작성 필요: 환경변수 이름과 자리표시자
├── .gitignore
├── .gitmodules                      # 외부 구현을 submodule로 제공하는 경우
│
├── README.md                        # 전체 설치·실행 방법 작성
├── KOREA_README.md                   # 있는 경우 포함
├── GITHUB_UPLOAD_GUIDE.md
│
├── CoT3_judge_test.py
├── test_cot4_then_cot5.py
│
├── research_agent/
│   └── **/*.py                      # 공통 에이전트·검색·검증 코드
│
├── CoT4/
│   ├── pyproject.toml
│   ├── README.md
│   ├── KOREA_README.md               # 있는 경우 포함
│   ├── src/cot4/
│   │   └── **/*.py
│   ├── examples/
│   │   └── idea.json
│   └── tests/
│       └── **/*.py
│
├── CoT5/
│   ├── pyproject.toml
│   ├── README.md                    # DB 구조·연결 방법과 DB 미제공 제한 명시
│   ├── KOREA_README.md               # 있는 경우 포함
│   ├── src/cot5/
│   │   └── **/*.py                   # DB 연결·검색 코드 포함
│   ├── examples/
│   │   └── idea.json
│   └── tests/
│       └── **/*.py                   # DB/API/GPU 의존 테스트도 코드는 공개
│
├── sample_inputs/                   # 추가 준비 필요
│   └── 직접 작성한 소형·비식별 예시 입력
│
└── external/
    └── idea_novelty_checker/
        ├── 실행에 필요한 Python 소스
        ├── 의존성 파일
        ├── 필수 프롬프트·incontext_examples 등의 정적 리소스
        ├── 사용법 문서
        └── 라이선스·저작권 고지
```

- **문서:** 설치, 입력 준비, 단계별 실행, 단계 간 출력 연결 방법을 안내한다. 없는 문서는 업로드 전에 작성하며, 기존 문서에서도 비밀정보와 실제 연구 데이터를 제거한다.
- **DB 구조:** `CoT5/README.md`에 필수 테이블·컬럼과 연결 방법을 안내한다. 실제 레코드·임베딩·인덱스는 포함하지 않는다.
- **실행 제한:** API 키 등은 사용자가 준비하며, **CoT5 DB 연동 실험은 호환 DB를 직접 준비해야 실행 가능**하다고 명시한다.
- **샘플 입력:** 실제 연구 논문·기존 실험 입력·DB 복제본이 아닌 직접 작성한 예시만 포함한다.
- **테스트:** `test_local_arxiv_retrieval.py` 등 DB 의존 테스트도 코드만 공개한다. DB/API/GPU가 필요한 테스트는 실행 조건을 안내하며, 테스트 데이터로 실제 DB를 포함하지 않는다.
- **외부 구현:** 필요한 파일을 직접 포함하거나 submodule로 제공한다. 직접 포함 시 라이선스·재배포 조건을 확인한다. submodule 방식이면 루트 `.gitmodules`와 Gitlink를 함께 관리하고, 참조 저장소·커밋에도 비공개 DB가 없어야 한다. 두 방식을 중복 적용하지 않는다.
- **외부 구현 경로:** `CoT5.py`가 참조하는 루트 `external/idea_novelty_checker` 경로가 clone 후 준비되어야 한다. `CoT5/` 내부의 `.gitmodules`만으로 대체하지 않는다.

## 안 올릴 것

```text
Future-Work-Researcher/
├── .env
├── config.yml
├── .current_experiment_path
├── .git/                            # 내부 메타데이터를 업로드 파일로 복사하지 않음
│
├── results/                         # 실제 실험 결과
├── cache_*/                         # LLM 응답·다운로드·중간 처리 캐시
├── workplace_future_work/           # 논문·작업 중간 파일
├── papers/                          # 실제 논문 원문
├── translated_parts/                # 번역 결과
│
├── research_agent/
│   ├── workplace_*/
│   ├── workspace_*/
│   └── 각종 실행 결과·캐시
│
├── CoT4/
│   ├── .git/
│   └── 각종 실행 결과·캐시
│
├── CoT5/
│   ├── .git/
│   ├── 실제 문헌 DB 및 파생 데이터   # 다른 위치에 저장되어 있어도 제외
│   └── 각종 실행 결과·캐시
│
└── external/
    └── idea_novelty_checker/
        ├── .git/
        ├── config.yml
        ├── results/
        ├── data/ 안의 실제 DB·연구 데이터
        └── assets/ 안의 논문·실험 자산
```

다음 항목은 **저장 위치와 관계없이 제외**한다.

| 제외 대상 | 파일·디렉토리 예시 |
|---|---|
| DB 원본·일부 데이터·덤프·백업 | `arxiv_cs_ai.db`, `*.db`, `*.sqlite`, `*.sqlite3`, DB 압축본, WAL/SHM 파일 |
| DB 파생 데이터 | 논문 메타데이터 레코드, 검색용 코퍼스, 임베딩 벡터, 검색·벡터 인덱스, DB 내용이 담긴 JSON/JSONL/CSV/Parquet/SQL 덤프 |
| 실제 실험 입력·논문 | 기존 논문별 입력 파일, 다운로드한 PDF·LaTeX·원문 |
| 실제 실험 산출물 | `result.json`, 판정 결과 JSON, 실험 CSV·이미지·표, 번역 결과 |
| 실행 기록 | `*.log`, `timing.json`, `timing_detailed.json`, 실행 결과용 `manifest.json` |
| 로컬 환경·캐시 | `__pycache__/`, `.pytest_cache/`, `*.pyc`, `*.egg-info/`, 가상환경, 빌드 산출물, 모델 캐시 |
| 비밀정보·개인 설정 | API 키, 토큰, 인증정보, 실제 DB 경로가 들어간 설정 파일 |
| Git 내부 메타데이터 | 루트 및 하위 디렉토리의 `.git/` 내부 파일. submodule Gitlink와 루트 `.gitmodules`는 공개 항목으로 관리 |

**확장자로 일괄 제외하지 않는다.** 필수 프롬프트·`incontext_examples`·샘플 입력 JSON은 올리고, 실제 데이터·실험 결과만 제외한다. `data/`나 `assets/` 내부에 있더라도 실행에 필요한 안전한 정적 리소스는 공개 항목으로 구분한다.

DB와 비밀정보는 현재 파일뿐 아니라 공개할 Git 이력과 submodule 참조에도 포함되지 않아야 한다. 이 문서는 선별 기준이며, 파일 제외 설정이나 과거 커밋 정리가 완료되었다는 의미는 아니다.
