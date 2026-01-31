"""Test async structured output with langchain."""

from dotenv import load_dotenv
load_dotenv()  # Load .env before any other imports

import asyncio
from typing import Literal
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI

from backend.core.config import config


class ToolDecision(BaseModel):
    """Decision about which tool to use."""
    reasoning: str = Field(description="Your reasoning for the decision")
    action: Literal["SEARCH", "STOP", "READ"] = Field(description="Action to take")
    query: str = Field(description="Search query if action is SEARCH")


# Real schema from decision.py
from typing import Union, Annotated, Optional

class BaseToolParams(BaseModel):
    pass

class WebSearchParams(BaseToolParams):
    tool: Literal["web_search"] = "web_search"
    themes: list[str] = Field(description="List of search queries to execute")

class TerminalParams(BaseToolParams):
    tool: Literal["terminal"] = "terminal"
    command: str = Field(description="Shell command to execute")
    timeout: int = Field(default=60, description="Timeout in seconds")

class ReadFileParams(BaseToolParams):
    tool: Literal["read_file"] = "read_file"
    path: str = Field(description="Path to the file to read")
    start_line: Optional[int] = Field(default=None, description="Starting line number")
    end_line: Optional[int] = Field(default=None, description="Ending line number")

class KnowledgeParams(BaseToolParams):
    tool: Literal["knowledge"] = "knowledge"
    answer: str = Field(description="Knowledge-based answer to provide")

ToolParams = Annotated[
    Union[WebSearchParams, TerminalParams, ReadFileParams, KnowledgeParams],
    Field(discriminator="tool"),
]

class RealToolDecision(BaseModel):
    """Schema for tool decision response - same as in decision.py."""
    reasoning: str = Field(description="1-2 sentences explaining the choice")
    params: ToolParams = Field(description="Tool selection and its parameters")


async def test_basic_structured():
    """Test basic structured output."""
    print("\n=== Test 1: Basic with_structured_output ===")

    llm = ChatOpenAI(
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
        model=config.llm.model,
        temperature=0,
    )

    prompt = "Decide whether to search for more info about Python programming. If searching, provide a query."

    structured_llm = llm.with_structured_output(ToolDecision)
    result = await structured_llm.ainvoke(prompt)

    print(f"Type: {type(result)}")
    print(f"Result: {result}")
    return result


async def test_structured_with_raw():
    """Test structured output with include_raw=True."""
    print("\n=== Test 2: with_structured_output + include_raw ===")

    llm = ChatOpenAI(
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
        model=config.llm.model,
        temperature=0,
    )

    prompt = "Decide whether to search for more info about Python programming. If searching, provide a query."

    structured_llm = llm.with_structured_output(ToolDecision, include_raw=True)
    result = await structured_llm.ainvoke(prompt)

    print(f"Keys: {result.keys()}")
    print(f"Parsed: {result.get('parsed')}")
    print(f"Raw type: {type(result.get('raw'))}")
    if result.get('raw'):
        raw = result['raw']
        print(f"Raw content: {raw.content[:200] if raw.content else 'empty'}...")
        print(f"Raw usage: {getattr(raw, 'usage_metadata', None)}")
    print(f"Parsing error: {result.get('parsing_error')}")
    return result


async def test_long_response():
    """Test with a prompt that requires longer response."""
    print("\n=== Test 3: Long response ===")

    llm = ChatOpenAI(
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
        model=config.llm.model,
        temperature=0,
    )

    prompt = """You are researching "How do large language models work internally?"

Previous search returned these results:
1. Transformers use attention mechanisms
2. GPT models are decoder-only
3. Training involves next-token prediction

Based on this, decide your next action. Provide detailed reasoning explaining why you chose this action and what specific information you're looking for."""

    structured_llm = llm.with_structured_output(ToolDecision, include_raw=True)
    result = await structured_llm.ainvoke(prompt)

    print(f"Parsed: {result.get('parsed')}")
    if result.get('parsing_error'):
        print(f"Error: {result.get('parsing_error')}")
        raw = result.get('raw')
        if raw:
            print(f"Raw content length: {len(raw.content) if raw.content else 0}")
            print(f"Raw content: {raw.content}")
    return result


