from nocomments import find_text, is_target, strip_sql, strip_text


def test_typescript_basic():
    src = "const a: string = 'x'; // c\ntype T = Array<number>; /* d */\nconst u = \"http://x\";\n"
    assert strip_text("a.ts", src) == "const a: string = 'x';\ntype T = Array<number>;\nconst u = \"http://x\";\n"


def test_tsx_attribute_strings_kept():
    src = '<a href="https://x.com/a">x</a>; // c\nconst r = /a\\/\\/b/;\n'
    assert strip_text("a.tsx", src) == '<a href="https://x.com/a">x</a>;\nconst r = /a\\/\\/b/;\n'


def test_other_js_suffixes():
    for name in ("a.mjs", "a.cjs", "a.jsx"):
        assert strip_text(name, "a(); // c\n") == "a();\n"


def test_await_regex_context():
    assert strip_text("a.ts", "const x = await /a\\//.exec(s); // c\n") == "const x = await /a\\//.exec(s);\n"


def test_rules_file():
    assert strip_text("firestore.rules", "// c\nallow read: if true; // d\n") == "allow read: if true;\n"


def test_sql_line_block_and_strings():
    src = "select 1; -- c\n/* b */\nselect '--x', \"a--b\", 'it''s -- y' ; /* z */\n"
    assert strip_sql(src) == "select 1;\nselect '--x', \"a--b\", 'it''s -- y' ;\n"


def test_sql_nested_block_comment():
    assert strip_sql("select 1; /* a /* b */ c */ select 2;\n") == "select 1;  select 2;\n"


def test_sql_e_string_escape():
    src = "select E'it\\'s -- x'; -- c\n"
    assert strip_sql(src) == "select E'it\\'s -- x';\n"


def test_sql_dollar_quote_body_stripped():
    src = "create function f() returns int as $$\nbegin\n  -- note\n  return 1; -- r\nend;\n$$ language plpgsql; -- t\nselect $1;\n"
    assert strip_sql(src) == "create function f() returns int as $$\nbegin\n  return 1;\nend;\n$$ language plpgsql;\nselect $1;\n"


def test_sql_tagged_dollar_quote():
    src = "select $tag$ a -- keep? $tag$; -- c\n"
    assert strip_sql(src) == "select $tag$ a$tag$;\n"


def test_sql_dispatch_and_find():
    assert strip_text("m.sql", "select 1; -- c\n") == "select 1;\n"
    assert find_text("m.sql", "select 1;\n-- c\nselect 2; -- d\n") == [2, 3]


def test_toml_comments():
    src = "# head\na = \"x # y\" # c\n[t] # c\nb = 'it # s'\nc = \"\"\"\n# in\n\"\"\"\n"
    assert strip_text("a.toml", src) == "a = \"x # y\"\n[t]\nb = 'it # s'\nc = \"\"\"\n# in\n\"\"\"\n"


def test_toml_escaped_quote():
    assert strip_text("a.toml", 'a = "q\\" # in" # c\n') == 'a = "q\\" # in"\n'


def test_shell_comments_and_expansions():
    src = "#!/bin/sh\n# c\necho \"a # b\" # c\necho $# ${#x} a#b \\# z\nls | grep x # d\n"
    assert strip_text("a.sh", src) == "#!/bin/sh\necho \"a # b\"\necho $# ${#x} a#b \\# z\nls | grep x\n"


def test_shell_heredoc_untouched():
    src = "cat <<EOF\n# inside\nEOF\n# c\ncat <<-'X'\n\t# in\n\tX\necho a <<< b # c\n"
    assert strip_text("a.sh", src) == "cat <<EOF\n# inside\nEOF\ncat <<-'X'\n\t# in\n\tX\necho a <<< b\n"


def test_batch_comments():
    src = "@echo off\nREM c\n:: d\n  rem e\necho hi\r\n"
    assert strip_text("a.bat", src) == "@echo off\necho hi\r\n"


def test_is_target_new_suffixes():
    for name in ("a.ts", "a.tsx", "a.jsx", "a.mjs", "a.cjs", "a.sql", "a.toml", "a.sh", "a.bash", "a.bat", "a.cmd", "firestore.rules"):
        assert is_target(name), name
    assert not is_target("a.md")
    assert not is_target("a.ipynb")
    assert not is_target("requirements.txt")


def test_idempotent_new_languages():
    for name, src in [
        ("a.ts", "const a = 1; // c\n"),
        ("a.sql", "select 1; -- c\n"),
        ("a.toml", "a = 1 # c\n"),
        ("a.sh", "echo a # c\n"),
        ("a.bat", "REM c\necho a\n"),
    ]:
        once = strip_text(name, src)
        assert strip_text(name, once) == once
