from pathlib import Path

cg = Path('codegen.c')
text = cg.read_text()
old = '''    if (node->ty && node->ty->kind == TY_STRUCT)
        materialize_record_call(node);
}
'''
new = '''    // SysV places scalar integer return values in the low part of RAX. For
    // types narrower than 64 bits the remaining bits are not a C value and
    // must be interpreted according to the declared return type at the call
    // site. Canonicalize signed/unsigned bool/char/short/int exactly as loads
    // and casts do before any enclosing expression consumes the result.
    if (node->ty && node->ty->kind != TY_STRUCT)
        normalize(node->ty);

    if (node->ty && node->ty->kind == TY_STRUCT)
        materialize_record_call(node);
}
'''
if text.count(old) != 1:
    raise SystemExit(f'expected one function-call return anchor, found {text.count(old)}')
cg.write_text(text.replace(old, new, 1))

mk = Path('Makefile')
text = mk.read_text()
old = '''\tbash ./test/float_abi.sh
\tbash ./test/incomplete_tags.sh
'''
new = '''\tbash ./test/float_abi.sh
\tbash ./test/function_return_abi.sh
\tbash ./test/incomplete_tags.sh
'''
if text.count(old) != 1:
    raise SystemExit(f'expected one float ABI anchor, found {text.count(old)}')
mk.write_text(text.replace(old, new, 1))
