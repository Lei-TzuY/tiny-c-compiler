from pathlib import Path

parse = Path('parse.c')
text = parse.read_text()
old = '''static Node *primary(Token **rest, Token *tok) {
    if (equal(tok, "__builtin_va_start")) {
'''
new = '''static Node *primary(Token **rest, Token *tok) {
    if (equal(tok, "__builtin_offsetof")) {
        Token *builtin = tok;
        tok = skip(tok->next, "(");
        Type *cur_ty = type_name(&tok, tok);
        if (!cur_ty || cur_ty->kind != TY_STRUCT || cur_ty->is_incomplete)
            error_at(builtin->loc, "offsetof requires a complete struct or union type");
        tok = skip(tok, ",");

        int64_t offset = 0;
        for (;;) {
            if (tok->kind != TK_IDENT)
                error_at(tok->loc, "offsetof requires a member designator");
            if (!cur_ty || cur_ty->kind != TY_STRUCT || cur_ty->is_incomplete)
                error_at(tok->loc, "member designator does not name a record subobject");

            MemberPath *path = find_record_member_path(cur_ty, tok);
            if (!path)
                error_at(tok->loc, "unknown member in offsetof");
            for (MemberPath *mp = path; mp; mp = mp->next) {
                offset += mp->member->offset;
                cur_ty = mp->member->ty;
            }
            free_member_path(path);
            tok = tok->next;

            while (equal(tok, "[")) {
                Token *bracket = tok;
                if (!cur_ty || cur_ty->kind != TY_ARRAY || !cur_ty->base ||
                    cur_ty->array_len <= 0 || cur_ty->base->size <= 0)
                    error_at(bracket->loc,
                             "offsetof array designator requires a complete array type");
                tok = tok->next;
                Node *index_expr = ternary(&tok, tok);
                add_type(index_expr);
                if (!is_integer(index_expr->ty))
                    error_at(bracket->loc, "offsetof array index must have integer type");

                int64_t raw = eval_const_expr(index_expr);
                uint64_t index;
                if (index_expr->ty->is_unsigned) {
                    index = (uint64_t)cast_const_integer(raw, index_expr->ty);
                } else {
                    int64_t signed_index = cast_const_integer(raw, index_expr->ty);
                    if (signed_index < 0)
                        error_at(bracket->loc, "offsetof array index must be nonnegative");
                    index = (uint64_t)signed_index;
                }
                if (index >= (uint64_t)cur_ty->array_len)
                    error_at(bracket->loc, "offsetof array index exceeds array bounds");
                if (index > (uint64_t)INT64_MAX / (uint64_t)cur_ty->base->size)
                    error_at(bracket->loc, "offsetof result is out of range");
                offset += (int64_t)(index * (uint64_t)cur_ty->base->size);
                cur_ty = cur_ty->base;
                tok = skip(tok, "]");
            }

            if (!equal(tok, "."))
                break;
            tok = tok->next;
        }

        *rest = skip(tok, ")");
        return new_size_t_num(offset);
    }

    if (equal(tok, "__builtin_va_start")) {
'''
if text.count(old) != 1:
    raise SystemExit(f'expected one primary/va_start anchor, found {text.count(old)}')
parse.write_text(text.replace(old, new, 1))

pp = Path('preprocess_v2.c')
text = pp.read_text()
old = '''    if (!strcmp(name, "limits.h")) {
'''
new = '''    if (!strcmp(name, "stddef.h")) {
        return "#ifndef __MINICC_STDDEF_H\\n"
               "#define __MINICC_STDDEF_H 1\\n"
               "typedef unsigned long size_t;\\n"
               "typedef long ptrdiff_t;\\n"
               "typedef int wchar_t;\\n"
               "typedef struct { long long __ll; double __d; } max_align_t;\\n"
               "#define NULL ((void *)0)\\n"
               "#define offsetof(type, member) __builtin_offsetof(type, member)\\n"
               "#endif\\n";
    }
    if (!strcmp(name, "limits.h")) {
'''
if text.count(old) != 1:
    raise SystemExit(f'expected one limits header anchor, found {text.count(old)}')
pp.write_text(text.replace(old, new, 1))

mk = Path('Makefile')
text = mk.read_text()
old = '''\tbash ./test/stdint_header.sh
\tbash ./test/limits_header.sh
\tbash ./test/noreturn.sh
'''
new = '''\tbash ./test/stdint_header.sh
\tbash ./test/limits_header.sh
\tbash ./test/stddef_header.sh
\tbash ./test/noreturn.sh
'''
if text.count(old) != 1:
    raise SystemExit(f'expected one limits test anchor, found {text.count(old)}')
mk.write_text(text.replace(old, new, 1))
