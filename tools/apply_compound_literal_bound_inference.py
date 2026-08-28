from pathlib import Path

p = Path('parse.c')
s = p.read_text()

old = '''    if (is_incomplete_object_type(ty))
        error_at(type_tok->loc,
                 "compound literal currently requires a complete object type");
'''
new = '''    if (is_incomplete_object_type(ty) &&
        !is_unknown_bound_array_with_complete_element(ty))
        error_at(type_tok->loc,
                 "compound literal requires a complete object type or an unknown-bound array with complete element type");
'''
assert old in s
s = s.replace(old, new, 1)

old = '''    if (!is_initializer_aggregate(ty))
        error_at(where->loc, "internal error: automatic aggregate initializer expected");
    if (ty->kind == TY_ARRAY && ty->array_len == 0)
        error_at(where->loc, "nested incomplete arrays are not supported");

    // Automatic aggregates are zero-initialized before their explicit
    // initializer-list entries are applied.  This is especially important for
    // repeated nested designators: later writes must preserve earlier siblings
    // rather than re-zeroing the whole enclosing subobject.
    append_zero_initializer(tail, lhs, ty, where);
    bool braced = consume(&tok, tok, "{");
'''
new = '''    if (!is_initializer_aggregate(ty))
        error_at(where->loc, "internal error: automatic aggregate initializer expected");

    bool infer_array = ty->kind == TY_ARRAY && ty->array_len == 0;
    if (infer_array && (lhs->kind != ND_VAR || !lhs->var))
        error_at(where->loc, "nested incomplete arrays are not supported");

    // Automatic aggregates are normally zero-initialized before explicit
    // writes. An outermost unknown-bound array has no size yet, so defer its
    // zero-fill until the initializer determines the completed array type.
    Node *before_init = *tail;
    if (!infer_array)
        append_zero_initializer(tail, lhs, ty, where);
    bool braced = consume(&tok, tok, "{");
    if (infer_array && !braced)
        error_at(where->loc, "unknown-bound array initializer requires braces");
'''
assert old in s
s = s.replace(old, new, 1)

old = '''        if (ty->kind == TY_ARRAY) {
            int next_index = 0;
            bool first = true;
'''
new = '''        if (ty->kind == TY_ARRAY) {
            int next_index = 0;
            int max_index = -1;
            bool first = true;
'''
assert old in s
s = s.replace(old, new, 1)

old = '''                    parse_automatic_designated_initializer(tail, target.lhs,
                                                            target.ty, &tok, tok,
                                                            where);
                    next_index = index + 1;
                    continue;
'''
new = '''                    parse_automatic_designated_initializer(tail, target.lhs,
                                                            target.ty, &tok, tok,
                                                            where);
                    if (index > max_index)
                        max_index = index;
                    next_index = index + 1;
                    continue;
'''
assert old in s
s = s.replace(old, new, 1)

old = '''                if (next_index >= ty->array_len)
                    error_at(tok->loc, "excess elements in array initializer");

                int index = next_index++;
'''
new = '''                if (ty->array_len > 0 && next_index >= ty->array_len)
                    error_at(tok->loc, "excess elements in array initializer");

                int index = next_index++;
                if (index > max_index)
                    max_index = index;
'''
assert old in s
s = s.replace(old, new, 1)

old = '''                Node *a = new_initializer_assign(child, rhs, where);
                *tail = (*tail)->next = new_unary(ND_EXPR_STMT, a);
            }
        } else {
'''
new = '''                Node *a = new_initializer_assign(child, rhs, where);
                *tail = (*tail)->next = new_unary(ND_EXPR_STMT, a);
            }

            if (infer_array) {
                if (max_index < 0)
                    error_at(where->loc, "cannot infer array size from empty initializer");
                ty = array_of(ty->base, max_index + 1);
                lhs->var->ty = ty;
                lhs->ty = ty;

                Node zero_head = {};
                Node *zero_cur = &zero_head;
                append_zero_initializer(&zero_cur, lhs, ty, where);
                zero_cur->next = before_init->next;
                before_init->next = zero_head.next;
            }
        } else {
'''
assert old in s
s = s.replace(old, new, 1)

old = '''        if (string_tok && is_character_array(ty)) {
            append_automatic_string_array_initializer(&tail, root, ty, &tok, tok);
        } else if (ty->kind == TY_ARRAY || ty->kind == TY_STRUCT) {
            parse_automatic_aggregate_subobject(&tail, root, ty, &tok, tok,
                                                type_tok);
'''
new = '''        if (string_tok && is_character_array(ty)) {
            prepare_string_array_type(var, &ty, string_tok);
            append_automatic_string_array_initializer(&tail, root, ty, &tok, tok);
        } else if (ty->kind == TY_ARRAY || ty->kind == TY_STRUCT) {
            parse_automatic_aggregate_subobject(&tail, root, ty, &tok, tok,
                                                type_tok);
            ty = var->ty;
'''
assert old in s
s = s.replace(old, new, 1)

old = '''        if (string_tok && is_character_array(ty)) {
            validate_string_array_initializer(ty, string_tok);
            var->init_data = build_string_array_image(ty, string_tok);
            tok = after_string;
        } else if (ty->kind == TY_ARRAY || ty->kind == TY_STRUCT) {
            Type *parsed = parse_static_image_initializer(var, &tok, tok, ty, 0);
            if (parsed != ty)
                error_at(type_tok->loc,
                         "compound literal array bound inference is not yet supported");
'''
new = '''        if (string_tok && is_character_array(ty)) {
            prepare_string_array_type(var, &ty, string_tok);
            var->init_data = build_string_array_image(ty, string_tok);
            tok = after_string;
        } else if (ty->kind == TY_ARRAY || ty->kind == TY_STRUCT) {
            ty = parse_static_image_initializer(var, &tok, tok, ty, 0);
            var->ty = ty;
'''
assert old in s
s = s.replace(old, new, 1)
p.write_text(s)

p = Path('test/compound_literals.sh')
s = p.read_text()
old = "assert_reject 'int main(){return (int[]){1,2}[0];}'\n"
assert old in s
new = '''# Unknown-bound array compound literals infer their bound from the initializer.\nassert_run 3 'int main(){return (int[]){1,2,3}[2];}'\nassert_run 12 'int main(){return sizeof((int[]){1,2,3});}'\nassert_run 9 'int main(){return (int[]){[3]=9}[3];}'\nassert_run 99 'int main(){return (char[]){"abc"}[2];}'\nassert_run 7 'int *p=(int[]){3,5,7}; int main(){return p[2];}'\nassert_run 98 'char *p=(char[]){"abc"}; int main(){return p[1];}'\n'''
s = s.replace(old, new, 1)
p.write_text(s)

p = Path('README.md')
s = p.read_text()
old = '''- C99 compound literals are supported for complete object types. Block-scope literals use anonymous automatic objects and remain modifiable lvalues (subject to qualifiers), while file-scope literals use anonymous static storage; scalar, fixed-size array, struct/union, nested, designated, string-array, address-taking, member/index, and by-value record uses share the ordinary initializer and ABI machinery. Unknown-bound array compound literals are diagnosed until reusable bound-inference support is added.\n'''
new = '''- C99 compound literals are supported for object types, including initializer-inferred unknown-bound arrays. Block-scope literals use anonymous automatic objects and remain modifiable lvalues (subject to qualifiers), while file-scope literals use anonymous static storage; scalar, fixed/inferred-size array, struct/union, nested, designated, string-array, address-taking, member/index, and by-value record uses share the ordinary initializer and ABI machinery.\n'''
assert old in s
s = s.replace(old, new, 1)
p.write_text(s)
