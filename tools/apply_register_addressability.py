from pathlib import Path


def replace_once(path, old, new, label):
    p = Path(path)
    s = p.read_text()
    if old not in s:
        raise SystemExit(f"missing anchor for {label} in {path}")
    p.write_text(s.replace(old, new, 1))


replace_once(
    "minicc.h",
    '''    bool is_static;    // static storage class\n    bool is_extern;    // extern storage class\n    bool is_defined;   // function symbol already has a body\n''',
    '''    bool is_static;    // static storage class\n    bool is_extern;    // extern storage class\n    bool is_register;  // register storage class; address may not be taken\n    bool is_defined;   // function symbol already has a body\n''',
    "Obj register storage metadata",
)

replace_once(
    "parse.c",
    '''static bool is_addressable_expr(Node *node) {\n    add_type(node);\n\n    // A function designator is not an lvalue in C, but unary & is explicitly\n    // permitted on one. Both a named function and *function_pointer reach\n    // here with TY_FUNC.\n    if (node->ty->kind == TY_FUNC)\n        return node->kind == ND_VAR || node->kind == ND_DEREF;\n    return is_lvalue(node);\n}\n''',
    '''// `register` forbids applying unary & to the declared object. Member\n// access still depends on the containing object, so `&r.member` must reject\n// when `r` itself is register-qualified. Dereference breaks that chain:\n// taking `&*p` or `&p->member` is valid even when the pointer object `p` was\n// declared register, because the addressed object is the pointee.\nstatic bool is_register_based_lvalue(Node *node) {\n    if (!node)\n        return false;\n    if (node->kind == ND_VAR)\n        return node->var && node->var->is_register;\n    if (node->kind == ND_MEMBER)\n        return is_register_based_lvalue(node->lhs);\n    return false;\n}\n\nstatic bool is_addressable_expr(Node *node) {\n    add_type(node);\n\n    // A function designator is not an lvalue in C, but unary & is explicitly\n    // permitted on one. Both a named function and *function_pointer reach\n    // here with TY_FUNC.\n    if (node->ty->kind == TY_FUNC)\n        return node->kind == ND_VAR || node->kind == ND_DEREF;\n    if (!is_lvalue(node))\n        return false;\n    return !is_register_based_lvalue(node);\n}\n''',
    "register-aware addressability",
)

replace_once(
    "parse.c",
    '''        Obj *param = calloc(1, sizeof(Obj));\n        param->ty = param_ty;\n        if (name)\n            param->name = strndup(name->loc, name->len);\n''',
    '''        Obj *param = calloc(1, sizeof(Obj));\n        param->ty = param_ty;\n        param->is_register = param_attrs.is_register;\n        if (name)\n            param->name = strndup(name->loc, name->len);\n''',
    "parameter register metadata",
)

replace_once(
    "parse.c",
    '''        apply_object_alignment(var, ty, attrs.align, ident);\n\n        if (!equal(tok, "="))\n            continue;\n''',
    '''        apply_object_alignment(var, ty, attrs.align, ident);\n        var->is_register = attrs.is_register;\n\n        if (!equal(tok, "="))\n            continue;\n''',
    "block object register metadata",
)

replace_once(
    "parse.c",
    '''                Obj *var = create_lvar(meta->name);\n                var->ty = meta->ty;\n                pcur = pcur->param_next = var;\n''',
    '''                Obj *var = create_lvar(meta->name);\n                var->ty = meta->ty;\n                var->is_register = meta->is_register;\n                pcur = pcur->param_next = var;\n''',
    "function-definition register parameter propagation",
)

replace_once(
    "Makefile",
    '''\tbash ./test/storage_class_specifiers.sh\n''',
    '''\tbash ./test/storage_class_specifiers.sh\n\tbash ./test/register_addressability.sh\n''',
    "register addressability test target",
)

replace_once(
    "README.md",
    "block-scope `auto` objects with single-storage-class constraint checking, C11 `_Noreturn`",
    "block-scope `auto`/`register` objects with single-storage-class constraint checking and C address-taking restrictions for register objects/parameters, C11 `_Noreturn`",
    "README register addressability support",
)
