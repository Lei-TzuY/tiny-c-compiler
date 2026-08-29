from pathlib import Path

pp = Path('preprocess_v2.c')
text = pp.read_text()
old = '''    if (!strcmp(name, "stdalign.h")) {
        return "#define alignas _Alignas\\n"
               "#define alignof _Alignof\\n"
               "#define __alignas_is_defined 1\\n"
               "#define __alignof_is_defined 1\\n";
    }
    if (!strcmp(name, "stdarg.h")) {
'''
new = '''    if (!strcmp(name, "stdalign.h")) {
        return "#define alignas _Alignas\\n"
               "#define alignof _Alignof\\n"
               "#define __alignas_is_defined 1\\n"
               "#define __alignof_is_defined 1\\n";
    }
    if (!strcmp(name, "stdint.h")) {
        return "typedef signed char int8_t;\\n"
               "typedef unsigned char uint8_t;\\n"
               "typedef short int16_t;\\n"
               "typedef unsigned short uint16_t;\\n"
               "typedef int int32_t;\\n"
               "typedef unsigned int uint32_t;\\n"
               "typedef long int64_t;\\n"
               "typedef unsigned long uint64_t;\\n"
               "typedef signed char int_least8_t;\\n"
               "typedef unsigned char uint_least8_t;\\n"
               "typedef short int_least16_t;\\n"
               "typedef unsigned short uint_least16_t;\\n"
               "typedef int int_least32_t;\\n"
               "typedef unsigned int uint_least32_t;\\n"
               "typedef long int_least64_t;\\n"
               "typedef unsigned long uint_least64_t;\\n"
               "typedef long int_fast8_t;\\n"
               "typedef unsigned long uint_fast8_t;\\n"
               "typedef long int_fast16_t;\\n"
               "typedef unsigned long uint_fast16_t;\\n"
               "typedef long int_fast32_t;\\n"
               "typedef unsigned long uint_fast32_t;\\n"
               "typedef long int_fast64_t;\\n"
               "typedef unsigned long uint_fast64_t;\\n"
               "typedef long intptr_t;\\n"
               "typedef unsigned long uintptr_t;\\n"
               "typedef long long intmax_t;\\n"
               "typedef unsigned long long uintmax_t;\\n"
               "#define INT8_MIN (-127 - 1)\\n"
               "#define INT8_MAX 127\\n"
               "#define UINT8_MAX 255\\n"
               "#define INT16_MIN (-32767 - 1)\\n"
               "#define INT16_MAX 32767\\n"
               "#define UINT16_MAX 65535\\n"
               "#define INT32_MIN (-2147483647 - 1)\\n"
               "#define INT32_MAX 2147483647\\n"
               "#define UINT32_MAX 4294967295U\\n"
               "#define INT64_MIN (-9223372036854775807L - 1)\\n"
               "#define INT64_MAX 9223372036854775807L\\n"
               "#define UINT64_MAX 18446744073709551615UL\\n"
               "#define INT_LEAST8_MIN INT8_MIN\\n"
               "#define INT_LEAST8_MAX INT8_MAX\\n"
               "#define UINT_LEAST8_MAX UINT8_MAX\\n"
               "#define INT_LEAST16_MIN INT16_MIN\\n"
               "#define INT_LEAST16_MAX INT16_MAX\\n"
               "#define UINT_LEAST16_MAX UINT16_MAX\\n"
               "#define INT_LEAST32_MIN INT32_MIN\\n"
               "#define INT_LEAST32_MAX INT32_MAX\\n"
               "#define UINT_LEAST32_MAX UINT32_MAX\\n"
               "#define INT_LEAST64_MIN INT64_MIN\\n"
               "#define INT_LEAST64_MAX INT64_MAX\\n"
               "#define UINT_LEAST64_MAX UINT64_MAX\\n"
               "#define INT_FAST8_MIN INT64_MIN\\n"
               "#define INT_FAST8_MAX INT64_MAX\\n"
               "#define UINT_FAST8_MAX UINT64_MAX\\n"
               "#define INT_FAST16_MIN INT64_MIN\\n"
               "#define INT_FAST16_MAX INT64_MAX\\n"
               "#define UINT_FAST16_MAX UINT64_MAX\\n"
               "#define INT_FAST32_MIN INT64_MIN\\n"
               "#define INT_FAST32_MAX INT64_MAX\\n"
               "#define UINT_FAST32_MAX UINT64_MAX\\n"
               "#define INT_FAST64_MIN INT64_MIN\\n"
               "#define INT_FAST64_MAX INT64_MAX\\n"
               "#define UINT_FAST64_MAX UINT64_MAX\\n"
               "#define INTPTR_MIN INT64_MIN\\n"
               "#define INTPTR_MAX INT64_MAX\\n"
               "#define UINTPTR_MAX UINT64_MAX\\n"
               "#define INTMAX_MIN (-9223372036854775807LL - 1)\\n"
               "#define INTMAX_MAX 9223372036854775807LL\\n"
               "#define UINTMAX_MAX 18446744073709551615ULL\\n"
               "#define INT8_C(value) value\\n"
               "#define UINT8_C(value) value\\n"
               "#define INT16_C(value) value\\n"
               "#define UINT16_C(value) value\\n"
               "#define INT32_C(value) value\\n"
               "#define UINT32_C(value) value ## U\\n"
               "#define INT64_C(value) value ## L\\n"
               "#define UINT64_C(value) value ## UL\\n"
               "#define INTMAX_C(value) value ## LL\\n"
               "#define UINTMAX_C(value) value ## ULL\\n";
    }
    if (!strcmp(name, "stdarg.h")) {
'''
if text.count(old) != 1:
    raise SystemExit(f'expected one stdalign/stdarg anchor, found {text.count(old)}')
pp.write_text(text.replace(old, new, 1))

mk = Path('Makefile')
text = mk.read_text()
old = '''\tbash ./test/alignof.sh
\tbash ./test/alignas.sh
\tbash ./test/stdalign_header.sh
\tbash ./test/noreturn.sh
'''
new = '''\tbash ./test/alignof.sh
\tbash ./test/alignas.sh
\tbash ./test/stdalign_header.sh
\tbash ./test/stdint_header.sh
\tbash ./test/noreturn.sh
'''
if text.count(old) != 1:
    raise SystemExit(f'expected one stdalign test anchor, found {text.count(old)}')
mk.write_text(text.replace(old, new, 1))
