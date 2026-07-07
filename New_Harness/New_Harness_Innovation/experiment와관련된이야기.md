지금 experiment_work_*가 돌아가는 방식은 "사람이 터미널에서 CLI를 한 단계씩 실행하고, 로컬 파일시스템에 결과를 쌓는 배치 실험 도구"입니다. 실서비스로 가려면 아래 지점들이 바뀌어야 합니다.

1. 입출력 계층: CLI 인자 → API/큐

지금: --input my_input.json --run-id x --run-root D:\... 처럼 사람이 값을 손으로 넣고, run_root는 로컬 임시 폴더.
실서비스: IngestStage/CandidateLoopStage/DraftGenerationStage/RevisionStage(new_harness/stages/*)를 그대로 두되, 앞단에 HTTP API(POST /runs, POST /runs/{id}/select 등)를 얹어서 웹/앱이 호출하게 해야 합니다. run_root도 로컬 경로가 아니라 DB(run 메타데이터) + 오브젝트 스토리지(S3 등, artifact 본문)로 바뀌어야 여러 서버 인스턴스에서 동일 run에 접근 가능합니다.
2. 실행 방식: 동기 블로킹 → 비동기 잡

run은 evidence card 생성 + 후보 생성/비평 + (light/strong)외부검색까지 한 프로세스가 끝날 때까지 블로킹합니다(OpenRouter 호출 여러 번 + SearchEngine 호출). 실서비스에서 사용자가 API를 호출하고 몇 초~몇십 초를 대기시킬 수 없으므로, 큐(예: Celery/RQ/Temporal)에 던지고 상태를 폴링/웹소켓으로 알려주는 구조가 필요합니다.
3. 시크릿 관리

지금은 .env.local 파일에 OPENROUTER_API_KEY를 넣고 CLI가 자동 로드합니다. 실서비스에서는 파일이 아니라 시크릿 매니저(예: AWS Secrets Manager/Vault)나 배포 환경변수로 주입해야 하고, 사용자별 키 분리·로테이션도 고려해야 합니다.
4. 외부 의존 서비스(SearchEngine/OpenSearch)

지금은 제가 로컬에서 uvicorn과 opensearch.bat를 수동으로 띄운 상태에 CLI가 http://127.0.0.1:8000/search로 붙는 구조입니다. 실서비스에서는 이게 컨테이너화되어 상시 배포·헬스체크·오토스케일되는 내부 서비스여야 하고, --external-search-url이 개발자 로컬 IP가 아니라 서비스 디스커버리 주소를 가리켜야 합니다.
5. 멀티유저 격리/권한

select/draft/revise는 run_id 일치만 검사하고 "이 run이 이 사용자 것인지"는 검사하지 않습니다(테스트에도 소유권 개념 없음). 실서비스는 인증된 사용자 ↔ run_id 소유권 매핑과 접근 제어가 필수입니다.
6. 비용/쿼터 통제

candidate loop가 라운드 수는 제한하지만, 사용자별 OpenRouter 호출 비용 한도나 요청 빈도 제한은 없습니다. 다수 사용자가 쓰면 비용 통제 계층이 필요합니다.
7. 알려진 버그

Windows에서 card_path가 백슬래시로 기록되는 문제(제가 지난 테스트에서 확인)처럼, 크로스플랫폼에서 깨지는 부분은 실서비스 배포 전에 고쳐야 합니다.
요약하면: 파이프라인 로직(new_harness/stages/*) 자체는 재사용 가능하지만, 그걸 감싸는 "CLI + 로컬 폴더 + 사람이 파일 복사" 레이어를 통째로 "API + 큐 + DB/오브젝트 스토리지 + 인증 + 시크릿 매니저"로 교체해야 합니다