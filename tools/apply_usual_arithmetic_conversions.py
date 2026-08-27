from pathlib import Path

# type.c: model integer promotions and the LP64 usual arithmetic conversions,
# and make shifts use the promoted left operand as their result type.
p = Path('type.c')
s = p.read_text()
old = r'''// Usual arithmetic conversions for the subset supported by minicc.
Type *get_common_type(Type *ty1, Type *ty2) {
    if (ty1->base)
        return pointer_to(ty1->base);

    if (ty1->kind == TY_DOUBLE || ty2->kind == TY_DOUBLE)
        return ty_double;
    if (ty1->kind == TY_FLOAT || ty2->kind == TY_FLOAT)
        return ty_float;

    if (ty1->size == 8 || ty2->size == 8) {
        if (ty1->is_unsigned || ty2->is_unsigned)
            return ty_ulong;
        return ty_long;
    }

    if (ty1->is_unsigned || ty2->is_unsigned)
        return ty_uint;
    return ty_int;
}
'''
new = r'''// Integer promotions for the LP64 target used by minicc.  All supported
// char/short/_Bool values fit in int, including their unsigned variants.
static Type *integer_promotion(Type *ty) {
    if (!is_integer(ty))
        return ty;
    if (ty->kind == TY_BOOL || ty->kind == TY_CHAR || ty->kind == TY_SHORT)
        return ty_int;
    return ty;
}

// Usual arithmetic conversions for the LP64 subset supported by minicc.
// After integer promotion, rank follows size for the integer types we expose:
// int < long.  If signedness differs, a wider signed type can represent every
// value of the narrower unsigned type; otherwise the unsigned type wins.
Type *get_common_type(Type *ty1, Type *ty2) {
    if (ty1->base)
        return pointer_to(ty1->base);

    if (ty1->kind == TY_DOUBLE || ty2->kind == TY_DOUBLE)
        return ty_double;
    if (ty1->kind == TY_FLOAT || ty2->kind == TY_FLOAT)
        return ty_float;

    ty1 = integer_promotion(ty1);
    ty2 = integer_promotion(ty2);

    if (ty1->is_unsigned == ty2->is_unsigned)
        return ty1->size >= ty2->size ? ty1 : ty2;

    Type *u = ty1->is_unsigned ? ty1 : ty2;
    Type *s = ty1->is_unsigned ? ty2 : ty1;

    if (u->size >= s->size)
        return u;

    // On x86-64 LP64, a wider signed integer type represents the complete
    // range of every narrower unsigned integer type supported here.
    return s;
}
'''
if s.count(old) != 1:
    raise SystemExit(f'type common-type block count={s.count(old)}')
s = s.replace(old, new, 1)
old = r'''    case ND_MOD:
    case ND_BITAND:
    case ND_BITOR:
    case ND_BITXOR:
    case ND_SHL:
    case ND_SHR:
        if (!is_integer(node->lhs->ty) || !is_integer(node->rhs->ty))
            error("integer operands required");
        node->ty = get_common_type(node->lhs->ty, node->rhs->ty);
        return;
'''
new = r'''    case ND_MOD:
    case ND_BITAND:
    case ND_BITOR:
    case ND_BITXOR:
        if (!is_integer(node->lhs->ty) || !is_integer(node->rhs->ty))
            error("integer operands required");
        node->ty = get_common_type(node->lhs->ty, node->rhs->ty);
        return;

    case ND_SHL:
    case ND_SHR:
        if (!is_integer(node->lhs->ty) || !is_integer(node->rhs->ty))
            error("integer operands required");
        // Each operand is integer-promoted independently; unlike ordinary
        // arithmetic there is no common type, and the result has the promoted
        // type of the left operand.
        node->ty = integer_promotion(node->lhs->ty);
        return;
'''
if s.count(old) != 1:
    raise SystemExit(f'type shift block count={s.count(old)}')
s = s.replace(old, new, 1)
p.write_text(s)

