from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1))


if Path("test/noreturn.sh").exists():
    print("C11 _Noreturn migration already applied")
    raise SystemExit(0)

replace_once(
    "tokenize.c",
    '                         "inline", "register", "_Bool", "float", "double",\n'
    '                         "_Alignas"};\n',
    '                         "inline", "register", "_Bool", "float", "double",\n'
    '                         "_Alignas", "_Noreturn"};\n',
)

replace_once(
    "parse.c",
    '''    bool is_register;
    bool is_inline;
    int align;
''',
    '''    bool is_register;
    bool is_inline;
    bool is_noreturn;
    int align;
''',
)

replace_once(
    "parse.c",
    '''    if (equal(tok, "register") || equal(tok, "inline")) return true;
    if (equal(tok, "_Alignas")) return true;
''',
    '''    if (equal(tok, "register") || equal(tok, "inline")) return true;
    if (equal(tok, "_Alignas") || equal(tok, "_Noreturn")) return true;
''',
)

replace_once(
    "parse.c",
    '''        if (consume(&tok, tok, "inline")) {
            if (attrs) attrs->is_inline = true;
            continue;
        }
''',
    '''        if (consume(&tok, tok, "inline")) {
            if (attrs) attrs->is_inline = true;
            continue;
        }
        Token *noreturn_tok = tok;
        if (consume(&tok, tok, "_Noreturn")) {
            if (!attrs)
                error_at(noreturn_tok->loc,
                         "_Noreturn is only allowed in a function declaration");
            attrs->is_noreturn = true;
            continue;
        }
''',
)

replace_once(
    "parse.c",
    '''        if (attrs.is_static || attrs.is_extern || attrs.is_register || attrs.is_inline)
            error_at(tok->loc, "storage/function specifier is not allowed on a record member");
''',
    '''        if (attrs.is_static || attrs.is_extern || attrs.is_register || attrs.is_inline ||
            attrs.is_noreturn)
            error_at(tok->loc, "storage/function specifier is not allowed on a record member");
''',
)

replace_once(
    "parse.c",
    '''    if (equal(tok, ";")) {
        if (attrs.align)
            error_at(tok->loc, "_Alignas requires an object declarator");
        *rest = tok->next;
''',
    '''    if (equal(tok, ";")) {
        if (attrs.align)
            error_at(tok->loc, "_Alignas requires an object declarator");
        if (attrs.is_noreturn)
            error_at(tok->loc, "_Noreturn requires a function declarator");
        *rest = tok->next;
''',
)

replace_once(
    "parse.c",
    '''        if (attrs.align && ty->kind == TY_FUNC)
            error_at(ident->loc, "_Alignas is not allowed on a function declaration");
        bool inferable_array = is_unknown_bound_array_with_complete_element(ty) &&
''',
    '''        if (attrs.align && ty->kind == TY_FUNC)
            error_at(ident->loc, "_Alignas is not allowed on a function declaration");
        if (attrs.is_noreturn && ty->kind != TY_FUNC)
            error_at(ident->loc, "_Noreturn may only declare a function");
        bool inferable_array = is_unknown_bound_array_with_complete_element(ty) &&
''',
)

replace_once(
    "parse.c",
    '''        if (consume(&tok, tok, ";")) {
            if (attrs.align)
                error_at(tok->loc, "_Alignas requires an object declarator");
            continue;
        }
''',
    '''        if (consume(&tok, tok, ";")) {
            if (attrs.align)
                error_at(tok->loc, "_Alignas requires an object declarator");
            if (attrs.is_noreturn)
                error_at(tok->loc, "_Noreturn requires a function declarator");
            continue;
        }
''',
)

replace_once(
    "parse.c",
    '''        } else {
            // Global variable(s) (possibly with initializer)
            for (;;) {
''',
    '''        } else {
            if (attrs.is_noreturn)
                error_at(ident->loc, "_Noreturn may only declare a function");
            // Global variable(s) (possibly with initializer)
            for (;;) {
''',
)

replace_once(
    "preprocess_v2.c",
    '''    if (!strcmp(name, "stdbool.h")) {
        return "#define bool _Bool\\n"
               "#define true 1\\n"
               "#define false 0\\n"
               "#define __bool_true_false_are_defined 1\\n";
    }
''',
    '''    if (!strcmp(name, "stdbool.h")) {
        return "#define bool _Bool\\n"
               "#define true 1\\n"
               "#define false 0\\n"
               "#define __bool_true_false_are_defined 1\\n";
    }
    if (!strcmp(name, "stdnoreturn.h")) {
        return "#define noreturn _Noreturn\\n";
    }
''',
)

replace_once(
    "README.md",
    '- **Declarations**: recursive C declarators',
    '- **Declarations**: C11 `_Noreturn` function declarations (including `<stdnoreturn.h>` `noreturn`), recursive C declarators',
)

replace_once(
    "Makefile",
    '\tbash ./test/alignas.sh\n',
    '\tbash ./test/alignas.sh\n\tbash ./test/noreturn.sh\n',
)

Path("test/noreturn.sh").write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-noreturn.c
  ./minicc tmp-noreturn.c > tmp-noreturn.s
  cc -o tmp-noreturn tmp-noreturn.s
  set +e
  ./tmp-noreturn
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(_Noreturn): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_compile() {
  input="$1"
  printf '%s\n' "$input" > tmp-noreturn.c
  ./minicc tmp-noreturn.c > tmp-noreturn.s
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-noreturn-bad.c
  if ./minicc tmp-noreturn-bad.c > /dev/null 2>tmp-noreturn.err; then
    echo "FAIL(_Noreturn): expected rejection"
    echo "$input"
    exit 1
  fi
}

assert_run 0 '_Noreturn void stop(void){for(;;){}} int main(void){return 0;}'
assert_run 0 'static inline _Noreturn int stop(void){for(;;){}} int main(void){return 0;}'
assert_run 0 '_Noreturn void f(void); void f(void){for(;;){}} int main(void){return 0;}'
assert_run 0 'void g(void); _Noreturn void g(void){for(;;){}} int main(void){return 0;}'
assert_run 0 '_Noreturn void f(void){for(;;){}} int main(void){ _Noreturn void f(void); return 0; }'

assert_run 0 $'#include <stdnoreturn.h>\nnoreturn void fatal(void){for(;;){}}\nint main(void){return 0;}'
assert_compile $'#include <stdnoreturn.h>\n#ifndef noreturn\n#error noreturn macro missing\n#endif\nnoreturn void fatal(void);\nint main(void){return 0;}'

# _Noreturn is a function specifier, not part of the function type.
assert_compile '_Noreturn int f(int); int f(int x){return x;} int main(void){return 0;}'

assert_reject '_Noreturn int x; int main(void){return 0;}'
assert_reject 'int main(void){ _Noreturn int x; return 0; }'
assert_reject '_Noreturn void (*fp)(void); int main(void){return 0;}'
assert_reject '_Noreturn struct S { int x; }; int main(void){return 0;}'
assert_reject 'typedef _Noreturn void F(void); int main(void){return 0;}'
assert_reject 'int main(void){ return sizeof(_Noreturn int); }'
assert_reject 'struct S { _Noreturn int x; }; int main(void){return 0;}'

rm -f tmp-noreturn.c tmp-noreturn.s tmp-noreturn \
      tmp-noreturn-bad.c tmp-noreturn.err

echo 'All C11 _Noreturn tests passed!'
''')

print("C11 _Noreturn migration applied")
