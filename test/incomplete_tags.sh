#!/bin/bash
set -e

assert_record() {
  expected="$1"
  input="$2"
  printf "%s\n" "$input" > tmp-record.c
  "${MINICC:-./minicc}" tmp-record.c > tmp-record.s
  gcc -o tmp-record tmp-record.s
  set +e
  ./tmp-record
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(record): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(record): $actual"
}

assert_reject() {
  input="$1"
  printf "%s\n" "$input" > tmp-record-reject.c
  if "${MINICC:-./minicc}" tmp-record-reject.c > /dev/null 2>&1; then
    echo "FAIL(record): expected rejection"
    echo "$input"
    exit 1
  fi
  echo "OK(record): rejected invalid incomplete-type use"
}

assert_record 7 'typedef struct FILE FILE; struct FILE { int fd; }; int main() { FILE f; f.fd=7; return f.fd; }'
assert_record 9 'typedef struct Node Node; struct Node { Node *next; int value; }; int main() { Node a; Node b; a.next=&b; b.value=9; return a.next->value; }'
assert_record 5 'struct Node { struct Node *next; int value; }; int main() { struct Node a; struct Node b; a.next=&b; b.value=5; return a.next->value; }'
assert_record 6 'struct B; struct A { struct B *b; }; struct B { struct A *a; int x; }; int main() { struct A a; struct B b; a.b=&b; b.a=&a; b.x=6; return a.b->x; }'
assert_record 4 'union U; union U { int x; char c; }; int main() { union U u; u.x=4; return u.x; }'
assert_record 8 'struct S { int x; }; int main() { struct S a; a.x=3; { struct S { int y; }; struct S b; b.y=5; a.x += b.y; } return a.x; }'
assert_record 8 'struct Opaque; int main() { return sizeof(struct Opaque*) == 8 ? 8 : 0; }'
assert_record 3 'struct S; extern struct S ext; struct S { int x; }; int main() { struct S s; s.x=3; return s.x; }'

assert_reject 'struct S; int main() { struct S value; return 0; }'
assert_reject 'struct S; int main() { return sizeof(struct S); }'
assert_reject 'struct S; struct T { struct S field; }; int main() { return 0; }'
assert_reject 'struct S { int x; }; struct S { int y; }; int main() { return 0; }'


# Every declarator in a comma-separated declaration must be validated independently.
assert_reject 'struct S; struct S *ptr, value; int main() { return 0; }'
assert_reject 'struct S; static struct S *ptr, value; int main() { return 0; }'
assert_record 6 'struct S; extern struct S *ptr, value; struct S { int x; }; int main() { struct S s; s.x=6; return s.x; }'

# typedef declarations may introduce more than one name.
assert_record 11 'typedef int A, B; int main() { A a=5; B b=6; return a+b; }'
assert_record 8 'typedef struct Pair Pair, *PairPtr; struct Pair { int x; }; int main() { Pair p; PairPtr q=&p; q->x=8; return p.x; }'
assert_record 9 'int main() { typedef int A, B; A a=4; B b=5; return a+b; }'

echo "All incomplete record/tag scope tests passed!"
