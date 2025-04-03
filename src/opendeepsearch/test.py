from opendeepsearch import OpenDeepSearchTool
from smolagents import CodeAgent, LiteLLMModel
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

# Initialize the tool (relies on env vars like SERPER_API_KEY, JINA_API_KEY, LITELLM_SEARCH_MODEL_ID)
# You can still override env vars by passing arguments here, e.g., reranker="jina"
search_tool = OpenDeepSearchTool(
    model_name="openrouter/google/gemini-2.0-flash-001", # Optional: relies on LITELLM_SEARCH_MODEL_ID
    reranker="jina" # Optional: relies on default or can be specified
)

# Initialize a model for the agent (relies on env vars like OPENROUTER_API_KEY, LITELLM_ORCHESTRATOR_MODEL_ID)
# You can override the model ID here if needed
model = LiteLLMModel(
    "openrouter/google/gemini-2.0-flash-001", # Optional: relies on LITELLM_ORCHESTRATOR_MODEL_ID or LITELLM_MODEL_ID
    temperature=0.2
)

# Initialize the agent with the tool and model
# The agent framework will call search_tool.setup() automatically
code_agent = CodeAgent(tools=[search_tool], model=model)

query = "Fastest land animal?"
# Run the query through the agent
result = code_agent.run(query)
print(result)