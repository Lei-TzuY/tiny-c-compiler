from pathlib import Path


def replace_once(text, old, new, label):
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"{label}: expected one anchor, found {n}")
    return text.replace(old, new, 1)

# Shared support predicate: parser firewall and backend must agree exactly.
p = Path('minicc.h')
s = p.read_text()
s = replace_once(s,
'''bool is_numeric(Type *ty);\nType *pointer_to(Type *base);\n''',
'''bool is_numeric(Type *ty);\nint sysv_integer_record_slots(Type *ty);\nType *pointer_to(Type *base);\n''', 'header ABI classifier')
p.write_text(s)

p = Path('type.c')
s = p.read_text()
anchor = '''bool is_numeric(Type *ty) {\n    return is_integer(ty) || is_flonum(ty);\n}\n'''
addition = anchor + r'''

// Conservative SysV AMD64 aggregate subset shared by semantic ABI checks and
// code generation. A record is supported by value only when its complete
// representation fits in one or two eightbytes and every leaf is INTEGER-class.
// Arrays/nested records recurse; floating/SSE and >16-byte MEMORY shapes stay
// behind the ABI firewall until their full classifier/lowering is implemented.
static bool sysv_integer_record_component(Type *ty) {
    if (!ty)
        return false;
    if (is_integer(ty) || ty->kind == TY_PTR)
        return true;
    if (ty->kind == TY_ARRAY)
        return ty->array_len > 0 && sysv_integer_record_component(ty->base);
    if (ty->kind == TY_STRUCT) {
        if (ty->is_incomplete || !ty->members)
            return false;
        for (Member *m = ty->members; m; m = m->next)
            if (!sysv_integer_record_component(m->ty))
                return false;
        return true;
    }
    return false;
}

int sysv_integer_record_slots(Type *ty) {
    if (!ty || ty->kind != TY_STRUCT || ty->is_incomplete ||
        ty->size <= 0 || ty->size > 16 || !sysv_integer_record_component(ty))
        return 0;
    return (ty->size + 7) / 8;
}
'''
s = replace_once(s, anchor, addition, 'type ABI classifier')
p.write_text(s)

# Replace the first implementation's private classifier with the shared one.
p = Path('codegen.c')
s = p.read_text()
start = s.index('// This focused SysV subset supports by-value records whose complete object')
req = s.index('static int require_integer_record_abi(Type *ty) {', start)
old_prefix = s[start:req]
new_prefix = '''// The parser and backend share one conservative SysV classification predicate,\n// so an accepted by-value record cannot drift into a different lowering here.\n'''
s = s[:start] + new_prefix + s[req:]
s = s.replace('int slots = integer_record_abi_slots(ty);',
              'int slots = sysv_integer_record_slots(ty);')
p.write_text(s)

# Evolve PR #49's blanket firewall into a shape-aware one and allocate hidden
# materialization slots for supported aggregate-returning calls.
p = Path('parse.c')
s = p.read_text()
old = r'''// Record object operations are supported inside a function, but the backend has
// not yet implemented the SysV AMD64 aggregate argument/return classification.
// Reject only actual ABI boundaries so harmless prototypes/typedefs remain
// representable while code generation can never silently pass an object address
// where the ABI requires record bytes/register classes or a hidden sret pointer.
static void check_supported_function_abi(Type *fty, Token *at) {
    if (!fty || fty->kind != TY_FUNC)
        return;

    if (fty->return_ty && fty->return_ty->kind == TY_STRUCT)
        error_at(at->loc,
                 "record return by value is not supported by the x86-64 backend");

    if (!fty->has_prototype)
        return;
    for (Obj *param = fty->params; param; param = param->param_next)
        if (param->ty && param->ty->kind == TY_STRUCT)
            error_at(at->loc,
                     "record parameter by value is not supported by the x86-64 backend");
}
'''
new = r'''// Keep PR #49's ABI firewall, but open the INTEGER-only subset that the backend
// can now lower exactly. Prototypes may still describe unsupported shapes when
// unused; definitions/calls reject floating/SSE or >16-byte record boundaries.
static void check_supported_function_abi(Type *fty, Token *at) {
    if (!fty || fty->kind != TY_FUNC)
        return;

    if (fty->return_ty && fty->return_ty->kind == TY_STRUCT &&
        !sysv_integer_record_slots(fty->return_ty))
        error_at(at->loc, "unsupported record return ABI for x86-64 backend");

    if (!fty->has_prototype)
        return;
    for (Obj *param = fty->params; param; param = param->param_next)
        if (param->ty && param->ty->kind == TY_STRUCT &&
            !sysv_integer_record_slots(param->ty))
            error_at(at->loc, "unsupported record parameter ABI for x86-64 backend");
}
'''
s = replace_once(s, old, new, 'shape-aware ABI firewall')

