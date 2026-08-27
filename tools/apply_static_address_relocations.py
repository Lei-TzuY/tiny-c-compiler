from pathlib import Path


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)

# Obj relocation metadata.
p = Path('minicc.h')
s = p.read_text()
old = '''    int64_t init_val;    // for initialized global scalars
    double finit_val;    // for initialized double/float global scalars
    bool has_init_val;
'''
new = '''    int64_t init_val;    // for initialized global scalars
    double finit_val;    // for initialized double/float global scalars
    bool has_init_val;
    char *init_reloc_label;   // static address constant relocation target
    int64_t init_reloc_addend; // byte addend applied to relocation target
    bool has_init_reloc;
'''
s = replace_once(s, old, new, 'Obj relocation fields')
p.write_text(s)

# Parser: evaluate linker-relocatable static address constants.
p = Path('parse.c')
s = p.read_text()
anchor = '''static double parse_const_double(Token **rest, Token *tok) {
    bool neg = consume(&tok, tok, "-");
    bool pos = false;
    if (!neg) pos = consume(&tok, tok, "+");
    (void)pos;
    if (tok->kind != TK_NUM)
        error_at(tok->loc, "expected numeric constant");
    double val = tok->is_float ? tok->fval
        : (tok->ty && tok->ty->is_unsigned ? (double)(uint64_t)tok->val
                                            : (double)tok->val);
    if (neg) val = -val;
    *rest = tok->next;
    return val;
}
'''
insert = anchor + r'''

typedef struct {
    char *label;
    int64_t addend;
} StaticAddress;

static StaticAddress eval_static_address(Node *node);

static StaticAddress eval_static_lvalue_address(Node *node) {
    add_type(node);

    switch (node->kind) {
    case ND_VAR:
        if (node->var->is_local)
            error("address of automatic object is not a static address constant");
        return (StaticAddress){node->var->name, 0};
    case ND_DEREF:
        // &*p is the value of p, subject to static-address constraints.
        return eval_static_address(node->lhs);
    case ND_MEMBER: {
        StaticAddress addr = eval_static_lvalue_address(node->lhs);
        addr.addend += node->member->offset;
        return addr;
    }
    default:
        error("unsupported lvalue in static address initializer");
    }
}

static StaticAddress eval_static_address(Node *node) {
    add_type(node);

    // Integer constant-expression zero is the null pointer constant case.
    if (is_integer(node->ty)) {
        int64_t val = eval_const_expr(node);
        if (val != 0)
            error("nonzero integer is not a valid static pointer initializer");
        return (StaticAddress){0};
    }

    switch (node->kind) {
    case ND_VAR:
        // Array and function designators decay to their link-time addresses.
        // Reading the value of an ordinary pointer object is not a constant.
        if (node->var->is_local)
            error("automatic object is not a static address constant");
        if (node->ty->kind != TY_ARRAY && node->ty->kind != TY_FUNC)
            error("object value is not a static address constant");
        return (StaticAddress){node->var->name, 0};

    case ND_ADDR:
        return eval_static_lvalue_address(node->lhs);

    case ND_ADD:
    case ND_SUB: {
        add_type(node->lhs);
        add_type(node->rhs);
        StaticAddress addr = eval_static_address(node->lhs);
        int64_t delta = eval_const_expr(node->rhs);
        addr.addend += node->kind == ND_ADD ? delta : -delta;
        return addr;
    }

    case ND_CAST:
        // Pointer-preserving casts are link-time no-ops. Casts of integer zero
        // reach the integer branch above when recursively evaluated.
        return eval_static_address(node->lhs);

    case ND_TERNARY:
        return eval_static_address(eval_const_expr(node->cond) ? node->then : node->els);

    default:
        error("not a static address constant");
    }
}

static void parse_static_pointer_initializer(Obj *var, Token **rest, Token *tok,
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

static void parse_static_scalar_initializer(Obj *var, Token **rest, Token *tok,
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
s = replace_once(s, anchor, insert, 'static address helpers')

# Static local pointer-to-string must fall through to scalar expression parsing.
old = '''        if (string_tok && (is_static || is_extern))
            error_at(string_tok->loc,
                     "static string initializer is supported only for character arrays");

