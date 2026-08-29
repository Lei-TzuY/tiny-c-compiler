from pathlib import Path

pp = Path('preprocess_v2.c')
text = pp.read_text()
old = '''    if (!strcmp(name, "stdint.h")) {
'''
insert = '''    if (!strcmp(name, "limits.h")) {
        return "#define CHAR_BIT 8\\n"
               "#define SCHAR_MIN (-127 - 1)\\n"
               "#define SCHAR_MAX 127\\n"
               "#define UCHAR_MAX 255\\n"
               "#define CHAR_MIN SCHAR_MIN\\n"
               "#define CHAR_MAX SCHAR_MAX\\n"
               "#define MB_LEN_MAX 1\\n"
               "#define SHRT_MIN (-32767 - 1)\\n"
               "#define SHRT_MAX 32767\\n"
               "#define USHRT_MAX 65535\\n"
               "#define INT_MIN (-2147483647 - 1)\\n"
               "#define INT_MAX 2147483647\\n"
               "#define UINT_MAX 4294967295U\\n"
               "#define LONG_MIN (-9223372036854775807L - 1)\\n"
               "#define LONG_MAX 9223372036854775807L\\n"
               "#define ULONG_MAX 18446744073709551615UL\\n"
               "#define LLONG_MIN (-9223372036854775807LL - 1)\\n"
               "#define LLONG_MAX 9223372036854775807LL\\n"
               "#define ULLONG_MAX 18446744073709551615ULL\\n";
    }
    if (!strcmp(name, "stdint.h")) {
'''
if text.count(old) != 1:
    raise SystemExit(f'expected one stdint anchor, found {text.count(old)}')
pp.write_text(text.replace(old, insert, 1))

mk = Path('Makefile')
text = mk.read_text()
old = '''\tbash ./test/stdalign_header.sh
\tbash ./test/stdint_header.sh
\tbash ./test/noreturn.sh
'''
new = '''\tbash ./test/stdalign_header.sh
\tbash ./test/stdint_header.sh
\tbash ./test/limits_header.sh
\tbash ./test/noreturn.sh
'''
if text.count(old) != 1:
    raise SystemExit(f'expected one stdint test anchor, found {text.count(old)}')
mk.write_text(text.replace(old, new, 1))
