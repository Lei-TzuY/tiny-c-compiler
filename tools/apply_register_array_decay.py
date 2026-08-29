from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


p = Path('parse.c').read_text()

p = replace_once(
    p,
    '''static bool is_register_based_lvalue(Node *node) {\n    if (!node)\n        return false;\n    if (node->kind == ND_VAR)\n        return node->var && node->var->is_register;\n    if (node->kind == ND_MEMBER)\n        return is_register_based_lvalue(node->lhs);\n    return false;\n}\n\nstatic bool is_addressable_expr(Node *node) {\n''',
    '''static bool is_register_based_lvalue(Node *node) {\n    if (!node)\n        return false;\n    if (node->kind == ND_VAR)\n        return node->var && node->var->is_register;\n    if (node->kind == ND_MEMBER)\n        return is_register_based_lvalue(node->lhs);\n    return false;\n}\n\n// Outside sizeof and unary &, an array expression undergoes the standard\n// array-to-pointer conversion. For a register array that conversion requires\n// the address that the storage-class contract intentionally makes unavailable.\n// Diagnose the otherwise-undefined C11 case, matching strict host compilers.\n// Member arrays inherit the restriction from a register aggregate root, while\n// dereference deliberately breaks that chain (the array then belongs to the\n// pointed-to object, not to the register pointer variable).\nstatic bool is_register_array_designator(Node *node) {\n    if (!node)\n        return false;\n    add_type(node);\n    return node->ty && node->ty->kind == TY_ARRAY &&\n           is_register_based_lvalue(node);\n}\n\nstatic void reject_register_array_decay(Node *node) {\n    if (is_register_array_designator(node))\n        error("register array cannot be converted to a pointer value");\n}\n\nstatic bool is_addressable_expr(Node *node) {\n''',
    'register array helper',
)

p = replace_once(
    p,
    '''static Type *generic_control_type(Node *node) {\n    add_type(node);\n    Type *ty = node->ty;\n''',
    '''static Type *generic_control_type(Node *node) {\n    add_type(node);\n    reject_register_array_decay(node);\n    Type *ty = node->ty;\n''',
    'generic controlling conversion',
)

p = replace_once(
    p,
    '''static Node *new_checked_deref(Node *operand, Token *op) {\n    add_type(operand);\n\n    Type *target = NULL;\n''',
    '''static Node *new_checked_deref(Node *operand, Token *op) {\n    add_type(operand);\n    reject_register_array_decay(operand);\n\n    Type *target = NULL;\n''',
    'explicit dereference conversion',
)

p = replace_once(
    p,
    '''static bool assignment_compatible(Type *dst, Node *rhs) {\n    add_type(rhs);\n    Type *src = rhs->ty;\n''',
    '''static bool assignment_compatible(Type *dst, Node *rhs) {\n    add_type(rhs);\n    reject_register_array_decay(rhs);\n    Type *src = rhs->ty;\n''',
    'assignment conversion',
)

p = replace_once(
    p,
    '''static bool is_scalar_expr(Node *node) {\n    add_type(node);\n    Type *ty = decay_value_type(node->ty);\n''',
    '''static bool is_scalar_expr(Node *node) {\n    add_type(node);\n    reject_register_array_decay(node);\n    Type *ty = decay_value_type(node->ty);\n''',
    'scalar value conversion',
)

p = replace_once(
    p,
    '''static bool cast_compatible(Type *dst, Node *expr) {\n    add_type(expr);\n\n    // A cast to void explicitly discards the value and accepts any complete\n''',
    '''static bool cast_compatible(Type *dst, Node *expr) {\n    add_type(expr);\n    reject_register_array_decay(expr);\n\n    // A cast to void explicitly discards the value and accepts any complete\n''',
    'cast conversion',
)

p = replace_once(
    p,
    '''static bool equality_operands_compatible(Node *lhs, Node *rhs) {\n    add_type(lhs);\n    add_type(rhs);\n\n    if (is_numeric(lhs->ty) && is_numeric(rhs->ty))\n''',
    '''static bool equality_operands_compatible(Node *lhs, Node *rhs) {\n    add_type(lhs);\n    add_type(rhs);\n    reject_register_array_decay(lhs);\n    reject_register_array_decay(rhs);\n\n    if (is_numeric(lhs->ty) && is_numeric(rhs->ty))\n''',
    'equality conversion',
)

