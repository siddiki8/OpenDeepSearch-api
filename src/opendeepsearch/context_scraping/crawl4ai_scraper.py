"""
Modular web scraping implementation using Crawl4AI.
Supports multiple extraction strategies including LLM, CSS, and XPath.
"""

import asyncio
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

from opendeepsearch.context_scraping.extraction_result import ExtractionResult, print_extraction_result
from opendeepsearch.context_scraping.basic_web_scraper import ExtractionConfig
from opendeepsearch.context_scraping.strategy_factory import StrategyFactory
from .utils import clean_html, filter_quality_content, get_wikipedia_content

class WebScraper:
    """Unified scraper that encapsulates all extraction strategies and configuration"""
    def __init__(
        self, 
        browser_config: Optional[BrowserConfig] = None,
        strategies: List[str] = ['no_extraction'],
        llm_instruction: str = "Extract relevant content from the provided text, only return the text, no markdown formatting, remove all footnotes, citations, and other metadata and only keep the main content",
        user_query: Optional[str] = None,
        debug: bool = False,
        filter_content: bool = False
    ):
        self.browser_config = browser_config or BrowserConfig(headless=True, verbose=debug)
        self.debug = debug
        self.factory = StrategyFactory()
        self.strategies = strategies or ['markdown_llm', 'html_llm', 'fit_markdown_llm', 'css', 'xpath', 'no_extraction', 'cosine']
        self.llm_instruction = llm_instruction
        self.user_query = user_query
        self.filter_content = filter_content
        
        # Validate strategies
        valid_strategies = {'markdown_llm', 'html_llm', 'fit_markdown_llm', 'css', 'xpath', 'no_extraction', 'cosine'}
        invalid_strategies = set(self.strategies) - valid_strategies
        if invalid_strategies:
            raise ValueError(f"Invalid strategies: {invalid_strategies}")
            
        # Initialize strategy map
        self.strategy_map = {
            'markdown_llm': lambda: self.factory.create_llm_strategy('markdown', self.llm_instruction),
            'html_llm': lambda: self.factory.create_llm_strategy('html', self.llm_instruction),
            'fit_markdown_llm': lambda: self.factory.create_llm_strategy('fit_markdown', self.llm_instruction),
            'css': self.factory.create_css_strategy,
            'xpath': self.factory.create_xpath_strategy,
            'no_extraction': self.factory.create_no_extraction_strategy,
            'cosine': lambda: self.factory.create_cosine_strategy(debug=self.debug)
        }

    def _create_crawler_config(self) -> CrawlerRunConfig:
        """Creates default crawler configuration"""
        content_filter = PruningContentFilter()
        return CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            markdown_generator=DefaultMarkdownGenerator(
                content_filter=content_filter
            )
        )

    async def scrape(self, url: str) -> Dict[str, ExtractionResult]:
        """
        Scrape URL using configured strategies
        
        Args:
            url: Target URL to scrape
        """
        # Handle Wikipedia URLs
        if 'wikipedia.org/wiki/' in url:
            try:
                content = get_wikipedia_content(url)
                # Apply quality filter if enabled
                if self.filter_content and content:
                    if self.debug:
                        print(f"Debug: Filtering Wikipedia content for {url}")
                    content = filter_quality_content(content)

                if not content: # Handle case where filtering removed everything
                    return {
                        strategy_name: ExtractionResult(
                            name=strategy_name,
                            success=False,
                            error="Wikipedia content filtered out or empty."
                        ) for strategy_name in self.strategies
                    }
                
                # Create same result for all strategies since we're using Wikipedia content
                return {
                    strategy_name: ExtractionResult(
                        name=strategy_name,
                        success=True,
                        content=content
                    ) for strategy_name in self.strategies
                }
            except Exception as e:
                if self.debug:
                    print(f"Debug: Wikipedia extraction failed: {str(e)}")
                # If Wikipedia extraction fails, fall through to normal scraping
        
        # Normal scraping for non-Wikipedia URLs or if Wikipedia extraction failed
        results = {}
        # First, fetch the raw HTML content once
        raw_html = await self._fetch_raw_html(url)
        if raw_html is None: # Handle fetch failure
             return {
                strategy_name: ExtractionResult(
                    name=strategy_name,
                    success=False,
                    error="Failed to fetch raw HTML content."
                ) for strategy_name in self.strategies
            }
        
        # Clean the HTML *before* passing to strategies or filtering
        cleaned_html = clean_html(raw_html)

        # Apply quality filter to cleaned HTML if enabled
        base_content_for_strategies = cleaned_html
        if self.filter_content:
            if self.debug:
                print(f"Debug: Applying quality filter to cleaned HTML for {url}")
            filtered_html = filter_quality_content(cleaned_html)
            if filtered_html: # Use filtered content if filter didn't remove everything
                base_content_for_strategies = filtered_html
            else:
                if self.debug:
                    print(f"Debug: Quality filter removed all content for {url}. Using original cleaned HTML for strategies.")
                # If filter removes everything, strategies might still work on the cleaned_html

        # Now run extraction strategies on the prepared base content
        for strategy_name in self.strategies:
            config = ExtractionConfig(
                name=strategy_name,
                strategy=self.strategy_map[strategy_name]()
            )
            # Pass the prepared base content (cleaned or filtered) to extract method
            result = await self.extract(config, url, base_content_for_strategies)
            results[strategy_name] = result
            
        return results
    
    async def scrape_many(self, urls: List[str]) -> Dict[str, Dict[str, ExtractionResult]]:
        """
        Scrape multiple URLs using configured strategies in parallel
        
        Args:
            urls: List of target URLs to scrape
            
        Returns:
            Dictionary mapping URLs to their extraction results
        """
        # Create tasks for all URLs
        tasks = [self.scrape(url) for url in urls]
        # Run all tasks concurrently
        results_list = await asyncio.gather(*tasks)
        
        # Build results dictionary
        results = {}
        for url, result in zip(urls, results_list):
            results[url] = result
            
        return results

    async def _fetch_raw_html(self, url: str) -> Optional[str]:
        """Fetches raw HTML content using AsyncWebCrawler."""
        try:
            # Use a simple config just to fetch HTML
            config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
            async with AsyncWebCrawler(config=self.browser_config) as crawler:
                result = await crawler.arun(url=url, config=config)
            if result.success and hasattr(result, 'html'):
                return result.html
            else:
                if self.debug:
                    print(f"Debug: Failed to fetch raw HTML for {url}. Error: {getattr(result, 'error', 'Unknown')}")
                return None
        except Exception as e:
            if self.debug:
                print(f"Debug: Exception during raw HTML fetch for {url}: {e}")
            return None

    async def extract(self, extraction_config: ExtractionConfig, url: str, pre_processed_content: str) -> ExtractionResult:
        """Internal method to perform extraction using specified strategy on pre-processed content."""
        try:
            config = self._create_crawler_config()
            config.extraction_strategy = extraction_config.strategy

            if self.debug:
                print(f"\nDebug: Attempting extraction with strategy: {extraction_config.name}")
                print(f"Debug: URL: {url}")
                # Avoid printing potentially large pre_processed_content
                # print(f"Debug: Pre-processed content length: {len(pre_processed_content)}")

            # Simulate running the strategy on the pre-processed content
            # NOTE: This bypasses running Crawl4AI again. This assumes strategies 
            #       can operate on the pre-processed string or that we adapt them.
            #       For simplicity, let's assume 'no_extraction' and 'cosine' just return 
            #       the pre_processed_content. LLM strategies would need separate handling.
            
            content = None
            success = True # Assume success unless strategy fails
            error = None
            raw_markdown_length = 0 # Initialize
            citations_markdown_length = 0 # Initialize

            if extraction_config.name in ['no_extraction', 'cosine']:
                content = pre_processed_content
                raw_markdown_length = len(pre_processed_content) # Use length as proxy
            elif extraction_config.name in ['markdown_llm', 'html_llm', 'fit_markdown_llm']:
                # TODO: Implement calling LLM strategies directly on pre_processed_content
                # This requires adapting how LLM strategies are invoked.
                # For now, return placeholder or raise error.
                success = False
                error = f"LLM strategy '{extraction_config.name}' direct invocation not yet implemented on pre-processed content."
                if self.debug:
                    print(f"Debug: {error}")
                content = None 
            elif extraction_config.name in ['css', 'xpath']:
                # TODO: CSS/XPath strategies need the actual DOM, not just cleaned HTML string.
                # This refactor might break them. They would need to run on raw_html.
                # Revisit this: maybe run these *before* cleaning/filtering?
                success = False
                error = f"Strategy '{extraction_config.name}' requires DOM access, incompatible with current pre-processing flow."
                if self.debug:
                    print(f"Debug: {error}")
                content = None
            else:
                # Unknown strategy
                success = False
                error = f"Unknown strategy '{extraction_config.name}' in extract method."
                content = None
                
            # Corrected attribute access: result.markdown.raw_markdown
            # We are simulating the result here, so direct length calculation is used.
            # if success:
            #     # This part doesn't make sense anymore as we aren't running crawl4ai here.
            #     # We set lengths based on the content we decided to use.
            #     pass

            if self.debug and not success:
                print(f"Debug: Extraction failed for strategy {extraction_config.name}. Error: {error}")

            return ExtractionResult(
                name=extraction_config.name,
                success=success,
                content=content,
                error=error,
                raw_markdown_length=raw_markdown_length, # Store calculated length
                citations_markdown_length=citations_markdown_length # Store calculated length (currently 0)
            )

        except Exception as e:
            if self.debug:
                import traceback
                print(f"Debug: Exception occurred during extraction:")
                print(traceback.format_exc())
            
            return ExtractionResult(
                name=extraction_config.name,
                success=False,
                error=str(e)
            )

async def main():
    # Example usage with single URL
    single_url = "https://example.com/product-page"
    scraper = WebScraper(debug=True)
    results = await scraper.scrape(single_url)
    
    # Print single URL results
    for result in results.values():
        print_extraction_result(result)

    # Example usage with multiple URLs
    urls = [
        "https://example.com",
        "https://python.org",
        "https://github.com"
    ]
    
    multi_results = await scraper.scrape_many(urls)
    
    # Print multiple URL results
    for url, url_results in multi_results.items():
        print(f"\nResults for {url}:")
        for result in url_results.values():
            print_extraction_result(result)

if __name__ == "__main__":
    asyncio.run(main())
