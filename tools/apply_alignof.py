from pathlib import Path

p = Path('parse.c')
text = p.read_text()
anchor = '''    if (equal(tok, "sizeof")) {
        tok = tok->next;
        if (equal(tok, "(") && is_typename(tok->next)) {
            tok = tok->next;
            Type *ty = type_name(&tok, tok);
            if (invalid_sizeof_type(ty))
                error_at(tok->loc, "invalid operand type for sizeof");
            *rest = skip(tok, ")");
            return new_num(ty->size);
        }
        Node *n = unary(rest, tok);
        add_type(n);
        if (invalid_sizeof_type(n->ty))
            error_at(tok->loc, "invalid operand type for sizeof");
        return new_num(n->ty->size);
    }
'''
insert = '''    if (equal(tok, "_Alignof")) {
        Token *op = tok;
        tok = skip(tok->next, "(");
        if (!is_typename(tok))
            error_at(op->loc, "_Alignof requires a type name");
        Type *ty = type_name(&tok, tok);
        if (!ty || ty->kind == TY_VOID || ty->kind == TY_FUNC ||
            ty->is_incomplete)
            error_at(op->loc, "invalid type for _Alignof");
        *rest = skip(tok, ")");
        return new_num(ty->align);
    }

'''
if anchor not in text:
    raise SystemExit('sizeof anchor not found')
p.write_text(text.replace(anchor, insert + anchor, 1))
