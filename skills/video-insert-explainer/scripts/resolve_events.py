"""Resolve an events template against the narration timeline, so a re-voiced line moves every effect with it.

usage: python3 resolve_events.py <events.template.json> <timeline.json> <events.json>

Any string value that starts with "=" is an expression. Names available:
  <id>.s / <id>.e / <id>.v   start / end / voice onset of narration segment <id> (from timeline.json)
  N_END                      length of the placed narration
  every key of the template's "vars" (evaluated in order, so a var may use earlier ones)
Operators: + - * / and min(), max(), round(). Everything else (paths, labels, rects) is copied as is.
Prints the resolved scalar times and runs the template's "checks" (expressions that must be true).
"""

import ast
import json
import operator
import re
import sys

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.USub: operator.neg, ast.UAdd: operator.pos, ast.Lt: operator.lt, ast.LtE: operator.le,
       ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Eq: operator.eq}
FUNCS = {"min": min, "max": max, "round": round, "abs": abs}
DOTTED = re.compile(r"\b([A-Za-z_]\w*)\.(s|e|v)\b")


def evaluate(expr, names):
    tree = ast.parse(DOTTED.sub(r"\1__\2", expr), mode="eval")

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.Name):
            if n.id not in names:
                raise KeyError(f"unknown name {n.id!r} in {expr!r}")
            return names[n.id]
        if isinstance(n, ast.BinOp) and type(n.op) in OPS:
            return OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in OPS:
            return OPS[type(n.op)](ev(n.operand))
        if isinstance(n, ast.Compare) and len(n.ops) == 1 and type(n.ops[0]) in OPS:
            return OPS[type(n.ops[0])](ev(n.left), ev(n.comparators[0]))
        if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.And):
            return all(ev(v) for v in n.values)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCS:
            return FUNCS[n.func.id](*[ev(a) for a in n.args])
        raise ValueError(f"unsupported syntax in {expr!r}")

    return ev(tree)


def resolve(x, names):
    if isinstance(x, str) and x.startswith("="):
        v = evaluate(x[1:], names)
        return round(v, 3) if isinstance(v, float) else v
    if isinstance(x, list):
        return [resolve(v, names) for v in x]
    if isinstance(x, dict):
        return {k: resolve(v, names) for k, v in x.items()}
    return x


def timeline_names(tl):
    names = {"N_END": tl["narr_end"]}
    for s in tl["segs"]:
        names[f'{s["id"]}__s'] = s["start"]
        names[f'{s["id"]}__e'] = s["end"]
        names[f'{s["id"]}__v'] = s.get("voice", s["start"])
    return names


def main():
    tpl_path, tl_path, out_path = sys.argv[1:4]
    tpl = json.load(open(tpl_path, encoding="utf-8"))
    names = timeline_names(json.load(open(tl_path, encoding="utf-8")))
    resolved_vars = {}
    for k, v in tpl.get("vars", {}).items():
        names[k] = resolved_vars[k] = resolve(v, names)
    out = {k: resolve(v, names) for k, v in tpl.items() if k not in ("vars", "checks")}
    out["vars"] = resolved_vars
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for k, v in resolved_vars.items():
        print(f"{k:<12}{v}")
    bad = 0
    for c in tpl.get("checks", []):
        ok = bool(evaluate(c, names))
        bad += not ok
        print("OK " if ok else "NG ", c)
    print("wrote", out_path)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
