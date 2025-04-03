import requests
import torch
from typing import List, Optional, Dict, Union
from dotenv import load_dotenv
import os
from .base_reranker import BaseSemanticSearcher

class JinaReranker(BaseSemanticSearcher):
    """
    Reranker implementation using Jina AI's Rerank API (v1).
    This overrides the base class rerank method to directly use the API.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "jina-reranker-v2-base-multilingual"):
        """
        Initialize the Jina reranker.

        Args:
            api_key: Jina AI API key. If None, will load from environment variable JINA_API_KEY
            model: Reranker model name to use (e.g., "jina-reranker-v2-base-multilingual")
        """
        if api_key is None:
            load_dotenv()
            api_key = os.getenv('JINA_API_KEY')
            if not api_key:
                # Try the key provided in the user example as a fallback if env var missing
                api_key = "jina_d50963a0c7da4ee5b59eb7b780a8afd1MpuPNvVPRqTLt2OF-D2ivtlJp7Zu"
                print("Warning: JINA_API_KEY not found in environment. Using example key. Please set the environment variable for security.", flush=True)
            if not api_key:
                 raise ValueError("No API key provided and JINA_API_KEY not found in environment variables.")

        self.api_url = 'https://api.jina.ai/v1/rerank' # Correct endpoint
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}'
        }
        self.model = model

    # Provide a dummy implementation for the abstract method
    # This won't be called by dr_agent for Jina, as it uses the ranking_utils helper
    def _get_embeddings(self, texts: List[str]) -> torch.Tensor:
        """
        Dummy implementation for BaseSemanticSearcher compatibility.
        Should not be called directly when using the Jina Rerank API.
        """
        # Option 1: Raise error
        raise NotImplementedError("JinaReranker uses the rerank API directly, not embeddings.")
        # Option 2: Return empty tensor (less informative if called accidentally)
        # return torch.empty((0, 0)) 

    def rerank(
        self,
        query: str, # Rerank API takes a single query string
        documents: List[str],
        top_k: int = 5 # Corresponds to top_n in Jina API
        # normalize parameter is ignored as Jina API returns relevance scores directly
    ) -> List[Dict[str, Union[int, float]]]: # Return format expected by dr_agent
        """
        Rerank documents using the Jina Rerank API.

        Args:
            query: Query string.
            documents: List of documents to rerank.
            top_k: Number of top results to return.

        Returns:
            List of dicts, each containing the original 'index' and the 'score'
            (relevance_score from Jina API), sorted by score descending.
            Example: [{'index': 0, 'score': 0.9}, {'index': 5, 'score': 0.8}]
        """
        if not isinstance(query, str):
            # The Jina rerank API expects a single query string.
            # Handle potential list input gracefully (e.g., use the first query)
            # Or raise an error if multiple queries aren't supported by this specific implementation.
            print(f"Warning: JinaReranker received multiple queries ({len(query)}). Only the first query will be used for reranking.")
            effective_query = query[0] if query else ""
        else:
            effective_query = query
            
        if not documents:
            return []

        payload = {
            "model": self.model,
            "query": effective_query,
            "documents": documents,
            "top_n": min(top_k, len(documents)) # Ensure top_n doesn't exceed doc count
        }

        try:
            response = requests.post(self.api_url, headers=self.headers, json=payload)
            response.raise_for_status() # Raise exception for non-200 status codes

            api_results = response.json().get("results", [])

            # Transform results into the expected format: List[{'index': int, 'score': float}]
            transformed_results = [
                {
                    "index": result.get("index"),
                    "score": result.get("relevance_score")
                }
                for result in api_results
                if result.get("index") is not None and result.get("relevance_score") is not None
            ]
            
            # The API already returns results sorted by relevance_score descending.
            return transformed_results

        except requests.exceptions.RequestException as e:
            # Log the error details, including response text if available
            error_detail = str(e)
            if e.response is not None:
                 error_detail += f" | Response: {e.response.text}"
            print(f"Error calling Jina Rerank API: {error_detail}", flush=True)
            # Return empty list or raise an exception based on desired error handling
            return [] 
        except Exception as e:
            print(f"Unexpected error during Jina reranking: {str(e)}", flush=True)
            return []
