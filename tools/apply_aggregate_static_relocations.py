from pathlib import Path


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


# ---- minicc.h: a byte image plus arbitrary relocation entries ----
p = Path('minicc.h')
s = p.read_text()
old = '''struct Obj {
'''
new = '''typedef struct Relocation Relocation;
struct Relocation {
    Relocation *next;
    int offset;          // byte offset within the initialized object
    char *label;         // linker symbol
    int64_t addend;      // byte addend applied to the linker symbol
};

struct Obj {
'''
s = replace_once(s, old, new, 'Relocation type')
old = '''    bool has_init_reloc;

    // Global array/struct initializer (list of int64/double values, one per element)
'''
new = '''    bool has_init_reloc;

    // Aggregate static initializer. The zero-filled byte image contains every
    // non-relocatable scalar byte and padding; relocation entries replace the
    // pointer-sized ranges at their offsets during assembly emission.
    char *init_image;
    int init_image_size;
    Relocation *init_relocs;

    // Legacy homogeneous aggregate storage retained for compatibility.
    // New brace-enclosed static aggregates use init_image/init_relocs instead.
    // Global array/struct initializer (list of int64/double values, one per element)
'''
s = replace_once(s, old, new, 'aggregate image fields')
p.write_text(s)


# ---- parse.c: factor scalar address parsing and add recursive image builder ----
p = Path('parse.c')
s = p.read_text()
old = '''static void parse_static_pointer_initializer(Obj *var, Token **rest, Token *tok,
                                             Type *target) {
    Token *start = tok;
    Node *node = assign(&tok, tok);
    add_type(node);

    // Preserve the broader null-pointer-constant rule already supported by
    // static integer initializers: any integer constant expression of value 0.
    if (is_integer(node->ty)) {
        int64_t val = eval_const_expr(node);
        if (val != 0)
            error_at(start->loc, "nonzero integer is not a valid static pointer initializer");
        var->init_val = 0;
        var->has_init_val = true;
        *rest = tok;
        return;
    }

    if (!assignment_compatible(target, node))
        error_at(start->loc, "incompatible static pointer initializer");

    StaticAddress addr = eval_static_address(node);
    if (!addr.label) {
        var->init_val = 0;
        var->has_init_val = true;
    } else {
        var->init_reloc_label = addr.label;
        var->init_reloc_addend = addr.addend;
        var->has_init_reloc = true;
    }
    *rest = tok;
}
'''
new = '''static StaticAddress parse_static_address_initializer(Token **rest, Token *tok,
                                                       Type *target) {
    Token *start = tok;
    Node *node = assign(&tok, tok);
    add_type(node);

    // Any integer constant expression whose value is zero is a null pointer
    // constant. Nonzero integer-to-pointer static initialization remains
    // outside this C subset even when written through an explicit cast.
    if (is_integer(node->ty)) {
        int64_t val = eval_const_expr(node);
        if (val != 0)
            error_at(start->loc, "nonzero integer is not a valid static pointer initializer");
        *rest = tok;
        return (StaticAddress){0};
    }

    if (!assignment_compatible(target, node))
        error_at(start->loc, "incompatible static pointer initializer");

    StaticAddress addr = eval_static_address(node);
    *rest = tok;
    return addr;
}

static void parse_static_pointer_initializer(Obj *var, Token **rest, Token *tok,
                                             Type *target) {
    StaticAddress addr = parse_static_address_initializer(rest, tok, target);
    if (!addr.label) {
        var->init_val = 0;
        var->has_init_val = true;
    } else {
        var->init_reloc_label = addr.label;
        var->init_reloc_addend = addr.addend;
        var->has_init_reloc = true;
    }
}
'''
s = replace_once(s, old, new, 'factor static pointer parser')

