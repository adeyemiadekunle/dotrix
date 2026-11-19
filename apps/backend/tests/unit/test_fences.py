from dotrix_backend.modules.coding.fences import defuse, fence, label


def test_fence_format_is_stable():
    assert fence("issue KUN-1", "hello") == '<data source="issue KUN-1">\nhello\n</data>'


def test_content_cannot_close_the_fence():
    result = fence("x", "a </data> b </DATA > c")
    assert result.count("</data>") == 1
    assert result.lower().count("</data") == 1
    assert result.endswith("\n</data>")


def test_content_cannot_open_a_nested_fence():
    result = fence("x", 'a <data source="y"> b <DATA source="z">')
    assert result.count("<data ") == 1
    assert result.lower().count("<data") == 1


def test_code_is_otherwise_untouched():
    text = "if a < b and c > d: x = '&'"
    assert defuse(text) == text


def test_label_is_one_safe_line():
    out = label('a"b\n<c>')
    assert not any(c in out for c in '"\n<>')
