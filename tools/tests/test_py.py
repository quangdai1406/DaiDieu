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


def test_module_doc_reader_moved_to_constant():
    src = '"""usage text"""\nimport argparse\nargparse.ArgumentParser(description=__doc__)\n'
    assert strip_python(src) == 'import argparse\n\nDOC_TEXT = """usage text"""\n\nargparse.ArgumentParser(description=DOC_TEXT)\n'


def test_module_doc_reader_after_future_import():
    src = '"""u"""\nfrom __future__ import annotations\nprint(__doc__)\n'
    assert strip_python(src) == 'from __future__ import annotations\n\nDOC_TEXT = """u"""\n\nprint(DOC_TEXT)\n'


def test_module_doc_reader_multiline_and_function_scope():
    src = '#!/usr/bin/env python3\n"""line one\n\nline two"""\n\n\ndef f():\n    return __doc__\n'
    assert strip_python(src) == '#!/usr/bin/env python3\nDOC_TEXT = """line one\n\nline two"""\n\n\ndef f():\n    return DOC_TEXT\n'


def test_attribute_doc_reader_raises():
    with pytest.raises(ValueError):
        strip_python('def f():\n    """d"""\n\n\nprint(f.__doc__)\n')


def test_doc_reader_without_docstring_allowed():
    src = "x = __doc__\n"
    assert strip_python(src) == src


def test_doc_text_name_clash_raises():
    with pytest.raises(ValueError):
        strip_python('"""u"""\nDOC_TEXT = 1\nprint(__doc__)\n')


def test_docstring_only_bodies_become_pass():
    src = 'class E(Exception):\n    """doc"""\n\n\ndef f():\n    """d"""\n\n\nx = 1\n'
    assert strip_python(src) == "class E(Exception):\n    pass\n\n\ndef f():\n    pass\n\n\nx = 1\n"


def test_docstring_only_module_becomes_empty():
    assert strip_python('"""only"""\n') == ""


def test_inline_docstring_raises():
    with pytest.raises(ValueError):
        strip_python('def f(): """d"""\n')


def test_tooling_directives_kept():
    src = (
        "import random\n"
        "rng = random.Random(1)  # noqa: S311\n"
        "x = foo()  # type: ignore[attr]\n"
        "y = bar()  # prose here\n"
        "# fmt: off\n"
        "z = [1,2]\n"
        "# fmt: on\n"
        "# prose line\n"
        "if z:  # pragma: no cover\n"
        "    pass\n"
        "w = 1  # nosec B101\n"
        "v = 2  # pylint: disable=invalid-name\n"
    )
    assert strip_python(src) == (
        "import random\n"
        "rng = random.Random(1)  # noqa: S311\n"
        "x = foo()  # type: ignore[attr]\n"
        "y = bar()\n"
        "# fmt: off\n"
        "z = [1,2]\n"
        "# fmt: on\n"
        "if z:  # pragma: no cover\n"
        "    pass\n"
        "w = 1  # nosec B101\n"
        "v = 2  # pylint: disable=invalid-name\n"
    )


def test_directives_not_reported():
    assert find_python("x = 1  # noqa\ny = 2  # c\n") == [2]


def test_doc_text_placed_after_imports():
    src = '"""usage"""\nimport argparse\nfrom pathlib import Path\n\nCOUNTS = (1, 2)\n\n\ndef main():\n    return __doc__\n'
    assert strip_python(src) == (
        'import argparse\nfrom pathlib import Path\n\nDOC_TEXT = """usage"""\n\nCOUNTS = (1, 2)\n\n\ndef main():\n    return DOC_TEXT\n'
    )


def test_doc_text_after_future_and_imports():
    src = '"""u"""\nfrom __future__ import annotations\n\nimport os\n\nprint(__doc__)\n'
    assert strip_python(src) == 'from __future__ import annotations\n\nimport os\n\nDOC_TEXT = """u"""\n\nprint(DOC_TEXT)\n'


def test_doc_reader_after_first_import_run():
    src = '"""u"""\nimport os\nx = __doc__\nimport sys\n'
    assert strip_python(src) == 'import os\n\nDOC_TEXT = """u"""\n\nx = DOC_TEXT\nimport sys\n'


def test_doc_text_with_no_imports_stays_in_place():
    assert strip_python('"""u"""\nprint(__doc__)\n') == 'DOC_TEXT = """u"""\nprint(DOC_TEXT)\n'