anchor = '''static void parse_static_scalar_initializer(Obj *var, Token **rest, Token *tok,
                                            Type *ty) {
    if (is_flonum(ty)) {
        var->finit_val = parse_const_double(rest, tok);
        var->has_init_val = true;
        return;
    }
    if (is_integer(ty)) {
        var->init_val = parse_static_integer_initializer(rest, tok, ty);
        var->has_init_val = true;
        return;
    }
    if (ty->kind == TY_PTR) {
        parse_static_pointer_initializer(var, rest, tok, ty);
        return;
    }
    error_at(tok->loc, "unsupported scalar static initializer type");
}
'''
insert = anchor + r'''

static void ensure_static_image(Obj *var, int size) {
    if (size <= var->init_image_size)
        return;
    int old = var->init_image_size;
    var->init_image = realloc(var->init_image, size);
    memset(var->init_image + old, 0, size - old);
    var->init_image_size = size;
}

static void clear_static_reloc_range(Obj *var, int offset, int size) {
    Relocation head = {};
    Relocation *tail = &head;
    for (Relocation *rel = var->init_relocs; rel;) {
        Relocation *next = rel->next;
        if (rel->offset < offset || rel->offset >= offset + size) {
            tail = tail->next = rel;
            rel->next = NULL;
        } else {
            free(rel);
        }
        rel = next;
    }
    var->init_relocs = head.next;
}

static void reset_static_subobject(Obj *var, int offset, int size) {
    ensure_static_image(var, offset + size);
    memset(var->init_image + offset, 0, size);
    clear_static_reloc_range(var, offset, size);
}

static void add_static_image_reloc(Obj *var, int offset, StaticAddress addr) {
    Relocation *rel = calloc(1, sizeof(Relocation));
    rel->offset = offset;
    rel->label = addr.label;
    rel->addend = addr.addend;
    rel->next = var->init_relocs;
    var->init_relocs = rel;
}

static void write_static_integer_bytes(Obj *var, int offset, Type *ty, int64_t val) {
    ensure_static_image(var, offset + ty->size);
    uint64_t bits = (uint64_t)val;
    for (int i = 0; i < ty->size; i++)
        var->init_image[offset + i] = (char)(bits >> (i * 8));
}

static void parse_static_image_scalar(Obj *var, Token **rest, Token *tok,
                                      Type *ty, int offset) {
    reset_static_subobject(var, offset, ty->size);

    if (is_integer(ty)) {
        int64_t val = parse_static_integer_initializer(rest, tok, ty);
        write_static_integer_bytes(var, offset, ty, val);
        return;
    }

    if (is_flonum(ty)) {
        double val = parse_const_double(rest, tok);
        if (ty->kind == TY_FLOAT) {
            float f = (float)val;
            memcpy(var->init_image + offset, &f, sizeof(f));
        } else {
            memcpy(var->init_image + offset, &val, sizeof(val));
        }
        return;
    }

    if (ty->kind == TY_PTR) {
        StaticAddress addr = parse_static_address_initializer(rest, tok, ty);
        if (addr.label)
            add_static_image_reloc(var, offset, addr);
        return;
    }

    error_at(tok->loc, "unsupported scalar in static aggregate initializer");
}

static Member *find_initializer_member(Type *ty, Token *tok) {
    for (Member *m = ty->members; m; m = m->next)
        if ((int)strlen(m->name) == tok->len &&
            !strncmp(m->name, tok->loc, tok->len))
            return m;
    return NULL;
}

static int parse_static_designator_index(Token **rest, Token *tok) {
    Token *start = tok;
    Node *node = ternary(&tok, tok);
    add_type(node);
    if (!is_integer(node->ty))
        error_at(start->loc, "array designator requires integer constant expression");

    int64_t raw = eval_const_expr(node);
    uint64_t value;
    if (node->ty->is_unsigned)
        value = (uint64_t)cast_const_integer(raw, node->ty);
    else {
        int64_t signed_value = cast_const_integer(raw, node->ty);
        if (signed_value < 0)
            error_at(start->loc, "array designator index is out of range");
        value = (uint64_t)signed_value;
    }
    if (value > INT32_MAX)
        error_at(start->loc, "array designator index is out of range");

    *rest = tok;
    return (int)value;
}

// Build a zero-filled static byte image recursively. Scalar leaves either
// write representation bytes or attach a linker relocation at the leaf's byte
// offset. This naturally preserves record padding and supports nested arrays
// and records without assuming homogeneous element values.
static Type *parse_static_image_initializer(Obj *var, Token **rest, Token *tok,
                                            Type *ty, int offset) {
    if (ty->kind != TY_ARRAY && ty->kind != TY_STRUCT) {
        if (equal(tok, "{")) {
            tok = tok->next;
            parse_static_image_scalar(var, &tok, tok, ty, offset);
            if (equal(tok, ","))
                tok = tok->next;
            *rest = skip(tok, "}");
            return ty;
        }
        parse_static_image_scalar(var, rest, tok, ty, offset);
        return ty;
    }

    Token *brace = tok;
    if (!equal(tok, "{"))
        error_at(tok->loc, "nested static aggregate initializer requires braces");
    tok = tok->next;

    if (ty->kind == TY_ARRAY) {
        if (ty->array_len > 0)
            ensure_static_image(var, offset + ty->size);

        int next_index = 0;
        int max_index = -1;
        while (!equal(tok, "}")) {
            if (equal(tok, ",")) {
                tok = tok->next;
                if (equal(tok, "}"))
                    break;
            }

            int index = next_index;
            if (consume(&tok, tok, "[")) {
                index = parse_static_designator_index(&tok, tok);
                tok = skip(tok, "]");
                tok = skip(tok, "=");
            }

            if (ty->array_len > 0 && index >= ty->array_len)
                error_at(tok->loc, "array designator or element exceeds array bounds");

            int elem_offset = offset + index * ty->base->size;
            reset_static_subobject(var, elem_offset, ty->base->size);
            Type *elem_ty = parse_static_image_initializer(var, &tok, tok,
                                                           ty->base, elem_offset);
            if (elem_ty != ty->base)
                error_at(brace->loc, "nested incomplete arrays are not supported");

            if (index > max_index)
                max_index = index;
            next_index = index + 1;
        }
        tok = skip(tok, "}");

        if (ty->array_len == 0) {
            if (max_index < 0)
                error_at(brace->loc, "cannot infer array size from empty initializer");
            ty = array_of(ty->base, max_index + 1);
        }
        ensure_static_image(var, offset + ty->size);
        *rest = tok;
        return ty;
    }

    ensure_static_image(var, offset + ty->size);
    Member *next_member = ty->members;
    while (!equal(tok, "}")) {
        if (equal(tok, ",")) {
            tok = tok->next;
            if (equal(tok, "}"))
                break;
        }

        Member *member = next_member;
        if (consume(&tok, tok, ".")) {
            if (tok->kind != TK_IDENT)
                error_at(tok->loc, "expected member name in designated initializer");
            member = find_initializer_member(ty, tok);
            if (!member)
                error_at(tok->loc, "unknown member in designated initializer");
            tok = skip(tok->next, "=");
        } else if (!member) {
            error_at(tok->loc, "excess elements in record initializer");
        }

        reset_static_subobject(var, offset + member->offset, member->ty->size);
        Type *member_ty = parse_static_image_initializer(var, &tok, tok,
                                                         member->ty,
                                                         offset + member->offset);
        if (member_ty != member->ty)
            error_at(brace->loc, "incomplete array record members are not supported");
        next_member = member->next;
    }

    *rest = skip(tok, "}");
    return ty;
}
'''
s = replace_once(s, anchor, insert, 'static image helpers')