p = replace_once(
    p,
    '''static bool relational_operands_compatible(Node *lhs, Node *rhs) {\n    add_type(lhs);\n    add_type(rhs);\n    if (is_numeric(lhs->ty) && is_numeric(rhs->ty))\n''',
    '''static bool relational_operands_compatible(Node *lhs, Node *rhs) {\n    add_type(lhs);\n    add_type(rhs);\n    reject_register_array_decay(lhs);\n    reject_register_array_decay(rhs);\n    if (is_numeric(lhs->ty) && is_numeric(rhs->ty))\n''',
    'relational conversion',
)

p = replace_once(
    p,
    '''static Type *conditional_result_type(Node *then, Node *els, Token *question) {\n    add_type(then);\n    add_type(els);\n\n    if (is_numeric(then->ty) && is_numeric(els->ty))\n''',
    '''static Type *conditional_result_type(Node *then, Node *els, Token *question) {\n    add_type(then);\n    add_type(els);\n    reject_register_array_decay(then);\n    reject_register_array_decay(els);\n\n    if (is_numeric(then->ty) && is_numeric(els->ty))\n''',
    'conditional operand conversion',
)

p = replace_once(
    p,
    '''static Node *expr(Token **rest, Token *tok) {\n    Node *node = assign(&tok, tok);\n\n    while (equal(tok, ","))\n        node = new_binary(ND_COMMA, node, assign(&tok, tok->next));\n\n    *rest = tok;\n    return node;\n}\n''',
    '''static Node *expr(Token **rest, Token *tok) {\n    Node *node = assign(&tok, tok);\n\n    while (equal(tok, ",")) {\n        reject_register_array_decay(node);\n        Node *rhs = assign(&tok, tok->next);\n        reject_register_array_decay(rhs);\n        node = new_binary(ND_COMMA, node, rhs);\n    }\n\n    *rest = tok;\n    return node;\n}\n''',
    'comma value conversion',
)

p = replace_once(
    p,
    '''static Node *add(Token **rest, Token *tok) {\n    Node *node = mul(&tok, tok);\n    for (;;) {\n        if (equal(tok, "+")) { node = new_add(node, mul(&tok, tok->next)); continue; }\n        if (equal(tok, "-")) { node = new_sub(node, mul(&tok, tok->next)); continue; }\n        *rest = tok;\n        return node;\n    }\n}\n''',
    '''static Node *add(Token **rest, Token *tok) {\n    Node *node = mul(&tok, tok);\n    for (;;) {\n        if (equal(tok, "+")) {\n            Node *rhs = mul(&tok, tok->next);\n            reject_register_array_decay(node);\n            reject_register_array_decay(rhs);\n            node = new_add(node, rhs);\n            continue;\n        }\n        if (equal(tok, "-")) {\n            Node *rhs = mul(&tok, tok->next);\n            reject_register_array_decay(node);\n            reject_register_array_decay(rhs);\n            node = new_sub(node, rhs);\n            continue;\n        }\n        *rest = tok;\n        return node;\n    }\n}\n''',
    'source pointer arithmetic conversion',
)

p = replace_once(
    p,
    '''        if (equal(tok, "[")) {\n            Node *idx = expr(&tok, tok->next);\n            tok = skip(tok, "]");\n            node = new_unary(ND_DEREF, new_add(node, idx));\n            continue;\n        }\n''',
    '''        if (equal(tok, "[")) {\n            Node *idx = expr(&tok, tok->next);\n            tok = skip(tok, "]");\n            reject_register_array_decay(node);\n            reject_register_array_decay(idx);\n            node = new_unary(ND_DEREF, new_add(node, idx));\n            continue;\n        }\n''',
    'subscript conversion',
)

p = replace_once(
    p,
    '''        Node *arg = assign(&tok, tok);\n        add_type(arg);\n\n        // Unprototyped calls and variadic tails have no declared parameter to\n''',
    '''        Node *arg = assign(&tok, tok);\n        add_type(arg);\n        reject_register_array_decay(arg);\n\n        // Unprototyped calls and variadic tails have no declared parameter to\n''',
    'call argument conversion',
)

