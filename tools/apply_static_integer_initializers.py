from pathlib import Path


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)

p = Path('parse.c')
s = p.read_text()
old = '''// Parse a constant integer (with optional sign) for global initializers
static int64_t parse_const_int(Token **rest, Token *tok) {
    bool neg = consume(&tok, tok, "-");
    bool pos = false;
    if (!neg) pos = consume(&tok, tok, "+");
    (void)pos;
    if (tok->kind != TK_NUM || tok->is_float)
        error_at(tok->loc, "expected integer constant");
    int64_t val = tok->val;
    if (neg) val = -val;
    *rest = tok->next;
    return val;
}
'''
new = '''// Parse and evaluate an integer constant expression used by an object with
// static storage duration. Reuse the same type-aware evaluator as enums, case
// labels, and array bounds so signedness, integer promotions, short-circuiting,
// casts, and shift/division diagnostics cannot drift between contexts.
static int64_t parse_static_integer_initializer(Token **rest, Token *tok,
                                                Type *target) {
    Token *start = tok;
    Node *node = assign(&tok, tok);
    add_type(node);

    if (!is_integer(node->ty))
        error_at(start->loc, "static initializer is not an integer constant expression");

    int64_t val = eval_const_expr(node);

    if (target) {
        if (is_integer(target)) {
            val = cast_const_integer(val, target);
        } else if (target->kind == TY_PTR) {
            // A null pointer constant is an integer constant expression with
            // value zero. Address constants are intentionally a separate
            // feature; reject arbitrary nonzero integer-to-pointer statics.
            if (val != 0)
                error_at(start->loc, "nonzero integer is not a valid static pointer initializer");
            val = 0;
        } else {
            error_at(start->loc, "unsupported static integer initializer target type");
        }
    }

    *rest = tok;
    return val;
}
'''
s = replace_once(s, old, new, 'parse_const_int')

old_array = '                    vals[cnt++] = parse_const_int(&tok, tok);\n'
if s.count(old_array) != 2:
    raise SystemExit(f"array initializer calls: expected two anchors, found {s.count(old_array)}")
new_array = '''                    Type *elem_ty = (ty->kind == TY_ARRAY) ? ty->base : NULL;
                    vals[cnt++] = parse_static_integer_initializer(&tok, tok, elem_ty);
'''
s = s.replace(old_array, new_array)

local_old = '''                if (is_flonum(ty))
                    var->finit_val = parse_const_double(&tok, tok);
                else
                    var->init_val = parse_const_int(&tok, tok);
                var->has_init_val = true;
'''
local_new = '''                if (is_flonum(ty)) {
                    var->finit_val = parse_const_double(&tok, tok);
                } else if (is_integer(ty) || ty->kind == TY_PTR) {
                    var->init_val = parse_static_integer_initializer(&tok, tok, ty);
                } else {
                    error_at(tok->loc, "unsupported scalar static initializer type");
                }
                var->has_init_val = true;
'''
s = replace_once(s, local_old, local_new, 'block-scope static scalar initializer')

global_old = '''                        if (is_flonum(ty))
                            var->finit_val = parse_const_double(&tok, tok);
                        else
                            var->init_val = parse_const_int(&tok, tok);
                        var->has_init_val = true;
'''
global_new = '''                        if (is_flonum(ty)) {
                            var->finit_val = parse_const_double(&tok, tok);
                        } else if (is_integer(ty) || ty->kind == TY_PTR) {
                            var->init_val = parse_static_integer_initializer(&tok, tok, ty);
                        } else {
                            error_at(tok->loc, "unsupported scalar static initializer type");
                        }
                        var->has_init_val = true;
'''
s = replace_once(s, global_old, global_new, 'file-scope scalar initializer')
p.write_text(s)

# Focused regression coverage.
test = r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-static-init.c
  ./minicc tmp-static-init.c > tmp-static-init.s
  cc -o tmp-static-init tmp-static-init.s
  set +e
  ./tmp-static-init
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "static initializer test failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(static initializer): $actual"
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-static-init.c
  if ./minicc tmp-static-init.c > /dev/null 2>&1; then
    echo 'static initializer test should have been rejected'
    echo "$input"
    exit 1
  fi
  echo 'OK(static initializer): rejected invalid initializer'
}

# File-scope integer constant expressions.
assert_run 0 'int g=1+2*3; int main(){return g==7?0:1;}'
assert_run 0 'enum { N=7 }; int g=N*3+1; int main(){return g==22?0:1;}'
assert_run 0 'int g=(int)(3L*4); int main(){return g==12?0:1;}'
assert_run 0 'int g=(1?9:1/0); int main(){return g==9?0:1;}'
assert_run 0 'int g=(0?1/0:11); int main(){return g==11?0:1;}'
assert_run 0 'int g=((1<<5)|3)^1; int main(){return g==34?0:1;}'
assert_run 0 'int g=(5>3)&&(2<=2); int main(){return g==1?0:1;}'
assert_run 0 'unsigned long g=0xffffffffffffffffULL>>63; int main(){return g==1?0:1;}'
assert_run 0 'unsigned int g=0xffffffffU/3U; int main(){return g==1431655765U?0:1;}'
assert_run 0 'unsigned char g=300; int main(){return g==44?0:1;}'
assert_run 0 '_Bool g=5-3; int main(){return g==1?0:1;}'
assert_run 0 'int *p=1-1; int main(){return p==0?0:1;}'

# Static locals use the same evaluator and keep lexical enum visibility.
assert_run 0 'int f(){enum { N=5 }; static int x=N*4+2; return x;} int main(){return f()==22?0:1;}'
assert_run 0 'int f(){static unsigned long x=1ULL<<63; return (x>>63)==1;} int main(){return f()?0:1;}'

# Brace-enclosed static/global integer arrays now accept full constant expressions.
assert_run 0 'int a[]={1+2,1<<4,10/2}; int main(){return a[0]==3&&a[1]==16&&a[2]==5?0:1;}'
assert_run 0 'unsigned char a[]={255+1,300,7*3}; int main(){return a[0]==0&&a[1]==44&&a[2]==21?0:1;}'
assert_run 0 'int f(){static int a[]={2*3,20/4,1?8:9};return a[0]+a[1]+a[2];} int main(){return f()==19?0:1;}'

# Non-constant or semantically invalid static initializers must be diagnosed.
assert_reject 'int x=1; int g=x+1; int main(){return g;}'
assert_reject 'int f(){return 3;} int g=f(); int main(){return g;}'
assert_reject 'int g=1/0; int main(){return g;}'
assert_reject 'int g=1<<64; int main(){return g;}'
assert_reject 'int x; int g=(x=3); int main(){return g;}'
assert_reject 'int *p=123; int main(){return p!=0;}'
assert_reject 'int a[]={1,2.5}; int main(){return 0;}'

rm -f tmp-static-init.c tmp-static-init.s tmp-static-init

echo 'All static integer initializer tests passed!'
'''
Path('test/static_integer_initializers.sh').write_text(test)

make = Path('Makefile')
ms = make.read_text()
anchor = '\tbash ./test/constant_expressions.sh\n'
if ms.count(anchor) != 1:
    raise SystemExit('Makefile anchor not found exactly once')
ms = ms.replace(anchor, anchor + '\tbash ./test/static_integer_initializers.sh\n', 1)
make.write_text(ms)

readme = Path('README.md')
rs = readme.read_text()
line = '- Static/global integer scalar and array initializers accept type-aware integer constant expressions, including enum constants, casts, shifts, short-circuit logic, and ternary expressions.\n'
if line not in rs:
    rs += '\n' + line
readme.write_text(rs)
