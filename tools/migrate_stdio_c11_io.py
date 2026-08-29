from pathlib import Path

pp = Path("preprocess_v2.c")
text = pp.read_text()
old = r'''    if (!strcmp(name, "stdio.h")) {
        return "typedef struct FILE FILE;\n"
               "extern FILE *stdin, *stdout, *stderr;\n"
               "int printf(const char *fmt, ...);\n"
               "int sprintf(char *str, const char *fmt, ...);\n"
               "int fprintf(FILE *stream, const char *fmt, ...);\n"
               "int puts(const char *s);\n"
               "int putchar(int c);\n";
    }
'''
new = r'''    if (!strcmp(name, "stdio.h")) {
        return "#ifndef __MINICC_STDIO_H\n"
               "#define __MINICC_STDIO_H 1\n"
               "#include <stddef.h>\n"
               "#define EOF (-1)\n"
               "#define SEEK_SET 0\n"
               "#define SEEK_CUR 1\n"
               "#define SEEK_END 2\n"
               "typedef struct FILE FILE;\n"
               "extern FILE *stdin, *stdout, *stderr;\n"
               "int remove(const char *filename);\n"
               "int rename(const char *oldname, const char *newname);\n"
               "FILE *fopen(const char * restrict filename, const char * restrict mode);\n"
               "FILE *freopen(const char * restrict filename, const char * restrict mode, FILE * restrict stream);\n"
               "int fclose(FILE *stream);\n"
               "int fflush(FILE *stream);\n"
               "int fprintf(FILE * restrict stream, const char * restrict format, ...);\n"
               "int printf(const char * restrict format, ...);\n"
               "int sprintf(char * restrict s, const char * restrict format, ...);\n"
               "int snprintf(char * restrict s, size_t n, const char * restrict format, ...);\n"
               "int fscanf(FILE * restrict stream, const char * restrict format, ...);\n"
               "int scanf(const char * restrict format, ...);\n"
               "int sscanf(const char * restrict s, const char * restrict format, ...);\n"
               "int fgetc(FILE *stream);\n"
               "char *fgets(char * restrict s, int n, FILE * restrict stream);\n"
               "int fputc(int c, FILE *stream);\n"
               "int fputs(const char * restrict s, FILE * restrict stream);\n"
               "int getc(FILE *stream);\n"
               "int getchar(void);\n"
               "int putc(int c, FILE *stream);\n"
               "int putchar(int c);\n"
               "int puts(const char *s);\n"
               "int ungetc(int c, FILE *stream);\n"
               "size_t fread(void * restrict ptr, size_t size, size_t nmemb, FILE * restrict stream);\n"
               "size_t fwrite(const void * restrict ptr, size_t size, size_t nmemb, FILE * restrict stream);\n"
               "int fseek(FILE *stream, long offset, int whence);\n"
               "long ftell(FILE *stream);\n"
               "void rewind(FILE *stream);\n"
               "void clearerr(FILE *stream);\n"
               "int feof(FILE *stream);\n"
               "int ferror(FILE *stream);\n"
               "void perror(const char *s);\n"
               "#endif\n";
    }
'''
if old not in text:
    raise SystemExit("expected stdio.h block not found")
pp.write_text(text.replace(old, new, 1))