async def test_raw_response():
    """Test what vLLM actually returns."""
    print("\n=== Test 6: Raw vLLM response ===")

    llm = ChatOpenAI(
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
        model=config.llm.model,
        temperature=0,
    )

    prompt = "Decide: SEARCH or STOP. Return JSON: {\"action\": \"...\", \"reason\": \"...\"}"

    # Direct call without structured output
    response = await llm.ainvoke(prompt)
    print(f"Type: {type(response)}")
    print(f"Content: {response.content!r}")
    print(f"Additional kwargs: {response.additional_kwargs}")
    print(f"Response metadata: {response.response_metadata}")


async def test_real_decision_schema():
    """Test with the real ToolDecision schema from decision.py."""
    print("\n=== Test 5: Real ToolDecision schema ===")

    llm = ChatOpenAI(
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
        model=config.llm.model,
        temperature=0,
        # NO max_tokens limit
    )

    prompt = """You are an executor agent deciding which tool to use to gather information for a research task.

CURRENT TASK:
Search for peer‑reviewed articles that discuss how large language models (LLMs) are used to automate literature reviews and meta‑analyses in various scientific fields.

ORIGINAL QUERY:
How are LLMs used to automate literature reviews?

PREVIOUS ATTEMPT FEEDBACK:
The search results were not specific enough. Focus on peer-reviewed journals and academic sources.

PREVIOUS TOOL CALLS (this attempt):
- [1] web_search: SUCCESS
  Params: {'themes': ['LLM literature review automation']}
  Result: Found some blog posts but no academic sources...

ACCUMULATED RESULTS SO FAR:
[web_search]: Found some blog posts but no academic sources...

REMAINING CALLS: 2

AVAILABLE TOOLS:
1. web_search - Search the web for information
2. terminal - Execute a shell command (requires approval)
3. read_file - Read a local file
4. knowledge - Answer from your own knowledge (use sparingly)

GUIDELINES:
- Prefer web_search for most information gathering
- Use terminal only when you need to run commands (e.g., check versions, run scripts)
- Use read_file when you need to examine specific local files
- Use knowledge only for well-established facts that don't need verification
- If you have feedback from a previous attempt, use it to guide your approach
- Always choose the most appropriate tool for the next step"""

    structured_llm = llm.with_structured_output(RealToolDecision, include_raw=True)
    result = await structured_llm.ainvoke(prompt)

    print(f"Parsed: {result.get('parsed')}")
    if result.get('parsed'):
        parsed = result['parsed']
        print(f"  Tool: {parsed.params.tool}")
        print(f"  Reasoning: {parsed.reasoning[:100]}...")
    if result.get('parsing_error'):
        print(f"Error: {result.get('parsing_error')}")
        raw = result.get('raw')
        if raw:
            print(f"Raw content: {raw.content}")
    return result


async def test_multiple_calls():
    """Test multiple sequential calls."""
    print("\n=== Test 4: Multiple sequential calls ===")

    llm = ChatOpenAI(
        api_key=config.llm.api_key,
        base_url=config.llm.base_url,
        model=config.llm.model,
        temperature=0,
    )

    structured_llm = llm.with_structured_output(ToolDecision)

    prompts = [
        "Should we search for info about machine learning? Decide.",
        "Should we search for info about neural networks? Decide.",
        "Should we stop searching and write a report? Decide.",
    ]

    for i, prompt in enumerate(prompts):
        print(f"\nCall {i+1}:")
        result = await structured_llm.ainvoke(prompt)
        print(f"  Action: {result.action}, Query: {result.query[:50] if result.query else 'N/A'}...")


async def main():
    print(f"Model: {config.llm.model}")
    print(f"Base URL: {config.llm.base_url}")

    try:
        await test_basic_structured()
    except Exception as e:
        print(f"ERROR: {e}")

    try:
        await test_structured_with_raw()
    except Exception as e:
        print(f"ERROR: {e}")

    try:
        await test_long_response()
    except Exception as e:
        print(f"ERROR: {e}")

    try:
        await test_raw_response()
    except Exception as e:
        print(f"ERROR: {e}")

    try:
        await test_real_decision_schema()
    except Exception as e:
        print(f"ERROR: {e}")

    try:
        await test_multiple_calls()
    except Exception as e:
        print(f"ERROR: {e}")

    print("\n=== DONE ===")


if __name__ == "__main__":
    asyncio.run(main())
