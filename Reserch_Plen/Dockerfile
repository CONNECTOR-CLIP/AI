FROM python:3.11-slim

WORKDIR /app
COPY . /app
ENV PYTHONPATH=/app/src

# 기본 동작: 단위 테스트 → 정답 예시 검증 → 실제 실행 데이터의 후보 목록 출력
CMD ["sh", "-c", "python -m unittest discover -s tests -v && python -m research_plan.validate examples/golden/idea06_unsupported_token && python -m research_plan list --run-dir data/cot45_public_run_20261029_154552"]