old = r'''        // An unprototyped call or variadic tail has no declared parameter to
        // inspect ahead of time. Catch aggregate values from their actual type
        // so these paths cannot bypass the same backend ABI limitation.
        if (arg->ty && arg->ty->kind == TY_STRUCT)
            error_at(arg_tok->loc,
                     "record argument by value is not supported by the x86-64 backend");
'''
new = r'''        // Unprototyped calls and variadic tails have no declared parameter to
        // inspect, so classify an aggregate from its actual type. Supported
        // INTEGER-class records use the same caller lowering as fixed params.
        if (arg->ty && arg->ty->kind == TY_STRUCT &&
            !sysv_integer_record_slots(arg->ty))
            error_at(arg_tok->loc, "unsupported record argument ABI for x86-64 backend");
'''
s = replace_once(s, old, new, 'actual aggregate firewall')

anchor = r'''static Obj *create_lvar(char *name) {
    Obj *var = calloc(1, sizeof(Obj));
    var->name = name;
    var->is_local = true;
    var->next = locals;
    locals = var;

    VarScope *vs = calloc(1, sizeof(VarScope));
    vs->name = name;
    vs->var = var;
    vs->next = current_scope->vars;
    current_scope->vars = vs;

    return var;
}
'''
addition = anchor + r'''

// Aggregate expressions are represented by an address in the backend. A small
// record returned in RAX/RDX is therefore materialized into an anonymous local
// immediately after the call, preserving ordinary record-expression behavior.
static void prepare_record_call_result(Node *node) {
    if (!current_return_ty || !node || !node->ty ||
        !sysv_integer_record_slots(node->ty))
        return;

    Obj *buf = create_lvar(new_unique_name());
    buf->ty = node->ty;
    node->ret_buffer = buf;
}
'''
s = replace_once(s, anchor, addition, 'record result temp helper')

old = '''    tok = skip(tok, "(");\n    node->args = parse_call_arguments(&tok, tok, fty);\n    *rest = tok;\n    return node;\n}\n\nstatic Node *postfix'''
new = '''    tok = skip(tok, "(");\n    node->args = parse_call_arguments(&tok, tok, fty);\n    prepare_record_call_result(node);\n    *rest = tok;\n    return node;\n}\n\nstatic Node *postfix'''
s = replace_once(s, old, new, 'indirect return temp')

old = '''                tok = skip(tok->next, "(");\n                node->args = parse_call_arguments(&tok, tok, fty);\n                *rest = tok;\n                return node;\n'''
new = '''                tok = skip(tok->next, "(");\n                node->args = parse_call_arguments(&tok, tok, fty);\n                prepare_record_call_result(node);\n                *rest = tok;\n                return node;\n'''
s = replace_once(s, old, new, 'direct return temp')
p.write_text(s)

# Keep the firewall regression suite, but make it verify the new frontier.
Path('test/record_abi_firewall.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-record-firewall.c
  ./minicc tmp-record-firewall.c > tmp-record-firewall.s
  cc -o tmp-record-firewall tmp-record-firewall.s
  set +e
  ./tmp-record-firewall
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "record ABI frontier failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(record ABI frontier): $actual"
}

assert_fail() {
  input="$1"
  printf '%s\n' "$input" > tmp-record-firewall-bad.c
  if ./minicc tmp-record-firewall-bad.c > tmp-record-firewall-bad.s 2>/dev/null; then
    echo 'record ABI frontier unexpectedly accepted unsupported shape'
    echo "$input"
    exit 1
  fi
  echo 'OK(record ABI frontier): rejected unsupported record ABI'
}

