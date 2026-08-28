from pathlib import Path

SRC = Path("preprocess_v2.c")
TEST = Path("test/preprocessor_advanced.sh")

src = SRC.read_text()

old = '''static int64_t eval_pp_expr_depth(const char *text, int depth);\n\nstatic int64_t pp_primary(PPExpr *e) {'''
new = '''static int64_t eval_pp_expr_depth(const char *text, int depth, bool suppress_eval);\nstatic int64_t pp_eval_function_macro(PPExpr *e, Macro *m);\n\nstatic int64_t pp_primary(PPExpr *e) {'''
if old in src:
    src = src.replace(old, new, 1)
elif new not in src:
    raise SystemExit("failed to find evaluator forward declaration")

old = '''        } else if (m && m->is_objlike && e->depth < 64) {\n            result = eval_pp_expr_depth(m->body, e->depth + 1);\n        }\n'''
new = '''        } else if (m && m->is_objlike && e->depth < 64) {\n            result = eval_pp_expr_depth(m->body, e->depth + 1, e->suppress_eval);\n        } else if (m && !m->is_objlike && e->depth < 64) {\n            result = pp_eval_function_macro(e, m);\n        }\n'''
if old in src:
    src = src.replace(old, new, 1)
elif new not in src:
    raise SystemExit("failed to find macro primary handling")

old = '''static int64_t eval_pp_expr_depth(const char *text, int depth) {\n    PPExpr e = {.p = text, .depth = depth};\n    int64_t val = pp_conditional(&e);\n    pp_skip_space(&e);\n    if (*e.p)\n        error("unexpected token in #if expression near '%s'", e.p);\n    return val;\n}\n\nstatic int64_t eval_pp_expr(const char *text) {\n    return eval_pp_expr_depth(text, 0);\n}\n'''
new = '''static int64_t eval_pp_expr_depth(const char *text, int depth, bool suppress_eval) {\n    PPExpr e = {.p = text, .depth = depth, .suppress_eval = suppress_eval};\n    int64_t val = pp_conditional(&e);\n    pp_skip_space(&e);\n    if (*e.p)\n        error("unexpected token in #if expression near '%s'", e.p);\n    return suppress_eval ? 0 : val;\n}\n\nstatic int64_t eval_pp_expr(const char *text) {\n    return eval_pp_expr_depth(text, 0, false);\n}\n'''
if old in src:
    src = src.replace(old, new, 1)
elif new not in src:
    raise SystemExit("failed to find evaluator implementation")

marker = '''static char *expand_text(const char *text, Expansion *stack, bool *in_block_comment) {\n'''
helper = '''static int64_t pp_eval_function_macro(PPExpr *e, Macro *m) {\n    const char *call = e->p;\n    while (*call == ' ' || *call == '\\t')\n        call++;\n    if (*call != '(')\n        return 0;\n\n    int argc = 0;\n    const char *after_call = call;\n    char **args = parse_macro_args(&after_call, &argc);\n    if ((!m->is_variadic && argc != m->num_params) ||\n        (m->is_variadic && argc < m->num_params))\n        error("macro '%s' argument count mismatch", m->name);\n\n    int slots = m->num_params + (m->is_variadic ? 1 : 0);\n    char **raw = calloc(slots ? slots : 1, sizeof(char *));\n    char **expanded = calloc(slots ? slots : 1, sizeof(char *));\n\n    for (int i = 0; i < m->num_params; i++)\n        raw[i] = strdup(args[i]);\n    if (m->is_variadic)\n        raw[m->num_params] = join_variadic_args(args, m->num_params, argc);\n\n    for (int i = 0; i < slots; i++) {\n        bool arg_comment = false;\n        expanded[i] = expand_text(raw[i], NULL, &arg_comment);\n    }\n\n    char *subst = substitute_func_macro(m, raw, expanded);\n    Expansion frame = {.macro = m};\n    bool nested_comment = false;\n    char *rescanned = expand_text(subst, &frame, &nested_comment);\n    int64_t result = eval_pp_expr_depth(rescanned, e->depth + 1, e->suppress_eval);\n\n    for (int i = 0; i < argc; i++)\n        free(args[i]);\n    free(args);\n    for (int i = 0; i < slots; i++) {\n        free(raw[i]);\n        free(expanded[i]);\n    }\n    free(raw);\n    free(expanded);\n    free(subst);\n    free(rescanned);\n    e->p = after_call;\n    return result;\n}\n\n'''
if helper not in src:
    if marker not in src:
        raise SystemExit("failed to find expand_text implementation")
    src = src.replace(marker, helper + marker, 1)

SRC.write_text(src)

test = TEST.read_text()
anchor = 'echo "All advanced preprocessor tests passed!"\n'
cases = r'''# Function-like macros are expanded in #if expressions, including nested calls.
assert_pp_adv 28 '#define ID(x) (x)
#if ID(1)
int main() { return 28; }
#else
int main() { return 0; }
#endif'

assert_pp_adv 29 '#define ADD(a,b) ((a) + (b))
#define TWICE(x) ADD((x), (x))
#if TWICE(3) == 6
int main() { return 29; }
#else
int main() { return 0; }
#endif'

# Arguments are macro-expanded before ordinary substitution.
assert_pp_adv 30 '#define ONE 1
#define ID(x) (x)
#if ID(ONE)
int main() { return 30; }
#else
int main() { return 0; }
#endif'

# Short-circuited macro expansions are parsed without evaluating zero divisors.
assert_pp_adv 31 '#define BAD() (1 / 0)
#if 0 && BAD()
int main() { return 0; }
#else
int main() { return 31; }
#endif'

assert_pp_adv 32 '#define BAD (1 / 0)
#if 1 || BAD
int main() { return 32; }
#else
int main() { return 0; }
#endif'

# A selected function-like macro arm still diagnoses division by zero.
assert_pp_fail '#define BAD() (1 / 0)
#if BAD()
int main() { return 0; }
#endif'

# Function-like macro argument count is validated in #if expressions.
assert_pp_fail '#define PICK(x) (x)
#if PICK(1, 2)
int main() { return 0; }
#endif'

'''
if cases not in test:
    if anchor not in test:
        raise SystemExit("failed to find preprocessor test footer")
    test = test.replace(anchor, cases + anchor, 1)
    TEST.write_text(test)
