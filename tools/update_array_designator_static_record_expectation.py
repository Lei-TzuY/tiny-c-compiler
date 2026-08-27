from pathlib import Path

p = Path('test/array_designators.sh')
s = p.read_text()
old = "assert_fail 'struct S{char c;long x;};struct S s={1,2};int main(){return 0;}'\n"
new = "assert_run 1 'struct S{char c;long x;};struct S s={1,2};int main(){return sizeof(s)==16&&s.c==1&&s.x==2;}'\n"
count = s.count(old)
if count != 1:
    raise SystemExit(f'expected one static-record regression anchor, found {count}')
p.write_text(s.replace(old, new, 1))
