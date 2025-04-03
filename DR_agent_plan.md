# Deep Research Agent (DR_Agent) Plan

This document outlines the plan for creating a multi-step, autonomous deep research agent within the OpenDeepSearch framework.

## Goal

To enable users to input a complex query and receive a detailed, well-structured report synthesized from multiple web sources, leveraging powerful LLMs for planning, summarization, and writing.

## Core Models

*   **Planner:** `openrouter/google/gemini-2.0-flash-thinking-exp:free` (Responsible for initial search strategy and report structure)
*   **Summarizer:** `openrouter/google/gemini-2.0-flash-exp:free` (Responsible for summarizing content from individual sources)
*   **Writer:** `openrouter/google/gemini-2.5-pro-exp-03-25:free` (Responsible for synthesizing the final report from summaries and iteratively refining it)
*   **Reranker:** Existing `InfinitySemanticSearcher` or `JinaReranker` (Configurable, used for ranking sources and chunks)

## Workflow Steps

1.  **Planning Phase:**
    *   **Input:** User Query (e.g., "Analyze the impact of quantum computing on cybersecurity threats")
    *   **Action:** Call the **Planner LLM** with the user query.
    *   **Output:** A JSON object adhering to the following structure:
        ```json
        {
          "search_tasks": [
            {
              "query": "Specific query string for Serper",
              "endpoint": "/search", // Planner chooses: "/search", "/scholar", or "/news"
              "num_results": 10,     // Planner can override (e.g., 20) if justified
              "reasoning": "Why this query, endpoint, and result count are chosen"
            }
            // Can include 1-3 search tasks in the list
          ],
          "writing_plan": { // Flexible structure for detailed instructions
            "overall_goal": "Provide a comprehensive analysis of [topic], focusing on [aspect1] and [aspect2], suitable for [audience].",
            "desired_tone": "Objective and analytical.", // e.g., Formal, Informal, Critical, Balanced
            "sections": [
              {
                "title": "Introduction", // Planner defines section titles
                "guidance": "Define [topic], outline the report structure, and state the main argument/thesis if applicable." // Planner provides specific instructions per section
              },
              // ... more sections as needed based on the query and planner's strategy
              {
                "title": "Conclusion",
                "guidance": "Summarize key findings, restate the main argument, and suggest potential implications or areas for further research."
              }
            ],
            "additional_directives": [ // Optional list for overall guidance
               "Ensure all claims are backed by citations from the provided source summaries. Use a consistent citation format (e.g., [Source Title/URL]).",
               "Address potential counterarguments regarding [specific point].",
               "Maintain a logical flow between sections."
            ]
          }
        }
        ```

2.  **Initial Search Execution:**
    *   **Input:** `search_tasks` list from the Planner's JSON output.
    *   **Action:** Execute a batch Serper POST request containing the specified queries, endpoints, and `num_results` for each task. Handle potential errors.

3.  **Initial Content Processing & Source Reranking:**
    *   **Input:** Raw Serper results (list of organic results, etc., per search task).
    *   **Action:**
        *   Consolidate results if multiple tasks returned overlapping links.
        *   Use the configured **Reranker** (e.g., Jina) to score the relevance of each unique source based on its title and snippet against the *original user query*.
        *   Identify the Top M sources (e.g., M=3) and the Next K sources (e.g., K=4) based on reranker scores.
        *   Use `Crawl4AI` (or similar) to fetch the web content for these M+K sources.

4.  **Hybrid Content Extraction:**
    *   **Input:** Fetched web content for M+K sources.
    *   **Action (Hybrid Approach):**
        *   **For Top M Sources:** Keep the full scraped text content.
        *   **For Next K Sources:**
            *   Use `Chunker` to split the text content into manageable chunks.
            *   Use the **Reranker** again to score these chunks based on relevance to the *original user query*.
            *   Keep the Top N highest-scoring chunks (e.g., N=15) for each of these K sources. Concatenate these chunks.

5.  **Intermediate Summarization:**
    *   **Input:** Extracted content for each of the M+K sources (full text for M, top N chunks for K), along with the original source URL/title for reference.
    *   **Action:** For each source, call the **Summarizer LLM** (`google/gemini-2.0-flash-exp:free`) with its extracted content.
    *   **Output:** A list of concise summaries, each linked to its original source (URL/title).

6.  **Initial Report Generation:**
    *   **Input:**
        *   Original User Query
        *   `writing_plan` object from the Planner's JSON output.
        *   List of source summaries (from Step 5) with their corresponding source references.
    *   **Action:** Call the **Writer LLM** (`google/gemini-2.5-pro-exp-03-25:free`) with a prompt instructing it to generate the first draft of the report according to the `writing_plan`, using the provided summaries as its knowledge base and citing sources appropriately (e.g., include the source URL/title with each summary provided in the prompt and instruct the model to reference them).
    *   **Output:** First draft of the report (string).

7.  **Refinement Loop (Iterative Improvement):**
    *   **Condition:** Check the Writer LLM's output (from Step 6 or subsequent iterations) for the specific tag: `<request_more_info topic="...">`. Loop up to a maximum number of iterations (e.g., Max Iterations = 2).
    *   **If Tag Found:**
        *   **7a. Refinement Planning:** Analyze the `topic` specified in the tag. Generate 1-2 highly targeted Serper search queries (using the Planner LLM or a simpler logic) to find information specifically addressing the gap. Decide on endpoint and `num_results`.
        *   **7b. Refinement Search:** Execute the new Serper search(es).
        *   **7c. Refinement Content Processing:** Fetch content for the top few results (e.g., 2-3) from the refinement search.
        *   **7d. Refinement Extraction & Summarization:** Extract relevant content (can use chunking/reranking or simpler extraction based on the targeted nature) and summarize it using the **Summarizer LLM**.
        *   **7e. Report Revision:** Call the **Writer LLM** again. Provide:
            *   Original User Query
            *   `writing_plan`
            *   *All* summaries gathered so far (initial summaries + summaries from *all* refinement iterations), each clearly associated with its source URL/title.
            *   The previous draft of the report.
            *   Specific instructions to revise the report, focusing on incorporating the new information to address the `<request_more_info topic="...">` request, and maintaining consistent citations.
        *   **Output:** Revised draft of the report. Go back to the start of Step 7 to check the new output.
    *   **If Tag Not Found (or Max Iterations Reached):** Exit the loop.

8.  **Final Output:**
    *   **Input:** The final report draft from the Writer LLM (after the loop finishes).
    *   **Action:** Perform any final formatting or cleanup if necessary. Ensure a bibliography or list of cited sources is included if appropriate based on the writing plan.
    *   **Output:** Present the completed, detailed report with citations to the user.

## Configuration Parameters (Examples)

*   `max_initial_search_tasks`: 3
*   `top_m_full_text_sources`: 3
*   `next_k_chunked_sources`: 4
*   `top_n_chunks_per_source`: 15
*   `max_refinement_iterations`: 2
*   `final_report_max_length`: [num_tokens]

## Next Steps

*   Implement the orchestration logic for this workflow.
*   Create specific prompts for the Planner, Summarizer, and Writer LLMs.
*   Adapt existing `ods_agent.py` or create a new `DeepResearchAgent` class.
*   Integrate the new Serper endpoint/num flexibility.
*   Implement the hybrid content extraction + summarization pipeline.
*   Implement the refinement loop logic, including parsing the `<request_more_info>` tag and triggering follow-up actions. 