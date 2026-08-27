from pathlib import Path

p = Path('parse.c')
s = p.read_text()

needle = '''static bool pointer_assignment_compatible(Type *dst, Type *src) {
'''
helper = r'''static bool record_shape_compatible(Type *a, Type *b) {
    if (a == b)
        return true;
    if (!a || !b || a->kind != TY_STRUCT || b->kind != TY_STRUCT)
        return false;
    if (a->size != b->size || a->align != b->align)
        return false;

    Member *ma = a->members;
    Member *mb = b->members;
    while (ma && mb) {
        if (ma->offset != mb->offset || strcmp(ma->name, mb->name) ||
            !type_compatible(ma->ty, mb->ty))
            return false;
        ma = ma->next;
        mb = mb->next;
    }
    return !ma && !mb;
}

static bool pointer_assignment_compatible(Type *dst, Type *src) {
'''
if s.count(needle) != 1:
    raise SystemExit(f'pointer helper anchor count={s.count(needle)}')
s = s.replace(needle, helper, 1)

needle = '''    if (type_compatible(dst->base, src->base))
        return true;

    // Object/incomplete-object pointers implicitly convert to and from void*.
'''
replacement = '''    if (type_compatible(dst->base, src->base))
        return true;

    // Preserve the compiler's long-standing educational extension for
    // pointers to separately declared anonymous records that have the same
    // member layout. File-scope redeclaration compatibility remains strict
    // Type identity; this exception exists only for expression conversion.
    if (dst->base && src->base && dst->base->kind == TY_STRUCT &&
        src->base->kind == TY_STRUCT &&
        record_shape_compatible(dst->base, src->base))
        return true;

    // Object/incomplete-object pointers implicitly convert to and from void*.
'''
if s.count(needle) != 1:
    raise SystemExit(f'compatibility insertion anchor count={s.count(needle)}')
s = s.replace(needle, replacement, 1)

needle = '''    if (dst->kind == TY_STRUCT && src->kind == TY_STRUCT)
        return type_compatible(dst, src);
'''
replacement = '''    if (dst->kind == TY_STRUCT && src->kind == TY_STRUCT)
        return type_compatible(dst, src) || record_shape_compatible(dst, src);
'''
if s.count(needle) != 1:
    raise SystemExit(f'record-value compatibility anchor count={s.count(needle)}')

p.write_text(s.replace(needle, replacement, 1))
