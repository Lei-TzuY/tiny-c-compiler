#!/bin/bash
set -eu

cat > tmp-alignof.c <<'EOF'
typedef long L;
struct S { char c; double d; };
union U { char c; long x; };
struct N { char c; struct S s; };
int main(void) {
  if (_Alignof(char) != 1) return 1;
  if (_Alignof(short) != 2) return 2;
  if (_Alignof(int) != 4) return 3;
  if (_Alignof(long) != 8) return 4;
  if (_Alignof(double) != 8) return 5;
  if (_Alignof(int *) != 8) return 6;
  if (_Alignof(int[4]) != 4) return 7;
  if (_Alignof(struct S) != 8) return 8;
  if (_Alignof(union U) != 8) return 9;
  if (_Alignof(struct N) != 8) return 10;
  if (_Alignof(L) != 8) return 11;
  if (sizeof(struct S) != 16) return 12;
  return 0;
}
EOF
./minicc tmp-alignof.c > tmp-alignof.s
cc -o tmp-alignof tmp-alignof.s
./tmp-alignof

echo 'OK(_Alignof): scalar, pointer, array, record and typedef alignments'

# Unlike sizeof(VLA), alignment does not depend on the runtime bound.  _Alignof
# therefore remains an integer constant expression even when its type-name is
# variably modified, including a pointer-to-VLA derived type.
cat > tmp-alignof-vla.c <<'EOF'
int main(void) {
  int n = 3;
  _Static_assert(_Alignof(int[n]) == _Alignof(int), "VLA alignment is constant");
  _Static_assert(_Alignof(int (*)[n]) == _Alignof(int *), "VM pointer alignment is constant");
  return 0;
}
EOF
./minicc tmp-alignof-vla.c > tmp-alignof-vla.s
cc -o tmp-alignof-vla tmp-alignof-vla.s
./tmp-alignof-vla

echo 'OK(_Alignof): VLA and variably-modified type names remain ICEs'

for src in \
  'int main(void){return _Alignof(void);}' \
  'struct F; int main(void){return _Alignof(struct F);}' \
  'int f(void); int main(void){return _Alignof(int(void));}' \
  'int main(void){int x; return _Alignof(x);}'
do
  printf '%s\n' "$src" > tmp-alignof-bad.c
  if ./minicc tmp-alignof-bad.c >/dev/null 2>&1; then
    echo "expected _Alignof rejection: $src"
    exit 1
  fi
done

rm -f tmp-alignof.c tmp-alignof.s tmp-alignof tmp-alignof-vla.c tmp-alignof-vla.s tmp-alignof-vla tmp-alignof-bad.c
echo 'All C11 _Alignof tests passed!'
