from pathlib import Path

pp = Path('preprocess_v2.c')
text = pp.read_text()
old = '''    if (!strcmp(name, "stdnoreturn.h")) {
        return "#define noreturn _Noreturn\\n";
    }
    if (!strcmp(name, "stdarg.h")) {
'''
new = '''    if (!strcmp(name, "stdnoreturn.h")) {
        return "#define noreturn _Noreturn\\n";
    }
    if (!strcmp(name, "stdalign.h")) {
        return "#define alignas _Alignas\\n"
               "#define alignof _Alignof\\n"
               "#define __alignas_is_defined 1\\n"
               "#define __alignof_is_defined 1\\n";
    }
    if (!strcmp(name, "stdarg.h")) {
'''
if text.count(old) != 1:
    raise SystemExit(f'expected one stdnoreturn/stdarg anchor, found {text.count(old)}')
pp.write_text(text.replace(old, new, 1))

mk = Path('Makefile')
text = mk.read_text()
old = '''\tbash ./test/alignof.sh
\tbash ./test/alignas.sh
\tbash ./test/noreturn.sh
'''
new = '''\tbash ./test/alignof.sh
\tbash ./test/alignas.sh
\tbash ./test/stdalign_header.sh
\tbash ./test/noreturn.sh
'''
if text.count(old) != 1:
    raise SystemExit(f'expected one alignas test anchor, found {text.count(old)}')
mk.write_text(text.replace(old, new, 1))
