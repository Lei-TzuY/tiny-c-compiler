from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, found {count}\n--- old ---\n{old}")
    p.write_text(text.replace(old, new, 1))


# `stmt()` also parses block-item declarations for compound statements, so
# callers whose grammar specifically requires a statement must reject a
# declaration before delegating to it.
replace_once(
    "parse.c",
    '''static void require_statement_after_label(Token *tok) {\n    if (equal(tok, "_Static_assert") || is_decl_start(tok))\n        error_at(tok->loc, "label must be followed by a statement, not a declaration");\n}\n\nstatic Node *stmt(Token **rest, Token *tok) {\n''',
    '''static void require_statement_after_label(Token *tok) {\n    if (equal(tok, "_Static_assert") || is_decl_start(tok))\n        error_at(tok->loc, "label must be followed by a statement, not a declaration");\n}\n\nstatic void require_control_substatement(Token *tok, const char *construct) {\n    if (equal(tok, "_Static_assert") || is_decl_start(tok))\n        error_at(tok->loc, "%s body must be a statement, not a declaration", construct);\n}\n\nstatic Node *stmt(Token **rest, Token *tok) {\n''')

replace_once(
    "parse.c",
    '''    if (equal(tok, "do")) {\n        Token *do_tok = tok;\n        Node *node = new_node(ND_DO);\n        current_loop_depth++;\n        node->then = stmt(&tok, tok->next);\n''',
    '''    if (equal(tok, "do")) {\n        Token *do_tok = tok;\n        Node *node = new_node(ND_DO);\n        Token *body_tok = tok->next;\n        require_control_substatement(body_tok, "do");\n        current_loop_depth++;\n        node->then = stmt(&tok, body_tok);\n''')

replace_once(
    "parse.c",
    '''        node->ty = get_common_type(node->cond->ty, ty_int);\n        tok = skip(tok, ")");\n\n        SwitchContext ctx = {};\n''',
    '''        node->ty = get_common_type(node->cond->ty, ty_int);\n        tok = skip(tok, ")");\n        require_control_substatement(tok, "switch");\n\n        SwitchContext ctx = {};\n''')

replace_once(
    "parse.c",
    '''        node->cond = expr(&tok, tok);\n        require_scalar_condition(node->cond, if_tok, "if");\n        tok = skip(tok, ")");\n        node->then = stmt(&tok, tok);\n        if (equal(tok, "else"))\n            node->els = stmt(&tok, tok->next);\n''',
    '''        node->cond = expr(&tok, tok);\n        require_scalar_condition(node->cond, if_tok, "if");\n        tok = skip(tok, ")");\n        require_control_substatement(tok, "if");\n        node->then = stmt(&tok, tok);\n        if (equal(tok, "else")) {\n            require_control_substatement(tok->next, "else");\n            node->els = stmt(&tok, tok->next);\n        }\n''')

replace_once(
    "parse.c",
    '''        node->cond = expr(&tok, tok);\n        require_scalar_condition(node->cond, while_tok, "while");\n        tok = skip(tok, ")");\n        current_loop_depth++;\n        node->then = stmt(&tok, tok);\n''',
    '''        node->cond = expr(&tok, tok);\n        require_scalar_condition(node->cond, while_tok, "while");\n        tok = skip(tok, ")");\n        require_control_substatement(tok, "while");\n        current_loop_depth++;\n        node->then = stmt(&tok, tok);\n''')

replace_once(
    "parse.c",
    '''        if (!equal(tok, ")"))\n            node->inc = expr(&tok, tok);\n        tok = skip(tok, ")");\n\n        current_loop_depth++;\n        node->then = stmt(rest, tok);\n''',
    '''        if (!equal(tok, ")"))\n            node->inc = expr(&tok, tok);\n        tok = skip(tok, ")");\n        require_control_substatement(tok, "for");\n\n        current_loop_depth++;\n        node->then = stmt(rest, tok);\n''')

# Extend the existing control-flow regression harness.
test = Path("test/control_flow_context.sh")
text = test.read_text()
positive_anchor = "assert_run 3 'int main(void){L:{_Static_assert(1,\"ok\"); return 3;}}'\n"
positive_addition = positive_anchor + \
    "assert_run 5 'int main(void){if(1){int x=5;return x;}return 0;}'\n" + \
    "assert_run 6 'int main(void){if(0)return 1;else{int x=6;return x;}}'\n" + \
    "assert_run 7 'int main(void){while(1){int x=7;return x;}}'\n" + \
    "assert_run 8 'int main(void){do{int x=8;return x;}while(0);}'\n" + \
    "assert_run 9 'int main(void){for(int i=0;i<1;i++){int x=9;return x;}return 0;}'\n" + \
    "assert_run 4 'int main(void){switch(1){int x;case 1:x=4;return x;}return 0;}'\n"
if text.count(positive_anchor) != 1:
    raise SystemExit("control-flow substatement positive insertion point not unique")
text = text.replace(positive_anchor, positive_addition, 1)

reject_anchor = "assert_reject_msg 'label must be followed by a statement, not a declaration' 'int main(void){switch(1){case 1:_Static_assert(1,\"ok\"); return 0;}}'\n"
reject_addition = reject_anchor + \
    "assert_reject_msg 'if body must be a statement, not a declaration' 'int main(void){if(1)int x;return 0;}'\n" + \
    "assert_reject_msg 'else body must be a statement, not a declaration' 'int main(void){if(0);else int x;return 0;}'\n" + \
    "assert_reject_msg 'while body must be a statement, not a declaration' 'int main(void){while(0)int x;return 0;}'\n" + \
    "assert_reject_msg 'do body must be a statement, not a declaration' 'int main(void){do int x;while(0);return 0;}'\n" + \
    "assert_reject_msg 'for body must be a statement, not a declaration' 'int main(void){for(;;)int x;}'\n" + \
    "assert_reject_msg 'switch body must be a statement, not a declaration' 'int main(void){switch(0)int x;return 0;}'\n" + \
    "assert_reject_msg 'if body must be a statement, not a declaration' 'int main(void){if(1)_Static_assert(1,\"ok\");return 0;}'\n" + \
    "assert_reject_msg 'while body must be a statement, not a declaration' 'int main(void){while(0)typedef int T;return 0;}'\n"
if text.count(reject_anchor) != 1:
    raise SystemExit("control-flow substatement rejection insertion point not unique")
text = text.replace(reject_anchor, reject_addition, 1)
test.write_text(text)

readme = Path("README.md")
text = readme.read_text()
old = "ordinary/case/default labels must prefix statements rather than declarations (a compound block may contain declarations)"
new = "ordinary/case/default labels and control-statement bodies (`if`/`else`/loops/`switch`) must be statements rather than declarations (a compound block may contain declarations)"
if text.count(old) != 1:
    raise SystemExit("README control substatement wording not unique")
readme.write_text(text.replace(old, new, 1))

print("control-substatement grammar migration applied")
