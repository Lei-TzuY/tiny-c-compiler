from pathlib import Path
import re

p = Path("parse.c")
s = p.read_text()

repls = []
repls.append((
'''struct Scope {
    Scope *parent;
    VarScope *vars;
    StructTag *tags;
};
''',
'''struct Scope {
    Scope *parent;
    VarScope *vars;
    StructTag *tags;
    TypeDef *typedefs;
};
''',
"scope typedef list"))

repls.append((
'''static StructTag *push_tag(const char *name, Type *ty) {
    StructTag *tag = calloc(1, sizeof(StructTag));
    tag->name = strdup(name);
    tag->ty = ty;
    tag->next = current_scope->tags;
    current_scope->tags = tag;
    return tag;
}

// ---- End Block Scope ----
''',
'''static StructTag *push_tag(const char *name, Type *ty) {
    StructTag *tag = calloc(1, sizeof(StructTag));
    tag->name = strdup(name);
    tag->ty = ty;
    tag->next = current_scope->tags;
    current_scope->tags = tag;
    return tag;
}

static bool token_matches_name(Token *tok, const char *name) {
    return tok->kind == TK_IDENT && strlen(name) == (size_t)tok->len &&
           !strncmp(tok->loc, name, tok->len);
}

// Typedef names live in the ordinary identifier namespace. A variable in a
// nearer block therefore hides an outer typedef name.
static TypeDef *find_typedef(Token *tok) {
    for (Scope *scope = current_scope; scope; scope = scope->parent) {
        for (VarScope *vs = scope->vars; vs; vs = vs->next)
            if (token_matches_name(tok, vs->name))
                return NULL;

        for (TypeDef *td = scope->typedefs; td; td = td->next)
            if (token_matches_name(tok, td->name))
                return td;
    }
    return NULL;
}

static void push_typedef(Token *ident, Type *ty) {
    TypeDef *td = calloc(1, sizeof(TypeDef));
    td->name = strndup(ident->loc, ident->len);
    td->ty = ty;
    td->next = current_scope->typedefs;
    current_scope->typedefs = td;
}

// ---- End Block Scope ----
''',
"typedef scope helpers"))

repls.append((
'''static Obj *locals;
static Obj *globals;
static EnumConst *enum_consts;
static TypeDef *typedefs;
''',
'''static Obj *locals;
static Obj *globals;
static EnumConst *enum_consts;
''',
"remove global typedef list"))

repls.append((
'''    for (TypeDef *td = typedefs; td; td = td->next)
        if ((int)strlen(td->name) == tok->len &&
            !strncmp(tok->loc, td->name, tok->len))
            return true;
    return false;
''',
'''    return find_typedef(tok) != NULL;
''',
"is_typename scoped lookup"))

repls.append((
'''        // Check for typedef name
        if (tok->kind == TK_IDENT) {
            bool found = false;
            for (TypeDef *td = typedefs; td; td = td->next) {
                if ((int)strlen(td->name) == tok->len &&
                    !strncmp(tok->loc, td->name, tok->len)) {
                    tok = tok->next;
                    ty = td->ty;
                    found = true;
                    break;
                }
            }
            if (found) continue;
        }
''',
'''        // Check for a typedef name visible in the current lexical scope.
        if (tok->kind == TK_IDENT) {
            TypeDef *td = find_typedef(tok);
            if (td) {
                tok = tok->next;
                ty = td->ty;
                continue;
            }
        }
''',
"declspec scoped typedef lookup"))

typedef_insert = re.compile(
    r'(?m)^(?P<indent>[ \t]*)TypeDef \*td = calloc\(1, sizeof\(TypeDef\)\);\n'
    r'(?P=indent)td->name = strndup\(ident->loc, ident->len\);\n'
    r'(?P=indent)td->ty = ty;\n'
    r'(?P=indent)td->next = typedefs;\n'
    r'(?P=indent)typedefs = td;\n'
)

def replace_typedef_insert(match):
    return match.group('indent') + 'push_typedef(ident, ty);\n'

s, count = typedef_insert.subn(replace_typedef_insert, s)
if count != 2:
    raise SystemExit(f"expected two typedef insertion blocks, found {count}")

for old, new, label in repls:
    if old not in s:
        raise SystemExit(f"expected parser block not found: {label}")
    s = s.replace(old, new, 1)

p.write_text(s)

make = Path("Makefile")
m = make.read_text()
needle = '\tbash ./test/incomplete_tags.sh\n'
if needle not in m:
    raise SystemExit("Makefile incomplete-tag test line not found")
if '\tbash ./test/typedef_scope.sh\n' not in m:
    m = m.replace(needle, needle + '\tbash ./test/typedef_scope.sh\n', 1)
make.write_text(m)

scope_test = Path("test/typedef_scope.sh")
scope_test.write_text(r'''#!/bin/bash
set -e

assert_scope() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-typedef.c
  "${MINICC:-./minicc}" tmp-typedef.c > tmp-typedef.s
  gcc -o tmp-typedef tmp-typedef.s
  set +e
  ./tmp-typedef
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(typedef scope): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(typedef scope): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-typedef-reject.c
  if "${MINICC:-./minicc}" tmp-typedef-reject.c > /dev/null 2>&1; then
    echo "FAIL(typedef scope): expected rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(typedef scope): rejected out-of-scope typedef"
}

assert_scope 4 'typedef int T; int main() { T x=3; return sizeof(x); }'
assert_scope 4 'typedef int T; int main() { { typedef char T; T x=3; if (sizeof(x)!=1) return 99; } T y=7; return sizeof(y); }'
assert_scope 7 'int main() { { typedef char T; T x=1; if (sizeof(x)!=1) return 1; } { typedef long T; T y=2; if (sizeof(y)!=8) return 2; } return 7; }'
assert_scope 6 'typedef int T; int main() { { int T=5; T=T+1; return T; } }'
assert_scope 7 'typedef int T; int main() { { int T=5; } T x=7; return x; }'
assert_scope 1 'int T; int main() { { typedef char T; T x=3; return sizeof(x); } }'
assert_reject 'int main() { { typedef int Local; Local x=3; } Local y; return 0; }'

echo "All typedef scope tests passed!"
''')

readme = Path("README.md")
r = readme.read_text()
old = '- **Scope**: full block-level scoping\n'
new = '- **Scope**: lexical block-level scoping for variables, record tags, and typedef names, including inner variable/typedef shadowing\n'
if old not in r:
    raise SystemExit("README scope line not found")
readme.write_text(r.replace(old, new, 1))

print("scoped typedef migration applied")
