import ast
import difflib
import io
import re
import tokenize
from pathlib import PurePath

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


_REGEX_PREV = set("(,=:[!&|?{;+-*%<>~^")
_REGEX_WORDS = {"return", "typeof", "case", "in", "of", "delete", "void", "throw", "new", "else", "do"}


def _tidy(text, touched):
    out = []
    for index, line in enumerate(io.StringIO(text).readlines()):
        if index in touched:
            body = line.rstrip("\r\n")
            eol = line[len(body):]
            body = body.rstrip(" \t")
            if not body:
                continue
            line = body + eol
        out.append(line)
    return "".join(out)


def strip_c_like(src, line_comments, regex=False):
    out = []
    touched = set()
    newlines = 0
    prev = ""
    word = ""
    i = 0
    n = len(src)

    def emit(text):
        nonlocal newlines
        out.append(text)
        newlines += text.count("\n")

    while i < n:
        c = src[i]
        two = src[i:i + 2]
        if two == "/*":
            end = src.find("*/", i + 2)
            touched.add(newlines)
            i = n if end < 0 else end + 2
            continue
        if line_comments and two == "//":
            end = src.find("\n", i)
            end = n if end < 0 else end
            if end > i and src[end - 1] == "\r":
                end -= 1
            touched.add(newlines)
            i = end
            continue
        if c in "'\"" or (regex and c == "`"):
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == "\\":
                    j += 1
                elif src[j] == "\n" and c != "`":
                    j -= 1
                    break
                j += 1
            emit(src[i:j + 1])
            i = j + 1
            prev, word = c, ""
            continue
        if not regex and src[i:i + 4].lower() == "url(" and (i == 0 or not (src[i - 1].isalnum() or src[i - 1] in "-_")):
            j = i + 4
            while j < n and src[j] in " \t":
                j += 1
            if j < n and src[j] not in "'\"":
                end = src.find(")", j)
                end = n if end < 0 else end + 1
                emit(src[i:end])
                i = end
                prev, word = ")", ""
                continue
        if regex and c == "/" and (prev == "" or prev in _REGEX_PREV or word in _REGEX_WORDS):
            j = i + 1
            in_class = False
            while j < n and src[j] != "\n":
                if src[j] == "\\":
                    j += 1
                elif src[j] == "[":
                    in_class = True
                elif src[j] == "]":
                    in_class = False
                elif src[j] == "/" and not in_class:
                    break
                j += 1
            if j < n and src[j] == "/":
                j += 1
                while j < n and (src[j].isalpha()):
                    j += 1
                emit(src[i:j])
                i = j
                prev, word = "x", ""
                continue
        emit(c)
        i += 1
        if c.isalnum() or c in "_$":
            word += c
            prev = c
        elif not c.isspace():
            prev, word = c, ""
    return _tidy("".join(out), touched)


_HTML = re.compile(
    r"<!--(?!\[if)(?!<!\[endif).*?-->"
    r"|\{%-?\s*comment\s*-?%\}.*?\{%-?\s*endcomment\s*-?%\}"
    r"|(?P<so><script\b[^>]*>)(?P<sb>.*?)(?P<sc></script\s*>)"
    r"|(?P<to><style\b[^>]*>)(?P<tb>.*?)(?P<tc></style\s*>)",
    re.S | re.I,
)


def strip_html(src):
    out = []
    touched = set()
    newlines = 0
    pos = 0

    def emit(text):
        nonlocal newlines
        out.append(text)
        newlines += text.count("\n")

    for match in _HTML.finditer(src):
        emit(src[pos:match.start()])
        pos = match.end()
        if match.group("so"):
            head = match.group("so")
            body = match.group("sb")
            if "json" not in head.lower() and "template" not in head.lower():
                body = strip_c_like(body, line_comments=True, regex=True)
            emit(head + body + match.group("sc"))
        elif match.group("to"):
            emit(match.group("to") + strip_c_like(match.group("tb"), line_comments=False) + match.group("tc"))
        else:
            touched.add(newlines)
    emit(src[pos:])
    return _tidy("".join(out), touched)


_LITERAL_START = re.compile(r"[:-]\s+[|>][+-]?\d*\s*$")


def strip_hash(src, kind="yaml"):
    escape = "\\" if kind == "yaml" else "`"
    out = []
    in_block = False
    literal_indent = None
    for number, line in enumerate(io.StringIO(src).readlines(), start=1):
        body = line.rstrip("\r\n")
        eol = line[len(body):]
        if literal_indent is not None:
            indent = len(body) - len(body.lstrip())
            if not body.strip() or indent > literal_indent:
                out.append(line)
                continue
            literal_indent = None
        changed = False
        if in_block:
            end = body.find("#>")
            if end < 0:
                continue
            body = body[end + 2:]
            in_block = False
            changed = True
        quote = None
        j = 0
        while j < len(body):
            c = body[j]
            if quote:
                if c == escape and quote == '"':
                    j += 1
                elif c == quote:
                    quote = None
            elif c in "'\"":
                before = body[:j].rstrip()[-1:]
                if kind != "yaml" or before == "" or before in ":-,[{":
                    quote = c
            elif kind == "ps1" and body[j:j + 2] == "<#":
                end = body.find("#>", j + 2)
                changed = True
                if end < 0:
                    in_block = True
                    body = body[:j]
                    break
                body = body[:j] + body[end + 2:]
                continue
            elif c == "#":
                if number == 1 and body.startswith("#!"):
                    break
                if kind == "yaml" and j > 0 and body[j - 1] not in " \t":
                    j += 1
                    continue
                body = body[:j]
                changed = True
                break
            j += 1
        if changed:
            body = body.rstrip(" \t")
            if not body:
                continue
        if kind == "yaml" and _LITERAL_START.search(body):
            literal_indent = len(body) - len(body.lstrip())
        out.append(body + eol)
    return "".join(out)


def strip_text(path, src):
    suffix = PurePath(path).suffix.lower()
    if suffix == ".py":
        return strip_python(src)
    if suffix == ".js":
        return strip_c_like(src, line_comments=True, regex=True)
    if suffix == ".css":
        return strip_c_like(src, line_comments=False)
    if suffix == ".scss":
        return strip_c_like(src, line_comments=True)
    if suffix in (".html", ".htm", ".xml"):
        return strip_html(src)
    if suffix in (".yml", ".yaml"):
        return strip_hash(src, kind="yaml")
    if suffix == ".ps1":
        return strip_hash(src, kind="ps1")
    return src


def find_text(path, src):
    if PurePath(path).suffix.lower() == ".py":
        return find_python(src)
    before = io.StringIO(src).readlines()
    after = io.StringIO(strip_text(path, src)).readlines()
    found = []
    for tag, i1, i2, _, _ in difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        if tag != "equal":
            found.extend(range(i1 + 1, i2 + 1))
    return found
