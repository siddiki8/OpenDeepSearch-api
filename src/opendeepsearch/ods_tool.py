from smolagents import Tool
from opendeepsearch.ods_agent import OpenDeepSearchAgent

class OpenDeepSearchTool(Tool):
    name = "web_search"
    description = """
    Performs web search based on your query (think a Google search) then returns the final answer that is processed by an llm."""
    inputs = {
        "query": {
            "type": "string",
            "description": "The search query to perform",
        },
    }
    output_type = "string"

    def __init__(self, model_name: str, reranker: str = "infinity"):
        super().__init__()
        self.search_model_name = model_name #LiteLLM model name
        self.reranker = reranker

    def forward(self, query: str) -> str:
        answer = self.search_tool.ask_sync(query, max_sources=2, pro_mode=True)
        return answer

    def setup(self):
        self.search_tool = OpenDeepSearchAgent(
            self.search_model_name,
            reranker=self.reranker
        )
