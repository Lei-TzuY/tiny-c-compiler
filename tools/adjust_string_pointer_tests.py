from pathlib import Path

p = Path('test/string_array_initializers.sh')
s = p.read_text()
old1 = "assert_fail 'char *p=\"abc\";int main(){return 0;}'\n"
new1 = "assert_run 1 'char *p=\"abc\";int main(){return p[0]==97&&p[3]==0;}'\n"
old2 = "assert_fail 'int main(){static char *p=\"abc\";return 0;}'\n"
new2 = "assert_run 1 'int main(){static char *p=\"abc\";return p[1]==98&&p[3]==0;}'\n"
if s.count(old1) != 1 or s.count(old2) != 1:
    raise SystemExit('string pointer expectation anchors not found exactly once')
s = s.replace(old1, new1, 1).replace(old2, new2, 1)
p.write_text(s)
