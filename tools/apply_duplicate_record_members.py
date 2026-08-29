from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}\n--- old ---\n{old}")
    p.write_text(text.replace(old, new, 1))


replace_once(
    "parse.c",
    '''            Member *m = calloc(1, sizeof(Member));\n            m->name = strndup(ident->loc, ident->len);\n''',
    '''            for (Member *prev = head.next; prev; prev = prev->next)\n                if (token_matches_name(ident, prev->name))\n                    error_at(ident->loc, "duplicate record member name");\n\n            Member *m = calloc(1, sizeof(Member));\n            m->name = strndup(ident->loc, ident->len);\n''')

Path("test/duplicate_record_members.sh").write_text(r'''#!/bin/bash
set -eu

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-dup-member.c
  ./minicc tmp-dup-member.c > tmp-dup-member.s
  cc -o tmp-dup-member tmp-dup-member.s
  set +e
  ./tmp-dup-member
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(duplicate record member): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-dup-member-bad.c
  if ./minicc tmp-dup-member-bad.c > /dev/null 2>tmp-dup-member.err; then
    echo "FAIL(duplicate record member): expected rejection"
    echo "$input"
    exit 1
  fi
}

# Member names only need to be unique within one record. Independent and nested
# record types may reuse the same spelling freely.
assert_run 5 'struct A{int x;};struct B{long x;};int main(void){struct A a={2};struct B b={3};return a.x+b.x;}'
assert_run 7 'struct O{int x;struct I{int x;} i;};int main(void){struct O o={2,{5}};return o.x+o.i.x;}'
assert_run 8 'union A{int x;long y;};union B{int x;double y;};int main(void){union A a={.x=3};union B b={.x=5};return a.x+b.x;}'

# C11 requires member names within a struct/union to be distinct.
assert_reject 'struct S{int x;long x;};int main(void){return 0;}'
assert_reject 'struct S{int x,x;};int main(void){return 0;}'
assert_reject 'struct S{int a;int b;char a;};int main(void){return 0;}'
assert_reject 'union U{int x;long x;};int main(void){return 0;}'
assert_reject 'union U{int x,x;};int main(void){return 0;}'
assert_reject 'typedef struct{int value;double value;} S;int main(void){return 0;}'
assert_reject 'struct O{struct I{int x;int x;} i;};int main(void){return 0;}'

rm -f tmp-dup-member.c tmp-dup-member.s tmp-dup-member \
      tmp-dup-member-bad.c tmp-dup-member.err

echo 'All duplicate record-member tests passed!'
''')

makefile = Path("Makefile")
text = makefile.read_text()
needle = "\tbash ./test/tag_definition_constraints.sh\n"
if text.count(needle) != 1:
    raise SystemExit("Makefile tag-definition test anchor not unique")
makefile.write_text(text.replace(needle, needle + "\tbash ./test/duplicate_record_members.sh\n", 1))

readme = Path("README.md")
text = readme.read_text()
old = "block-scoped tags, and C11 non-empty struct/union/enum definition bodies."
new = "block-scoped tags, C11 non-empty struct/union/enum definition bodies, and duplicate-member diagnostics within each record."
if text.count(old) != 1:
    raise SystemExit("README record-types wording not unique")
readme.write_text(text.replace(old, new, 1))

print("duplicate record-member constraints applied")
