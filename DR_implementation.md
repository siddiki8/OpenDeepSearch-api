# Deep Research Agent Implementation Plan

This plan outlines the steps to implement the Deep Research Agent (DR_Agent) based on the specifications in `DR_agent_plan.md` and leveraging the existing `OpenDeepSearch` codebase.

## Organizational Structure

To keep the new components organized, we will create a new directory: `src/opendeepsearch/deep_research/`.

*   `src/opendeepsearch/deep_research/__init__.py`: Expose the main agent class.
*   `src/opendeepsearch/deep_research/dr_agent.py`: Contains the `DeepResearchAgent` class and orchestration logic.
*   `src/opendeepsearch/deep_research/prompts.py`: Specific system prompts and instructions for Planner, Summarizer, and Writer LLMs.
*   `src/opendeepsearch/deep_research/utils.py`: Helper functions specific to the deep research workflow (e.g., JSON parsing, refinement loop logic).

## Implementation Steps

1.  **Directory Setup:**
    *   Create the `src/opendeepsearch/deep_research/` directory and the initial Python files (`__init__.py`, `dr_agent.py`, `prompts.py`, `utils.py`).

2.  **Refactor/Adapt Existing Components:**
    *   **Serper Integration (`serp_search.py`):** Modify `SerperAPI.get_sources` or create a new method to handle the batch POST request format specified in `DR_agent_plan.md` (Step 2), allowing different endpoints (`/search`, `/scholar`, `/news`) and `num_results` per query within the batch.
    *   **Content Scraping (`context_scraping/`):** Ensure `Crawl4AI` (or the chosen scraper) can reliably fetch content for the identified sources (Step 3).
    *   **Reranking (`ranking_models/`):** Verify `JinaReranker`/`InfinitySemanticSearcher` can handle both source-level reranking (based on snippets, Step 3) and chunk-level reranking (Step 4). Ensure `Chunker` is suitable.
    *   **LiteLLM Integration:** The existing `litellm.completion` usage in `ods_agent.py` can likely be reused for calling the Planner, Summarizer, and Writer LLMs specified in the plan. Ensure proper model IDs and API keys are configurable (likely via environment variables as currently done).

3.  **Develop `DeepResearchAgent` Class (`dr_agent.py`):**
    *   Define the `DeepResearchAgent` class.
    *   **Initialization (`__init__`):** Accept configuration parameters (LLM model IDs, reranker choice, `max_iterations`, `top_m`, `next_k`, `top_n`, API keys/env vars, etc.). Initialize necessary components (Serper API, scraper, reranker, chunker).
    *   **Main Orchestration Method (e.g., `run_deep_research(user_query: str)`):** Implement the core workflow outlined in `DR_agent_plan.md` (Steps 1-8).
    *   **Verbose Logging/Feedback:** Within the orchestration method, add logging statements or a mechanism to report progress to the user (e.g., using `print` or a dedicated callback function). This should include:
        *   Confirmation of receiving the user query.
        *   Planner LLM call initiation and the resulting plan (search tasks, writing plan).
        *   Initiation of Serper searches (mentioning queries/endpoints).
        *   Sources identified for processing (Top M full text, Next K chunks).
        *   Initiation of content fetching.
        *   Initiation of summarization step.
        *   Initiation of initial report writing.
        *   Start of refinement loop (if applicable), including the topic requested by the writer.
        *   Refinement search/summarization/writing steps.
        *   Completion of the process.

4.  **Implement Workflow Logic (`dr_agent.py`, `utils.py`):**
    *   **Planner Interaction:** Function to call the Planner LLM, validate/parse the JSON output (potentially in `utils.py`).
    *   **Serper Batch Execution:** Call the modified Serper method.
    *   **Hybrid Extraction:** Implement the logic to process Top M (full text) and Next K (top N chunks) sources.
    *   **Summarizer Interaction:** Function to loop through extracted content and call the Summarizer LLM for each.
    *   **Writer Interaction:** Function to call the Writer LLM with the correct prompt (initial generation and revision), including the writing plan and accumulated summaries with citations.
    *   **Refinement Loop:** Implement the loop logic, including parsing the `<request_more_info>` tag (maybe using regex in `utils.py`), triggering refinement planning/search, managing state (accumulated summaries, iteration count), and calling the writer for revision.

5.  **Develop Prompts (`prompts.py`):**
    *   Create detailed system prompts and task instructions for:
        *   **Planner:** Instruct it to analyze the query, generate search tasks (query, endpoint, num, reasoning), and create the detailed `writing_plan` in the specified JSON format.
        *   **Summarizer:** Instruct it to create concise, factual summaries of the provided text (full or chunked), retaining key information relevant to the likely report topic.
        *   **Writer (Initial):** Instruct it to follow the `writing_plan`, synthesize the provided summaries, cite sources clearly (using the provided source references), and use the `<request_more_info>` tag if necessary.
        *   **Writer (Revision):** Instruct it to revise the previous draft, incorporating the *new* summaries to address the specific `topic` from the `<request_more_info>` tag, while maintaining the overall structure and consistent citations.

6.  **Configuration and Integration:**
    *   Update `src/opendeepsearch/__init__.py` to expose `DeepResearchAgent`.
    *   Ensure environment variables or a configuration file can manage API keys and model IDs.
    *   Potentially update `gradio_demo.py` or create a new example script to showcase the `DeepResearchAgent`.

7.  **Testing:**
    *   Unit tests for helper functions (JSON parsing, tag parsing).
    *   Integration tests for individual steps (planning, search, summarization, writing).
    *   End-to-end tests with various complex queries to validate the full workflow, including the refinement loop and citation accuracy.

## Dependencies

*   Leverages existing dependencies (`litellm`, `requests`, `crawl4ai`, reranker libraries, etc.).
*   No major new external dependencies anticipated, primarily internal code development. 