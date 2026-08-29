from pathlib import Path

path = Path('test/thread_local.sh')
text = path.read_text()
old = "assert_run 0 '_Thread_local char s[]=\"abc\";int main(void){return sizeof(s)!=4||s[2]!=\\047c\\047||s[3]!=0;}'"
new = "assert_run 0 '_Thread_local char s[]=\"abc\";int main(void){return sizeof(s)!=4||s[2]!=99||s[3]!=0;}'"
if text.count(old) != 1:
    raise SystemExit(f'expected one string regression literal, found {text.count(old)}')
path.write_text(text.replace(old, new, 1))
