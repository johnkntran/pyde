import pytest

from pyde import jsonc


def test_plain_json_parses():
    assert jsonc.loads('{"a": [1, 2], "b": null}') == {"a": [1, 2], "b": None}


def test_line_and_block_comments_are_ignored():
    text = """
    // a line comment
    {
      "a": 1, // a trailing comment
      /* a block
         comment */
      "b": 2
    }
    """

    assert jsonc.loads(text) == {"a": 1, "b": 2}


def test_trailing_commas_are_ignored():
    assert jsonc.loads('{"a": [1, 2,], "b": 3,\n}') == {"a": [1, 2], "b": 3}


def test_comment_markers_and_commas_inside_strings_are_kept():
    text = r'{"url": "http://x/*y*/", "list": "a,]", "quote": "\"// no,}"}'

    assert jsonc.loads(text) == {
        "url": "http://x/*y*/",
        "list": "a,]",
        "quote": '"// no,}',
    }


def test_error_line_numbers_survive_comment_removal():
    text = '{\n  /* two\n     lines */\n  "a": oops\n}'

    with pytest.raises(ValueError, match="line 4"):
        jsonc.loads(text)
