# Script to run the DeepResearchAgent

import os
import sys
import asyncio # Added for async support
import argparse # Import argparse

async def main():
    # --- Argument Parsing --- 
    parser = argparse.ArgumentParser(description="Run the Deep Research Agent.")
    parser.add_argument(
        "query", 
        nargs='?', # Make query optional
        type=str, 
        default="Analyze the impact of quantum computing on cybersecurity threats", # Default query
        help="The research query for the agent."
    )
    args = parser.parse_args()
    user_query = args.query # Get query from parsed args
    # --------------------------
    
    # Add the src directory to the Python path to allow imports
    # Assuming the script is run from the root of the OpenDeepSearch-api workspace
    workspace_root = os.getcwd()
    src_path = os.path.join(workspace_root, 'src')
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    print(f"Workspace root: {workspace_root}")
    print(f"Adding src path: {src_path}")
    print(f"Current sys.path includes: {src_path in sys.path}")

    # Attempt to load environment variables from .env file
    try:
        from dotenv import load_dotenv
        load_dotenv()
        print("Loaded environment variables from .env (if present).", flush=True)
    except ImportError:
        print("dotenv library not found. Skipping loading .env file. Ensure env vars are set.", flush=True)

    # Check for necessary API keys (optional, but good practice)
    serper_key = os.getenv("SERPER_API_KEY")
    jina_key = os.getenv("JINA_API_KEY")
    openrouter_key = os.getenv("OPENROUTER_API_KEY")

    if not serper_key:
        print("Warning: SERPER_API_KEY not found in environment.", flush=True)
    # Jina key check is usually handled within the class if required and not found
    if not openrouter_key:
        print("Warning: OPENROUTER_API_KEY not found in environment. LiteLLM might fail.", flush=True)
    
    try:
        # Import necessary components AFTER potentially modifying sys.path
        print("Importing OpenDeepSearch components...", flush=True)
        from opendeepsearch import DeepResearchAgent, Chunker
        # Import both reranker types
        from opendeepsearch.ranking_models.jina_reranker import JinaReranker 
        from opendeepsearch.ranking_models.infinity_rerank import InfinitySemanticSearcher
        from opendeepsearch.context_scraping.crawl4ai_scraper import WebScraper
        print("Imports successful.", flush=True)

        # 1. Configure LLMs based on DR_agent_plan.md (using potentially updated free models)
        # Using free models might be slow or have rate limits
        planner_config = {"model": "openrouter/google/gemini-2.0-flash-thinking-exp-1219:free"}
        summarizer_config = {"model": "openrouter/google/gemini-2.0-flash-exp:free"}
        writer_config = {"model": "openrouter/google/gemini-2.5-pro-exp-03-25:free"}
        print(f"LLM Configs: Planner={planner_config['model']}, Summarizer={summarizer_config['model']}, Writer={writer_config['model']}", flush=True)

        # 2. Configure and Instantiate Reranker & Chunker
        print("Instantiating Reranker and Chunker...", flush=True)
        # Switch to InfinitySemanticSearcher
        # Ensure your Infinity server is running at the specified endpoint
        # You can customize endpoint and model if needed:
        # reranker = InfinitySemanticSearcher(embedding_endpoint="YOUR_ENDPOINT", model_name="YOUR_MODEL")
        reranker = InfinitySemanticSearcher() 
        print(f"Using Reranker: {type(reranker).__name__} (Endpoint: {reranker.embedding_endpoint}, Model: {reranker.model_name})")

        chunker = Chunker(chunk_size=512, chunk_overlap=50)
        print("Reranker and Chunker instantiated.", flush=True)

        # 3. Instantiate Agent
        print("Instantiating DeepResearchAgent...", flush=True)
        agent = DeepResearchAgent(
            planner_llm_config=planner_config,
            summarizer_llm_config=summarizer_config,
            writer_llm_config=writer_config,
            reranker=reranker,
            chunker=chunker,
            scraper_strategies=['no_extraction'],  # Updated parameter name
            verbose=True # Enable verbose logging to see progress
        )
        print("DeepResearchAgent instantiated.", flush=True)

        # 4. Define User Query (Now from CLI args)
        # user_query = "Analyze the impact of quantum computing on cybersecurity threats"
        print(f"User query: \"{user_query}\"", flush=True)

        # 5. Run Research (now with await since it's async)
        print("\n--- STARTING DEEP RESEARCH ---", flush=True)
        final_report = await agent.run_deep_research(user_query)
        print("\n--- DEEP RESEARCH COMPLETE ---", flush=True)

        # 6. Print Final Report
        print("\n\n======== FINAL REPORT ========", flush=True)
        print(final_report)
        print("============================", flush=True)

    except ImportError as e:
         print(f"Import Error: {e}", file=sys.stderr, flush=True)
         print("Please ensure you are running this script from the root directory of the OpenDeepSearch-api project", file=sys.stderr, flush=True)
         print(f"Current working directory: {os.getcwd()}", file=sys.stderr, flush=True)
         print(f"sys.path: {sys.path}", file=sys.stderr, flush=True)
         sys.exit(1)
    except Exception as e:
        print(f"\n\nAn error occurred during agent setup or execution: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)

# Add the code to run the main function
if __name__ == "__main__":
    # Run the async main function
    asyncio.run(main()) 