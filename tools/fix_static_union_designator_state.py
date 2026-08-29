from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


p = Path('parse.c').read_text()

p = replace_once(
    p,
    '''static void reset_static_subobject(Obj *var, int offset, int size) {\n    ensure_static_image(var, offset + size);\n    memset(var->init_image + offset, 0, size);\n    clear_static_reloc_range(var, offset, size);\n}\n''',
    '''static void reset_static_subobject(Obj *var, int offset, int size) {\n    ensure_static_image(var, offset + size);\n    memset(var->init_image + offset, 0, size);\n    clear_static_reloc_range(var, offset, size);\n}\n\ntypedef struct StaticUnionSelection StaticUnionSelection;\nstruct StaticUnionSelection {\n    StaticUnionSelection *next;\n    Obj *var;\n    Type *ty;\n    int offset;\n    Member *member;\n};\n\nstatic StaticUnionSelection *static_union_selections;\n\nstatic void invalidate_static_union_selections(Obj *var, int offset, int size) {\n    StaticUnionSelection head = {};\n    StaticUnionSelection *tail = &head;\n    for (StaticUnionSelection *sel = static_union_selections; sel;) {\n        StaticUnionSelection *next = sel->next;\n        bool contained = sel->var == var && sel->offset >= offset &&\n                         sel->offset < offset + size;\n        if (contained) {\n            free(sel);\n        } else {\n            tail = tail->next = sel;\n            sel->next = NULL;\n        }\n        sel = next;\n    }\n    static_union_selections = head.next;\n}\n\n// Designators may enter the same union member repeatedly, e.g. `.s.a` then\n// `.s.b`. Preserve earlier writes while that selected member stays active, but\n// clear the complete overlapping representation (including relocations) when a\n// later designator switches the union to another member. Offset plus Type\n// identifies each physical union subobject within one static object image.\nstatic void select_static_union_member(Obj *var, Type *ty, int offset,\n                                       Member *member) {\n    for (StaticUnionSelection *sel = static_union_selections; sel; sel = sel->next) {\n        if (sel->var == var && sel->ty == ty && sel->offset == offset) {\n            if (sel->member == member)\n                return;\n            break;\n        }\n    }\n\n    reset_static_subobject(var, offset, ty->size);\n    invalidate_static_union_selections(var, offset, ty->size);\n\n    StaticUnionSelection *sel = calloc(1, sizeof(StaticUnionSelection));\n    sel->var = var;\n    sel->ty = ty;\n    sel->offset = offset;\n    sel->member = member;\n    sel->next = static_union_selections;\n    static_union_selections = sel;\n}\n''',
    'static union selection state',
)

p = replace_once(
    p,
    '''            // Selecting a union member replaces the complete overlapping\n            // representation.  Clear both bytes and relocations before walking\n            // farther into the selected member.\n            if (cur->is_union)\n                reset_static_subobject(var, offset, cur->size);\n            offset += step->member->offset;\n''',
    '''            if (cur->is_union)\n                select_static_union_member(var, cur, offset, step->member);\n            offset += step->member->offset;\n''',
    'designator union selection',
)

p = replace_once(
    p,
    '''        if (ty->is_union)\n            reset_static_subobject(var, offset, ty->size);\n        else\n            reset_static_subobject(var, offset + m->offset, m->ty->size);\n''',
    '''        if (ty->is_union)\n            select_static_union_member(var, ty, offset, m);\n        else\n            reset_static_subobject(var, offset + m->offset, m->ty->size);\n''',
    'brace-elided positional union selection',
)

p = replace_once(
    p,
    '''    Member *next_member = ty->members;\n    Member *active_union_member = NULL;\n    bool first = true;\n''',
    '''    Member *next_member = ty->members;\n    bool first = true;\n''',
    'remove local active union member',
)

p = replace_once(
    p,
    '''            int target_offset = apply_static_designator_path(var, ty, offset, &path);\n            if (ty->is_union && active_union_member && active_union_member != member)\n                reset_static_subobject(var, offset, ty->size);\n            reset_static_subobject(var, target_offset, target_ty->size);\n            if (ty->is_union)\n                active_union_member = member;\n            free_initializer_designator_path(&path);\n''',
    '''            int target_offset = apply_static_designator_path(var, ty, offset, &path);\n            reset_static_subobject(var, target_offset, target_ty->size);\n            free_initializer_designator_path(&path);\n''',
    'root union designator reset',
)

p = replace_once(
    p,
    '''        // All union members overlap at offset zero. Clear the complete union so\n        // a positional pointer member cannot leave stale relocation/data bytes.\n        if (ty->is_union)\n            reset_static_subobject(var, offset, ty->size);\n        else\n            reset_static_subobject(var, offset + member->offset, member->ty->size);\n''',
    '''        // All union members overlap at offset zero. Selecting a positional\n        // member participates in the same active-member state as designators.\n        if (ty->is_union)\n            select_static_union_member(var, ty, offset, member);\n        else\n            reset_static_subobject(var, offset + member->offset, member->ty->size);\n''',
    'braced positional union selection',
)

Path('parse.c').write_text(p)

# Lock the general named nested-union case alongside the anonymous promotion
# regression that exposed it.
path = Path('test/union_initializers.sh')
t = path.read_text()
t = replace_once(
    t,
    "assert_run 8 'int main(){union U{struct {int a; int b;} s; long y;}; union U u={.s.a=3,.s.b=5}; return u.s.a+u.s.b;}'\n",
    "assert_run 8 'int main(){union U{struct {int a; int b;} s; long y;}; union U u={.s.a=3,.s.b=5}; return u.s.a+u.s.b;}'\nassert_run 8 'union U{struct {int a; int b;} s; long y;}; static union U u={.s.a=3,.s.b=5}; int main(){return u.s.a+u.s.b;}'\nassert_run 8 'struct W{int h;union U{struct {int a;int b;} s;long y;} u;}; static struct W w={.u.s.a=3,.u.s.b=5}; int main(){return w.u.s.a+w.u.s.b;}'\n",
    'static repeated nested union regressions',
)
path.write_text(t)
