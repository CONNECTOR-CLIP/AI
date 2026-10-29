import asyncio
import pandas as pd

from noveltychecker.retrieval.query_based_retrieval import get_query_based_papers_helper
from noveltychecker.ranking.embedding import get_embeddings_ideapapers
from noveltychecker.retrieval.input_collection import get_papers_similar_to_input_papers
from noveltychecker.ranking.embedding_ranker import embeddingFiltering
from noveltychecker.ranking.llm_reranker import rank_gpt_filter
from noveltychecker.utils.prompts import prompt_RankGPT_IdeaFacets
from noveltychecker.utils.model_client import get_llm_client
import os


async def get_priority_facets(idea):

    priority_prompt = prompt_RankGPT_IdeaFacets(idea)
    client = get_llm_client(os.getenv("DEFAULT_MODEL"))
    output, _ = client.chat(
        model=os.getenv("DEFAULT_MODEL"),
        messages=(
            [{"role": "system", "content": priority_prompt}]
            if isinstance(priority_prompt, str)
            else priority_prompt
        ),
        temperature=float(os.getenv("DEFAULT_TEMPERATURE", 0)),
    )
    return output


async def get_query_based_papers(idea, seed_papers, max_papers_specter=100, cutoff_date=None):
    # Full-corpus vectors are an independent source, not gated by LLM keywords.
    from cot5.retrieval_sources import lexical_candidates, vector_candidates

    vector_task = asyncio.create_task(vector_candidates(idea, cutoff_date))
    query_error = None
    try:
        query_retrieval_trace = await get_query_based_papers_helper(idea)
    except Exception as exc:
        query_error = exc
        query_retrieval_trace = {
            "snippet_papers": {}, "keyword_papers": {},
            "idea_keywords": [], "title_keywords": [], "query_hit_counts": [],
        }
    vector_papers, vector_status = await vector_task
    keyword_papers_temp = query_retrieval_trace["keyword_papers"]
    if keyword_papers_temp:
        lexical_papers, lexical_status = {}, {"state": "not_needed"}
    else:
        lexical_papers, lexical_status = await lexical_candidates(idea)
    query_retrieval_trace.update({
        "vector_index": vector_status,
        "lexical_index": lexical_status,
        "vector_candidate_count": len(vector_papers),
        "lexical_candidate_count": len(lexical_papers),
        "keyword_candidate_count": len(keyword_papers_temp),
        "retrieval_warnings": ([f"keyword retrieval failed: {type(query_error).__name__}: {query_error}"]
                               if query_error else []),
    })

    snippet_papers = {}
    for key, paper in query_retrieval_trace["snippet_papers"].items():
        paper["source"] = "snippet"
        snippet_papers[key] = paper
    keyword_papers = {}
    for key, paper in keyword_papers_temp.items():
        paper["source"] = "keyword+title+snippet" if key in snippet_papers else "keyword+title"
        keyword_papers[key] = paper
    idea_papers = {**snippet_papers, **keyword_papers, **lexical_papers}
    for key, paper in vector_papers.items():
        if key in idea_papers:
            paper["source"] = f"{idea_papers[key].get('source', 'other')}+vector"
        idea_papers[key] = paper
    # The FTS fallback returns metadata without vectors. Existing vector/CSO
    # candidates keep their embeddings; encode only the new lexical papers.
    idea_papers = await get_embeddings_ideapapers(idea_papers)

    if isinstance(seed_papers, pd.DataFrame):
        input_papers_temp = {
            str(paper["corpusId"]): paper
            for paper in seed_papers.to_dict(orient="records")
            if paper.get("corpusId")
        }
    else:
        input_papers_temp = seed_papers.copy() if isinstance(seed_papers, dict) else {}
    input_papers = {}
    corpus_ids = []
    for key, paper in input_papers_temp.items():
        paper["source"] = "input"
        input_papers[key] = paper
        corpus_ids.append(paper["corpusId"])

    if query_error and not idea_papers and not input_papers:
        raise query_error
    if not idea_papers and not input_papers and (
        vector_status.get("state") == "error" or lexical_status.get("state") == "error"
    ):
        raise RuntimeError("all available paper retrieval sources failed")

    input_paper_similar_temp = await get_papers_similar_to_input_papers(corpus_ids)
    input_paper_similar = {}
    for key, paper in input_paper_similar_temp.items():
        paper["source"] = "similar_to_input"
        input_paper_similar[key] = paper

    input_papers = await get_embeddings_ideapapers(input_papers)
    input_paper_similar = await get_embeddings_ideapapers(input_paper_similar)
    input_papers.update(input_paper_similar)
    input_papers.update(idea_papers)
    query_retrieval_trace["embedding_ranked"] = await embeddingFiltering(
        idea, input_papers, max_papers_specter
    )
    return query_retrieval_trace


async def get_most_relevant_papers(idea, seed_papers, max_papers_specter=100, cutoff_date=None):

    query_retrieval_trace = await get_query_based_papers(
        idea, seed_papers, max_papers_specter, cutoff_date=cutoff_date
    )
    if len(query_retrieval_trace["embedding_ranked"]) == 0:
        query_retrieval_trace.update({
            "idea_priority_facets": "",
            "most_relevant_papers": query_retrieval_trace["embedding_ranked"],
        })
        return query_retrieval_trace
    idea_priority_facets = await get_priority_facets(idea)

    most_similar_documents_filtered = query_retrieval_trace["embedding_ranked"].dropna(
        subset=["title", "abstract"]
    )

    similar_documents = most_similar_documents_filtered.copy()

    hits = [
        {"content": f"Title: {row['title']}. Content: {row['abstract']}"}
        for _, row in similar_documents.iterrows()
    ]

    item = {"query": idea, "hits": hits}
    similar_documents["content"] = [i["content"] for i in item["hits"]]

    await rank_gpt_filter(
        item,
        similar_documents,
        os.getenv("RANKGPT_MODEL"),
        os.getenv("RANKGPT_VARIANT"),
        idea_priority_facets,
    )

    similar_documents.sort_values(
        f'rankGPT_{os.getenv("RANKGPT_VARIANT")}', inplace=True
    )

    query_retrieval_trace.update(
        {
            "idea_priority_facets": idea_priority_facets,
            "most_relevant_papers": similar_documents,
        }
    )
    return query_retrieval_trace
