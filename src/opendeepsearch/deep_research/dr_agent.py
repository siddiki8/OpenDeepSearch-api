from typing import Any, Dict, Optional, Callable, List
import litellm
import json # Added for parsing planner output
import re # Added for parsing refinement tag
import traceback # Import traceback for detailed error logging
from collections import Counter # For tracking usage

# Import components from the existing library (adjust paths as needed)
from opendeepsearch.ranking_models.base_reranker import BaseSemanticSearcher
from opendeepsearch.ranking_models.chunker import Chunker
from opendeepsearch.ranking_models.jina_reranker import JinaReranker # Keep import for type checking
# Replace incorrect scraper imports with WebScraper
from opendeepsearch.context_scraping.crawl4ai_scraper import WebScraper

# Import the new batch Serper utility
from .utils.serp_utils import execute_batch_serper_search, SerperConfig, SearchResult
# Import the new Jina rerank utility
from .utils.ranking_utils import rerank_with_jina_api
from .prompts import get_planner_prompt, get_summarizer_prompt, get_writer_initial_prompt, get_writer_refinement_prompt

class DeepResearchAgent:
    """Agent responsible for conducting deep research based on a user query."""

    def __init__(
        self,
        planner_llm_config: Dict[str, Any], # e.g., {"model": "openrouter/google/gemini-flash-1.5"}
        summarizer_llm_config: Dict[str, Any], # e.g., {"model": "openrouter/google/gemini-flash-1.5"}
        writer_llm_config: Dict[str, Any], # e.g., {"model": "openrouter/google/gemini-pro-1.5"}
        reranker: BaseSemanticSearcher, # Pass an initialized reranker instance
        chunker: Chunker,       # Pass an initialized chunker instance
        scraper_strategies: List[str] = ['no_extraction'], # WebScraper strategies instead of enum
        serper_config: Optional[SerperConfig] = None,
        max_initial_search_tasks: int = 3,
        top_m_full_text_sources: int = 3,
        next_k_chunked_sources: int = 4,
        top_n_chunks_per_source: int = 15,
        max_refinement_iterations: int = 2,
        verbose: bool = True,
        logger_callback: Optional[Callable[[str], None]] = None
    ):
        """
        Initializes the DeepResearchAgent.

        Args:
            planner_llm_config: Configuration for the Planner LLM (passed to litellm).
            summarizer_llm_config: Configuration for the Summarizer LLM.
            writer_llm_config: Configuration for the Writer LLM.
            reranker: An instance of a BaseSemanticSearcher implementation.
            chunker: An instance of a Chunker.
            scraper_strategies: List of strategy names for WebScraper (e.g., ['no_extraction', 'markdown_llm']).
            serper_config: Optional SerperConfig. If None, created from environment.
            max_initial_search_tasks: Max number of search tasks planner can generate.
            top_m_full_text_sources: Number of top sources to use full text from.
            next_k_chunked_sources: Number of next sources to use chunks from.
            top_n_chunks_per_source: Number of top chunks to keep per source.
            max_refinement_iterations: Maximum number of refinement loops.
            verbose: If True, prints progress messages.
            logger_callback: Optional function to call for logging instead of print.
        """
        self.planner_llm_config = planner_llm_config
        self.summarizer_llm_config = summarizer_llm_config
        self.writer_llm_config = writer_llm_config
        self.reranker = reranker
        self.chunker = chunker
        self.scraper_strategies = scraper_strategies
        # Initialize the scraper
        self.scraper = WebScraper(
            strategies=scraper_strategies, 
            debug=verbose
        )
        self.serper_config = serper_config or SerperConfig.from_env()

        # Workflow parameters
        self.max_initial_search_tasks = max_initial_search_tasks
        self.top_m = top_m_full_text_sources
        self.next_k = next_k_chunked_sources
        self.top_n = top_n_chunks_per_source
        self.max_refinement_iterations = max_refinement_iterations

        self.verbose = verbose
        self.log = logger_callback if logger_callback else (print if verbose else lambda _: None)

        # Initialize usage trackers
        self.token_usage = Counter() # Stores total_tokens, prompt_tokens, completion_tokens
        self.estimated_cost = 0.0
        self.serper_queries_used = 0

        self.log("DeepResearchAgent initialized.")
        self.log(f"- Planner LLM: {self.planner_llm_config}")
        self.log(f"- Summarizer LLM: {self.summarizer_llm_config}")
        self.log(f"- Writer LLM: {self.writer_llm_config}")
        self.log(f"- Reranker: {type(self.reranker).__name__}")
        self.log(f"- Chunker: {type(self.chunker).__name__}")
        self.log(f"- Scraper Strategies: {self.scraper_strategies}")
        self.log(f"- Workflow Params: top_m={self.top_m}, next_k={self.next_k}, top_n={self.top_n}, max_iterations={self.max_refinement_iterations}")

    # Helper to update usage
    def _update_usage(self, response):
        if hasattr(response, 'usage') and response.usage is not None:
            self.token_usage['completion_tokens'] += response.usage.completion_tokens
            self.token_usage['prompt_tokens'] += response.usage.prompt_tokens
            self.token_usage['total_tokens'] += response.usage.total_tokens
            # Cost is often available directly (e.g., response.cost['total_cost']) 
            # or can be estimated if needed using litellm.cost_per_token
            # For simplicity, we'll just add the reported cost if available.
            if hasattr(response, 'cost') and isinstance(response.cost, dict) and 'total_cost' in response.cost:
                 current_cost = response.cost['total_cost']
                 self.estimated_cost += current_cost
                 self.log(f"    LLM call cost: ${current_cost:.6f}. Cumulative cost: ${self.estimated_cost:.6f}")
            self.log(f"    Tokens Used: Prompt={response.usage.prompt_tokens}, Completion={response.usage.completion_tokens}, Total={response.usage.total_tokens}")
            self.log(f"    Cumulative Tokens: {self.token_usage['total_tokens']}")
        else:
            self.log("    Usage/cost information not available in LLM response.")

    async def run_deep_research(self, user_query: str) -> str:
        # Reset counters at the start of each run
        self.token_usage = Counter()
        self.estimated_cost = 0.0
        self.serper_queries_used = 0
        
        self.log(f"\n--- Starting Deep Research for query: '{user_query}' ---")

        # == Step 1: Planning Phase ==
        self.log("\n[Step 1/8] Calling Planner LLM...")
        planner_output_json = {}
        search_tasks = []
        writing_plan = {}

        try:
            planner_messages = get_planner_prompt(user_query)
            self.log(f"Calling Planner LLM ({self.planner_llm_config.get('model')}) with retries...")
            response = litellm.completion(
                messages=planner_messages,
                response_format={ "type": "json_object" }, # Request JSON output
                num_retries=3, # Add retries
                **self.planner_llm_config # Unpack model, api_key, etc.
            )
            self._update_usage(response) # Update usage
            # Extract content, potentially strip markdown code block fences
            response_content = response.choices[0].message.content
            cleaned_response_content = response_content.strip().removeprefix("```json").removesuffix("```").strip()

            planner_output_json = json.loads(cleaned_response_content)

            # Validate structure (basic check)
            if "search_tasks" not in planner_output_json or "writing_plan" not in planner_output_json:
                raise ValueError("Planner output missing required keys: 'search_tasks' or 'writing_plan'")
            if not isinstance(planner_output_json['search_tasks'], list):
                 raise ValueError("Planner output 'search_tasks' is not a list")

            search_tasks = planner_output_json['search_tasks']
            writing_plan = planner_output_json['writing_plan']

            # Optional: Validate search_tasks against max_initial_search_tasks
            if len(search_tasks) > self.max_initial_search_tasks:
                self.log(f"Warning: Planner generated {len(search_tasks)} tasks, exceeding limit {self.max_initial_search_tasks}. Truncating.")
                search_tasks = search_tasks[:self.max_initial_search_tasks]

            self.log("Planner LLM call complete.")
            self.log(f"- Planned Search Tasks ({len(search_tasks)}): {json.dumps(search_tasks, indent=2)}")
            self.log(f"- Writing Plan: {json.dumps(writing_plan, indent=2)}")

        except Exception as e:
            self.log(f"Error during Planning Phase: {e}")
            # Optionally re-raise or return an error state
            return f"Failed during planning phase: {e}"

        # == Step 2: Initial Search Execution ==
        self.log("\n[Step 2/8] Executing initial Serper searches...")
        if not search_tasks: # Handle case where planner returned no tasks
            self.log("No search tasks planned. Skipping search execution.")
            raw_search_results = []
        else:
            self.log(f"Executing {len(search_tasks)} Serper search tasks...") # Log count
            search_result_obj: SearchResult[List[Dict[str, Any]]] = execute_batch_serper_search(
                search_tasks=search_tasks,
                config=self.serper_config
            )
            self.serper_queries_used += len(search_tasks) # Increment Serper count

            if search_result_obj.failed:
                self.log(f"Error during Serper batch search: {search_result_obj.error}")
                # Depending on desired robustness, could retry or return error
                return f"Failed to execute search: {search_result_obj.error}"

            raw_search_results = search_result_obj.data or [] # Ensure it's a list even if data is None
            self.log(f"Initial Serper searches complete. Received results for {len(raw_search_results)} tasks.")
            # Optional: Log details of the raw results if needed for debugging
            # self.log(f"Raw Search Results: {json.dumps(raw_search_results, indent=2)}")

        # == Step 3: Initial Content Processing & Source Reranking ==
        self.log("\n[Step 3/8] Processing sources and reranking...")
        unique_sources_map: Dict[str, Dict[str, Any]] = {}
        for task_result in raw_search_results:
            # Assuming batch response structure mirrors single response structure within the list
            # Focus on 'organic' results as per common usage, but could extend
            for source in task_result.get('organic', []):
                link = source.get('link')
                if link and link not in unique_sources_map:
                    # Store relevant fields
                    unique_sources_map[link] = {
                        'title': source.get('title', 'No Title'),
                        'link': link,
                        'snippet': source.get('snippet', ''),
                        # Keep other fields if needed later, e.g., 'date'
                    }

        all_sources = list(unique_sources_map.values())
        self.log(f"Consolidated {len(all_sources)} unique sources from search results.")

        top_m_sources = []
        next_k_sources = []

        if not all_sources:
            self.log("Warning: No unique sources found to process.")
            # Depending on desired behavior, could stop or continue with empty sources
            # For now, continue, subsequent steps should handle empty inputs
        else:
            try:
                docs_for_rerank = [f"{s.get('title', '')} {s.get('snippet', '')}" for s in all_sources]

                # Check if the configured reranker is JinaReranker
                is_jina = isinstance(self.reranker, JinaReranker)
                if is_jina:
                    self.log(f"Reranking {len(docs_for_rerank)} sources using Jina Rerank API via utility...")
                    # Call the utility function, passing the model from the JinaReranker instance
                    reranked_results = rerank_with_jina_api(
                        query=user_query,
                        documents=docs_for_rerank,
                        top_k=len(docs_for_rerank), # Rerank all initially
                        model=self.reranker.model # Get model name from the instance
                        # API key is handled internally by the utility function
                    )
                else:
                    self.log(f"Reranking {len(docs_for_rerank)} sources using {type(self.reranker).__name__}...")
                    # Use the standard rerank method for other rerankers (like Infinity)
                    reranked_results = self.reranker.rerank(
                        query=user_query, 
                        documents=docs_for_rerank, 
                        top_k=len(docs_for_rerank) # Rerank all initially
                        # Assuming other rerankers return the expected format
                    )

                if not reranked_results: # Handle potential empty list from API failure
                    raise ValueError("Reranking failed or returned empty results.")
                
                # Sort sources based on the reranked results
                # Results are already sorted by score descending by the API/rerank method
                sorted_sources = [all_sources[result['index']] for result in reranked_results]
                top_scores = [result['score'] for result in reranked_results]

                self.log(f"Reranking complete. Source scores range from {top_scores[0]:.4f} to {top_scores[-1]:.4f} (higher is better).")

                # Select Top M and Next K
                top_m_sources = sorted_sources[:self.top_m]
                next_k_sources = sorted_sources[self.top_m : self.top_m + self.next_k]

                self.log(f"Selected Top {len(top_m_sources)} sources for full text processing.")
                # Log selected source titles/links for verbosity
                for i, source in enumerate(top_m_sources):
                    self.log(f"  M{i+1}: {source.get('title')} ({source.get('link')})")

                self.log(f"Selected Next {len(next_k_sources)} sources for chunk processing.")
                for i, source in enumerate(next_k_sources):
                    self.log(f"  K{i+1}: {source.get('title')} ({source.get('link')})")

            except Exception as e:
                self.log(f"Error during source reranking: {e}. Proceeding without reranking.")
                # Fallback: Use original order or stop? For now, maybe take first M+K
                num_available = len(all_sources)
                top_m_sources = all_sources[:min(self.top_m, num_available)]
                next_k_sources = all_sources[self.top_m:min(self.top_m + self.next_k, num_available)]
                self.log(f"Fallback: Selected Top {len(top_m_sources)} and Next {len(next_k_sources)} sources based on original order.")

        # Ensure subsequent steps know which sources to process
        sources_to_fetch = top_m_sources + next_k_sources
        if not sources_to_fetch:
             self.log("No sources selected for fetching content.")
             # Decide if we should terminate the process here
             # return "Process terminated: No relevant sources found or processed."

        # == Step 4: Fetch Full Content ==
        # Fetch FULL content for ALL selected M+K sources
        self.log(f"\n[Step 4/8] Fetching full content for {len(sources_to_fetch)} sources...")
        fetched_content_map: Dict[str, Dict[str, Any]] = {} # Map source link -> {'content': str, 'title': str, 'link': str}

        for i, source in enumerate(sources_to_fetch):
            link = source.get('link')
            title = source.get('title', 'No Title')
            self.log(f"  [4.{i+1}/{len(sources_to_fetch)}] Processing source: {title} ({link})")

            if not link:
                self.log("    Skipping source: Missing link.")
                continue

            try:
                # Fetch content using the configured scraper
                extraction_results = await self.scraper.scrape(url=link)
                
                # Get the first successful result (assuming 'no_extraction' or similar)
                scraped_content = None
                for strategy_name, result in extraction_results.items():
                    # Prioritize 'no_extraction' if available and successful
                    if strategy_name == 'no_extraction' and result.success and result.content:
                         scraped_content = result.content
                         self.log(f"    Successfully extracted content using strategy: {strategy_name}")
                         break 
                    # Fallback to any other successful strategy
                    elif result.success and result.content:
                         scraped_content = result.content
                         self.log(f"    Successfully extracted content using strategy: {strategy_name} (fallback)")
                         # Don't break here, prefer no_extraction if it comes later
                
                # If no_extraction wasn't found or failed, check if we stored a fallback
                if not scraped_content:
                     # Check again if any strategy succeeded (in case no_extraction was checked first but failed)
                     for result in extraction_results.values():
                          if result.success and result.content:
                               scraped_content = result.content
                               self.log(f"    Successfully extracted content using strategy: {result.name} (final fallback)")
                               break

                if not scraped_content:
                    self.log(f"    Failed to fetch or extract content for: {link}")
                    continue

                # Store the full fetched content
                self.log(f"    Storing full content ({len(scraped_content)} chars).")
                fetched_content_map[link] = {'content': scraped_content, 'title': title, 'link': link}

            except Exception as e:
                self.log(f"    Error processing source {link}: {e}")
                # Continue to the next source

        self.log(f"Content fetching complete. Successfully fetched content for {len(fetched_content_map)} sources.")

        # == Step 5: Summarization == 
        # Removed refinement chunking/reranking of summaries
        self.log("\n[Step 5/8] Summarizing content...")
        source_summaries = [] # Use this list directly now

        if not fetched_content_map:
            self.log("No content fetched. Skipping summarization.")
        else:
            processed_count = 0
            for link, source_data in fetched_content_map.items():
                processed_count += 1
                self.log(f"  [5.{processed_count}/{len(fetched_content_map)}] Summarizing: {source_data['title']}")
                content_to_summarize = source_data.get('content')
                title = source_data.get('title', 'No Title')

                if not content_to_summarize:
                    self.log("    Skipping summary: No content found.")
                    continue
                
                # --- Get Summary --- 
                summary = ""
                try:
                    summarizer_messages = get_summarizer_prompt(
                        user_query=user_query,
                        source_title=title,
                        source_link=link,
                        source_content=content_to_summarize
                    )
                    self.log(f"    Calling Summarizer LLM ({self.summarizer_llm_config.get('model')}) for summary with retries...")
                    response = litellm.completion(
                        messages=summarizer_messages,
                        num_retries=3, # Add retries
                        **self.summarizer_llm_config
                    )
                    self._update_usage(response) # Update usage
                    summary = response.choices[0].message.content.strip()
                    if not summary:
                         self.log("    Summarizer returned empty content. Skipping source.")
                         continue # Skip adding this source if summary is empty
                    self.log(f"    Summary generated ({len(summary)} chars).")

                except Exception as e:
                    self.log(f"    Error summarizing source {link}: {e}. Skipping source.")
                    continue # Skip adding this source if summarization fails
                
                # --- Store Summary --- 
                source_summaries.append({
                     'title': title,
                     'link': link,
                     'summary': summary # Store the summary directly
                })

        self.log(f"Summarization complete. Generated {len(source_summaries)} summaries.")

        # == Step 6: Initial Report Generation ==
        self.log("\n[Step 6/8] Generating initial report...")
        report_draft = ""

        if not writing_plan:
            self.log("Cannot generate report: Missing writing plan from Planner.")
            return "Failed: No writing plan was generated."
        if not source_summaries:
            self.log("Warning: No summaries available to generate report from. Generating report based on plan only.")
            # Or potentially return an error/message here?

        try:
            writer_messages = get_writer_initial_prompt(
                user_query=user_query,
                writing_plan=writing_plan,
                source_summaries=source_summaries # Use the direct summaries
            )
            
            # Log the approximate size of the input messages
            total_input_chars = sum(len(msg.get('content', '')) for msg in writer_messages)
            self.log(f"Approximate characters in Writer LLM input: {total_input_chars}")
            # Optional: Estimate tokens (very rough)
            # estimated_tokens = total_input_chars / 4 # Rough estimate
            # self.log(f"Roughly estimated tokens: {estimated_tokens}")

            # Consider adding max_tokens for the writer response as well
            self.log(f"Calling Writer LLM ({self.writer_llm_config.get('model')}) for initial draft with retries...")
            response = litellm.completion(
                messages=writer_messages,
                num_retries=3, # Add retries
                # max_tokens=4000, # Example: Set a max output token limit
                **self.writer_llm_config
            )
            self._update_usage(response) # Update usage
            report_draft = response.choices[0].message.content.strip()
            self.log(f"Initial report generated ({len(report_draft)} chars).")
            # Log first few hundred chars of the draft for preview
            self.log(f"Initial Draft Preview:\n{report_draft[:300]}...")

        except Exception as e:
            self.log(f"Error during initial report generation: {e}")
            # Add detailed traceback logging
            self.log("--- Traceback Start ---")
            traceback_str = traceback.format_exc()
            self.log(traceback_str)
            self.log("--- Traceback End ---")
            # Return failure message
            return f"Failed during initial report generation. See logs for traceback. Error: {e}"

        # Keep track of all summaries accumulated across iterations
        all_summaries = list(source_summaries) # Start with these summaries

        # == Step 7: Refinement Loop ==
        self.log("\n[Step 7/8] Starting refinement loop...")
        current_iteration = 0
        while current_iteration < self.max_refinement_iterations:
            self.log(f"-- Refinement Iteration {current_iteration + 1}/{self.max_refinement_iterations} --")

            # Check for refinement request tag
            match = re.search(r'<request_more_info topic="(.*?)">', report_draft, re.IGNORECASE)

            if match:
                refinement_topic = match.group(1).strip()
                self.log(f"Writer requested more info on topic: '{refinement_topic}'")

                # --- Step 7a: Refinement Planning ---
                self.log("  [7a] Planning refinement search...")
                # TODO: Generate 1-2 targeted search queries for the topic.
                #       Could reuse Planner LLM or implement simpler logic.
                #       Example: Just use the topic as a query.
                refinement_search_tasks = [{
                    "query": refinement_topic, # Simple approach
                    "endpoint": "/search", # Default endpoint
                    "num_results": 5 # Fewer results needed for targeted search
                }]
                self.log(f"  Planned refinement tasks: {refinement_search_tasks}")

                # --- Step 7b: Refinement Search ---
                self.log("  [7b] Executing refinement search...")
                self.log(f"  Executing {len(refinement_search_tasks)} refinement Serper search tasks...") # Log count
                refinement_search_result_obj: SearchResult[List[Dict[str, Any]]] = execute_batch_serper_search(
                    search_tasks=refinement_search_tasks,
                    config=self.serper_config
                )
                self.serper_queries_used += len(refinement_search_tasks) # Increment Serper count

                if refinement_search_result_obj.failed:
                    self.log(f"    Error during refinement Serper search: {refinement_search_result_obj.error}. Skipping refinement iteration.")
                    # Skip to next iteration or break?
                    current_iteration += 1 # Ensure loop progresses
                    continue

                refinement_raw_results = refinement_search_result_obj.data or []
                self.log(f"  Refinement search complete. Received results for {len(refinement_raw_results)} tasks.")

                # --- Step 7c: Refinement Content Processing ---
                self.log("  [7c] Processing refinement sources...")
                refinement_unique_sources_map: Dict[str, Dict[str, Any]] = {}
                for task_result in refinement_raw_results:
                    for source in task_result.get('organic', []):
                        link = source.get('link')
                        if link and link not in refinement_unique_sources_map:
                            refinement_unique_sources_map[link] = {
                                'title': source.get('title', 'No Title'),
                                'link': link,
                                'snippet': source.get('snippet', '')
                            }

                # Select top N (e.g., 3) sources from refinement search results directly
                # No complex reranking usually needed for targeted refinement
                num_refinement_sources_to_select = 3 # Configurable? For now, hardcode.
                refinement_sources_to_fetch = list(refinement_unique_sources_map.values())[:num_refinement_sources_to_select]
                self.log(f"  Selected {len(refinement_sources_to_fetch)} unique sources for refinement processing.")

                # --- Step 7d: Refinement Extraction & Summarization ---
                self.log("  [7d] Fetching, extracting, and summarizing refinement content...")
                new_summaries = []
                if not refinement_sources_to_fetch:
                    self.log("    No refinement sources to process.")
                else:
                    for idx, source in enumerate(refinement_sources_to_fetch):
                        link = source.get('link')
                        title = source.get('title', 'No Title')
                        self.log(f"    [7d.{idx+1}] Processing refinement source: {title} ({link})")
                        if not link:
                            continue
                        try:
                            # Fetch & Extract
                            extraction_results = await self.scraper.scrape(url=link)
                            
                            # Get the first successful result
                            scraped_content = None
                            for strategy_name, result in extraction_results.items():
                                if result.success and result.content:
                                    scraped_content = result.content
                                    self.log(f"      Successfully extracted refinement content using strategy: {strategy_name}")
                                    break

                            if not scraped_content:
                                self.log(f"      Failed to fetch/extract refinement content for: {link}")
                                continue
                            self.log(f"      Fetched content ({len(scraped_content)} chars). Summarizing...")

                            # Summarize
                            try: # Add try/except around refinement summarizer call
                                summarizer_messages = get_summarizer_prompt(
                                    user_query=user_query, # Pass original query for context
                                    source_title=title,
                                    source_link=link,
                                    source_content=scraped_content
                                )
                                self.log(f"      Calling Summarizer LLM ({self.summarizer_llm_config.get('model')}) for refinement summary with retries...")
                                response = litellm.completion(
                                    messages=summarizer_messages,
                                    num_retries=3, # Add retries
                                    **self.summarizer_llm_config
                                )
                                self._update_usage(response) # Update usage
                                summary = response.choices[0].message.content.strip()
                                if summary:
                                    new_summaries.append({
                                        'title': title,
                                        'link': link,
                                        'summary': summary
                                    })
                                    self.log(f"      Summary generated ({len(summary)} chars).")
                                else:
                                    self.log("      Summarizer returned empty content for refinement source.")
                            except Exception as e_ref_sum:
                                self.log(f"      Error summarizing refinement source {link}: {e_ref_sum}")

                        except Exception as e:
                            self.log(f"      Error processing refinement source {link}: {e}")

                self.log(f"  Generated {len(new_summaries)} new summaries for refinement topic '{refinement_topic}'.")

                # Add new summaries to the accumulated list if any were generated
                if new_summaries:
                    all_summaries.extend(new_summaries)
                else:
                    self.log("    No new summaries generated in this refinement iteration. Report might not be updated.")
                    # Optionally skip the writer call if no new info?

                # --- Step 7e: Report Revision ---
                self.log("  [7e] Revising report with new information...")
                try:
                    writer_refinement_messages = get_writer_refinement_prompt(
                        user_query=user_query,
                        writing_plan=writing_plan,
                        previous_draft=report_draft,
                        refinement_topic=refinement_topic,
                        new_summaries=new_summaries,
                        all_summaries=all_summaries
                    )
                    
                    # Log input size for refinement call
                    total_refinement_chars = sum(len(msg.get('content', '')) for msg in writer_refinement_messages)
                    self.log(f"  Approximate characters in Writer refinement input: {total_refinement_chars}")
                    self.log(f"  Calling Writer LLM ({self.writer_llm_config.get('model')}) for revision with retries...")
                    
                    response = litellm.completion(
                        messages=writer_refinement_messages,
                        num_retries=3, # Add retries
                        **self.writer_llm_config
                    )
                    self._update_usage(response) # Update usage
                    revised_report_draft = response.choices[0].message.content.strip()
                    self.log("  Report revision complete.")
                    # Log first few hundred chars of the revised draft
                    self.log(f"  Revised Draft Preview:\n{revised_report_draft[:300]}...")
                    # Update report draft for the next iteration check or final output
                    report_draft = revised_report_draft
                except Exception as e:
                    self.log(f"    Error during report revision: {e}. Keeping previous draft.")
                    # Add traceback for revision errors too?
                    self.log("    --- Revision Traceback Start ---")
                    traceback_str = traceback.format_exc()
                    self.log(traceback_str)
                    self.log("    --- Revision Traceback End ---")
                    # Keep the old draft and proceed to check again or exit loop

            else:
                # No tag found, refinement not needed for this iteration
                self.log("No refinement request found in the draft. Exiting loop.")
                break

            current_iteration += 1

        if current_iteration >= self.max_refinement_iterations:
            self.log(f"Reached maximum refinement iterations ({self.max_refinement_iterations}).")

        self.log("-- Refinement loop complete. --")

        # == Step 8: Final Output ==
        self.log("\n[Step 8/8] Finalizing report...")
        # Append the reference list
        if all_summaries:
            reference_list_str = "\n\nReferences:\n"
            for i, summary_info in enumerate(all_summaries):
                title = summary_info.get('title', 'Untitled')
                link = summary_info.get('link', '#')
                reference_list_str += f"{i+1}. [{title}]({link})\n"
            final_report = report_draft.strip() + "\n" + reference_list_str.strip()
            self.log("Appended reference list to the final report.")
        else:
            final_report = report_draft # No references to append
            self.log("No summaries generated, final report has no references.")
            
        # Log final usage stats
        self.log("--- Usage Summary --- ")
        self.log(f"LLM Tokens: Total={self.token_usage['total_tokens']}, Prompt={self.token_usage['prompt_tokens']}, Completion={self.token_usage['completion_tokens']}")
        self.log(f"Estimated LLM Cost: ${self.estimated_cost:.6f}")
        self.log(f"Serper Queries Used: {self.serper_queries_used}")
        self.log("---------------------")
        
        self.log("--- Deep Research complete! --- Delivering final report.")

        return final_report