'''
s = replace_once(s, old, '', 'local static string restriction')

# Replace the local static scalar branch with the shared helper.
old = '''            } else {
                if (is_flonum(ty)) {
                    var->finit_val = parse_const_double(&tok, tok);
                } else if (is_integer(ty) || ty->kind == TY_PTR) {
                    var->init_val = parse_static_integer_initializer(&tok, tok, ty);
                } else {
                    error_at(tok->loc, "unsupported scalar static initializer type");
                }
                var->has_init_val = true;
            }
            continue;
'''
new = '''            } else {
                parse_static_scalar_initializer(var, &tok, tok, ty);
            }
            continue;
'''
s = replace_once(s, old, new, 'local static scalar initializer')

# Global string literals only take the character-array special path when the
# destination itself is an array. Pointer destinations are ordinary expressions.
old = '''                    if (string_tok) {
                        if (!is_character_array(ty))
                            error_at(string_tok->loc,
                                     "global string initializer is supported only for character arrays");
                        prepare_string_array_type(var, &ty, string_tok);
                        var->init_data = build_string_array_image(ty, string_tok);
                        tok = after_string;
                    } else if (equal(tok, "{")) {
'''
new = '''                    if (string_tok && ty->kind == TY_ARRAY) {
                        if (!is_character_array(ty))
                            error_at(string_tok->loc,
                                     "global string initializer is supported only for character arrays");
                        prepare_string_array_type(var, &ty, string_tok);
                        var->init_data = build_string_array_image(ty, string_tok);
                        tok = after_string;
                    } else if (equal(tok, "{")) {
'''
s = replace_once(s, old, new, 'global string pointer fallthrough')

# Replace the file-scope scalar branch with the shared helper.
old = '''                    } else {
                        if (is_flonum(ty)) {
                            var->finit_val = parse_const_double(&tok, tok);
                        } else if (is_integer(ty) || ty->kind == TY_PTR) {
                            var->init_val = parse_static_integer_initializer(&tok, tok, ty);
                        } else {
                            error_at(tok->loc, "unsupported scalar static initializer type");
                        }
                        var->has_init_val = true;
                    }
'''
new = '''                    } else {
                        parse_static_scalar_initializer(var, &tok, tok, ty);
                    }
