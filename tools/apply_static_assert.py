from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}")
    p.write_text(text.replace(old, new, 1))


p = Path("parse.c")
text = p.read_text()
anchor = '''static bool is_label(Token *tok) {
'''
helper = '''// Parse C11 _Static_assert(constant-expression, string-literal); at either
// file or block scope. The controlling expression must be an integer constant
// expression and is evaluated entirely during parsing, so no runtime node is
// emitted for a successful assertion.
static Token *parse_static_assertion(Token *tok) {
    Token *keyword = tok;
    tok = skip(tok->next, "(");

    Node *cond = ternary(&tok, tok);
    add_type(cond);
    if (!is_integer(cond->ty))
        error_at(keyword->loc, "_Static_assert requires an integer constant expression");
    int64_t value = eval_const_expr(cond);

    tok = skip(tok, ",");
    if (tok->kind != TK_STR)
        error_at(tok->loc, "_Static_assert requires a string literal message");
    char *message = tok->str;
    tok = skip(tok->next, ")");
    tok = skip(tok, ";");

    if (!value)
        error_at(keyword->loc, "static assertion failed: %s", message);
    return tok;
}

'''
if anchor not in text:
    raise SystemExit("is_label anchor not found")
p.write_text(text.replace(anchor, helper + anchor, 1))

replace_once(
    "parse.c",
    '''static Node *stmt(Token **rest, Token *tok) {
    if (equal(tok, "return")) {
''',
    '''static Node *stmt(Token **rest, Token *tok) {
    if (equal(tok, "_Static_assert")) {
        *rest = parse_static_assertion(tok);
        return new_node(ND_EXPR_STMT);
    }

    if (equal(tok, "return")) {
''',
)

replace_once(
    "parse.c",
    '''    while (tok->kind != TK_EOF) {
        // Top-level typedef
''',
    '''    while (tok->kind != TK_EOF) {
        if (equal(tok, "_Static_assert")) {
            tok = parse_static_assertion(tok);
            continue;
        }

        // Top-level typedef
''',
)