# Local static brace initializers now share the recursive byte-image parser.
old = '''        // Static/extern: constant initializer only
        if (is_static || is_extern) {
            if (equal(tok, "{")) {
                tok = tok->next;
                int cap = 16, cnt = 0;
                int64_t *vals = calloc(cap, sizeof(int64_t));
                while (!equal(tok, "}")) {
                    if (cnt > 0) tok = skip(tok, ",");
                    if (equal(tok, "}")) break;
                    if (ty->kind == TY_ARRAY && ty->array_len > 0 && cnt >= ty->array_len)
                        error_at(tok->loc, "excess elements in array initializer");
                    if (cnt >= cap) { cap *= 2; vals = realloc(vals, cap * sizeof(int64_t)); }
                    Type *elem_ty = (ty->kind == TY_ARRAY) ? ty->base : NULL;
                    vals[cnt++] = parse_static_integer_initializer(&tok, tok, elem_ty);
                }
                tok = skip(tok, "}");
                if (ty->kind == TY_ARRAY && ty->array_len == 0) {
                    ty = array_of(ty->base, cnt);
                    var->ty = ty;
                }
                var->init_vals = vals;
                var->init_vals_count = cnt;
            } else {
                parse_static_scalar_initializer(var, &tok, tok, ty);
            }
            continue;
        }
'''
new = '''        // Static/extern: constant initializer only. Brace-enclosed
        // aggregates use a byte image plus per-offset linker relocations.
        if (is_static || is_extern) {
            if (equal(tok, "{")) {
                ty = parse_static_image_initializer(var, &tok, tok, ty, 0);
                var->ty = ty;
            } else {
                parse_static_scalar_initializer(var, &tok, tok, ty);
            }
            continue;
        }
'''
s = replace_once(s, old, new, 'local static aggregate branch')

old = '''static bool object_has_initializer(Obj *var) {
    return var->has_init_val || var->has_init_reloc ||
           var->init_vals_count > 0 || var->init_data;
}
'''
new = '''static bool object_has_initializer(Obj *var) {
    return var->has_init_val || var->has_init_reloc || var->init_image ||
           var->init_vals_count > 0 || var->init_data;
}
'''
s = replace_once(s, old, new, 'object_has_initializer image')

