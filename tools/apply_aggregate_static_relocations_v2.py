from pathlib import Path


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


# ---- minicc.h: byte image + relocation entries ----
p = Path('minicc.h')
s = p.read_text()
s = replace_once(s, 'struct Obj {\n', '''typedef struct Relocation Relocation;
struct Relocation {
    Relocation *next;
    int offset;
    char *label;
    int64_t addend;
};

struct Obj {
''', 'Relocation type')
s = replace_once(s, '''    bool has_init_reloc;

    // Global array/struct initializer (list of int64/double values, one per element)
''', '''    bool has_init_reloc;

    // Typed aggregate static initializer. The image is zero-filled and stores
    // all ordinary bytes/padding; relocations replace pointer-sized ranges.
    char *init_image;
    int init_image_size;
    Relocation *init_relocs;

    // Legacy homogeneous aggregate storage retained for compatibility.
    // Global array/struct initializer (list of int64/double values, one per element)
''', 'aggregate image fields')
p.write_text(s)


# ---- parse.c ----
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

# Insert the generic image builder immediately before declaration parsing, after
# PR #40's shared parse_array_designator_index helper is already defined.
anchor = '''// declaration = declspec (declarator ("=" (expr | "{" initializer "}"))?)
//               ("," declarator ("=" (expr | "{" initializer "}"))?)* ";"
'''
helpers = r'''static void ensure_static_image(Obj *var, int size) {
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

static Member *find_static_initializer_member(Type *ty, Token *tok) {
    for (Member *m = ty->members; m; m = m->next)
        if ((int)strlen(m->name) == tok->len &&
            !strncmp(m->name, tok->loc, tok->len))
            return m;
    return NULL;
}

static Type *parse_static_image_initializer(Obj *var, Token **rest, Token *tok,
                                            Type *ty, int offset) {
    if (ty->kind != TY_ARRAY && ty->kind != TY_STRUCT) {
        if (equal(tok, "{")) {
            Token *brace = tok;
            tok = tok->next;
            if (equal(tok, "}"))
                error_at(brace->loc, "empty scalar initializer");
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
        bool first = true;
        while (!equal(tok, "}")) {
            if (!first) {
                tok = skip(tok, ",");
                if (equal(tok, "}"))
                    break;
            }
            first = false;

            if (equal(tok, "."))
                error_at(tok->loc, "member designator requires a record initializer");

            int index = next_index;
            if (equal(tok, "[")) {
                Token *designator = tok;
                tok = tok->next;
                index = parse_array_designator_index(&tok, tok, designator);
                tok = skip(tok, "]");
                tok = skip(tok, "=");
            }

            if (ty->array_len > 0 && index >= ty->array_len)
                error_at(tok->loc, "array designator index exceeds array bounds");

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
    bool first = true;
    while (!equal(tok, "}")) {
        if (!first) {
            tok = skip(tok, ",");
            if (equal(tok, "}"))
                break;
        }
        first = false;

        if (equal(tok, "["))
            error_at(tok->loc, "array designator requires an array initializer");

        Member *member = next_member;
        if (consume(&tok, tok, ".")) {
            if (tok->kind != TK_IDENT)
                error_at(tok->loc, "expected member name in designated initializer");
            member = find_static_initializer_member(ty, tok);
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
s = replace_once(s, anchor, helpers + anchor, 'insert static image builder')

# Route local static brace initialization through the generic builder instead of
# PR #40's integer-array-only serializer / record rejection path.
old = '''        // Static/extern: constant initializer only. Integer arrays share the
        // file-scope designated-initializer parser so block/static and global
        // objects cannot drift in their [constant-expression] semantics.
        if (is_static || is_extern) {
            if (equal(tok, "{")) {
                Token *brace = tok;

                // The historical fallback serialized record members as packed
                // 4-byte integers, ignoring real member offsets/padding. Refuse
                // that miscompile until typed static-record serialization lands.
                if (ty->kind == TY_STRUCT)
                    error_at(brace->loc, "static record brace initializers are not yet supported");

                if (ty->kind == TY_ARRAY) {
                    parse_static_integer_array_initializer(var, &ty, &tok, tok);
                    continue;
                }

                // Preserve scalar brace initialization as a single scalar
                // constant with an optional trailing comma.
                tok = tok->next;
                if (equal(tok, "}"))
                    error_at(brace->loc, "empty scalar initializer");
                parse_static_scalar_initializer(var, &tok, tok, ty);
                if (equal(tok, ","))
                    tok = tok->next;
                tok = skip(tok, "}");
                continue;
            }

            parse_static_scalar_initializer(var, &tok, tok, ty);
            continue;
        }
