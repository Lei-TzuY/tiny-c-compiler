#!/usr/bin/env python3
from pathlib import Path
import runpy

helper = Path('tools/migrate_long_double.py')
s = helper.read_text()

# Static scalar emission is patched below because quoting PRI macros inside the
# generated Python replacement is unnecessarily fragile.
start = s.index('# static scalar emission\n')
end = s.index('# named parameter stack handling:', start)
s = s[:start] + '# static scalar emission handled by runner\n' + s[end:]

# parse.c's scalar compatibility switch intentionally falls through `default:
# return true` for arithmetic kinds, so TY_LDOUBLE needs no dedicated case.
marker = 'parse type compatibility")\n'
end = s.index(marker) + len(marker)
start = s.rfind('p = rep(p,', 0, end)
if start < 0:
    raise SystemExit('parse compatibility migration block not found')
s = s[:start] + '# scalar compatibility already handled by default branch\n' + s[end:]
helper.write_text(s)

runpy.run_path(str(helper), run_name='__main__')

p = Path('codegen.c')
s = p.read_text()
old = '''            if (var->ty->kind == TY_FLOAT) {
                union { float f; uint32_t u; } u = { (float)var->finit_val };
                printf("  .long %" PRIu32 "\\n", u.u);
            } else if (var->ty->kind == TY_DOUBLE) {
                union { double d; uint64_t u; } u = { var->finit_val };
                printf("  .quad %" PRIu64 "\\n", u.u);
            } else if (var->ty->size == 1)
'''
new = '''            if (var->ty->kind == TY_FLOAT) {
                union { float f; uint32_t u; } u = { (float)var->finit_val };
                printf("  .long %" PRIu32 "\\n", u.u);
            } else if (var->ty->kind == TY_DOUBLE) {
                union { double d; uint64_t u; } u = { (double)var->finit_val };
                printf("  .quad %" PRIu64 "\\n", u.u);
            } else if (var->ty->kind == TY_LDOUBLE) {
                unsigned char raw[16] = {0};
                long double ld = var->finit_val;
                memcpy(raw, &ld, sizeof(ld));
                for (int i = 0; i < 16; i++)
                    printf("  .byte %u\\n", raw[i]);
            } else if (var->ty->size == 1)
'''
if s.count(old) != 1:
    raise SystemExit(f'static emission anchor count={s.count(old)}')
p.write_text(s.replace(old, new))
print('long double migration runner complete')