p = replace_once(
    p,
    '''    Node *node = new_node(ND_EXPR_STMT);\n    if (!equal(tok, ";"))\n        node->lhs = expr(&tok, tok);\n    *rest = skip(tok, ";");\n    return node;\n}\n''',
    '''    Node *node = new_node(ND_EXPR_STMT);\n    if (!equal(tok, ";")) {\n        node->lhs = expr(&tok, tok);\n        reject_register_array_decay(node->lhs);\n    }\n    *rest = skip(tok, ";");\n    return node;\n}\n''',
    'expression statement conversion',
)

Path('parse.c').write_text(p)

# Extend the existing storage-class regression rather than creating a second
# overlapping suite.
path = Path('test/register_addressability.sh')
t = path.read_text()
anchor = '''# Unary & may not be applied to an object declared with register storage class.\n'''
insert = '''# sizeof is one of the standard contexts that does not perform array-to-pointer\n# conversion. Declaration initialization also remains valid: compiler-internal\n# stores must not be mistaken for source-level decay.\nassert_run 0 'int main(void){register int a[2]={1,2};return sizeof(a)==8?0:1;}'\nassert_run 0 'struct S{int a[2];};int main(void){register struct S s={{1,2}};return sizeof(s.a)==8?0:1;}'\n# Parameter array syntax is adjusted to a pointer type before register applies.\nassert_run 0 'int f(register int a[2]){return a[1]==7?0:1;}int main(void){int a[2]={3,7};return f(a);}'\n\n# C11 leaves array-to-pointer conversion of a register array undefined because\n# the conversion requires an unavailable address. Diagnose every supported\n# value context that would perform that conversion, matching strict GCC.\nassert_reject 'int main(void){register int a[2];int *p=a;return p!=0;}'\nassert_reject 'int *f(void){register int a[2];return a;}'\nassert_reject 'int main(void){register int a[2];_Bool b=a;return b;}'\nassert_reject 'int main(void){register int a[2];a;return 0;}'\nassert_reject 'int main(void){register int a[2];return a[0];}'\nassert_reject 'int main(void){register int a[2];return 0[a];}'\nassert_reject 'int main(void){register int a[2];return *a;}'\nassert_reject 'int main(void){register int a[2];int *p=a+1;return p!=0;}'\nassert_reject 'int main(void){register int a[2];int *p=1+a;return p!=0;}'\nassert_reject 'int main(void){register int a[2];if(a)return 1;return 0;}'\nassert_reject 'int main(void){register int a[2];return !a;}'\nassert_reject 'int main(void){register int a[2];int *p=0;return a==p;}'\nassert_reject 'int main(void){register int a[2];int *p=0;return a<p;}'\nassert_reject 'int main(void){register int a[2];int *p=(int*)a;return p!=0;}'\nassert_reject 'int main(void){register int a[2];(void)a;return 0;}'\nassert_reject 'int main(void){register int a[2];int *p=0;return (1?a:p)!=0;}'\nassert_reject 'int main(void){register int a[2];int *p=(0,a);return p!=0;}'\nassert_reject 'int main(void){register int a[2];(a,0);return 0;}'\nassert_reject 'int f(int *p){return p!=0;}int main(void){register int a[2];return f(a);}'\nassert_reject 'int f();int main(void){register int a[2];return f(a);}'\nassert_reject 'int f(int n,...){return n;}int main(void){register int a[2];return f(1,a);}'\nassert_reject 'int main(void){register int a[2];return _Generic(a,int*:1,default:0);}'\nassert_reject 'struct S{int a[2];};int main(void){register struct S s;int *p=s.a;return p!=0;}'\n\n'''
if anchor not in t:
    raise SystemExit('register test anchor missing')
t = t.replace(anchor, insert + anchor, 1)
path.write_text(t)

# Document strict handling beside the existing register-addressability claim.
path = Path('README.md')
t = path.read_text()
old = 'block-scope `auto`/`register` objects with single-storage-class constraint checking and C address-taking restrictions for register objects/parameters,'
new = 'block-scope `auto`/`register` objects with single-storage-class constraint checking, C address-taking restrictions for register objects/parameters, and strict diagnostics for register-array value conversions that require an address,'
if t.count(old) != 1:
    raise SystemExit(f'README register phrase: expected one match, found {t.count(old)}')
t = t.replace(old, new, 1)
path.write_text(t)
