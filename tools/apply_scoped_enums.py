from pathlib import Path

p = Path("parse.c")
s = p.read_text()

repls = [
(
'''struct Scope {
    Scope *parent;
    VarScope *vars;
    StructTag *tags;
    TypeDef *typedefs;
};
''',
'''struct Scope {
    Scope *parent;
    VarScope *vars;
    StructTag *tags;
    TypeDef *typedefs;
    EnumConst *enum_consts;
};
''',
"scope enum constants"),
(
'''static void push_typedef(Token *ident, Type *ty) {
    TypeDef *td = calloc(1, sizeof(TypeDef));
    td->name = strndup(ident->loc, ident->len);
    td->ty = ty;
    td->next = current_scope->typedefs;
    current_scope->typedefs = td;
}

// ---- End Block Scope ----
''',
'''static void push_typedef(Token *ident, Type *ty) {
    TypeDef *td = calloc(1, sizeof(TypeDef));
    td->name = strndup(ident->loc, ident->len);
    td->ty = ty;
    td->next = current_scope->typedefs;
    current_scope->typedefs = td;
}

// Enumeration constants share C's ordinary identifier namespace with
// variables and typedef names. A nearer variable/typedef therefore hides an
// outer enumerator, while an enumerator in the current scope hides outer names.
static EnumConst *find_enum_const(Token *tok) {
    for (Scope *scope = current_scope; scope; scope = scope->parent) {
        for (VarScope *vs = scope->vars; vs; vs = vs->next)
            if (token_matches_name(tok, vs->name))
                return NULL;
        for (TypeDef *td = scope->typedefs; td; td = td->next)
            if (token_matches_name(tok, td->name))
                return NULL;
        for (EnumConst *ec = scope->enum_consts; ec; ec = ec->next)
            if (token_matches_name(tok, ec->name))
                return ec;
    }
    return NULL;
}

static void push_enum_const(char *name, int64_t val) {
    EnumConst *ec = calloc(1, sizeof(EnumConst));
    ec->name = name;
    ec->val = val;
    ec->next = current_scope->enum_consts;
    current_scope->enum_consts = ec;
}

// ---- End Block Scope ----
''',
"enum scope helpers"),
(
'''static Obj *locals;
static Obj *globals;
static EnumConst *enum_consts;
''',
'''static Obj *locals;
static Obj *globals;
''',
"remove global enum list"),
(
'''                    EnumConst *ec = calloc(1, sizeof(EnumConst));
                    ec->name = name;
                    ec->val = val++;
                    ec->next = enum_consts;
                    enum_consts = ec;
''',
'''                    push_enum_const(name, val++);
''',
"enum insertion"),
(
'''    if (tok->kind == TK_IDENT) {
        // Check for enum constant
        for (EnumConst *ec = enum_consts; ec; ec = ec->next) {
            if (strlen(ec->name) == (size_t)tok->len &&
                !strncmp(tok->loc, ec->name, tok->len)) {
                *rest = tok->next;
                return new_num(ec->val);
            }
        }

        // Function call
''',
'''    if (tok->kind == TK_IDENT) {
        // Check for an enumeration constant visible in lexical scope.
        EnumConst *ec = find_enum_const(tok);
        if (ec) {
            *rest = tok->next;
            return new_num(ec->val);
        }

        // Function call
''',
"enum primary lookup"),
]

for old, new, label in repls:
    if old not in s:
        raise SystemExit(f"expected parser block not found: {label}")
    s = s.replace(old, new, 1)

p.write_text(s)

make = Path("Makefile")
m = make.read_text()
needle = '\tbash ./test/typedef_scope.sh\n'
if needle not in m:
    raise SystemExit("Makefile typedef-scope line not found")
if '\tbash ./test/enum_scope.sh\n' not in m:
    m = m.replace(needle, needle + '\tbash ./test/enum_scope.sh\n', 1)
make.write_text(m)

Path("test/enum_scope.sh").write_text(r'''#!/bin/bash
set -e

assert_enum() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-enum.c
  "${MINICC:-./minicc}" tmp-enum.c > tmp-enum.s
  gcc -o tmp-enum tmp-enum.s
  set +e
  ./tmp-enum
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(enum scope): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(enum scope): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-enum-reject.c
  if "${MINICC:-./minicc}" tmp-enum-reject.c > /dev/null 2>&1; then
    echo "FAIL(enum scope): expected rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(enum scope): rejected out-of-scope enumerator"
}

assert_enum 3 'enum { A=3 }; int main() { return A; }'
assert_enum 3 'enum { A=3 }; int main() { { enum { A=5 }; if (A!=5) return 99; } return A; }'
assert_enum 7 'enum { X=3 }; int main() { { int X=7; return X; } }'
assert_enum 3 'enum { X=3 }; int main() { { int X=7; } return X; }'
assert_enum 9 'int X; int main() { { enum { X=9 }; return X; } }'
assert_enum 1 'enum { T=9 }; int main() { { typedef char T; T x=3; return sizeof(x); } }'
assert_reject 'int main() { { enum { LOCAL=5 }; } return LOCAL; }'

echo "All enum scope tests passed!"
''')

readme = Path("README.md")
r = readme.read_text()
old = '- **Scope**: lexical block-level scoping for variables, record tags, and typedef names, including inner variable/typedef shadowing\n'
new = '- **Scope**: lexical block-level scoping for variables, record tags, typedef names, and enumeration constants, including ordinary-identifier shadowing\n'
if old not in r:
    raise SystemExit("README scope line not found")
readme.write_text(r.replace(old, new, 1))

print("scoped enum migration applied")
