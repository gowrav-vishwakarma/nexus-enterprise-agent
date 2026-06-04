"""Tests for LLM Proxy and TokenCounter."""

import pytest

from nexus.llm.token_counter import TokenCounter


def test_token_counter_string():
    """Test counting tokens in raw strings."""
    # tiktoken counts standard strings
    assert TokenCounter.count_string("") == 0
    
    text = "Hello world! This is a simple test."
    tokens = TokenCounter.count_string(text, model="gpt-4o")
    # tiktoken installed or estimated
    assert tokens > 0


def test_token_counter_messages():
    """Test message token counting overheads."""
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
    ]
    
    tokens = TokenCounter.count_messages(messages, model="gpt-4o")
    assert tokens > 0
    
    # Adding a message should increase count
    messages.append({"role": "assistant", "content": "Hi there!"})
    tokens_after = TokenCounter.count_messages(messages, model="gpt-4o")
    assert tokens_after > tokens


def test_token_counter_fallback():
    """Test that token counter always returns a positive integer regardless of model name."""
    # For an unknown model, tiktoken falls back to cl100k_base encoding — still a positive count.
    count = TokenCounter.count_string("a" * 40, model="unsupported-model")
    assert count > 0
