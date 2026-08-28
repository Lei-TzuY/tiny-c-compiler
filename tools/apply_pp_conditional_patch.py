from pathlib import Path

pp = Path('preprocess_v2.c')
text = pp.read_text()

old = 'static int64_t pp_logor(PPExpr *e);\n'
new = 'static int64_t pp_conditional(PPExpr *e);\n'
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit('forward declaration anchor not found')

old = '''    if (pp_consume(e, "(")) {\n        int64_t val = pp_logor(e);\n        if (!pp_consume(e, ")"))\n            error("expected ')' in #if expression");\n        return val;\n    }\n'''
new = '''    if (pp_consume(e, "(")) {\n        int64_t val = pp_conditional(e);\n        if (!pp_consume(e, ")"))\n            error("expected ')' in #if expression");\n        return val;\n    }\n'''
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit('parenthesized-expression anchor not found')

old = '''static int64_t pp_logor(PPExpr *e) {\n    int64_t val = pp_logand(e);\n    while (pp_consume(e, "||")) {\n        bool saved = e->suppress_eval;\n        if (!saved && val)\n            e->suppress_eval = true;\n        int64_t rhs = pp_logand(e);\n        e->suppress_eval = saved;\n        if (!saved)\n            val = val || rhs;\n    }\n    return val;\n}\n\nstatic int64_t eval_pp_expr_depth(const char *text, int depth) {\n    PPExpr e = {.p = text, .depth = depth};\n    int64_t val = pp_logor(&e);\n'''
new = '''static int64_t pp_logor(PPExpr *e) {\n    int64_t val = pp_logand(e);\n    while (pp_consume(e, "||")) {\n        bool saved = e->suppress_eval;\n        if (!saved && val)\n            e->suppress_eval = true;\n        int64_t rhs = pp_logand(e);\n        e->suppress_eval = saved;\n        if (!saved)\n            val = val || rhs;\n    }\n    return val;\n}\n\nstatic int64_t pp_conditional(PPExpr *e) {\n    int64_t cond = pp_logor(e);\n    if (!pp_consume(e, "?"))\n        return cond;\n\n    bool saved = e->suppress_eval;\n    if (!saved && !cond)\n        e->suppress_eval = true;\n    int64_t then_val = pp_conditional(e);\n    e->suppress_eval = saved;\n\n    if (!pp_consume(e, ":"))\n        error("expected ':' in #if conditional expression");\n\n    if (!saved && cond)\n        e->suppress_eval = true;\n    int64_t else_val = pp_conditional(e);\n    e->suppress_eval = saved;\n\n    if (saved)\n        return 0;\n    return cond ? then_val : else_val;\n}\n\nstatic int64_t eval_pp_expr_depth(const char *text, int depth) {\n    PPExpr e = {.p = text, .depth = depth};\n    int64_t val = pp_conditional(&e);\n'''
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit('logical-or/evaluator anchor not found')

pp.write_text(text)

test = Path('test/preprocessor_advanced.sh')
t = test.read_text()
marker = '''# A zero divisor in an actually evaluated operand remains an error.\nassert_pp_fail '#if 1 && (1 / 0)\nint main() { return 0; }\n#endif'\n\necho "All advanced preprocessor tests passed!"\n'''
replacement = '''# A zero divisor in an actually evaluated operand remains an error.\nassert_pp_fail '#if 1 && (1 / 0)\nint main() { return 0; }\n#endif'\n\n# #if supports the conditional operator and evaluates only the selected arm.\nassert_pp_adv 24 '#if 1 ? 7 : 0\nint main() { return 24; }\n#else\nint main() { return 0; }\n#endif'\n\nassert_pp_adv 25 '#define PICK 0\n#if PICK ? (1 / 0) : 9\nint main() { return 25; }\n#else\nint main() { return 0; }\n#endif'\n\nassert_pp_adv 26 '#if 1 ? 1 : (7 % 0)\nint main() { return 26; }\n#else\nint main() { return 0; }\n#endif'\n\n# Conditional expressions associate to the right and nest in either arm.\nassert_pp_adv 27 '#if 0 ? 0 : 1 ? 3 : 0\nint main() { return 27; }\n#else\nint main() { return 0; }\n#endif'\n\n# The selected arm is still evaluated normally.\nassert_pp_fail '#if 1 ? (1 / 0) : 1\nint main() { return 0; }\n#endif'\n\n# Malformed conditional expressions are diagnosed.\nassert_pp_fail '#if 1 ? 2\nint main() { return 0; }\n#endif'\n\necho "All advanced preprocessor tests passed!"\n'''
if marker in t:
    t = t.replace(marker, replacement, 1)
elif replacement not in t:
    raise SystemExit('test anchor not found')
test.write_text(t)
