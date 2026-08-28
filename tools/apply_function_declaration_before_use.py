from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, found {count}\n--- old ---\n{old}")
    p.write_text(text.replace(old, new, 1))


replace_once(
    "parse.c",
    '''        // Direct function calls keep a named callee for codegen. A variable\n        // of function-pointer type falls through to ND_VAR and is handled by\n        // the ordinary postfix-call path, sharing the same argument parser.\n        if (equal(tok->next, "(")) {\n            Obj *fn = find_var(tok);\n            if (!fn && find_typedef(tok))\n                error_at(tok->loc, "typedef name is not callable");\n            if (!fn || fn->is_function) {\n                Node *node = new_node(ND_FUNCALL);\n                node->funcname = strndup(tok->loc, tok->len);\n\n                Type *fty = NULL;\n                if (fn && fn->ty && fn->ty->kind == TY_FUNC) {\n                    fty = fn->ty;\n                    node->ty = fty->return_ty;\n                }\n                check_supported_function_abi(fty, tok);\n\n                tok = skip(tok->next, "(");\n                node->args = parse_call_arguments(&tok, tok, fty);\n                prepare_record_call_result(node);\n                *rest = tok;\n                return node;\n            }\n        }\n''',
    '''        // Direct function calls keep a named callee for codegen. C99 and\n        // later require a visible declaration at the call site; a definition or\n        // declaration appearing later in the translation unit cannot retroactively\n        // supply the old implicit-function declaration. A function-pointer object\n        // falls through to ND_VAR and the ordinary postfix-call path.\n        if (equal(tok->next, "(")) {\n            Obj *fn = find_var(tok);\n            if (!fn) {\n                if (find_typedef(tok))\n                    error_at(tok->loc, "typedef name is not callable");\n                error_at(tok->loc, "call to undeclared function");\n            }\n            if (fn->is_function) {\n                Node *node = new_node(ND_FUNCALL);\n                node->funcname = strndup(tok->loc, tok->len);\n\n                Type *fty = fn->ty;\n                node->ty = fty->return_ty;\n                check_supported_function_abi(fty, tok);\n\n                tok = skip(tok->next, "(");\n                node->args = parse_call_arguments(&tok, tok, fty);\n                prepare_record_call_result(node);\n                *rest = tok;\n                return node;\n            }\n        }\n''')

sem = Path("semantic_validate.c")
text = sem.read_text()
old = '''static bool program_has_function_symbol(Program *prog, const char *name) {\n    if (!prog || !name)\n        return false;\n\n    for (Obj *obj = prog->globals; obj; obj = obj->next)\n        if (obj->is_function && obj->name && !strcmp(obj->name, name))\n            return true;\n    return false;\n}\n\n'''
if text.count(old) != 1:
    raise SystemExit("semantic_validate.c function-symbol helper not unique")
text = text.replace(old, "", 1)
old_case = '''        case ND_FUNCALL:\n            // Direct calls retain their source-level callee name.  The parser\n            // historically allowed an unknown identifier here and assigned an\n            // implicit int return type, deferring misspellings to the linker.\n            // Reject calls that never resolve to any function declaration in\n            // the translation unit; indirect calls have funcname == NULL and\n            // were already type-checked against their function-pointer type.\n            if (node->funcname && !program_has_function_symbol(prog, node->funcname))\n                error("call to undeclared function '%s'", node->funcname);\n            break;\n'''
if text.count(old_case) != 1:
    raise SystemExit("semantic_validate.c ND_FUNCALL validation not unique")
text = text.replace(old_case, "", 1)
sem.write_text(text)

# The validator no longer needs Program while walking nodes; keep the public
# signature stable and mark it unused through the recursive helper simplification.
text = sem.read_text()
text = text.replace('static void validate_node(Program *prog, Node *node) {',
                    'static void validate_node(Node *node) {', 1)
for field in ['lhs', 'rhs', 'cond', 'then', 'els', 'init', 'inc', 'body', 'args']:
    text = text.replace(f'        validate_node(prog, node->{field});',
                        f'        validate_node(node->{field});', 1)
text = text.replace('        validate_node(prog, fn->body);',
                    '        validate_node(fn->body);', 1)
sem.write_text(text)

# Extend the focused #103 regression instead of adding a second overlapping test.
test = Path("test/unresolved_function_calls.sh")
text = test.read_text()
text = text.replace(
    '''# A direct call whose identifier never resolves to any function declaration is\n# not a valid C11 call. Reject it in the front end instead of emitting a call\n# with an invented int return type and deferring the typo to the linker.\n''',
    '''# C99 and later require a function declaration to be visible at the call site.\n# A later declaration/definition cannot retroactively legitimize an implicit call.\n''', 1)
needle = "assert_reject 'int main(void){return misspelled_name();}int real_name(void){return 1;}'\n"
addition = needle + "assert_reject 'int main(void){return f();}int f(void){return 6;}'\n" + \
    "assert_reject 'int main(void){return f();}extern int f(void);int f(void){return 6;}'\n" + \
    "assert_reject 'int main(void){int x=f();extern int f(void);return x;}int f(void){return 6;}'\n"
if text.count(needle) != 1:
    raise SystemExit("unresolved call rejection insertion point not unique")
text = text.replace(needle, addition, 1)
positive_anchor = "assert_run 4 'extern int f(void);int f(void){return 4;}int main(void){return f();}'\n"
positive_add = positive_anchor + \
    "assert_run 3 'int f(int n){if(n==0)return 3;return f(n-1);}int main(void){return f(2);}'\n" + \
    "assert_run 7 'int g(int);int f(int n){return n?g(n-1):3;}int g(int n){return n?f(n-1)+1:4;}int main(void){return f(2);}'\n" + \
    "assert_run 8 'int main(void){extern int f(void);return f();}int f(void){return 8;}'\n"
if text.count(positive_anchor) != 1:
    raise SystemExit("unresolved call positive insertion point not unique")
text = text.replace(positive_anchor, positive_add, 1)
test.write_text(text)

readme = Path("README.md")
text = readme.read_text()
needle = "prototype-aware call arity checking (`f()` remains old-style/unprototyped while `f(void)` is strict)"
replacement = "C99-style declaration-before-use checking for direct function calls and prototype-aware call arity checking (`f()` remains old-style/unprototyped while `f(void)` is strict)"
if text.count(needle) != 1:
    raise SystemExit("README call-semantics insertion point not unique")
readme.write_text(text.replace(needle, replacement, 1))

print("function declaration-before-use migration applied")
