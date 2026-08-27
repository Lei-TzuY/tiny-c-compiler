from pathlib import Path

p = Path('codegen.c')
s = p.read_text()

anchor = '''static int align_up_cg(int n, int a) { return (n + a - 1) / a * a; }\n\nstatic void assign_lvar_offsets(Program *prog) {\n'''
replacement = '''static int align_up_cg(int n, int a) { return (n + a - 1) / a * a; }\n\n// File-scope and block-static objects must begin at an address satisfying their\n// declared type alignment. GAS data directives do not implicitly realign the\n// location counter, so a one-byte object emitted immediately before a long,\n// pointer, double or record would otherwise leave the later symbol misaligned.\nstatic void emit_data_alignment(Obj *var) {\n    int align = var->ty && var->ty->align > 0 ? var->ty->align : 1;\n    if (align > 1)\n        printf("  .balign %d\\n", align);\n}\n\nstatic void assign_lvar_offsets(Program *prog) {\n'''
if s.count(anchor) != 1:
    raise SystemExit(f'codegen helper anchor count={s.count(anchor)}')
s = s.replace(anchor, replacement, 1)

start = s.index('static void emit_data(Program *prog) {')
end = s.index('\nvoid codegen(Program *prog) {', start)
prefix = s[:start]
body = s[start:end]
suffix = s[end:]
label = '            printf("%s:\\n", var->name);\n'
count = body.count(label)
if count != 6:
    raise SystemExit(f'emit_data label count={count}, expected 6')
body = body.replace(label, '            emit_data_alignment(var);\n' + label)
p.write_text(prefix + body + suffix)

p = Path('Makefile')
s = p.read_text()
needle = '\tbash ./test/gnu_stack.sh\n'
if s.count(needle) != 1:
    raise SystemExit(f'Makefile anchor count={s.count(needle)}')
s = s.replace(needle, needle + '\tbash ./test/static_object_alignment.sh\n', 1)
p.write_text(s)

p = Path('README.md')
s = p.read_text()
needle = '- Union types retain their record kind through semantic analysis; automatic/static union initializers select exactly one member (the first by default or a designated member), preserve overlapping storage correctly, and reject excess initializer elements.\n'
addition = needle + '\n- Static-storage objects are emitted at their declared type alignment, including initialized/uninitialized scalars, relocatable pointers, arrays, records, unions, and block-static objects.\n'
if s.count(needle) != 1:
    raise SystemExit(f'README anchor count={s.count(needle)}')
p.write_text(s.replace(needle, addition, 1))

Path('test/static_object_alignment.sh').write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-static-align.c
  ./minicc tmp-static-align.c > tmp-static-align.s
  cc -o tmp-static-align tmp-static-align.s
  set +e
  ./tmp-static-align
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "static object alignment failed: expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(static object alignment): $actual"
}

# Globals are stored in reverse declaration order internally. Put a one-byte
# object after each target declaration so it is emitted immediately before the
# target and exposes missing alignment directives deterministically.
assert_run 0 'long x=1; char pad; int main(){return (unsigned long)&x%8;}'
assert_run 0 'double x=1.25; char pad; int main(){return (unsigned long)&x%8;}'
assert_run 0 'int x=3; char pad; int main(){return (unsigned long)&x%4;}'
assert_run 0 'short x=3; char pad; int main(){return (unsigned long)&x%2;}'

# Zero-initialized storage and scalar linker-relocation storage use separate
# emitter branches and require the same type alignment guarantee.
assert_run 0 'long x; char pad; int main(){return (unsigned long)&x%8;}'
assert_run 0 'int g; int *p=&g; char pad; int main(){return (unsigned long)&p%8;}'

# Typed static aggregate images must honor their aggregate/base alignment, not
# merely preserve internal member padding.
assert_run 0 'long a[2]={1,2}; char pad; int main(){return (unsigned long)&a%8;}'
assert_run 0 'int a[2]={1,2}; char pad; int main(){return (unsigned long)&a%4;}'
assert_run 0 'struct S{char c;long x;}; struct S s={1,2}; char pad; int main(){return (unsigned long)&s%8;}'
assert_run 0 'union U{char c;long x;}; union U u={.x=7}; char pad; int main(){return (unsigned long)&u%8;}'

# Block-static objects are emitted through the same global data path despite
# being declared inside a function.
assert_run 0 'int main(){static long x=1; static char pad; return (unsigned long)&x%8;}'
assert_run 0 'int main(){struct S{char c;long x;}; static struct S s={1,2}; static char pad; return (unsigned long)&s%8;}'

echo 'All static-object alignment tests passed!'
''')
