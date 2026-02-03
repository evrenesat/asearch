from unittest.mock import MagicMock, patch, ANY
import pytest
from asky.core.page_crawler import PageCrawlerState, execute_page_crawler


def test_page_crawler_state_add_links():
    state = PageCrawlerState()
    # Turn 1
    links1 = [
        {"text": "Goog", "href": "http://google.com"},
        {"text": "Bing", "href": "http://bing.com"},
    ]
    simplified1 = state.add_links(links1)

    assert len(simplified1) == 2
    assert simplified1[0]["id"] == 1
    assert simplified1[1]["id"] == 2

    # Turn 2 - Encounter same link again
    links2 = [
        {"text": "Goog Again", "href": "http://google.com"},
        {"text": "Yahoo", "href": "http://yahoo.com"},
    ]
    simplified2 = state.add_links(links2)

    assert len(simplified2) == 2
    assert simplified2[0]["id"] == 1  # Reused ID
    assert simplified2[0]["text"] == "Goog Again"
    assert simplified2[1]["id"] == 3  # New ID

    # Check persistent mapping
    assert len(state.url_mapping) == 3
    assert state.url_mapping[1] == "http://google.com"
    assert state.url_mapping[2] == "http://bing.com"
    assert state.url_mapping[3] == "http://yahoo.com"


def test_page_crawler_state_resolve_ids():
    state = PageCrawlerState()
    state.url_mapping = {1: "http://a.com", 2: "http://b.com"}

    urls = state.get_urls_by_ids([1, 2, 3])
    assert len(urls) == 2
    assert "http://a.com" in urls
    assert "http://b.com" in urls


@patch("asky.core.page_crawler.execute_get_url_details")
def test_execute_page_crawler_url_mode(mock_details):
    mock_details.return_value = {
        "content": "Page content",
        "links": [{"text": "About", "href": "http://site.com/about"}],
    }

    state = PageCrawlerState()
    args = {"url": "http://site.com"}

    result = execute_page_crawler(args, state)

    assert result["content"] == "Page content"
    assert "1:About" in result["links"]
    assert state.url_mapping[1] == "http://site.com/about"


@patch("asky.core.page_crawler.execute_get_url_content")
def test_execute_page_crawler_link_ids_mode(mock_content):
    mock_content.return_value = {"http://a.com": "Content A"}

    state = PageCrawlerState()
    state.url_mapping = {1: "http://a.com"}

    # Test string input "1"
    args = {"link_ids": "1"}
    execute_page_crawler(args, state)
    mock_content.assert_called_with({"urls": ["http://a.com"]})

    # Test int input 1
    args = {"link_ids": 1}
    execute_page_crawler(args, state)
    mock_content.assert_called_with({"urls": ["http://a.com"]})


@patch("asky.core.page_crawler.execute_get_url_content")
@patch("asky.summarization._summarize_content")
def test_execute_page_crawler_summarize(mock_summarize, mock_content):
    mock_content.return_value = {"http://a.com": "Long content"}
    mock_summarize.return_value = "Short summary"

    state = PageCrawlerState()
    state.url_mapping = {1: "http://a.com"}

    args = {"link_ids": "1"}

    # Test with summarize=True
    result = execute_page_crawler(args, state, summarize=True)

    assert "http://a.com" in result
    assert "Summary of http://a.com" in result["http://a.com"]
    assert "Short summary" in result["http://a.com"]
    mock_summarize.assert_called_once()

    # Verify usage_tracker is passed
    mock_summarize.assert_called_with(
        content="Long content",
        prompt_template=ANY,
        max_output_chars=ANY,
        get_llm_msg_func=ANY,
        usage_tracker=None,
    )


def test_execute_page_crawler_mutual_exclusion():
    state = PageCrawlerState()
    args = {"url": "http://a.com", "link_ids": "1"}

    result = execute_page_crawler(args, state)
    assert "error" in result
    assert "Provide either 'url' OR 'link_ids'" in result["error"]


def test_execute_page_crawler_missing_args():
    state = PageCrawlerState()
    result = execute_page_crawler({}, state)
    assert "error" in result


def test_execute_page_crawler_invalid_ids():
    state = PageCrawlerState()
    # IDs not in state
    result = execute_page_crawler({"link_ids": "99"}, state)
    assert "error" in result
    assert "No valid URLs found" in result["error"]
