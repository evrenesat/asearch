import pytest
from asearch.html import HTMLStripper, strip_tags, strip_think_tags


def test_html_stripper_basic():
    html = "<html><body><p>Hello world</p></body></html>"
    stripper = HTMLStripper()
    stripper.feed(html)
    assert stripper.get_data() == "Hello world"


def test_html_stripper_with_scripts_and_styles():
    html = """
    <html>
        <head>
            <style>body { color: red; }</style>
            <script>console.log('ignore me');</script>
        </head>
        <body>
            <p>Content</p>
        </body>
    </html>
    """
    stripper = HTMLStripper()
    stripper.feed(html)
    assert stripper.get_data() == "Content"


def test_html_stripper_links():
    html = '<p>Check out <a href="https://example.com">Example</a>.</p>'
    stripper = HTMLStripper()
    stripper.feed(html)
    data = stripper.get_data()
    links = stripper.get_links()

    assert "Check out Example." in data
    assert len(links) == 1
    assert links[0] == {"text": "Example", "href": "https://example.com"}


def test_strip_tags_function():
    assert strip_tags("<p>Test</p>") == "Test"
    assert strip_tags("No tags") == "No tags"
    assert strip_tags("<script>var x=1;</script>Visible") == "Visible"


def test_strip_think_tags():
    text = "Here is <think>inner thought</think> the answer."
    assert strip_think_tags(text) == "Here is  the answer."

    text_multiline = """Start
    <think>
    Thinking...
    </think>
    End"""
    assert (
        strip_think_tags(text_multiline).replace("\n", "").replace(" ", "")
        == "StartEnd"
    )


def test_strip_think_tags_no_tags():
    text = "Just plain text."
    assert strip_think_tags(text) == text