Path("test/stdio_header.sh").write_text(r'''#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-stdio-h.c
  "$MINICC" tmp-stdio-h.c > tmp-stdio-h.s
  cc -o tmp-stdio-h tmp-stdio-h.s
  set +e
  ./tmp-stdio-h >/dev/null 2>&1
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(stdio.h): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
}

cleanup_files() {
  rm -f tmp-stdio-h.c tmp-stdio-h.s tmp-stdio-h \
        tmp-stdio-text.txt tmp-stdio-bin.dat tmp-stdio-old.txt tmp-stdio-new.txt
}
trap cleanup_files EXIT

# Repeated inclusion must preserve FILE, size_t-backed declarations, constants,
# standard streams, and representative exact function-pointer types.
assert_run 0 '#include <stdio.h>
#include <stdio.h>
int main(void){
  FILE *a=stdin,*b=stdout,*c=stderr;
  FILE *(*openfn)(const char *,const char *)=fopen;
  int (*closefn)(FILE *)=fclose;
  size_t (*readfn)(void *,size_t,size_t,FILE *)=fread;
  size_t (*writefn)(const void *,size_t,size_t,FILE *)=fwrite;
  long (*tellfn)(FILE *)=ftell;
  void (*errfn)(const char *)=perror;
  if(!a||!b||!c||!openfn||!closefn||!readfn||!writefn||!tellfn||!errfn)return 1;
  return !(EOF<0 && SEEK_SET==0 && SEEK_CUR==1 && SEEK_END==2);
}'

# Keep the existing variadic-output ABI coverage, including default float promotion.
assert_run 0 '#include <stdio.h>
int main(void){char b[32];float f=2.5f;int n=sprintf(b,"%d %.1f %s",7,f,"ok");if(n!=8)return 1;return b[0]!='"'"'7'"'"'||b[1]!='"'"' '"'"'||b[2]!='"'"'2'"'"'||b[3]!='"'"'.'"'"'||b[4]!='"'"'5'"'"'||b[5]!='"'"' '"'"'||b[6]!='"'"'o'"'"'||b[7]!='"'"'k'"'"'||b[8]!=0;}'

assert_run 0 '#include <stdio.h>
int main(void){char b[8];int n=snprintf(b,sizeof(b),"%d-%s",42,"abcdef");if(n!=9)return 1;return b[0]!='"'"'4'"'"'||b[1]!='"'"'2'"'"'||b[2]!='"'"'-'"'"'||b[6]!='"'"'d'"'"'||b[7]!=0;}'

# Formatted input uses the host variadic ABI for writable pointer arguments.
assert_run 0 '#include <stdio.h>
int main(void){int n=0;char s[8]={0};if(sscanf("42 hello","%d %7s",&n,s)!=2)return 1;if(n!=42)return 2;return s[0]!='"'"'h'"'"'||s[4]!='"'"'o'"'"'||s[5]!=0;}'

# Text file I/O covers open/close, buffering, tell/rewind, line input,
# character input, ungetc, EOF state, and clearerr.
assert_run 0 '#include <stdio.h>
int main(void){
  FILE *f=fopen("tmp-stdio-text.txt","w+"); if(!f)return 1;
  if(fputs("abc\n",f)<0)return 2;
  if(fputc('"'"'Z'"'"',f)!='"'"'Z'"'"')return 3;
  if(fflush(f)!=0)return 4;
  if(ftell(f)!=5)return 5;
  rewind(f);
  char line[8]={0}; if(!fgets(line,sizeof(line),f))return 6;
  if(line[0]!='"'"'a'"'"'||line[1]!='"'"'b'"'"'||line[2]!='"'"'c'"'"'||line[3]!='"'"'\n'"'"')return 7;
  if(getc(f)!='"'"'Z'"'"')return 8;
  if(ungetc('"'"'Q'"'"',f)!='"'"'Q'"'"')return 9;
  if(fgetc(f)!='"'"'Q'"'"')return 10;
  if(fgetc(f)!=EOF)return 11;
  if(!feof(f))return 12;
  clearerr(f); if(feof(f)||ferror(f))return 13;
  return fclose(f)!=0;
}'

# Binary block I/O and positioning exercise size_t counts and host FILE state.
assert_run 0 '#include <stdio.h>
int main(void){
  int out[3]={11,22,33},in[3]={0,0,0};
  FILE *f=fopen("tmp-stdio-bin.dat","wb+"); if(!f)return 1;
  if(fwrite(out,sizeof(int),3,f)!=3)return 2;
  if(fseek(f,0,SEEK_SET)!=0)return 3;
  if(fread(in,sizeof(int),3,f)!=3)return 4;
  if(in[0]!=11||in[1]!=22||in[2]!=33)return 5;
  if(fseek(f,-(long)sizeof(int),SEEK_END)!=0)return 6;
  if(fread(in,sizeof(int),1,f)!=1||in[0]!=33)return 7;
  return fclose(f)!=0;
}'

# Filesystem-facing stdio declarations must link and behave through host libc.
assert_run 0 '#include <stdio.h>
int main(void){
  FILE *f=fopen("tmp-stdio-old.txt","w"); if(!f)return 1;
  if(fputs("x",f)<0||fclose(f)!=0)return 2;
  if(rename("tmp-stdio-old.txt","tmp-stdio-new.txt")!=0)return 3;
  f=fopen("tmp-stdio-new.txt","r"); if(!f)return 4;
  if(fgetc(f)!='"'"'x'"'"'||fclose(f)!=0)return 5;
  if(remove("tmp-stdio-new.txt")!=0)return 6;
  return fopen("tmp-stdio-new.txt","r")!=0;
}'

# Preserve the original standard stream and character-output coverage.
assert_run 0 '#include <stdio.h>
int main(void){if(printf("%s","")!=0)return 1;if(fprintf(stdout,"%s","")!=0)return 2;if(fprintf(stderr,"%s","")!=0)return 3;if(putchar('"'"'A'"'"')!='"'"'A'"'"')return 4;if(puts("")<0)return 5;return 0;}'

echo 'All expanded <stdio.h> tests passed!'
''')
