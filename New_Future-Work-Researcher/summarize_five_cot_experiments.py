"""Build audited Korean reports from saved stage outputs (no model/API calls)."""
from __future__ import annotations
import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


HIGHLIGHTS = {
    "01_agent_reflection": "복잡한 행동 공간에서의 실패 대응, 반성 기억의 장기화, 토큰 비용을 함께 다루는 방향이 도출됐다. 특히 벡터 기억 교체와 기억 가지치기는 대규모 재학습보다 비교적 분리된 후속 검증 과제로 볼 수 있다.",
    "02_adaptive_rag": "검색·생성·자기비판의 공동 사전학습과, 근거가 없을 때의 명시적 거절·설명이라는 두 축이 나타났다. 공동 사전학습은 자원 부담이 크므로 근거 부족 토큰·인용형 거절부터 별도 비교실험을 설계하는 것이 현실적이다.",
    "03_reasoning_search": "트리·그래프 구조 자체의 효과와 모델·프롬프트·탐색 비용의 효과를 분리하는 통제 실험이 핵심이다. recurrence on/off, 동일 과제의 구조별 비교, 가지치기·캐싱의 비용 대비 효과가 구체적 후속 과제다.",
    "04_agent_memory": "계층적 paging과 동적 연결·기억 진화의 결합, 장기 일관성, 멀티모달 확장이 주요 축이다. 메모리 구조만 교체하면서 검색 지연·메모리 사용량·일관성을 함께 측정하는 실험이 상대적으로 비교 가능성이 높다.",
    "05_tool_use": "API 호출 문자열의 정합성에서 실제 실행 성공으로 평가를 확장하는 방향이 두드러졌다. 실행 샌드박스와 실패 추적, 제약 인식 도구 선택, 도구 조합 제거 실험이 주요 검증 과제다.",
}


