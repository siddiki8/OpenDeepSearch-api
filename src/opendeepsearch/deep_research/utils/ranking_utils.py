import requests
import os
from typing import List, Dict, Union, Optional
from dotenv import load_dotenv

# Function to call the Jina Rerank API
def rerank_with_jina_api(
    query: str,
    documents: List[str],
    top_k: int = 5,
    api_key: Optional[str] = None,
    model: str = "jina-reranker-v2-base-multilingual"
) -> List[Dict[str, Union[int, float]]]:
    """
    Reranks documents using the Jina Rerank API (v1).

    Args:
        query: The query string.
        documents: A list of document strings to rerank.
        top_k: The number of top results to return.
        api_key: Jina AI API key. If None, attempts to load from JINA_API_KEY env var.
        model: The reranker model name to use.

    Returns:
        A list of dictionaries, each containing the original 'index' of the document
        in the input list and its 'score' (relevance_score from Jina API),
        sorted by score descending. Returns empty list on failure.
        Example: [{'index': 0, 'score': 0.9}, {'index': 5, 'score': 0.8}]
    """
    if not documents:
        return []

    if api_key is None:
        load_dotenv()
        api_key = os.getenv('JINA_API_KEY')
        if not api_key:
            # Fallback to example key if env var not found (with warning)
            # Consider removing this for production environments
            api_key = "jina_d50963a0c7da4ee5b59eb7b780a8afd1MpuPNvVPRqTLt2OF-D2ivtlJp7Zu"
            print("Warning: JINA_API_KEY not found. Using example key.", flush=True)
        if not api_key:
            print("Error: JINA_API_KEY is required but not found.", flush=True)
            return [] # Cannot proceed without API key

    api_url = 'https://api.jina.ai/v1/rerank'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {api_key}'
    }

    payload = {
        "model": model,
        "query": query,
        "documents": documents,
        "top_n": min(top_k, len(documents))
    }

    try:
        response = requests.post(api_url, headers=headers, json=payload)
        response.raise_for_status()
        api_results = response.json().get("results", [])

        transformed_results = [
            {
                "index": result.get("index"),
                "score": result.get("relevance_score")
            }
            for result in api_results
            if result.get("index") is not None and result.get("relevance_score") is not None
        ]
        return transformed_results

    except requests.exceptions.RequestException as e:
        error_detail = str(e)
        if e.response is not None:
            error_detail += f" | Response: {e.response.text}"
        print(f"Error calling Jina Rerank API: {error_detail}", flush=True)
        return []
    except Exception as e:
        print(f"Unexpected error during Jina reranking utility call: {str(e)}", flush=True)
        return [] 