# codegen.c: choose signed/unsigned instructions from the converted operation
# type rather than from the unconverted left operand.
p = Path('codegen.c')
s = p.read_text()
old = r'''    gen_addr(node->lhs);
    push();
    load(node->ty);
    push();
    gen_expr(node->rhs);
    printf("  mov %%rax, %%rsi\n");
    pop("%rax");

    switch (node->kind) {
    case ND_ADD_EQ: printf("  add %%rsi, %%rax\n"); break;
    case ND_SUB_EQ: printf("  sub %%rsi, %%rax\n"); break;
    case ND_MUL_EQ: printf("  imul %%rsi, %%rax\n"); break;
    case ND_DIV_EQ:
        printf("  cqo\n");
        printf("  idiv %%rsi\n");
        break;
    case ND_MOD_EQ:
        printf("  cqo\n");
        printf("  idiv %%rsi\n");
        printf("  mov %%rdx, %%rax\n");
        break;
    case ND_AND_EQ: printf("  and %%rsi, %%rax\n"); break;
    case ND_OR_EQ:  printf("  or %%rsi, %%rax\n"); break;
    case ND_XOR_EQ: printf("  xor %%rsi, %%rax\n"); break;
    case ND_SHL_EQ:
        printf("  mov %%rsi, %%rcx\n");
        printf("  shl %%cl, %%rax\n");
        break;
    case ND_SHR_EQ:
        printf("  mov %%rsi, %%rcx\n");
        printf("  sar %%cl, %%rax\n");
        break;
    default: error("invalid compound assignment");
    }
'''
new = r'''    gen_addr(node->lhs);
    push();
    load(node->ty);
    push();
    gen_expr(node->rhs);
    printf("  mov %%rax, %%rsi\n");
    pop("%rax");

    Type *operation_ty = NULL;
    if (node->kind == ND_DIV_EQ || node->kind == ND_MOD_EQ)
        operation_ty = get_common_type(node->lhs->ty, node->rhs->ty);
    else if (node->kind == ND_SHR_EQ)
        // Integer promotion of the left operand.  Using int as the second
        // operand is a compact way to request exactly that promotion here.
        operation_ty = get_common_type(node->lhs->ty, ty_int);

    switch (node->kind) {
    case ND_ADD_EQ: printf("  add %%rsi, %%rax\n"); break;
    case ND_SUB_EQ: printf("  sub %%rsi, %%rax\n"); break;
    case ND_MUL_EQ: printf("  imul %%rsi, %%rax\n"); break;
    case ND_DIV_EQ:
        if (operation_ty && operation_ty->is_unsigned) {
            printf("  mov $0, %%rdx\n");
            printf("  div %%rsi\n");
        } else {
            printf("  cqo\n");
            printf("  idiv %%rsi\n");
        }
        break;
    case ND_MOD_EQ:
        if (operation_ty && operation_ty->is_unsigned) {
            printf("  mov $0, %%rdx\n");
            printf("  div %%rsi\n");
        } else {
            printf("  cqo\n");
            printf("  idiv %%rsi\n");
        }
        printf("  mov %%rdx, %%rax\n");
        break;
    case ND_AND_EQ: printf("  and %%rsi, %%rax\n"); break;
    case ND_OR_EQ:  printf("  or %%rsi, %%rax\n"); break;
    case ND_XOR_EQ: printf("  xor %%rsi, %%rax\n"); break;
    case ND_SHL_EQ:
        printf("  mov %%rsi, %%rcx\n");
        printf("  shl %%cl, %%rax\n");
        break;
    case ND_SHR_EQ:
        printf("  mov %%rsi, %%rcx\n");
        if (operation_ty && operation_ty->is_unsigned)
            printf("  shr %%cl, %%rax\n");
        else
            printf("  sar %%cl, %%rax\n");
        break;
    default: error("invalid compound assignment");
    }
'''
if s.count(old) != 1:
    raise SystemExit(f'compound codegen block count={s.count(old)}')