'''
new = '''        // Static/extern: constant initializer only. Brace-enclosed objects
        // use typed byte images plus linker relocations, sharing PR #40's
        // integer-constant-expression array designator parser.
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
s = replace_once(s, old, new, 'local static aggregate branch v2')

s = replace_once(s, '''static bool object_has_initializer(Obj *var) {
    return var->has_init_val || var->has_init_reloc ||
           var->init_vals_count > 0 || var->init_data;
}
''', '''static bool object_has_initializer(Obj *var) {
    return var->has_init_val || var->has_init_reloc || var->init_image ||
           var->init_vals_count > 0 || var->init_data;
}
''', 'object_has_initializer image')

old = '''                    } else if (equal(tok, "{")) {
                        Token *brace = tok;

                        // Do not silently serialize padded records as a dense
                        // list of .long values. Typed static-record data is a
                        // separate feature and should fail clearly for now.
                        if (ty->kind == TY_STRUCT)
                            error_at(brace->loc, "static record brace initializers are not yet supported");

                        if (ty->kind == TY_ARRAY) {
                            parse_static_integer_array_initializer(var, &ty, &tok, tok);
                        } else {
                            tok = tok->next;
                            if (equal(tok, "}"))
                                error_at(brace->loc, "empty scalar initializer");
                            parse_static_scalar_initializer(var, &tok, tok, ty);
                            if (equal(tok, ","))
                                tok = tok->next;
                            tok = skip(tok, "}");
                        }
                    } else {
'''
new = '''                    } else if (equal(tok, "{")) {
                        ty = parse_static_image_initializer(var, &tok, tok, ty, 0);
                        var->ty = ty;
                    } else {
'''
s = replace_once(s, old, new, 'global static aggregate branch v2')
p.write_text(s)


# ---- codegen.c ----
p = Path('codegen.c')
s = p.read_text()
s = replace_once(s, '''        if (var->init_data) {
''', '''        if (var->init_image) {
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
''', 'emit aggregate static image')
p.write_text(s)


# ---- focused regression coverage ----
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
assert_run 0 'enum{I=2}; int x=9; int *p[]={[I]=&x}; int main(){return sizeof(p)==24&&p[0]==0&&p[1]==0&&p[2]==&x?0:1;}'
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
assert_run 0 'int a[4]={[2]=7,[0]=3}; int main(){return a[0]==3&&a[1]==0&&a[2]==7&&a[3]==0?0:1;}'

printf '%s\n' 'extern int host_a,host_b; int *p[]={&host_a,&host_b}; int main(){return *p[0]==31&&*p[1]==37?0:1;}' > tmp-aggregate-static.c
./minicc tmp-aggregate-static.c > tmp-aggregate-static.s
printf '%s\n' 'int host_a=31; int host_b=37;' > tmp-aggregate-static-helper.c
cc -c -o tmp-aggregate-static-helper.o tmp-aggregate-static-helper.c
cc -o tmp-aggregate-static tmp-aggregate-static.s tmp-aggregate-static-helper.o
./tmp-aggregate-static

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
s = replace_once(s, '\tbash ./test/static_address_initializers.sh\n', '\tbash ./test/static_address_initializers.sh\n\tbash ./test/aggregate_static_relocations.sh\n', 'Makefile test hook')
p.write_text(s)

p = Path('README.md')
s = p.read_text()
line = '- Static aggregate initializers use zero-filled byte images plus per-offset linker relocations, supporting pointer/function/string addresses inside arrays and records, nested aggregates, designators, and record padding.\n'
if line not in s:
    s += '\n' + line
p.write_text(s)
