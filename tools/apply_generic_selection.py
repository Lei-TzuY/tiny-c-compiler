from pathlib import Path

p = Path('parse.c')
text = p.read_text()
anchor = '''    if (equal(tok, "(")) {\n        Node *node = expr(&tok, tok->next);\n        *rest = skip(tok, ")");\n        return node;\n    }\n\n    if (equal(tok, "_Alignof")) {\n'''
insert = r'''    if (equal(tok, "_Generic")) {
        Token *op = tok;
        tok = skip(tok->next, "(");
        Node *control = assign(&tok, tok);
        add_type(control);
        tok = skip(tok, ",");

        typedef struct GenericType GenericType;
        struct GenericType {
            GenericType *next;
            Type *ty;
        };

        GenericType *seen = NULL;
        Node *selected = NULL;
        Node *default_expr = NULL;
        bool have_assoc = false;

        for (;;) {
            have_assoc = true;
            if (equal(tok, "default")) {
                if (default_expr)
                    error_at(tok->loc, "duplicate default generic association");
                tok = skip(tok->next, ":");
                default_expr = assign(&tok, tok);
            } else {
                if (!is_typename(tok))
                    error_at(tok->loc, "expected type name or default in _Generic");
                Token *type_tok = tok;
                Type *assoc_ty = type_name(&tok, tok);
                if (!assoc_ty || assoc_ty->kind == TY_VOID || assoc_ty->kind == TY_FUNC ||
                    assoc_ty->is_incomplete ||
                    (assoc_ty->kind == TY_ARRAY && assoc_ty->array_len == 0))
                    error_at(type_tok->loc,
                             "generic association requires a complete object type");

                for (GenericType *g = seen; g; g = g->next)
                    if (type_compatible(g->ty, assoc_ty))
                        error_at(type_tok->loc,
                                 "duplicate compatible type in generic association");
                GenericType *g = calloc(1, sizeof(GenericType));
                g->ty = assoc_ty;
                g->next = seen;
                seen = g;

                tok = skip(tok, ":");
                Node *expr_node = assign(&tok, tok);
                if (type_compatible(control->ty, assoc_ty)) {
                    if (selected)
                        error_at(type_tok->loc,
                                 "controlling type matches multiple generic associations");
                    selected = expr_node;
                }
            }

            if (!equal(tok, ","))
                break;
            tok = tok->next;
        }

        if (!have_assoc)
            error_at(op->loc, "_Generic requires at least one association");
        tok = skip(tok, ")");
        if (!selected)
            selected = default_expr;
        if (!selected)
            error_at(op->loc, "no matching generic association");

        *rest = tok;
        return selected;
    }

    if (equal(tok, "(")) {
        Node *node = expr(&tok, tok->next);
        *rest = skip(tok, ")");
        return node;
    }

    if (equal(tok, "_Alignof")) {
'''
if anchor not in text:
    raise SystemExit('primary anchor not found')
p.write_text(text.replace(anchor, insert, 1))
