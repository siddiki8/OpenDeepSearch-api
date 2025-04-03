import json

_PLANNER_SYSTEM_PROMPT = \
"""
You are an expert research assistant responsible for planning the steps needed to answer a complex user query.
Your goal is to generate a structured plan containing:
1.  A list of `search_tasks`: Define 1-3 specific search queries for a web search engine (like Google via Serper API) to gather the necessary information. For each task, specify the query string, the most appropriate Serper endpoint (`/search`, `/scholar`, or `/news`), the desired number of results (`num_results`, typically 10 unless more are justified), and a brief reasoning.
2.  A detailed `writing_plan`: Outline the structure of the final report. This includes the overall goal, desired tone, specific sections with titles and guidance for each, and any additional directives for the writer.

Analyze the user's query carefully and devise a plan that will lead to a comprehensive and well-structured report.

Output *only* a single JSON object adhering to the following schema. Do not include any other text before or after the JSON object.

```json
{
  "search_tasks": [
    {
      "query": "Specific query string for Serper",
      "endpoint": "/search | /scholar | /news",
      "num_results": <integer>,
      "reasoning": "Why this query, endpoint, and result count are chosen"
    }
    // ... (1 to 3 tasks total)
  ],
  "writing_plan": {
    "overall_goal": "Provide a comprehensive analysis of [topic], focusing on [aspect1] and [aspect2], suitable for [audience].",
    "desired_tone": "Objective and analytical | Formal | Informal | etc.",
    "sections": [
      {
        "title": "Section Title",
        "guidance": "Specific instructions for the writer for this section."
      }
      // ... (multiple sections)
    ],
    "additional_directives": [
       "Directive 1 (e.g., citation style)",
       "Directive 2 (e.g., address counterarguments)"
       // ... (optional)
    ]
  }
}
```
"""

_PLANNER_USER_MESSAGE_TEMPLATE = "Create a research plan for the following query: {user_query}"

