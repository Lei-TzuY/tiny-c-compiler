from pathlib import Path

p = Path("tools/apply_float_abi.py")
text = p.read_text()
old1 = '''assert_abi 1 '#include <stdio.h>\nint main() { char buf[32]; int n=sprintf(buf,"%.1f",2.5); return n==3 && buf[0]=='"'"'2'"'"' && buf[1]=='"'"'.'"'"' && buf[2]=='"'"'5'"'"'; }' '''
new1 = '''assert_abi 1 'int sprintf(char *str, char *fmt, ...);\nint main() { char buf[32]; int n=sprintf(buf,"%.1f",2.5); return n==3 && buf[0]=='"'"'2'"'"' && buf[1]=='"'"'.'"'"' && buf[2]=='"'"'5'"'"'; }' '''
old2 = '''assert_abi 1 '#include <stdio.h>\nint main() { char buf[32]; float x=2.5f; int n=sprintf(buf,"%.1f",x); return n==3 && buf[0]=='"'"'2'"'"' && buf[2]=='"'"'5'"'"'; }' '''
new2 = '''assert_abi 1 'int sprintf(char *str, char *fmt, ...);\nint main() { char buf[32]; float x=2.5f; int n=sprintf(buf,"%.1f",x); return n==3 && buf[0]=='"'"'2'"'"' && buf[2]=='"'"'5'"'"'; }' '''
if old1 not in text or old2 not in text:
    raise SystemExit("expected stdio ABI test snippets not found")
text = text.replace(old1, new1, 1).replace(old2, new2, 1)
p.write_text(text)
print("rewrote sprintf ABI tests without stdio.h")
