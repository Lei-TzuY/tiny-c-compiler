from pathlib import Path

p = Path('test/integer_literals.sh')
s = p.read_text()
old = "assert_run 8 'int main(){return sizeof(1L)+sizeof(1UL)+sizeof(1LU);}'"
new = "assert_run 24 'int main(){return sizeof(1L)+sizeof(1UL)+sizeof(1LU);}'"
if s.count(old) != 1:
    raise SystemExit(f'integer literal test expectation anchor count={s.count(old)}')
p.write_text(s.replace(old, new, 1))