def get_planner_prompt(user_query: str) -> list[dict[str, str]]:
    """
    Generates the message list for the Planner LLM.

    Args:
        user_query: The user's research query.

    Returns:
        A list of messages suitable for litellm.completion.
    """
    return [
        {"role": "system", "content": _PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": _PLANNER_USER_MESSAGE_TEMPLATE.format(user_query=user_query)}
    ]

# TODO: Add prompts for Summarizer and Writer LLMs later
# def get_writer_initial_prompt(...)
# def get_writer_refinement_prompt(...)

_SUMMARIZER_SYSTEM_PROMPT = \
"""
You are an expert summarizer. Your task is to create a concise, factual summary of the provided text content. 
Focus specifically on extracting information relevant to answering the user's original research query, which will be used to generate a comprehensive report.
Extract key facts, findings, arguments, and data points pertinent to the user's query topic.
Maintain a neutral, objective tone.
The summary should be dense with relevant information but easy to understand.
Do not add introductions or conclusions like 'The text discusses...' or 'In summary...'. Just provide the summary content itself.
Focus on accurately representing the information from the provided text ONLY.
"""

_SUMMARIZER_USER_MESSAGE_TEMPLATE = \
"""
Please summarize the following text content extracted from the source titled '{source_title}' (URL: {source_link}). Focus on information that might be relevant for a research report addressing the query: '{user_query}'

Text Content:
```
{source_content}
```

Concise Summary:"""

def get_summarizer_prompt(user_query: str, source_title: str, source_link: str, source_content: str) -> list[dict[str, str]]:
    """
    Generates the message list for the Summarizer LLM.

    Args:
        user_query: The original user research query (for context).
        source_title: The title of the source document.
        source_link: The URL of the source document.
        source_content: The extracted text content (full or chunked) to summarize.

    Returns:
        A list of messages suitable for litellm.completion.
    """
    return [
        {"role": "system", "content": _SUMMARIZER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _SUMMARIZER_USER_MESSAGE_TEMPLATE.format(
                user_query=user_query,
                source_title=source_title,
                source_link=source_link,
                source_content=source_content
            )
        }
    ]

# --- Writer Prompts ---

_WRITER_SYSTEM_PROMPT_BASE = \
"""
You are an expert research report writer. Your goal is to synthesize information from provided source summaries into a well-structured, coherent, and informative report.
Follow the provided writing plan precisely, including the overall goal, tone, section structure, and specific guidance for each section.
Integrate the information from the source summaries naturally into the report narrative.
**Crucially, you MUST cite your sources using numerical markers.** Each source summary is provided with a numerical marker (e.g., [1], [2]). When you use information from a summary, add the corresponding numerical citation marker immediately after the information (e.g., 'Quantum computing poses a threat [1].'). Use multiple citations if information comes from several sources (e.g., 'Several sources discuss this [2][3].').
Maintain a logical flow and ensure the report directly addresses the original user query.
**Do NOT generate a bibliography or reference list at the end; this will be added later.**

If, while writing, you determine that you lack sufficient specific information on a crucial sub-topic required by the writing plan, you can request more information. To do this, insert the exact tag `<request_more_info topic="...">` at the point in the text where the information is needed. Replace "..." with a concise description of the specific information required. Use this tag *only* if absolutely necessary to fulfill the writing plan requirements and *only once* per draft.
"""

# For Initial Draft Generation
_WRITER_USER_MESSAGE_TEMPLATE_INITIAL = \
"""
Original User Query: {user_query}

Writing Plan:
```json
{writing_plan_json}
```

Source Summaries (Cite using the numerical markers provided, e.g., [1], [2]):
{formatted_summaries}

---

Please generate the initial draft of the research report based *only* on the provided writing plan and source summaries. Follow all instructions in the system prompt, especially regarding structure, tone, and numerical citations (e.g., [1], [2]). **Do NOT include a reference list.** If necessary, use the `<request_more_info topic="...">` tag as described in the system prompt.

Report Draft:
"""

def format_summaries_for_prompt(source_summaries: list[dict[str, str]]) -> str:
    """Formats the list of summaries for inclusion in the writer prompt, using numerical citations."""
    if not source_summaries:
        return "No summaries available."
    
    formatted = []
    for i, summary_info in enumerate(source_summaries):
        # Create numerical citation marker
        citation_marker = f"[{i+1}]"
        title = summary_info.get('title', 'Untitled')
        link = summary_info.get('link', '#')
        summary = summary_info.get('summary', 'No summary content.')
        # Include Title/Link for context, but instruct LLM to use the marker [i+1]
        formatted.append(f"Source {citation_marker} (Title: {title}, Link: {link})\nSummary: {summary}")
    
    return "\n\n".join(formatted)

def get_writer_initial_prompt(user_query: str, writing_plan: dict, source_summaries: list[dict[str, str]]) -> list[dict[str, str]]:
    """
    Generates the message list for the Writer LLM (initial draft).

    Args:
        user_query: The original user query.
        writing_plan: The JSON writing plan from the Planner.
        source_summaries: List of dictionaries, each containing 'title', 'link', 'summary'.

    Returns:
        A list of messages suitable for litellm.completion.
    """
    formatted_summaries_str = format_summaries_for_prompt(source_summaries)
    writing_plan_str = json.dumps(writing_plan, indent=2)
    
    return [
        {"role": "system", "content": _WRITER_SYSTEM_PROMPT_BASE},
        {
            "role": "user",
            "content": _WRITER_USER_MESSAGE_TEMPLATE_INITIAL.format(
                user_query=user_query,
                writing_plan_json=writing_plan_str,
                formatted_summaries=formatted_summaries_str
            )
        }
    ]

# For Refinement/Revision
_WRITER_USER_MESSAGE_TEMPLATE_REFINEMENT = \
"""
Original User Query: {user_query}

Writing Plan:
```json
{writing_plan_json}
```

Previously Generated Draft:
```
{previous_draft}
```

*New* Source Summaries (to address the request for more info on '{refinement_topic}'. Cite using their *new* numerical markers as provided below):
{formatted_new_summaries}

All Available Source Summaries (Initial + Previous Refinements - Use these markers for citation):
{formatted_all_summaries}

---

Please revise the previous draft of the research report.
Your primary goal is to incorporate the *new* source summaries provided above to specifically address the request for more information on the topic: '{refinement_topic}'.
Integrate the new information smoothly into the existing structure defined by the writing plan.
Ensure you *maintain* the overall structure, tone, and guidance from the original writing plan.
Crucially, continue to cite *all* sources accurately using the provided numerical markers (e.g., [1], [2], [15]) for both new and previously used information based on the 'All Available Source Summaries' list. **Do NOT include a reference list.**
If necessary, you may use the `<request_more_info topic="...">` tag again if *absolutely critical* information for the plan is still missing, but avoid it if possible.

Revised Report Draft:
"""

def get_writer_refinement_prompt(
    user_query: str,
    writing_plan: dict,
    previous_draft: str,
    refinement_topic: str,
    new_summaries: list[dict[str, str]],
    all_summaries: list[dict[str, str]] # Includes initial + all refinement summaries so far
) -> list[dict[str, str]]:
    """
    Generates the message list for the Writer LLM (refinement/revision).

    Args:
        user_query: The original user query.
        writing_plan: The JSON writing plan from the Planner.
        previous_draft: The previous report draft generated by the writer.
        refinement_topic: The specific topic requested via the <request_more_info> tag.
        new_summaries: List of summaries gathered specifically for this refinement topic.
        all_summaries: List of all summaries gathered so far (initial + all refinements).

    Returns:
        A list of messages suitable for litellm.completion.
    """
    # Format the summaries with their correct numerical indices based on the FULL list
    # Find the starting index for new summaries within the all_summaries list
    start_index_new = len(all_summaries) - len(new_summaries)
    formatted_new_summaries_str = format_summaries_for_prompt_with_offset(new_summaries, start_index_new)
    formatted_all_summaries_str = format_summaries_for_prompt(all_summaries) # Uses standard 1-based indexing
    writing_plan_str = json.dumps(writing_plan, indent=2)

    return [
        {"role": "system", "content": _WRITER_SYSTEM_PROMPT_BASE},
        {
            "role": "user",
            "content": _WRITER_USER_MESSAGE_TEMPLATE_REFINEMENT.format(
                user_query=user_query,
                writing_plan_json=writing_plan_str,
                previous_draft=previous_draft,
                refinement_topic=refinement_topic,
                formatted_new_summaries=formatted_new_summaries_str,
                formatted_all_summaries=formatted_all_summaries_str
            )
        }
    ]

# Helper for refinement prompt to show correct indices for new summaries
def format_summaries_for_prompt_with_offset(summaries: list[dict[str, str]], offset: int) -> str:
    """Formats summaries with numerical citations starting from an offset."""
    if not summaries:
        return "No new summaries available."
    
    formatted = []
    for i, summary_info in enumerate(summaries):
        citation_marker = f"[{offset + i + 1}]" # Index starts from offset + 1
        title = summary_info.get('title', 'Untitled')
        link = summary_info.get('link', '#')
        summary = summary_info.get('summary', 'No summary content.')
        formatted.append(f"Source {citation_marker} (Title: {title}, Link: {link})\nSummary: {summary}")
    
    return "\n\n".join(formatted)
