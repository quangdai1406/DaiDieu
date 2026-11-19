import ast

import pytest

from nocomments import find_python, strip_python


def test_removes_hash_and_inline_comment():
    src = "# top\nx = 1  # inline\ny = 2\n"
    assert strip_python(src) == "x = 1\ny = 2\n"


def test_keeps_hash_in_string():
    src = 'x = "# not a comment"\ny = """a\n# still text\n"""\n'
    assert strip_python(src) == src
    assert find_python(src) == []


def test_removes_docstrings():
    src = 'def f():\n    """doc"""\n    return 1\n\n\nclass C:\n    """doc"""\n    x = 1\n'
    assert strip_python(src) == "def f():\n    return 1\n\n\nclass C:\n    x = 1\n"


def test_module_docstring_removed():
    assert strip_python('"""mod"""\nx = 1\n') == "x = 1\n"


def test_keeps_shebang_and_encoding():
    src = "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\nx = 1  # c\n"
    assert strip_python(src) == "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\nx = 1\n"


def test_ast_equal_minus_docstrings():
    src = '"""m"""\n\n\ndef f(a):\n    """d"""\n    # c\n    return a  # r\n'
    out = strip_python(src)

    def bare(tree):
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
                body = node.body
                if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0].value, "value", None), str):
                    node.body = body[1:] or [ast.Pass()]
        return ast.dump(tree)

    assert bare(ast.parse(src)) == bare(ast.parse(out))


def test_crlf_preserved():
    src = "x = 1  # c\r\ny = 2\r\n"
    assert strip_python(src) == "x = 1\r\ny = 2\r\n"


def test_find_python_reports_lines():
    assert find_python("x = 1\n# a\ny = 2  # b\n") == [2, 3]


def test_empty_block_raises():
    with pytest.raises(ValueError):
        strip_python("if x:\n    # todo\n")


def test_idempotent():
    src = "x = 1  # c\n"
    once = strip_python(src)
    assert strip_python(once) == once


def test_doc_reference_raises():
    with pytest.raises(ValueError):
        strip_python('"""usage"""\nimport argparse\nargparse.ArgumentParser(description=__doc__)\n')


def test_doc_reference_without_docstring_allowed():
    src = "x = __doc__\n"
    assert strip_python(src) == src