# Pointer boundaries and local record operations remain valid.
assert_run 7 'struct S{int x;};int get(struct S *p){return p->x;}int main(){struct S s;s.x=7;return get(&s);}'
assert_run 11 'struct S{int x;};struct S *id(struct S *p){return p;}int main(){struct S s;s.x=11;return id(&s)->x;}'
assert_run 9 'union U{int x;long y;};long get(union U *p){return p->y;}int main(){union U u;u.y=9;return get(&u);}'
assert_run 5 'struct S{int x;};int get(struct S a[]){return a[0].x;}int main(){struct S a[1];a[0].x=5;return get(a);}'

# PR #49's former blanket-rejection cases are now valid INTEGER-class ABI.
assert_run 7 'struct S{int x;};int f(struct S s){return s.x;}int main(){struct S s={7};return f(s);}'
assert_run 9 'union U{long x;};long f(union U u){return u.x;}int main(){union U u={.x=9};return f(u);}'
assert_run 6 'struct S{int x;};struct S f(void){struct S s={6};return s;}int main(){return f().x;}'
assert_run 8 'union U{long x;};union U f(void){union U u={.x=8};return u;}int main(){return f().x;}'
assert_run 4 'struct S{int x;};int id(struct S s){return s.x;}int main(){int (*fp)(struct S)=id;struct S s={4};return fp(s);}'

# Unsupported classes remain safely diagnosed at actual ABI boundaries.
assert_fail 'struct F{double x;};int f(struct F x){return 0;}int main(){return 0;}'
assert_fail 'struct M{double x;long y;};long f(struct M x){return x.y;}int main(){return 0;}'
assert_fail 'struct Big{long a;long b;long c;};long f(struct Big x){return x.a;}int main(){return 0;}'
assert_fail 'struct F{double x;};struct F f(void){struct F x={1.0};return x;}int main(){return 0;}'
assert_fail 'struct Big{long a;long b;long c;};struct Big f(void){struct Big x={1,2,3};return x;}int main(){return 0;}'

# Unsupported prototypes remain representable if never crossed.
assert_run 0 'struct F{double x;};struct F ext(struct F);int main(){return 0;}'

# Actual aggregate type still protects unprototyped/variadic paths.
assert_fail 'struct F{double x;};int f();int main(){struct F x={1.0};return f(x);}'
assert_fail 'struct F{double x;};int f(int,...);int main(){struct F x={1.0};return f(1,x);}'

echo 'All record-ABI frontier tests passed!'
''')

# Run the detailed interoperability suite in addition to the firewall/frontier.
p = Path('Makefile')
s = p.read_text()
s = replace_once(s, '\tbash ./test/record_abi_firewall.sh\n',
                    '\tbash ./test/record_abi_firewall.sh\n\tbash ./test/sysv_record_abi.sh\n',
                    'Makefile SysV record suite')
p.write_text(s)

p = Path('README.md')
s = p.read_text()
old = '- **Record types**: `struct`/`union` forward declarations, completion-in-place, recursive pointer members, and block-scoped tags. Incomplete records are permitted behind pointers/`extern` declarations and rejected where object size is required. Record objects support local assignment and aggregate initialization; by-value record parameters/returns are intentionally diagnosed at function definitions and calls until SysV AMD64 aggregate classification/return lowering is implemented, while record pointers remain fully supported at function boundaries.\n'
new = '- **Record types**: `struct`/`union` forward declarations, completion-in-place, recursive pointer members, and block-scoped tags. Incomplete records are permitted behind pointers/`extern` declarations and rejected where object size is required. Record objects support local assignment and aggregate initialization. SysV AMD64 by-value calls/returns support records up to 16 bytes whose leaves classify entirely as INTEGER (integers, pointers, arrays/nested records of those); larger or floating/SSE-class records remain diagnosed at actual ABI boundaries, while record pointers are fully supported.\n'
s = replace_once(s, old, new, 'README ABI frontier')
note = '- Character-array string initialization is supported recursively inside automatic/static aggregates, including struct/union members, multidimensional character arrays, and designated subobjects, with C-compatible NUL truncation and zero-fill.\n'
s = replace_once(s, note, note + '\n- Small INTEGER-class records use the SysV AMD64 by-value ABI across direct/indirect calls and returns, including whole-record stack fallback when remaining GP registers cannot hold every eightbyte and interoperability with host-compiled C.\n', 'README ABI note')
p.write_text(s)
