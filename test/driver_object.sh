#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

fail() {
  echo "FAIL(object driver): $*" >&2
  exit 1
}

rm -rf tmp-object-driver-dir
rm -f object-driver.o object-driver-custom.o object-driver-pipe.o object-driver-stdin.o \
      object-driver-md.o object-driver-md.d object-driver-custom.d \
      object-driver-keep.o object-driver-bad.c object-driver-bad.err \
      object-driver.err object-driver.c
mkdir -p tmp-object-driver-dir

cat > tmp-object-driver-dir/object-driver.c <<'EOF'
int add(int a, int b) { return a + b; }
int main(void) { return add(20, 22) == 42 ? 0 : 1; }
EOF

# -c without -o follows compiler-driver convention and emits basename.o in CWD.
"$MINICC" -c tmp-object-driver-dir/object-driver.c
[ -f object-driver.o ] || fail "default object output was not created"
cc object-driver.o -o tmp-object-driver-dir/default-bin
./tmp-object-driver-dir/default-bin || fail "default object did not link/run"
readelf -h object-driver.o | grep -q 'REL (Relocatable file)' || \
  fail "default output is not an ELF relocatable object"

# Explicit object output paths are honored without exposing the temporary assembly.
"$MINICC" -c tmp-object-driver-dir/object-driver.c -o object-driver-custom.o
cc object-driver-custom.o -o tmp-object-driver-dir/custom-bin
./tmp-object-driver-dir/custom-bin || fail "explicit object did not link/run"
[ ! -e object-driver-custom.o.tmp.XXXXXX ] || fail "temporary object path leaked"

# Binary stdout is supported when -o - is requested.
"$MINICC" -c tmp-object-driver-dir/object-driver.c -o - > object-driver-pipe.o
cc object-driver-pipe.o -o tmp-object-driver-dir/pipe-bin
./tmp-object-driver-dir/pipe-bin || fail "stdout object did not link/run"

# Standard input is accepted when an object output name is supplied.
printf '%s\n' 'int answer(void){return 42;}' | "$MINICC" -c - -o object-driver-stdin.o
cat > tmp-object-driver-dir/stdin-main.c <<'EOF'
int answer(void);
int main(void) { return answer() == 42 ? 0 : 1; }
EOF
cc tmp-object-driver-dir/stdin-main.c object-driver-stdin.o -o tmp-object-driver-dir/stdin-bin
./tmp-object-driver-dir/stdin-bin || fail "stdin object did not link/run"

if printf '%s\n' 'int x;' | "$MINICC" -c - >/dev/null 2>object-driver.err; then
  fail "-c stdin without -o should be rejected"
fi
grep -q "standard input requires '-o'" object-driver.err || \
  fail "stdin diagnostic is missing"

for mode in -S -E -fsyntax-only; do
  if "$MINICC" -c "$mode" tmp-object-driver-dir/object-driver.c >/dev/null 2>object-driver.err; then
    fail "-c $mode should be rejected"
  fi
done

# Dependency side effects follow the object target rather than the assembly target.
cp tmp-object-driver-dir/object-driver.c object-driver.c
"$MINICC" -c -MD object-driver.c
[ -f object-driver.o ] || fail "-MD object output missing"
[ -f object-driver.d ] || fail "-MD dependency output missing"
grep -q '^object-driver\.o: object-driver\.c' object-driver.d || \
  fail "-MD default target is not the object file"

"$MINICC" -c -MD object-driver.c -o object-driver-md.o
[ -f object-driver-md.d ] || fail "explicit object dependency output missing"
grep -q '^object-driver-md\.o: object-driver\.c' object-driver-md.d || \
  fail "explicit -o dependency target is incorrect"

# Frontend or assembler failure must not clobber a pre-existing object output.
printf 'KEEP-ME\n' > object-driver-keep.o
cat > object-driver-bad.c <<'EOF'
int main( { return 0; }
EOF
if "$MINICC" -c object-driver-bad.c -o object-driver-keep.o >/dev/null 2>object-driver-bad.err; then
  fail "frontend failure unexpectedly succeeded"
fi
grep -q '^KEEP-ME$' object-driver-keep.o || fail "frontend failure clobbered output"

if MINICC_AS=false "$MINICC" -c object-driver.c -o object-driver-keep.o >/dev/null 2>object-driver.err; then
  fail "assembler failure unexpectedly succeeded"
fi
grep -q '^KEEP-ME$' object-driver-keep.o || fail "assembler failure clobbered output"
if find . -maxdepth 1 -name 'object-driver-keep.o.tmp.*' | grep -q .; then
  fail "assembler failure leaked temporary object"
fi
grep -q "assembler 'false' failed" object-driver.err || \
  fail "assembler failure diagnostic is missing"

# Object stdout and dependency stdout cannot share the same stream.
if "$MINICC" -c -MD -MF - object-driver.c -o - >/dev/null 2>object-driver.err; then
  fail "object and dependency output should not share stdout"
fi
grep -q 'cannot both use standard output' object-driver.err || \
  fail "stdout collision diagnostic is missing"

"$MINICC" --help | grep -q -- '-c.*relocatable object' || \
  fail "help does not advertise -c"

rm -rf tmp-object-driver-dir
rm -f object-driver.o object-driver-custom.o object-driver-pipe.o object-driver-stdin.o \
      object-driver-md.o object-driver.d object-driver-md.d object-driver-custom.d \
      object-driver-keep.o object-driver-bad.c object-driver-bad.err \
      object-driver.err object-driver.c

echo 'All object-emission driver tests passed!'
