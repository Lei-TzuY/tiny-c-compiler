from pathlib import Path

p = Path('codegen.c')
s = p.read_text()

old = r'''static void cast_value(Type *from, Type *to) {
    if (!from || !to || from == to || from->kind == to->kind)
        return;
'''
new = r'''static void cast_value(Type *from, Type *to) {
    if (!from || !to || from == to)
        return;

    // Most same-kind conversions are representation-preserving, but signed
    // and unsigned integer types of the same rank still require the target
    // width/sign interpretation (notably int <-> unsigned int).
    if (from->kind == to->kind &&
        (!is_integer(from) || from->is_unsigned == to->is_unsigned))
        return;
'''
if s.count(old) != 1:
    raise SystemExit(f'cast_value prologue count={s.count(old)}')
s = s.replace(old, new, 1)

old = r'''    gen_addr(node->lhs);
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
'''
new = r'''    Type *operation_ty = NULL;
    if (node->kind == ND_DIV_EQ || node->kind == ND_MOD_EQ)
        operation_ty = get_common_type(node->lhs->ty, node->rhs->ty);
    else if (node->kind == ND_SHR_EQ)
        // Integer promotion of the left operand.  Using int as the second
        // operand is a compact way to request exactly that promotion here.
        operation_ty = get_common_type(node->lhs->ty, ty_int);

    gen_addr(node->lhs);
    push();
    load(node->ty);
    if (operation_ty)
        cast_value(node->lhs->ty, operation_ty);
    push();
    gen_expr(node->rhs);
    if (operation_ty &&
        (node->kind == ND_DIV_EQ || node->kind == ND_MOD_EQ))
        cast_value(node->rhs->ty, operation_ty);
    printf("  mov %%rax, %%rsi\n");
    pop("%rax");

    switch (node->kind) {
'''
if s.count(old) != 1:
    raise SystemExit(f'compound conversion block count={s.count(old)}')
s = s.replace(old, new, 1)

old = r'''    bool arithmetic = node->kind == ND_ADD || node->kind == ND_SUB ||
                      node->kind == ND_MUL || node->kind == ND_DIV ||
                      node->kind == ND_MOD;
'''
new = r'''    bool arithmetic = node->kind == ND_ADD || node->kind == ND_SUB ||
                      node->kind == ND_MUL || node->kind == ND_DIV ||
                      node->kind == ND_MOD || node->kind == ND_BITAND ||
                      node->kind == ND_BITOR || node->kind == ND_BITXOR;
'''
if s.count(old) != 1:
    raise SystemExit(f'arithmetic classification count={s.count(old)}')
s = s.replace(old, new, 1)

old = r'''    gen_expr(node->rhs);
    push();
    gen_expr(node->lhs);
    pop("%rdi");

    switch (node->kind) {
    case ND_ADD: printf("  add %%rdi, %%rax\n"); return;
    case ND_SUB: printf("  sub %%rdi, %%rax\n"); return;
    case ND_MUL: printf("  imul %%rdi, %%rax\n"); return;
    case ND_DIV:
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
    case ND_BITAND: printf("  and %%rdi, %%rax\n"); return;
    case ND_BITOR:  printf("  or %%rdi, %%rax\n"); return;
    case ND_BITXOR: printf("  xor %%rdi, %%rax\n"); return;
    case ND_SHL:
        printf("  mov %%rdi, %%rcx\n");
        printf("  shl %%cl, %%rax\n");
        return;
    case ND_SHR:
        printf("  mov %%rdi, %%rcx\n");
        if (node->ty && node->ty->is_unsigned)
            printf("  shr %%cl, %%rax\n");
        else
            printf("  sar %%cl, %%rax\n");
        return;
'''
new = r'''    gen_expr(node->rhs);
    if (common && is_integer(common))
        cast_value(node->rhs->ty, common);
    push();
    gen_expr(node->lhs);
    if (common && is_integer(common))
        cast_value(node->lhs->ty, common);
    pop("%rdi");

    switch (node->kind) {
    case ND_ADD:
        printf("  add %%rdi, %%rax\n");
        if (common && is_integer(common)) normalize(common);
        return;
    case ND_SUB:
        printf("  sub %%rdi, %%rax\n");
        if (common && is_integer(common)) normalize(common);
        return;
    case ND_MUL:
        printf("  imul %%rdi, %%rax\n");
        if (common && is_integer(common)) normalize(common);
        return;
    case ND_DIV:
        if (common && common->is_unsigned) {
            printf("  mov $0, %%rdx\n");
            printf("  div %%rdi\n");
        } else {
            printf("  cqo\n");
            printf("  idiv %%rdi\n");
        }
        if (common && is_integer(common)) normalize(common);
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
        if (common && is_integer(common)) normalize(common);
        return;
    case ND_BITAND:
        printf("  and %%rdi, %%rax\n");
        if (common) normalize(common);
        return;
    case ND_BITOR:
        printf("  or %%rdi, %%rax\n");
        if (common) normalize(common);
        return;
    case ND_BITXOR:
        printf("  xor %%rdi, %%rax\n");
        if (common) normalize(common);
        return;
    case ND_SHL:
        printf("  mov %%rdi, %%rcx\n");
        printf("  shl %%cl, %%rax\n");
        normalize(node->ty);
        return;
    case ND_SHR:
        printf("  mov %%rdi, %%rcx\n");
        if (node->ty && node->ty->is_unsigned)
            printf("  shr %%cl, %%rax\n");
        else
            printf("  sar %%cl, %%rax\n");
        normalize(node->ty);
        return;
'''
if s.count(old) != 1:
    raise SystemExit(f'integer binary codegen block count={s.count(old)}')
s = s.replace(old, new, 1)
p.write_text(s)

p = Path('test/arithmetic_conversions.sh')
s = p.read_text()
needle = r'''assert_run 1 'int main(){long x=-2;x>>=1;return x==-1;}'

echo 'All arithmetic-conversion tests passed!'
'''
replacement = r'''assert_run 1 'int main(){long x=-2;x>>=1;return x==-1;}'

# Same-rank signed/unsigned conversion must change the actual register value,
# not merely the instruction signedness.  Integer results are normalized back
# to their C width so unsigned-int arithmetic wraps modulo 2^32.
assert_run 1 'int main(){int a=-2;unsigned int b=(unsigned int)-1;return a<b;}'
assert_run 1 'int main(){unsigned int a=(unsigned int)-1;return (a+1)==0;}'
assert_run 1 'int main(){unsigned int a=0;return a-1==(unsigned int)-1;}'
assert_run 1 'int main(){unsigned int a=(unsigned int)-1;return a*2==(unsigned int)-2;}'
assert_run 1 'int main(){unsigned int a=(unsigned int)-1;return (a<<1)==(unsigned int)-2;}'
assert_run 1 'int main(){int a=-2;unsigned int b=2;return a/b==(unsigned int)2147483647;}'
assert_run 1 'int main(){int a=-2;unsigned int b=7;return a%b==2;}'
assert_run 1 'int main(){int x=-2;unsigned int y=2;x/=y;return x==2147483647;}'
assert_run 1 'int main(){int a=-2;unsigned int b=0;return (a|b)==(unsigned int)-2;}'
assert_run 1 'int main(){return (1?-1:(unsigned int)0)==(unsigned int)-1;}'

echo 'All arithmetic-conversion tests passed!'
'''
if s.count(needle) != 1:
    raise SystemExit(f'test anchor count={s.count(needle)}')
p.write_text(s.replace(needle, replacement, 1))
