from pathlib import Path

p = Path('parse.c')
s = p.read_text()

old = '''    ensure_static_image(var, offset + ty->size);\n    Member *next_member = ty->members;\n    bool first = true;\n    int initialized_members = 0;\n'''
new = '''    ensure_static_image(var, offset + ty->size);\n    Member *next_member = ty->members;\n    Member *active_union_member = NULL;\n    bool first = true;\n    int initialized_members = 0;\n'''
assert old in s
s = s.replace(old, new, 1)

old = '''        if (ty->is_union && initialized_members)\n            error_at(tok->loc, "excess elements in union initializer");\n\n        if (equal(tok, ".") || equal(tok, "[")) {\n'''
new = '''        if (ty->is_union && initialized_members && !equal(tok, "."))\n            error_at(tok->loc, "excess elements in union initializer");\n\n        if (equal(tok, ".") || equal(tok, "[")) {\n'''
assert old in s
s = s.replace(old, new, 1)

old = '''            Member *member = path.first_member;\n            Type *target_ty = path.target_ty;\n            int target_offset = apply_static_designator_path(var, ty, offset, &path);\n            reset_static_subobject(var, target_offset, target_ty->size);\n            free_initializer_designator_path(&path);\n'''
new = '''            Member *member = path.first_member;\n            Type *target_ty = path.target_ty;\n            int target_offset = apply_static_designator_path(var, ty, offset, &path);\n            if (ty->is_union && active_union_member && active_union_member != member)\n                reset_static_subobject(var, offset, ty->size);\n            reset_static_subobject(var, target_offset, target_ty->size);\n            if (ty->is_union)\n                active_union_member = member;\n            free_initializer_designator_path(&path);\n'''
assert old in s
s = s.replace(old, new, 1)

# Automatic local aggregate path: allow further designated union initializers.
old = '''            Member *cur_mem = (ty->kind == TY_STRUCT) ? ty->members : NULL;\n            Node *before_init = block_cur;\n            int initialized_union_members = 0;\n'''
new = '''            Member *cur_mem = (ty->kind == TY_STRUCT) ? ty->members : NULL;\n            Member *active_union_member = NULL;\n            Node *before_init = block_cur;\n            int initialized_union_members = 0;\n'''
assert old in s
s = s.replace(old, new, 1)

old = '''                if (ty->kind == TY_STRUCT && ty->is_union && initialized_union_members)\n                    error_at(tok->loc, "excess elements in union initializer");\n\n                // Designated initializer-list. A chain such as\n'''
new = '''                if (ty->kind == TY_STRUCT && ty->is_union &&\n                    initialized_union_members && !equal(tok, "."))\n                    error_at(tok->loc, "excess elements in union initializer");\n\n                // Designated initializer-list. A chain such as\n'''
assert old in s
s = s.replace(old, new, 1)

old = '''                        Member *member = path.first_member;\n                        int mi = record_member_index(ty, member);\n                        if (mi < 0)\n                            error_at(designator->loc, "invalid record initializer member");\n                        was_initialized = member_init[mi];\n                        member_init[mi] = true;\n                        cur_mem = member->next;\n                        if (ty->is_union)\n                            initialized_union_members++;\n'''
new = '''                        Member *member = path.first_member;\n                        int mi = record_member_index(ty, member);\n                        if (mi < 0)\n                            error_at(designator->loc, "invalid record initializer member");\n                        if (ty->is_union && active_union_member != member) {\n                            for (int i = 0; i < member_count; i++)\n                                member_init[i] = false;\n                            was_initialized = false;\n                            Node *top = new_node(ND_MEMBER);\n                            top->lhs = new_var_node(var);\n                            top->member = member;\n                            append_zero_initializer(&block_cur, top, member->ty, brace);\n                            active_union_member = member;\n                        } else {\n                            was_initialized = member_init[mi];\n                        }\n                        member_init[mi] = true;\n                        cur_mem = member->next;\n                        if (ty->is_union)\n                            initialized_union_members++;\n'''
assert old in s
s = s.replace(old, new, 1)

p.write_text(s)

t = Path('test/union_initializers.sh')
s = t.read_text()
old = '''# A union initializer contains at most one initializer element. The previous\n# struct-like implementation silently accepted these and overwrote offset zero.\nassert_fail 'int main(){union U{int x; int y;}; union U u={1,2}; return u.x;}'\nassert_fail 'union U{int x; int y;}; union U u={.x=1,.y=2}; int main(){return 0;}'\nassert_fail 'int main(){union U{int x; int y;}; union U u={.y=1,2}; return 0;}'\nassert_fail 'union U{int x; int y;}; static union U u={1,2}; int main(){return 0;}'\n'''
new = '''# C designated initializers may override an earlier union member selection;\n# the last designated initializer determines the resulting stored value.\nassert_run 2 'int main(){union U{int x; int y;}; union U u={.x=1,.y=2}; return u.y;}'\nassert_run 7 'int main(){union U{int x; int y;}; union U u={.x=3,.x=7}; return u.x;}'\nassert_run 5 'union U{int x; long y;}; union U u={.y=99,.x=5}; int main(){return u.x;}'\nassert_run 8 'int main(){union U{struct {int a; int b;} s; long y;}; union U u={.s.a=3,.s.b=5}; return u.s.a+u.s.b;}'\nassert_run 6 'int main(){union U{struct {int a; int b;} s; long y;}; union U u={.s.a=9,.y=4,.s.b=6}; return u.s.a+u.s.b;}'\n\n# Positional elements after the selected union member remain excess elements.\nassert_fail 'int main(){union U{int x; int y;}; union U u={1,2}; return u.x;}'\nassert_fail 'int main(){union U{int x; int y;}; union U u={.y=1,2}; return 0;}'\nassert_fail 'union U{int x; int y;}; static union U u={1,2}; int main(){return 0;}'\n'''
assert old in s
s = s.replace(old, new, 1)
t.write_text(s)

r = Path('README.md')
s = r.read_text()
old = 'Union types retain their record kind through semantic analysis; automatic/static union initializers select exactly one member (the first by default or a designated member), preserve overlapping storage correctly, and reject excess initializer elements.'
new = 'Union types retain their record kind through semantic analysis; automatic/static union initializers select the first member by default, honor designated-member overrides with last-designator-wins semantics, preserve overlapping storage correctly, and reject excess positional initializer elements.'
assert old in s
r.write_text(s.replace(old, new, 1))
