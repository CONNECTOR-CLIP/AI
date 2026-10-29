from copy import deepcopy
from export_cot5_web_view import build_web_view


def test_only_completed_web_results_are_displayed_without_mutating_raw():
    rows = [{"idea_title": str(i), "overlaps": {"web": {
        "status": "\uc5c6\uc74c", "error": None, "candidates": []}}} for i in range(8)]
    rows[3]["overlaps"]["web"] = {"status": "\ud655\uc778\ubd88\uac00", "error": "TimeoutError"}
    raw = {"results": rows}
    before = deepcopy(raw)
    view = build_web_view(raw)
    assert view["displayed_count"] == 7
    assert [r["candidate_index"] for r in view["results"]] == [1, 2, 3, 5, 6, 7, 8]
    assert raw == before
    assert "TimeoutError" not in str(view)
    assert view["view_scope"] == "successful_web_results_only"


def test_unknown_missing_or_error_results_are_not_shown_as_success():
    raw = {"results": [{}, {"overlaps": {"web": {"status": "\uc5c6\uc74c", "error": "offline"}}}]}
    assert build_web_view(raw)["results"] == []