s = s.replace(old, new, 1)
old = r'''    bool arithmetic = node->kind == ND_ADD || node->kind == ND_SUB ||
                      node->kind == ND_MUL || node->kind == ND_DIV;
'''
new = r'''    bool arithmetic = node->kind == ND_ADD || node->kind == ND_SUB ||
                      node->kind == ND_MUL || node->kind == ND_DIV ||
                      node->kind == ND_MOD;
'''
if s.count(old) != 1:
    raise SystemExit(f'arithmetic classification count={s.count(old)}')
s = s.replace(old, new, 1)
old = r'''    case ND_DIV:
        if (node->lhs->ty && node->lhs->ty->is_unsigned) {
            printf("  mov $0, %%rdx\n");
            printf("  div %%rdi\n");
        } else {
            printf("  cqo\n");
            printf("  idiv %%rdi\n");
        }
        return;
    case ND_MOD:
        if (node->lhs->ty && node->lhs->ty->is_unsigned) {
            printf("  mov $0, %%rdx\n");
            printf("  div %%rdi\n");
            printf("  mov %%rdx, %%rax\n");
        } else {
            printf("  cqo\n");
            printf("  idiv %%rdi\n");
            printf("  mov %%rdx, %%rax\n");
        }
        return;
'''
new = r'''    case ND_DIV:
        if (common && common->is_unsigned) {
            printf("  mov $0, %%rdx\n");
            printf("  div %%rdi\n");
        } else {
            printf("  cqo\n");
            printf("  idiv %%rdi\n");
        }
        return;
    case ND_MOD:
        if (common && common->is_unsigned) {
            printf("  mov $0, %%rdx\n");
            printf("  div %%rdi\n");
            printf("  mov %%rdx, %%rax\n");
        } else {
            printf("  cqo\n");
            printf("  idiv %%rdi\n");
            printf("  mov %%rdx, %%rax\n");
        }
        return;
'''
if s.count(old) != 1:
    raise SystemExit(f'div/mod codegen block count={s.count(old)}')
s = s.replace(old, new, 1)
old = r'''    case ND_SHR:
        printf("  mov %%rdi, %%rcx\n");
        if (node->lhs->ty && node->lhs->ty->is_unsigned)
            printf("  shr %%cl, %%rax\n");
        else
            printf("  sar %%cl, %%rax\n");
        return;
    case ND_EQ: case ND_NE: case ND_LT: case ND_LE:
        printf("  cmp %%rdi, %%rax\n");
        if (node->kind == ND_EQ) printf("  sete %%al\n");
        else if (node->kind == ND_NE) printf("  setne %%al\n");
        else if (node->lhs->ty && node->lhs->ty->is_unsigned) {
            if (node->kind == ND_LT) printf("  setb %%al\n");
            else if (node->kind == ND_LE) printf("  setbe %%al\n");
        } else {
            if (node->kind == ND_LT) printf("  setl %%al\n");
            else if (node->kind == ND_LE) printf("  setle %%al\n");
        }
'''
new = r'''    case ND_SHR:
        printf("  mov %%rdi, %%rcx\n");
        if (node->ty && node->ty->is_unsigned)
            printf("  shr %%cl, %%rax\n");
        else
            printf("  sar %%cl, %%rax\n");
        return;
    case ND_EQ: case ND_NE: case ND_LT: case ND_LE:
        printf("  cmp %%rdi, %%rax\n");
        if (node->kind == ND_EQ) printf("  sete %%al\n");
        else if (node->kind == ND_NE) printf("  setne %%al\n");
        else if ((common && common->is_unsigned) ||
                 (!common && node->lhs->ty && node->lhs->ty->kind == TY_PTR)) {
            if (node->kind == ND_LT) printf("  setb %%al\n");
            else if (node->kind == ND_LE) printf("  setbe %%al\n");
        } else {
            if (node->kind == ND_LT) printf("  setl %%al\n");
            else if (node->kind == ND_LE) printf("  setle %%al\n");
        }
'''
if s.count(old) != 1:
    raise SystemExit(f'shift/comparison codegen block count={s.count(old)}')
