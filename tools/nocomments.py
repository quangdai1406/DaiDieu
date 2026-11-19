import ast
import io
import re
import tokenize

_ENCODING = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*[-\w.]+")


def _python_targets(src):
    lines = io.StringIO(src).readlines()
    cuts = {}
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type != tokenize.COMMENT:
            continue
        row, col = tok.start
        if row == 1 and tok.string.startswith("#!"):
            continue
        if row <= 2 and _ENCODING.match(lines[row - 1]):
            continue
        cuts[row] = col
    docs = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docs.append((first.lineno, first.end_lineno))
    return lines, cuts, docs


def find_python(src):
    _, cuts, docs = _python_targets(src)
    found = set(cuts) | {start for start, _ in docs}
    return sorted(found)


def strip_python(src):
    try:
        lines, cuts, docs = _python_targets(src)
    except (SyntaxError, tokenize.TokenError) as exc:
        raise ValueError(f"cannot parse python: {exc}") from exc
    dropped = set()
    for start, end in docs:
        dropped.update(range(start, end + 1))
    out = []
    for number, line in enumerate(lines, start=1):
        if number in dropped:
            continue
        if number in cuts:
            body = line[: cuts[number]].rstrip()
            if not body:
                continue
            eol = line[len(line.rstrip("\r\n")):]
            line = body + eol
        out.append(line)
    result = "".join(out)
    try:
        ast.parse(result)
    except SyntaxError as exc:
        raise ValueError(f"stripping left an empty block: {exc}") from exc
    return result
