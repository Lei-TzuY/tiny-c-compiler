#!/bin/bash
set -eu

compile_and_run() {
  cat > tmp-generic-array.c
  ./minicc tmp-generic-array.c > tmp-generic-array.s
  cc -o tmp-generic-array tmp-generic-array.s
  ./tmp-generic-array
}

reject() {
  name=$1
  cat > tmp-generic-array-bad.c
  if ./minicc tmp-generic-array-bad.c >/dev/null 2>tmp-generic-array.err; then
    echo "expected rejection: $name"
    exit 1
  fi
  echo "OK(_Generic array reject): $name"
}

# A fixed-bound array is a complete, non-variably-modified object type and is
# therefore permitted in an association list, even though ordinary controlling
# expressions undergo array-to-pointer conversion and cannot select it here.
compile_and_run <<'EOF'
int main(void) {
  int a[3] = {0};
  return _Generic(a, int *: 0, int[3]: 1, default: 2);
}
EOF

# An unknown-bound array is incomplete and may not be used as a generic
# association type.
reject incomplete-array-association <<'EOF'
int main(void) {
  return _Generic(1, int[]: 1, default: 0);
}
EOF

# The same incomplete-type constraint applies through a typedef alias.
reject typedef-incomplete-array-association <<'EOF'
typedef int IncompleteArray[];
int main(void) {
  return _Generic(1, IncompleteArray: 1, default: 0);
}
EOF

rm -f tmp-generic-array.c tmp-generic-array.s tmp-generic-array \
      tmp-generic-array-bad.c tmp-generic-array.err

echo 'All _Generic array-association constraint tests passed!'