# File-scope aggregate branch uses the same recursive parser.
old = '''                    } else if (equal(tok, "{")) {
                        tok = tok->next;
                        int cap = 16, cnt = 0;
                        int64_t *vals = calloc(cap, sizeof(int64_t));
                        while (!equal(tok, "}")) {
                            if (cnt > 0) tok = skip(tok, ",");
                            if (equal(tok, "}")) break;
                            if (cnt >= cap) { cap *= 2; vals = realloc(vals, cap * sizeof(int64_t)); }
                            Type *elem_ty = (ty->kind == TY_ARRAY) ? ty->base : NULL;
                    vals[cnt++] = parse_static_integer_initializer(&tok, tok, elem_ty);
                        }
                        tok = skip(tok, "}");

                        if (ty->kind == TY_ARRAY && ty->array_len == 0) {
                            ty = array_of(ty->base, cnt);
                            var->ty = ty;
                        }

                        var->init_vals = vals;
                        var->init_vals_count = cnt;
                    } else {
'''
new = '''                    } else if (equal(tok, "{")) {
                        ty = parse_static_image_initializer(var, &tok, tok, ty, 0);
                        var->ty = ty;
                    } else {
'''
s = replace_once(s, old, new, 'global static aggregate branch')
p.write_text(s)


# ---- codegen.c: interleave raw image bytes with .quad relocations ----
p = Path('codegen.c')
s = p.read_text()
old = '''        if (var->init_data) {
'''
new = '''        if (var->init_image) {
            printf("  .data\\n");
            if (!var->is_static)
                printf("  .globl %s\\n", var->name);
            printf("%s:\\n", var->name);

            for (int off = 0; off < var->init_image_size;) {
                Relocation *found = NULL;
                for (Relocation *rel = var->init_relocs; rel; rel = rel->next) {
                    if (rel->offset == off) {
                        found = rel;
                        break;
                    }
                }

                if (found) {
                    if (found->addend > 0)
                        printf("  .quad %s+%" PRId64 "\\n", found->label, found->addend);
                    else if (found->addend < 0)
                        printf("  .quad %s%" PRId64 "\\n", found->label, found->addend);
                    else
                        printf("  .quad %s\\n", found->label);
                    off += 8;
                    continue;
                }

                printf("  .byte %u\\n", (unsigned char)var->init_image[off]);
                off++;
            }
            if (var->init_image_size < var->ty->size)
                printf("  .zero %d\\n", var->ty->size - var->init_image_size);
        } else if (var->init_data) {
'''
s = replace_once(s, old, new, 'emit aggregate static image')
p.write_text(s)


# ---- regression tests ----
p = Path('test/aggregate_static_relocations.sh')
p.write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-aggregate-static.c
  ./minicc tmp-aggregate-static.c > tmp-aggregate-static.s
  cc -o tmp-aggregate-static tmp-aggregate-static.s
  set +e
  ./tmp-aggregate-static
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "aggregate static relocation failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(aggregate static relocation): $actual"
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-aggregate-static.c
  if ./minicc tmp-aggregate-static.c > /dev/null 2>&1; then
    echo 'aggregate static relocation unexpectedly accepted invalid program'
    echo "$input"
    exit 1
  fi
  echo 'OK(aggregate static relocation): rejected invalid initializer'
}