'''
s = replace_once(s, old, new, 'global scalar initializer')

# Relocations count as initializers for duplicate-definition checking.
old = '''static bool object_has_initializer(Obj *var) {
    return var->has_init_val || var->init_vals_count > 0 || var->init_data;
}
'''
new = '''static bool object_has_initializer(Obj *var) {
    return var->has_init_val || var->has_init_reloc ||
           var->init_vals_count > 0 || var->init_data;
}
'''
s = replace_once(s, old, new, 'object_has_initializer')
p.write_text(s)

# Codegen: emit an assembler/linker relocation rather than baking an address.
p = Path('codegen.c')
s = p.read_text()
old = '''        } else if (var->has_init_val) {
            printf("  .data\\n");
            if (!var->is_static)
                printf("  .globl %s\\n", var->name);
            printf("%s:\\n", var->name);
            if (var->ty->kind == TY_FLOAT) {
'''
new = '''        } else if (var->has_init_reloc) {
            printf("  .data\\n");
            if (!var->is_static)
                printf("  .globl %s\\n", var->name);
            printf("%s:\\n", var->name);
            if (var->init_reloc_addend > 0)
                printf("  .quad %s+%" PRId64 "\\n", var->init_reloc_label,
                       var->init_reloc_addend);
            else if (var->init_reloc_addend < 0)
                printf("  .quad %s%" PRId64 "\\n", var->init_reloc_label,
                       var->init_reloc_addend);
            else
                printf("  .quad %s\\n", var->init_reloc_label);
        } else if (var->has_init_val) {
            printf("  .data\\n");
            if (!var->is_static)
                printf("  .globl %s\\n", var->name);
            printf("%s:\\n", var->name);
            if (var->ty->kind == TY_FLOAT) {
'''
s = replace_once(s, old, new, 'codegen relocation emission')
p.write_text(s)

# Focused end-to-end regression coverage.
p = Path('test/static_address_initializers.sh')
p.write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-static-address.c
  ./minicc tmp-static-address.c > tmp-static-address.s
  cc -o tmp-static-address tmp-static-address.s
  set +e
  ./tmp-static-address
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "static address initializer test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(static address): $actual"
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-static-address.c
  if ./minicc tmp-static-address.c > /dev/null 2>&1; then
    echo 'static address initializer test should have been rejected'
    echo "$input"
    exit 1
  fi
  echo 'OK(static address): rejected invalid initializer'
}

assert_run 0 'int g=17; int *p=&g; int main(){return *p==17?0:1;}'
assert_run 0 'int a[4]={3,5,7,9}; int *p=a+2; int main(){return p==&a[2]&&*p==7?0:1;}'
assert_run 0 'int a[4]; int *p=&a[3]; int main(){return p-a==3?0:1;}'
assert_run 0 'struct S{int a;int b;}; struct S s; int *p=&s.b; int main(){s.b=41;return *p==41?0:1;}'
assert_run 0 'char *p="hello"; int main(){return p[1]==101?0:1;}'
assert_run 0 'char *p="hello"+2; int main(){return p[0]==108&&p[2]==111?0:1;}'
assert_run 0 'int f(){return 23;} int (*fp)(void)=f; int main(){return fp()==23?0:1;}'
assert_run 0 'int f(){return 29;} int (*fp)(void)=&f; int main(){return fp()==29?0:1;}'
assert_run 0 'int g; int *p=1?&g:0; int main(){return p==&g?0:1;}'
assert_run 0 'int g; int *p=0?&g:0; int main(){return p==0?0:1;}'
assert_run 0 'int g; void *p=(void*)&g; int main(){return p==&g?0:1;}'
assert_run 0 'int g=8; int f(){static int *p=&g;return *p;} int main(){return f()==8?0:1;}'
assert_run 0 'int f(){static int x=9;static int *p=&x;return *p;} int main(){return f()==9?0:1;}'

# External object relocation resolves through the host linker.
printf '%s\n' 'extern int host_global; int *p=&host_global; int main(){return *p==31?0:1;}' > tmp-static-address.c
./minicc tmp-static-address.c > tmp-static-address.s
printf '%s\n' 'int host_global=31;' > tmp-static-address-helper.c
cc -c -o tmp-static-address-helper.o tmp-static-address-helper.c
cc -o tmp-static-address tmp-static-address.s tmp-static-address-helper.o
./tmp-static-address

# External function relocation resolves through the host linker.
printf '%s\n' 'extern int host_fn(void); int (*fp)(void)=host_fn; int main(){return fp()==19?0:1;}' > tmp-static-address.c
./minicc tmp-static-address.c > tmp-static-address.s
printf '%s\n' 'int host_fn(void){return 19;}' > tmp-static-address-helper.c
cc -c -o tmp-static-address-helper.o tmp-static-address-helper.c
cc -o tmp-static-address tmp-static-address.s tmp-static-address-helper.o
./tmp-static-address

assert_reject 'int f(){int x;static int *p=&x;return 0;} int main(){return f();}'
assert_reject 'int g; double *p=&g; int main(){return 0;}'
assert_reject 'int *p=(int*)123; int main(){return 0;}'
assert_reject 'int g; int n=1; int *p=&g+n; int main(){return 0;}'
assert_reject 'int *q; int *p=q; int main(){return 0;}'
assert_reject 'int g; int *p=(&g,&g); int main(){return 0;}'

rm -f tmp-static-address.c tmp-static-address.s tmp-static-address \
      tmp-static-address-helper.c tmp-static-address-helper.o

echo 'All static address initializer tests passed!'
''')

p = Path('Makefile')
s = p.read_text()
anchor = '\tbash ./test/static_integer_initializers.sh\n'
s = replace_once(s, anchor, anchor + '\tbash ./test/static_address_initializers.sh\n', 'Makefile test hook')
p.write_text(s)

p = Path('README.md')
s = p.read_text()
line = '- Static pointer initializers support linker-relocatable address constants such as global/object addresses, array offsets, function addresses, member addresses, and string literals.\n'
if line not in s:
    s += '\n' + line
p.write_text(s)
