"""Verify G-11: strip MQL strings/comments/char-literals, then re-count braces/parens.
If balanced after stripping -> the naive counter tripped on a brace inside a string/comment."""
import re

FILES = [
    r"active_ea\CLAUDE_BRAIN_EA_v1.mq5",
    r"live_ea\Agentic_Profiled_Grid_GOLD_LIVE.mq5",
    r"r_native\v2\mql5_experts\FRIDAY_Brain_Executor.mq5",
]


def strip_code(s: str) -> str:
    out = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        nxt = s[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":                 # line comment
            while i < n and s[i] != "\n":
                i += 1
        elif c == "/" and nxt == "*":               # block comment
            i += 2
            while i + 1 < n and not (s[i] == "*" and s[i + 1] == "/"):
                i += 1
            i += 2
        elif c == '"':                              # string literal
            i += 1
            while i < n and s[i] != '"':
                i += 2 if s[i] == "\\" else 1
            i += 1
        elif c == "'":                              # char literal
            i += 1
            while i < n and s[i] != "'":
                i += 2 if s[i] == "\\" else 1
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def find_offenders(code: str):
    """Walk the stripped code; report the line where brace depth first goes wrong
    or the final non-zero depth."""
    depth = 0
    line = 1
    bad_line = None
    for ch in code:
        if ch == "\n":
            line += 1
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0 and bad_line is None:
                bad_line = line
    return depth, bad_line


for f in FILES:
    raw = open(f, encoding="utf-8", errors="replace").read()
    code = strip_code(raw)
    rb, rB = raw.count("{"), raw.count("}")
    cb, cB = code.count("{"), code.count("}")
    rp, rP = raw.count("("), raw.count(")")
    cp, cP = code.count("("), code.count(")")
    balanced = (cb == cB and cp == cP)
    print(f)
    print(f"   raw : braces {rb}/{rB}  parens {rp}/{rP}")
    print(f"  clean: braces {cb}/{cB}  parens {cp}/{cP}  -> "
          + ("BALANCED — FALSE POSITIVE" if balanced else "STILL UNBALANCED — REAL"))
    if not balanced:
        depth, bad = find_offenders(code)
        print(f"        final brace depth {depth}" + (f", first negative at line {bad}" if bad else ""))
    print()
