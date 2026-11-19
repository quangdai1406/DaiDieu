from nocomments import find_text, strip_c_like, strip_hash, strip_html, strip_text


def test_js_url_in_string_kept():
    src = 'var u = "http://x.com/a"; // c\nvar v = \'//y\';\n'
    assert strip_c_like(src, line_comments=True, regex=True) == 'var u = "http://x.com/a";\nvar v = \'//y\';\n'


def test_js_regex_with_slashes_kept():
    src = "var r = /a\\/\\/b/; // c\nvar q = /\"/;\nvar d = a / b; // c\n"
    assert strip_c_like(src, line_comments=True, regex=True) == "var r = /a\\/\\/b/;\nvar q = /\"/;\nvar d = a / b;\n"


def test_js_template_literal_kept():
    src = "var t = `a // b`; // c\n"
    assert strip_c_like(src, line_comments=True, regex=True) == "var t = `a // b`;\n"


def test_css_block_comment():
    src = "/* head */\na { color: red; /* x */ }\nb { background: url(http://x/y.png); }\n"
    assert strip_c_like(src, line_comments=False) == "a { color: red;  }\nb { background: url(http://x/y.png); }\n"


def test_scss_line_comment():
    src = "// head\n$a: 1; // tail\n.b { background: url(//cdn/x.png); }\n"
    assert strip_c_like(src, line_comments=True) == "$a: 1;\n.b { background: url(//cdn/x.png); }\n"


def test_block_comment_multiline_dropped_whole():
    src = "a;\n/*\n * x\n */\nb;\n"
    assert strip_c_like(src, line_comments=True) == "a;\nb;\n"


def test_html_comment_multiline():
    src = "<p>a</p>\n<!--\n  x\n-->\n<p>b</p> <!-- t -->\n"
    assert strip_html(src) == "<p>a</p>\n<p>b</p>\n"


def test_html_inline_script_and_style():
    src = "<script>\n// c\nvar a = 1; /* d */\n</script>\n<style>\n/* e */\na{b:c}\n</style>\n"
    assert strip_html(src) == "<script>\nvar a = 1;\n</script>\n<style>\na{b:c}\n</style>\n"


def test_html_json_script_untouched():
    src = '<script type="application/ld+json">{"u": "http://x"}</script>\n'
    assert strip_html(src) == src


def test_liquid_comment_block():
    src = "a\n{% comment %}\nnote\n{% endcomment %}\nb {%- comment -%}x{%- endcomment -%}\n"
    assert strip_html(src) == "a\nb\n"


def test_yaml_hash_in_quotes_kept():
    src = "# head\na: 'x # y'  # tail\nb: \"q # r\"\nu: http://h/#frag\n"
    assert strip_hash(src, kind="yaml") == "a: 'x # y'\nb: \"q # r\"\nu: http://h/#frag\n"


def test_ps1_hash_and_block_comment():
    src = "#!/x\n# c\n<#\n.SYNOPSIS\n#>\n$a = \"C:\\p\\\"  # c\nWrite-Host 'x#y'\n"
    assert strip_text("a.ps1", src) == "#!/x\n$a = \"C:\\p\\\"\nWrite-Host 'x#y'\n"


def test_crlf_preserved_in_c_like():
    assert strip_c_like("a; // c\r\nb;\r\n", line_comments=True) == "a;\r\nb;\r\n"


def test_strip_text_dispatch():
    assert strip_text("x.py", "a = 1  # c\n") == "a = 1\n"
    assert strip_text("x.scss", "a{} // c\n") == "a{}\n"
    assert strip_text("x.css", "a{} /* c */\n") == "a{}\n"
    assert strip_text("x.yml", "a: 1 # c\n") == "a: 1\n"
    assert strip_text("x.xml", "<a/><!-- c -->\n") == "<a/>\n"
    assert strip_text("x.txt", "# keep\n") == "# keep\n"


def test_find_text_reports_lines():
    assert find_text("x.js", "a;\n// c\nb; // d\nc;\n") == [2, 3]


def test_idempotent():
    for name, src in [
        ("a.js", "var a = 1; // c\n/* d */\n"),
        ("a.html", "<!-- c --><p>x</p>\n"),
        ("a.yml", "a: 1 # c\n"),
        ("a.scss", "a{} // c\n"),
    ]:
        once = strip_text(name, src)
        assert strip_text(name, once) == once


def test_html_ie_conditional_kept():
    src = (
        '<!--[if IE 8]><html class="ie8"><![endif]-->\n'
        "<!--[if !(IE 7) | !(IE 8)  ]><!-->\n"
        '<html lang="en">\n'
        "<!--<![endif]-->\n"
        "<p>x</p><!-- c -->\n"
    )
    assert strip_html(src) == src.replace("<!-- c -->", "")
