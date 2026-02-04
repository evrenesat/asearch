import os
import tempfile
from unittest.mock import patch, MagicMock
from asky.rendering import save_html_report, _create_html_content


def test_create_html_content_basic():
    """Test standard HTML wrapping."""
    with patch("asky.config.TEMPLATE_PATH") as mock_path:
        mock_path.exists.return_value = True
        # Mock open() on the template path
        with patch("builtins.open", new_callable=MagicMock) as mock_open:
            mock_file = MagicMock()
            mock_file.read.return_value = "<html><body>{{CONTENT}}</body></html>"
            mock_open.return_value.__enter__.return_value = mock_file

            result = _create_html_content("# Hello")
            assert "<html><body># Hello</body></html>" in result


def test_create_html_content_no_template():
    """Test fallback when template is missing."""
    with patch("asky.config.TEMPLATE_PATH") as mock_path:
        mock_path.exists.return_value = False
        result = _create_html_content("# Hello")
        assert "<pre># Hello</pre>" in result


def test_save_html_report():
    """Test saving the HTML report to a file."""
    content = "# Test Content"

    # Mock _create_html_content to avoid template file I/O complexity
    with patch(
        "asky.rendering._create_html_content",
        return_value="<htmled># Test Content</htmled>",
    ):
        path = save_html_report(content, "test_output.html")

        assert path.endswith("test_output.html")
        assert os.path.exists(path)

        with open(path, "r") as f:
            saved = f.read()
            assert saved == "<htmled># Test Content</htmled>"

        # Clean up
        try:
            os.remove(path)
        except OSError:
            pass


def test_save_html_report_overwrite():
    """Test that it overwrites existing files."""
    filename = "test_overwrite.html"
    temp_dir = tempfile.gettempdir()
    path = os.path.join(temp_dir, filename)

    # Create valid dummy file
    with open(path, "w") as f:
        f.write("OLD CONTENT")

    with patch("asky.rendering._create_html_content", return_value="NEW CONTENT"):
        returned_path = save_html_report("foo", filename)
        assert returned_path == path

        with open(path, "r") as f:
            assert f.read() == "NEW CONTENT"

    try:
        os.remove(path)
    except OSError:
        pass
