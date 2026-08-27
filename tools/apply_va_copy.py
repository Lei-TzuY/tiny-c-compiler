from pathlib import Path


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


p = Path("preprocess_v2.c")
s = p.read_text()
old = '''               "#define va_start(ap, last) __builtin_va_start(&(ap))\\n"\n               "#define va_arg(ap, type) __builtin_va_arg(&(ap), type)\\n"\n               "#define va_end(ap) ((void)0)\\n";\n'''
new = '''               "#define va_start(ap, last) __builtin_va_start(&(ap))\\n"\n               "#define va_arg(ap, type) __builtin_va_arg(&(ap), type)\\n"\n               "#define va_copy(dest, src) ((dest) = (src))\\n"\n               "#define __va_copy(dest, src) va_copy(dest, src)\\n"\n               "#define va_end(ap) ((void)0)\\n";\n'''
s = replace_once(s, old, new, "builtin stdarg va_copy")
p.write_text(s)

p = Path("test/sysv_variadic_callee.sh")
s = p.read_text()
anchor = '''# Compile variadic callees with minicc and call them from the host compiler.\n'''
insert = r'''# va_copy duplicates the cursor state, not an alias to mutable offsets.  Consume
# one list after copying and verify the copy still starts from the same point.
compile_and_run <<'EOF'
#include <stdarg.h>
int copy_probe(int tag, ...) {
  va_list ap, cp;
  va_start(ap, tag);
  int first = va_arg(ap, int);
  va_copy(cp, ap);

  int a1 = va_arg(ap, int);
  double d1 = va_arg(ap, double);
  int a2 = va_arg(ap, int);

  int c1 = va_arg(cp, int);
  double cd1 = va_arg(cp, double);
  int c2 = va_arg(cp, int);

  va_end(cp);
  va_end(ap);
  return first==10 && a1==20 && d1==1.5 && a2==30 &&
         c1==20 && cd1==1.5 && c2==30;
}
int main(void) { return !copy_probe(0,10,20,1.5,30); }
EOF

# Copy before exhausting either register class, then drain the original across
# both GP/SSE register-save areas and the shared overflow stack.  The copied
# cursor must independently reproduce the whole sequence afterwards.
compile_and_run <<'EOF'
#include <stdarg.h>
int copy_overflow(int tag, ...) {
  va_list ap, cp;
  va_start(ap, tag);
  __va_copy(cp, ap);

  int a1=va_arg(ap,int), a2=va_arg(ap,int), a3=va_arg(ap,int);
  int a4=va_arg(ap,int), a5=va_arg(ap,int), a6=va_arg(ap,int), a7=va_arg(ap,int);
  double d1=va_arg(ap,double), d2=va_arg(ap,double), d3=va_arg(ap,double);
  double d4=va_arg(ap,double), d5=va_arg(ap,double), d6=va_arg(ap,double);
  double d7=va_arg(ap,double), d8=va_arg(ap,double), d9=va_arg(ap,double);

  int c1=va_arg(cp,int), c2=va_arg(cp,int), c3=va_arg(cp,int);
  int c4=va_arg(cp,int), c5=va_arg(cp,int), c6=va_arg(cp,int), c7=va_arg(cp,int);
  double e1=va_arg(cp,double), e2=va_arg(cp,double), e3=va_arg(cp,double);
  double e4=va_arg(cp,double), e5=va_arg(cp,double), e6=va_arg(cp,double);
  double e7=va_arg(cp,double), e8=va_arg(cp,double), e9=va_arg(cp,double);

  return a1+a2+a3+a4+a5+a6+a7==28 && c1+c2+c3+c4+c5+c6+c7==28 &&
         d1+d2+d3+d4+d5+d6+d7+d8+d9==45.0 &&
         e1+e2+e3+e4+e5+e6+e7+e8+e9==45.0;
}
int main(void) {
  return !copy_overflow(0,1,2,3,4,5,6,7,
                        1.0,2.0,3.0,4.0,5.0,6.0,7.0,8.0,9.0);
}
EOF

'''
s = replace_once(s, anchor, insert + anchor, "va_copy regressions")
p.write_text(s)
