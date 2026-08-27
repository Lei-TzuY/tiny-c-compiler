from pathlib import Path

# codegen.c: mark generated assembly as not requiring an executable stack.
p = Path('codegen.c')
s = p.read_text()
old = '''        printf("  ret\\n");
    }
}
'''
new = '''        printf("  ret\\n");
    }

    // GNU/ELF linkers treat an input object without this marker as potentially
    // requiring an executable stack. Generated C code never needs one, so emit
    // the conventional empty note section explicitly.
    printf("  .section .note.GNU-stack,\\\"\\\",@progbits\\n");
}
'''
if s.count(old) != 1:
    raise SystemExit(f'codegen tail anchor count={s.count(old)}')
p.write_text(s.replace(old, new, 1))

# Add a focused regression suite.
p = Path('test/gnu_stack.sh')
p.write_text(r'''#!/bin/bash
set -eu

cat > tmp-gnu-stack.c <<'EOF'
int main(){return 0;}
EOF

./minicc tmp-gnu-stack.c > tmp-gnu-stack.s

grep -F '.section .note.GNU-stack,"",@progbits' tmp-gnu-stack.s >/dev/null

cc -c -o tmp-gnu-stack.o tmp-gnu-stack.s
readelf -SW tmp-gnu-stack.o | grep -F '.note.GNU-stack' >/dev/null

# Linker warnings are fatal here so the historical
# "missing .note.GNU-stack section implies executable stack" regression cannot
# silently return.
cc -Wl,--fatal-warnings -o tmp-gnu-stack tmp-gnu-stack.o 2>tmp-gnu-stack.err
if grep -F 'missing .note.GNU-stack' tmp-gnu-stack.err >/dev/null; then
  cat tmp-gnu-stack.err
  exit 1
fi

# The resulting ELF must not request an executable GNU_STACK segment.
if readelf -W -l tmp-gnu-stack | grep 'GNU_STACK' | grep -q 'RWE'; then
  echo 'GNU_STACK is unexpectedly executable'
  readelf -W -l tmp-gnu-stack | grep 'GNU_STACK'
  exit 1
fi

./tmp-gnu-stack

echo 'All GNU-stack note tests passed!'
''')

# Makefile: wire the focused regression into the full suite.
p = Path('Makefile')
s = p.read_text()
old = '''\tbash ./test/arithmetic_conversions.sh\n'''
new = '''\tbash ./test/arithmetic_conversions.sh\n\tbash ./test/gnu_stack.sh\n'''
if s.count(old) != 1:
    raise SystemExit(f'Makefile test anchor count={s.count(old)}')
p.write_text(s.replace(old, new, 1))

# README: document the ELF stack hygiene guarantee in the build/test section.
p = Path('README.md')
s = p.read_text()
needle = '## Build and test\n\n'
if needle not in s:
    raise SystemExit('README build/test heading not found')
insert = '''The x86-64 ELF backend emits a `.note.GNU-stack` marker so generated objects do not request an executable process stack.\n\n'''
s = s.replace(needle, needle + insert, 1)
p.write_text(s)