def load(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.output.resolve()
    plan = load(root / "experiment_plan.json")
    scope = load(root / "database_scope.json")
    reports, rows, review_flags = [], [], []
    total_goals, total_limits, total_classes = Counter(), 0, Counter()
    for experiment in plan:
        folder = root / experiment["id"]
        cot3 = load(folder / "CoT3/result.json", [])
        cot4 = load(folder / "CoT4/result.json", {}).get("results", [])
        cot5 = load(folder / "CoT5/result.json", {}).get("results", [])
        if not (len(cot3) == len(cot4) == len(cot5)):
            raise RuntimeError(f"Stage count mismatch: {folder}")
        goals, limits, papers, aux = Counter(), 0, [], {s: Counter() for s in ("web", "patent")}
        lines = [f"# {experiment['topic']}", "", experiment["rationale"], "", "## 1. 입력 논문 및 CoT1·CoT2", ""]
        for paper in experiment["papers"]:
            first = load(folder / f"CoT1/{paper['id']}.json")
            second = load(folder / f"CoT2/{paper['id']}.json")
            counts = Counter(s["status"] for s in first["subgoals"])
            goals.update(counts)
            limit_count = len(second["candidates"])
            limits += limit_count
            papers.append({**paper, "goals": dict(counts), "explicit_limitations": limit_count})
            lines += [f"### [{paper['title']}](https://arxiv.org/abs/{paper['id']})",
                      f"- CoT1 목표 판정: 달성 {counts['achieved']}, 부분 달성 {counts['partially_achieved']}, 미달성 {counts['not_achieved']}",
                      f"- CoT2 명시적 한계·후속연구 문장: {limit_count}개"]
            for subgoal in first["subgoals"]:
                if subgoal["status"] != "achieved":
                    lines.append(f"- 남은 목표: {subgoal['label']} ({subgoal['status']})")
        classes = Counter(r["classification"] for r in cot5)
        checked = sum(r.get("evaluated_paper_count", r.get("overlaps", {}).get("paper", {}).get("checked_count", 0)) for r in cot5)
        for result in cot5:
            for source in aux:
                aux[source][result.get("overlaps", {}).get(source, {}).get("status", "미기록")] += 1
        lines += ["", "## 2. CoT3 교차비교 → CoT4 자원 안내 → CoT5 신규성 검사", "",
                  f"- CoT3 최종 후보: **{len(cot3)}개**", f"- CoT4 결과: {len(cot4)}개 (오류 {sum(r.get('status') == 'error' for r in cot4)}개)",
                  f"- CoT5 판정: {dict(classes)}", f"- 개별 논문 비교: {checked}회 (후보 간 동일 논문 중복 포함)",
                  f"- 외부 검색 상태: { {k: dict(v) for k,v in aux.items()} }", "", "### 해석", HIGHLIGHTS[experiment["id"]], ""]
        for number, (candidate, resource, result) in enumerate(zip(cot3, cot4, cot5), 1):
            search = result.get("paper_search", {})
            lines += [f"### 후보 {number} · {candidate['candidate_id']}",
                      f"- 공백: {candidate['gap_statement']}", f"- 제안: {candidate['proposed_direction']}",
                      f"- CoT4 계산 자원(모델 추정): {resource.get('requirements', {}).get('compute_requirements', '원본 결과 참조')}",
                      f"- CoT4 데이터: {resource.get('requirements', {}).get('data_requirements', '원본 결과 참조')}",
                      f"- CoT5: **{result['classification']}** — {result.get('reason', result.get('error', ''))}",
                      f"- 검토 논문 수: {result.get('evaluated_paper_count', result.get('overlaps', {}).get('paper', {}).get('checked_count', 0))}; 키워드 후보 {search.get('keyword_candidate_count', 0)}; 제목·초록 후보 {search.get('lexical_candidate_count', 0)}",
                      f"- 검색 경고: {'; '.join(search.get('retrieval_warnings', [])) or '기록 없음'}", ""]
            if result["classification"] == "NOT_NOVEL" and not any(x.get("equivalent") for x in result.get("equivalence_results", result.get("overlaps", {}).get("paper", {}).get("candidates", []))):
                note = f"{experiment['id']} / {candidate['candidate_id']}: 종합 문헌 검토는 NOT_NOVEL이지만 개별 논문 동등성 판정은 모두 false입니다. 넓은 의미의 선행연구 중복과 엄격한 동등성 기준의 차이를 수동 점검해야 합니다."
                review_flags.append(note)
                lines += [f"**수동 검토:** {note}", f"종합 검토 내용: {result.get('review', '')}", ""]
            for source, overlap in result.get("overlaps", {}).items():
                for match in overlap.get("matches", []):
                    note = f"{experiment['id']} / {candidate['candidate_id']}: 문헌 판정 {result['classification']}과 별개로 {source}에서 기존 연구·구현과의 중복 신호가 발견됐습니다."
                    review_flags.append(note)
                    lines += [f"**외부 중복 신호:** [{match.get('title', '')}]({match.get('url', '')})", match.get("reason", ""), ""]
            rows.append({"experiment": experiment["id"], "topic": experiment["topic"], "candidate_id": candidate["candidate_id"],
                         "proposed_direction": candidate["proposed_direction"], "classification": result["classification"],
                         "evaluated_paper_count": result.get("evaluated_paper_count", result.get("overlaps", {}).get("paper", {}).get("checked_count", 0)),
                         "web_status": result.get("overlaps", {}).get("web", {}).get("status"),
                         "patent_status": result.get("overlaps", {}).get("patent", {}).get("status")})
        lines += ["## 주의사항", "- NOVEL은 검색된 문헌·현재 판정 기준에서의 결과이며 실제 독창성의 확정이 아닙니다.",
                  "- CoT2의 0개는 정규식에 맞는 문장을 못 찾았다는 뜻이지 한계가 없다는 뜻이 아닙니다.",
                  "- CoT4는 자원 안내이며, 제안된 연구의 구현·학습·성능 평가를 실제로 수행한 결과가 아닙니다.",
                  "- 외부 검색의 확인불가는 중복 없음으로 해석하지 않습니다."]
        (folder / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        report = {**experiment, "counts": {"CoT1_papers": len(papers), "CoT2_limitations": limits, "CoT3_candidates": len(cot3),
                  "CoT4_results": len(cot4), "CoT5_results": len(cot5)}, "goal_statuses": dict(goals), "classifications": dict(classes),
                  "paper_comparisons": checked, "auxiliary_statuses": {k:dict(v) for k,v in aux.items()}, "papers_analysis": papers,
                  "interpretation": HIGHLIGHTS[experiment["id"]], "rechecked": (folder / "CoT5/recheck_result.json").is_file()}
        reports.append(report); total_goals.update(goals); total_limits += limits; total_classes.update(classes)
    lines = ["# 관련 논문 5개 그룹: CoT1–5 통합 실험 결과", "", "## 실행 범위", "",
             "논문 2편씩 5개 주제로 묶어 총 10편을 분석했습니다. CoT1 목표 분해 → CoT2 한계 추출 → CoT3 교차비교·판정 → 후보 변환 → CoT4 자원 안내 → CoT5 문헌·외부자료 중복 검사를 실행했습니다.",
             "CoT1·CoT3 생성 및 CoT4는 기존 Grok 구성, CoT3 판정은 Qwen, CoT5는 OpenRouter 경유 GPT-6 Luna를 사용했습니다. 실험은 순차 실행했고 CoT4·5의 동시 모델 호출은 4개로 제한했습니다.",
             "", "## 실험별 결과", "", "| 실험 | 논문 | CoT2 문장 | CoT3 후보 | CoT5 판정 |", "|---|---|---:|---:|---|"]
    for r in reports:
        lines.append(f"| [{r['topic']}]({r['id']}/REPORT.md) | {' + '.join(p['title'].split(':')[0] for p in r['papers'])} | {r['counts']['CoT2_limitations']} | {r['counts']['CoT3_candidates']} | {r['classifications']} |")
    lines += ["", f"**총 후보 {len(rows)}개 / 명시적 한계·후속연구 문장 {total_limits}개 / CoT5 {dict(total_classes)}**", "",
              "## 주제별 핵심 요약", ""]
    for r in reports:
        lines += [f"### {r['topic']}", r["interpretation"], ""]
    lines += ["## 우선 수동 검토할 항목", ""] + [f"- {note}" for note in review_flags] + ["",
              "트리·그래프 실험 C1의 웹 중복 신호는 [SRA-MCTS](https://www.ijcai.org/proceedings/2025/965)의 MCTS+자기평가 메커니즘과 관련됩니다. 동일 과제·동일 기여라는 확정은 아닙니다.", "",
              "## 결과를 해석할 때의 한계", "",
              f"- 문헌 DB: {scope['active_papers']:,}편, 수록 논문의 최신 최초등록일 {scope['latest_created_date']}. 실행일 현재의 전체 문헌을 포함하지 않습니다.",
              "- 전체 문헌 벡터 인덱스는 없어, 키워드 후보 검색 및 필요한 경우 완성된 전체 제목·초록 FTS 인덱스에서 후보를 찾고 SPECTER2로 재정렬했습니다. 후보별 검색 상태는 원본 JSON에 보관했습니다.",
              "- 초기 검색 인덱스가 stale/building이어서 NO_MATCH_IN_SCOPE였던 항목은 인덱스 완성 뒤 재검사했습니다. 최초 결과도 result.initial.json으로 보존했습니다.",
              "- 외부 검색에 확인불가 항목이 있으면 해당 범위는 미검증입니다. NOVEL은 이 미확인 영역까지 신규성을 보장하지 않습니다.",
              "- 입력 논문 10편은 모두 로컬 신규성 DB에 존재하는 것을 별도로 확인했습니다(input_db_coverage.json). 다만 존재한다는 사실이 해당 논문이 각 후보의 최종 Top-10에 포함됨을 뜻하지는 않습니다.",
              "- 비교 문헌 샘플 검수에서 일부 후보의 주제 관련성이 낮은 사례를 확인했습니다. 예를 들어 LLM API 실행 검증 후보에 일반 런타임·형식 검증 문헌이 비교 대상으로 포함됐습니다. 이 때문에 검색 재현율과 관련성에 대한 추가 검수 없이 NOVEL을 독창성의 근거로 단독 사용하면 안 됩니다.",
              "- 정답 라벨·대조군이 없으므로 신규성 판정 정확도나 모델 간 우열을 계산할 수 없습니다. 높은 통과율은 실제 신규성뿐 아니라 검색 재현율·판정 기준의 느슨함도 반영할 수 있습니다.",
              "- 주제별 생성·교차비교는 단일 실행입니다. 반복 실행 변동성은 측정하지 않았고, 검색 인덱스 복구 후 재검사는 모델 간 비교실험이 아닙니다.",
              "- 입력 논문은 연대가 다른 관련 연구 쌍입니다. 새 논문이 옛 논문의 공백을 이미 해결했는지에 대한 추가 수동 검토가 필요합니다.",
              "- 각 제안의 실제 학습·구현·벤치마크 성능 실험은 수행하지 않았습니다. 이번 실행 대상은 CoT 분석 파이프라인입니다.",
              "", "## 파일 안내", "- 각 실험 폴더의 REPORT.md: CoT1~5 통합 상세 요약", "- CoT1/·CoT2/·CoT3/·FutureWork/·CoT4/·CoT5/: 원본 단계별 JSON", "- candidate_results.csv: 후보별 판정·검토 수·외부 검색 상태", "- run.jsonl·CoT3/run.log·cot5_recheck.jsonl: 실행 및 재검사 로그"]
    (root / "SUMMARY.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    (root / "final_summary.json").write_text(json.dumps({"experiments":reports, "total_candidates":len(rows),
        "total_limitations":total_limits,"goal_statuses":dict(total_goals),"classifications":dict(total_classes),"manual_review_flags":review_flags},ensure_ascii=False,indent=2),encoding="utf-8")
    with (root / "candidate_results.csv").open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    archive = root.parent / f"{root.name}_reports.zip"
    with ZipFile(archive,"w",ZIP_DEFLATED) as z:
        for path in root.rglob("*"):
            if path.is_file() and not any(s in path.relative_to(root).parts for s in ("cache","workplace","__pycache__")):
                z.write(path,path.relative_to(root.parent))
    print(json.dumps({"candidates":len(rows),"classifications":dict(total_classes),"archive":str(archive)},ensure_ascii=False))


if __name__ == "__main__":
    main()
