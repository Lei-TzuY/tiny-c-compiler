from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, found {count}")
    p.write_text(text.replace(old, new, 1))


# In C11, a label prefixes a statement. A declaration (including a static
# assertion declaration) is not itself a statement; declarations must be placed
# inside a compound statement when they are the first construct after a label.
replace_once(
    "parse.c",
    '''static void require_scalar_condition(Node *cond, Token *keyword,\n                                     const char *construct) {\n    if (!is_scalar_expr(cond))\n        error_at(keyword->loc, "%s condition must have scalar type", construct);\n}\n\nstatic Node *stmt(Token **rest, Token *tok) {\n''',
    '''static void require_scalar_condition(Node *cond, Token *keyword,\n                                     const char *construct) {\n    if (!is_scalar_expr(cond))\n        error_at(keyword->loc, "%s condition must have scalar type", construct);\n}\n\nstatic void require_statement_after_label(Token *tok) {\n    if (equal(tok, "_Static_assert") || is_decl_start(tok))\n        error_at(tok->loc, "label must be followed by a statement, not a declaration");\n}\n\nstatic Node *stmt(Token **rest, Token *tok) {\n''')

replace_once(
    "parse.c",
    '''        tok = skip(tok, ":");\n        Node *node = new_node(ND_CASE);\n''',
    '''        tok = skip(tok, ":");\n        require_statement_after_label(tok);\n        Node *node = new_node(ND_CASE);\n''')

replace_once(
    "parse.c",
    '''        tok = skip(tok->next, ":");\n        Node *node = new_node(ND_DEFAULT);\n''',
    '''        tok = skip(tok->next, ":");\n        require_statement_after_label(tok);\n        Node *node = new_node(ND_DEFAULT);\n''')

replace_once(
    "parse.c",
    '''        current_labels = node;\n        tok = skip(tok->next, ":");\n        node->lhs = stmt(rest, tok);\n''',
    '''        current_labels = node;\n        tok = skip(tok->next, ":");\n        require_statement_after_label(tok);\n        node->lhs = stmt(rest, tok);\n''')

# Extend the existing control-flow suite with grammar-focused label cases.
test = Path("test/control_flow_context.sh")
text = test.read_text()
positive_anchor = "assert_run 7 'int f(void){same:return 3;} int g(void){same:return 4;} int main(void){return f()+g();}'\n"
positive_addition = positive_anchor + \
    "assert_run 5 'int main(void){goto L; L:{int x=5; return x;}}'\n" + \
    "assert_run 7 'int main(void){switch(1){case 1:{int x=7; return x;} default:return 2;}}'\n" + \
    "assert_run 9 'int main(void){switch(0){default:{int x=9; return x;}}}'\n" + \
    "assert_run 3 'int main(void){L:{_Static_assert(1,\"ok\"); return 3;}}'\n"
if text.count(positive_anchor) != 1:
    raise SystemExit("control-flow labeled-statement positive insertion point not unique")
text = text.replace(positive_anchor, positive_addition, 1)

reject_anchor = "assert_reject_msg 'undefined label: missing' 'int main(void){goto missing; return 0;}'\n"
reject_addition = reject_anchor + \
    "assert_reject_msg 'label must be followed by a statement, not a declaration' 'int main(void){L:int x=1; return x;}'\n" + \
    "assert_reject_msg 'label must be followed by a statement, not a declaration' 'int main(void){L:typedef int T; return 0;}'\n" + \
    "assert_reject_msg 'label must be followed by a statement, not a declaration' 'int main(void){L:_Static_assert(1,\"ok\"); return 0;}'\n" + \
    "assert_reject_msg 'label must be followed by a statement, not a declaration' 'int main(void){switch(1){case 1:int x=1; return x;} return 0;}'\n" + \
    "assert_reject_msg 'label must be followed by a statement, not a declaration' 'int main(void){switch(0){default:const int x=1; return x;}}'\n" + \
    "assert_reject_msg 'label must be followed by a statement, not a declaration' 'int main(void){switch(1){case 1:_Static_assert(1,\"ok\"); return 0;}}'\n"
if text.count(reject_anchor) != 1:
    raise SystemExit("control-flow labeled-statement rejection insertion point not unique")
text = text.replace(reject_anchor, reject_addition, 1)
test.write_text(text)

readme = Path("README.md")
text = readme.read_text()
old = "ordinary labels have function scope, with undefined and duplicate label diagnostics for `goto`/labeled statements"
new = "ordinary labels have function scope, with undefined and duplicate label diagnostics for `goto`/labeled statements; under the C11 grammar, ordinary/case/default labels must prefix statements rather than declarations (a compound block may contain declarations)"
if text.count(old) != 1:
    raise SystemExit("README labeled-statement wording not unique")
readme.write_text(text.replace(old, new, 1))

print("labeled-statement declaration constraints migration applied")
