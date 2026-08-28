from pathlib import Path


def replace_once(path, old, new, label):
    p = Path(path)
    s = p.read_text()
    if old not in s:
        raise SystemExit(f"missing anchor for {label} in {path}")
    p.write_text(s.replace(old, new, 1))

replace_once(
    "parse.c",
    '''static Type *enum_decl(Token **rest, Token *tok) {\n''',
    '''// C11 enumerator identifiers have type int, and every enumerator value\n// must be representable as int. Evaluate using the expression's actual signedness\n// first so large unsigned constants cannot masquerade as negative int64_t values.\nstatic int64_t eval_enum_value(Node *node, Token *at) {\n    add_type(node);\n    if (!node->ty || !is_integer(node->ty))\n        error_at(at->loc, "enumerator value must be an integer constant expression");\n\n    int64_t raw = eval_const_expr(node);\n    if (node->ty->is_unsigned) {\n        uint64_t value = (uint64_t)cast_const_integer(raw, node->ty);\n        if (value > INT32_MAX)\n            error_at(at->loc, "enumerator value is not representable as int");\n        return (int64_t)value;\n    }\n\n    int64_t value = cast_const_integer(raw, node->ty);\n    if (value < INT32_MIN || value > INT32_MAX)\n        error_at(at->loc, "enumerator value is not representable as int");\n    return value;\n}\n\nstatic Type *enum_decl(Token **rest, Token *tok) {\n''',
    "enum range helper",
)
replace_once(
    "parse.c",
    '''    tok = skip(tok, "{");\n    int64_t val = 0;\n\n    while (!equal(tok, "}")) {\n        if (tok->kind != TK_IDENT)\n            error_at(tok->loc, "expected enumerator name");\n\n        Token *enumerator = tok;\n        tok = tok->next;\n\n        if (consume(&tok, tok, "=")) {\n            Node *value = ternary(&tok, tok);\n            val = eval_const_expr(value);\n        }\n\n        push_enum_const(enumerator, val++);\n\n        if (consume(&tok, tok, ","))\n            continue;\n''',
    '''    tok = skip(tok, "{");\n    int64_t next_val = 0;\n    bool implicit_value_valid = true;\n\n    while (!equal(tok, "}")) {\n        if (tok->kind != TK_IDENT)\n            error_at(tok->loc, "expected enumerator name");\n\n        Token *enumerator = tok;\n        tok = tok->next;\n\n        int64_t val;\n        if (consume(&tok, tok, "=")) {\n            Node *value = ternary(&tok, tok);\n            val = eval_enum_value(value, enumerator);\n        } else {\n            if (!implicit_value_valid)\n                error_at(enumerator->loc,\n                         "implicit enumerator value is not representable as int");\n            val = next_val;\n        }\n\n        push_enum_const(enumerator, val);\n        if (val == INT32_MAX) {\n            implicit_value_valid = false;\n        } else {\n            next_val = val + 1;\n            implicit_value_valid = true;\n        }\n\n        if (consume(&tok, tok, ","))\n            continue;\n''',
    "enum implicit value tracking",
)
replace_once(
    "Makefile",
    '''\tbash ./test/enum_constexpr_tags.sh\n''',
    '''\tbash ./test/enum_constexpr_tags.sh\n\tbash ./test/enum_value_range.sh\n''',
    "enum range test target",
)
replace_once(
    "README.md",
    '''enumerators accept integer constant expressions\n''',
    '''enumerators accept integer constant expressions whose values are representable as `int`\n''',
    "README enum range semantics",
)
