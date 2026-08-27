from pathlib import Path
p=Path('parse.c')
t=p.read_text()
block='''    if (equal(tok, "_Alignof")) {
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
count=t.count(block)
if count < 1:
    raise SystemExit('_Alignof block missing')
while t.count(block) > 1:
    first=t.find(block)
    second=t.find(block, first+len(block))
    t=t[:second]+t[second+len(block):]
p.write_text(t)