s = s.replace(old, new, 1)
p.write_text(s)

# Hook the focused regression suite into the complete test target.
p = Path('Makefile')
s = p.read_text()
needle = '\tbash ./test/pointer_arithmetic.sh\n'
if s.count(needle) != 1:
    raise SystemExit(f'Makefile anchor count={s.count(needle)}')
s = s.replace(needle, needle + '\tbash ./test/arithmetic_conversions.sh\n', 1)
p.write_text(s)

# Document the strengthened arithmetic semantics.
p = Path('README.md')
s = p.read_text()
needle = '- **Operators**: arithmetic, bitwise, logical, comparison, ternary `?:`, comma `,`, `sizeof`, prefix/postfix `++/--`, all compound assignments (`+= -= *= /= %= &= |= ^= <<= >>=`), type cast; pointer arithmetic follows complete-object rules with array decay, element-size scaling, compatible pointer subtraction, and rejection of `void *`/function-pointer arithmetic\n'
replacement = '- **Operators**: arithmetic, bitwise, logical, comparison, ternary `?:`, comma `,`, `sizeof`, prefix/postfix `++/--`, all compound assignments (`+= -= *= /= %= &= |= ^= <<= >>=`), type cast; pointer arithmetic follows complete-object rules with array decay, element-size scaling, compatible pointer subtraction, and rejection of `void *`/function-pointer arithmetic; integer promotions and LP64 usual arithmetic conversions drive mixed signed/unsigned arithmetic, comparison, shifts, and compound division/remainder/right-shift code generation\n'
if s.count(needle) != 1:
    raise SystemExit(f'README operator anchor count={s.count(needle)}')
p.write_text(s.replace(needle, replacement, 1))

Path('test/arithmetic_conversions.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-arithconv.c
  ./minicc tmp-arithconv.c > tmp-arithconv.s
  cc -o tmp-arithconv tmp-arithconv.s
  set +e
  ./tmp-arithconv
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "arithmetic conversion failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(arithmetic conversion): $actual"
}

# Integer promotions: unsigned char/short/_Bool promote to int on LP64.
assert_run 0 'int main(){unsigned short a=1;return (a+0)<-1;}'
assert_run 0 'int main(){unsigned short a=1;return (a|0)<-1;}'
assert_run 4 'int main(){return sizeof((unsigned short)1 << (long)1);}'
assert_run 4 'int main(){return sizeof((unsigned int)1 << (long)1);}'
assert_run 4 'int main(){return sizeof((_Bool)1 << (long)1);}'

# A wider signed long represents every unsigned-int value, so long wins over
# unsigned int in the usual arithmetic conversions on this LP64 target.
assert_run 1 'int main(){unsigned int a=0;long b=-1;return (a+b)<0;}'
assert_run 0 'int main(){unsigned int a=1;long b=-1;return a<b;}'
assert_run 1 'int main(){return ((long)-1)<(unsigned int)1;}'
assert_run 1 'int main(){unsigned int a=4;long b=-2;return a/b==-2;}'
assert_run 1 'int main(){unsigned int a=5;long b=-2;return a%b==1;}'

# Conditional arithmetic alternatives use the same converted result type.
assert_run 1 'int main(){return (1?(long)-1:(unsigned int)1)<0;}'

# Compound division/remainder use the operation's converted type before the
# result is stored back into the left operand.
assert_run 1 'int main(){unsigned long x=4;long y=-2;x/=y;return x==0;}'
assert_run 1 'int main(){unsigned long x=5;long y=-2;x%=y;return x==5;}'

# Right shift uses the promoted left operand's signedness, including compound
# assignment.  Unsigned long must use a logical right shift.
assert_run 1 'int main(){unsigned long x=(unsigned long)-1;x>>=1;return (long)x>0;}'
assert_run 1 'int main(){long x=-2;x>>=1;return x==-1;}'

echo 'All arithmetic-conversion tests passed!'
''')
