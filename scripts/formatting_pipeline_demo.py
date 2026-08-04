#!/usr/bin/env python3
"""
Manual diagnostic: compare raw LLM output against Streamlit's rendered Markdown.

Not a test - it calls the live OpenAI API and the real vector store, so it's
kept out of test/ where pytest would collect and run it automatically. Run
directly: python scripts/formatting_pipeline_demo.py
"""

# Standard library imports
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Local imports
from app import format_markdown_response
from core.ai_services.llm.chatbot import ChatbotService
from core.storage.vector_stores import get_vector_store_provider


def print_separator(title: str) -> None:
    """Print a visual separator with title."""
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def print_comparison(raw_text: str, processed_text: str) -> None:
    """Print side-by-side comparison of raw vs Streamlit-rendered text."""
    print_separator("RAW LLM OUTPUT")
    print(raw_text)

    print_separator("AFTER format_markdown_response (what Streamlit renders)")
    print(processed_text)

    print_separator("DIFFERENCES SUMMARY")
    print(f"Raw length: {len(raw_text)} characters")
    print(f"Processed length: {len(processed_text)} characters")


async def get_real_llm_response(query: str) -> str:
    """Get a real response from the LLM using the chatbot service."""
    try:
        chatbot_service = ChatbotService()

        _, current_embeddings, current_documents = get_vector_store_provider().get_data()

        if current_embeddings is None:
            current_embeddings = []

        result = await chatbot_service.async_get_response(
            query=query,
            embeddings=current_embeddings,
            documents=current_documents,
        )

        return result.get("response", "")

    except Exception as e:
        print(f"Error getting LLM response: {e}")
        return f"Error: {str(e)}"


def demo_real_llm_responses() -> None:
    """Run the formatting pipeline against real LLM responses."""
    test_queries = [
        "có template không?",
    ]

    print_separator("TESTING WITH REAL LLM RESPONSES")
    print("Getting real responses from the chatbot service...")

    for i, query in enumerate(test_queries, 1):
        print(f"\n--- Query {i}: {query} ---")

        raw_response = asyncio.run(get_real_llm_response(query))

        if raw_response.startswith("Error:"):
            print(f" Failed to get response: {raw_response}")
            continue

        processed_response = format_markdown_response(raw_response)

        print_separator(f"REAL LLM RESPONSE {i}: {query[:50]}...")
        print_comparison(raw_response, processed_response)
        print("\n" + "-" * 80 + "\n")

        # Small delay to avoid rate limiting between queries
        time.sleep(1)


def demo_edge_cases() -> None:
    """Run the formatting pipeline against edge cases and special scenarios."""
    print_separator("TESTING EDGE CASES")

    edge_cases = [
        ("Empty string", ""),
        ("Only escape sequences", "\\n\\n\\n"),
        ("Mixed escape sequences", "Text\\n\\nMore text\\nAnd more"),
        ("URLs only", "https://example.com and https://test.com"),
        ("Already formatted URLs", "[Example](https://example.com)"),
        ("No formatting needed", "Simple text without any special formatting"),
        ("Multiple consecutive newlines", "Text\\n\\n\\n\\n\\nMore text"),
    ]

    for title, raw_text in edge_cases:
        print(f"\n--- {title} ---")
        print(f"Raw: {repr(raw_text)}")
        processed = format_markdown_response(raw_text)
        print(f"Processed: {repr(processed)}")
        print(f"Result: {processed}")


def main() -> None:
    """Run both demos."""
    print("FORMATTING PIPELINE DEMO")
    print("Compares raw LLM output against what app.py actually renders.")

    demo_real_llm_responses()
    demo_edge_cases()

    print_separator("DONE")


if __name__ == "__main__":
    main()
