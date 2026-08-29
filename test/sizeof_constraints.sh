#!/bin/bash
set -eu

cat > tmp-sizeof-constraints.c <<'EOF'
struct S { char c; long x; };
int f(void) { return 7; }
int main(void) {
  int a[3];
  if (sizeof(char) != 1) return 1;
  if (sizeof(int) != 4) return 2;
  if (sizeof(a) != 12) return 3;
  if (sizeof(struct S) != 16) return 4;
  if (sizeof(&f) != 8) return 5;
  return 0;
}
EOF
./minicc tmp-sizeof-constraints.c > tmp-sizeof-constraints.s
cc -o tmp-sizeof-constraints tmp-sizeof-constraints.s
./tmp-sizeof-constraints

echo 'OK(sizeof): complete object types and function pointers remain valid'

for src in \
  'int main(void){return sizeof(void);}' \
  'int f(void); int main(void){return sizeof(f);}' \
  'int main(void){return sizeof(int(void));}' \
  'struct F; int main(void){return sizeof(struct F);}' \
  'extern int a[]; int main(void){return sizeof(a);}'
do
  printf '%s\n' "$src" > tmp-sizeof-constraints-bad.c
  if ./minicc tmp-sizeof-constraints-bad.c >/dev/null 2>&1; then
    echo "expected sizeof rejection: $src"
    exit 1
  fi
done

rm -f tmp-sizeof-constraints.c tmp-sizeof-constraints.s tmp-sizeof-constraints \
      tmp-sizeof-constraints-bad.c
echo 'All sizeof operand-constraint tests passed!'