assert_run 0 'int a=3,b=5; int *p[]={&a,&b}; int main(){return sizeof(p)==16&&*p[0]==3&&*p[1]==5?0:1;}'
assert_run 0 'int a[4]={2,4,6,8}; int *p[]={a,a+3}; int main(){return *p[0]==2&&*p[1]==8?0:1;}'
assert_run 0 'int x=7; int *p[4]={[2]=&x}; int main(){return p[0]==0&&p[1]==0&&p[2]==&x&&p[3]==0?0:1;}'
assert_run 0 'int x=9; int *p[]={[1+1]=&x}; int main(){return sizeof(p)==24&&p[0]==0&&p[1]==0&&p[2]==&x?0:1;}'
assert_run 0 'int f(){return 13;} int g(){return 17;} int (*fp[])(void)={f,g}; int main(){return fp[0]()==13&&fp[1]()==17?0:1;}'
assert_run 0 'char *words[]={"ab","xyz"+1}; int main(){return words[0][1]==98&&words[1][0]==121?0:1;}'
assert_run 0 'int x=11; struct C{int *p;int value;}; struct C c={&x,31}; int main(){return c.p==&x&&*c.p==11&&c.value==31?0:1;}'
assert_run 0 'int x=12; struct C{char tag;int *p;short value;}; struct C c={65,&x,123}; int main(){return c.tag==65&&c.p==&x&&c.value==123?0:1;}'
assert_run 0 'int x=14; struct C{int *p;int value;}; struct C c={.value=7,.p=&x}; int main(){return *c.p==14&&c.value==7?0:1;}'
assert_run 0 'struct C{int value;int *p;}; struct C c={.value=5}; int main(){return c.value==5&&c.p==0?0:1;}'
assert_run 0 'int x=21; struct I{int *p;int n;}; struct O{struct I inner;int *q;}; struct O o={{&x,4},&x}; int main(){return *o.inner.p==21&&o.inner.n==4&&o.q==&x?0:1;}'
assert_run 0 'int a=6,b=8; struct S{int *p[2];int n;}; struct S s={{&a,&b},3}; int main(){return *s.p[0]+*s.p[1]+s.n==17?0:1;}'
assert_run 0 'int x=23; int f(){static int *p[]={&x,0};return p[0]==&x&&p[1]==0;} int main(){return f()?0:1;}'
assert_run 0 'int x=27; int f(){static struct C{int *p;int n;} c={&x,2};return *c.p+c.n;} int main(){return f()==29?0:1;}'
assert_run 0 'struct S{char c;double d;int n;}; struct S s={65,2.5,7}; int main(){return s.c==65&&s.d>2.4&&s.d<2.6&&s.n==7?0:1;}'

# External object relocations inside one aggregate are resolved by the host linker.
printf '%s\n' 'extern int host_a,host_b; int *p[]={&host_a,&host_b}; int main(){return *p[0]==31&&*p[1]==37?0:1;}' > tmp-aggregate-static.c
./minicc tmp-aggregate-static.c > tmp-aggregate-static.s
printf '%s\n' 'int host_a=31; int host_b=37;' > tmp-aggregate-static-helper.c
cc -c -o tmp-aggregate-static-helper.o tmp-aggregate-static-helper.c
cc -o tmp-aggregate-static tmp-aggregate-static.s tmp-aggregate-static-helper.o
./tmp-aggregate-static

# External function relocation embedded in a struct is likewise link-resolved.
printf '%s\n' 'extern int host_fn(void); struct C{int (*f)(void);int n;}; struct C c={host_fn,5}; int main(){return c.f()==41&&c.n==5?0:1;}' > tmp-aggregate-static.c
./minicc tmp-aggregate-static.c > tmp-aggregate-static.s
printf '%s\n' 'int host_fn(void){return 41;}' > tmp-aggregate-static-helper.c
cc -c -o tmp-aggregate-static-helper.o tmp-aggregate-static-helper.c
cc -o tmp-aggregate-static tmp-aggregate-static.s tmp-aggregate-static-helper.o
./tmp-aggregate-static

assert_reject 'int f(){int x;static int *p[]={&x};return 0;} int main(){return f();}'
assert_reject 'int x; double *p[]={&x}; int main(){return 0;}'
assert_reject 'int n=3; int a[]={n}; int main(){return 0;}'
assert_reject 'int *p[1]={0,0}; int main(){return 0;}'
assert_reject 'int x; int *p[1]={[2]=&x}; int main(){return 0;}'
assert_reject 'struct C{int x;}; struct C c={.missing=1}; int main(){return 0;}'
assert_reject 'struct C{int x;}; struct C c={1,2}; int main(){return 0;}'

rm -f tmp-aggregate-static.c tmp-aggregate-static.s tmp-aggregate-static \
      tmp-aggregate-static-helper.c tmp-aggregate-static-helper.o

echo 'All aggregate static relocation tests passed!'
''')

p = Path('Makefile')
s = p.read_text()
anchor = '\tbash ./test/static_address_initializers.sh\n'
s = replace_once(s, anchor, anchor + '\tbash ./test/aggregate_static_relocations.sh\n', 'Makefile aggregate relocation test hook')
p.write_text(s)

p = Path('README.md')
s = p.read_text()
line = '- Static aggregate initializers use zero-filled byte images plus per-offset linker relocations, supporting pointer/function/string addresses inside arrays and records, nested aggregates, designators, and record padding.\n'
if line not in s:
    s += '\n' + line
p.write_text(s)
