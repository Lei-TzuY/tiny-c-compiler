#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

assert_run() {
  expected="$1"
  input="$2"
  printf '%s\n' "$input" > tmp-vla.c
  "$MINICC" tmp-vla.c > tmp-vla.s
  cc -o tmp-vla tmp-vla.s
  set +e
  ./tmp-vla
  actual="$?"
  set -e
  if [ "$actual" != "$expected" ]; then
    echo "FAIL(VLA): expected $expected, got $actual"
    echo "$input"
    exit 1
  fi
  echo "OK(VLA): $actual"
}

assert_reject() {
  input="$1"
  printf '%s\n' "$input" > tmp-vla-bad.c
  if "$MINICC" tmp-vla-bad.c > /dev/null 2>tmp-vla.err; then
    echo 'FAIL(VLA): expected rejection'
    echo "$input"
    exit 1
  fi
  echo 'OK(VLA): rejected unsupported/invalid form'
}

# Basic automatic runtime extent, indexing, and decay.
assert_run 7 'int main(void){int n=5;int a[n];a[0]=3;a[4]=4;return a[0]+a[n-1];}'

# A declaration bound is evaluated exactly once. sizeof(object) keeps the saved
# allocation extent even when the source variable changes afterward.
assert_run 0 'int main(void){int n=3;int a[n++];if(n!=4)return 1;n=8;return sizeof a==12?0:2;}'

# sizeof(VLA) keeps the target LP64 size_t type, while a VLA type-name evaluates
# its bound when the sizeof expression executes.
assert_run 0 'int main(void){int n=6;int a[n];return _Generic(sizeof a,unsigned long:0,default:1);}'
assert_run 0 'int main(void){int n=7;return sizeof(int[n])==28?0:1;}'
assert_run 0 'int main(void){int n=3;unsigned long x=sizeof(int[n++]);return x==12&&n==4?0:1;}'

# Unlike sizeof(VLA), _Alignof(type-name) never evaluates a variably-modified
# bound expression; only the completed element type's alignment is queried.
assert_run 0 'int main(void){int n=3;unsigned long a=_Alignof(int[n++]);return a==4&&n==3?0:1;}'
assert_run 0 'int main(void){int n=5;unsigned long a=_Alignof(double[++n]);return a==8&&n==5?0:1;}'

# Outer runtime dimension with a fixed inner stride remains ordinary C pointer
# arithmetic after decay.
assert_run 0 'int main(void){int n=3;int a[n][4];a[2][3]=9;return sizeof a==48&&a[2][3]==9?0:1;}'

# Non-scalar complete element types use their compile-time stride.
assert_run 0 'struct S{long x;};int main(void){int n=3;struct S a[n];a[2].x=11;return sizeof a==24&&a[2].x==11?0:1;}'


# Every variably-modified dimension has an allocation-time byte extent. This
# enables true runtime row/plane strides rather than requiring fixed inner sizes.
assert_run 0 'int main(void){int n=3,m=5;int a[n][m];a[2][4]=17;return sizeof a==60&&sizeof a[0]==20&&a[2][4]==17?0:1;}'
assert_run 0 'int main(void){int n=4;int a[3][n];a[2][3]=11;return sizeof a==48&&sizeof a[0]==16&&a[2][3]==11?0:1;}'
assert_run 0 'int main(void){int x=2,y=3,z=4;int a[x][y][z];a[1][2][3]=23;return sizeof a==96&&sizeof a[0]==48&&sizeof a[0][0]==16&&a[1][2][3]==23?0:1;}'

# Bounds are saved once. Later mutation must not change object sizeof or row
# stride, and sizeof(type-name) recursively evaluates all runtime dimensions.
assert_run 0 'int main(void){int n=2,m=3;int a[n++][m++];if(n!=3||m!=4)return 1;n=9;m=10;a[1][2]=7;return sizeof a==24&&sizeof a[0]==12&&a[1][2]==7?0:2;}'
assert_run 0 'int main(void){int n=2,m=3;unsigned long s=sizeof(int[n][m]);return s==24?0:1;}'
assert_run 0 'int main(void){int n=2,m=3;unsigned long a=_Alignof(int[n++][m++]);return a==4&&n==2&&m==3?0:1;}'

# Pointer-to-VLA objects use the saved runtime row extent for indexing,
# increment/decrement, compound arithmetic and pointer difference.
assert_run 0 'int main(void){int n=3,m=4;int a[n][m];int (*p)[m]=a;p[2][3]=19;return sizeof *p==16&&a[2][3]==19?0:1;}'
assert_run 0 'int main(void){int n=4,m=3;int a[n][m];int (*p)[m]=a;int (*q)[m]=p;p++;p+=2;return p-q==3?0:1;}'
assert_run 0 'int main(void){int n=4,m=3;int a[n][m];int (*p)[m]=a+3;p--;return p-a==2?0:1;}'

# Callee-side parameter adjustment retains inner VLA dimensions. Their bounds
# are rebound to the real parameter locals and materialized before the body.
assert_run 0 'int get(int n,int m,int a[n][m]){return sizeof a[0]==(unsigned long)m*4&&a[n-1][m-1]==29?0:1;}int main(void){int n=3,m=5;int a[n][m];a[2][4]=29;return get(n,m,a);}'
assert_run 0 'int get(int m,int (*p)[m]){p++;return sizeof *p==(unsigned long)m*4&&p[-1][m-1]==31?0:1;}int main(void){int n=2,m=6;int a[n][m];a[0][5]=31;return get(m,a);}'
assert_run 0 'int get(int x,int y,int z,int a[x][y][z]){return a[1][2][3]==37&&sizeof a[0]==(unsigned long)y*z*4?0:1;}int main(void){int a[2][3][4];a[1][2][3]=37;return get(2,3,4,a);}'

# Dynamic allocations satisfy the element alignment and preserve call ABI
# alignment because every stack decrement is rounded to 16 bytes.
assert_run 0 'int check(double *p){return ((unsigned long)p)&7;}int main(void){int n=5;double a[n];return check(a);}'
assert_run 0 'long add(long a,long b,long c,long d,long e,long f,long g){return a+b+c+d+e+f+g;}int main(void){int n=5;char a[n];a[0]=1;return add(1,2,3,4,5,6,7)==28&&a[0]==1?0:1;}'

# Earlier declarators and their initializers are visible to later VLA bounds in
# the same declaration and execute before the allocation.
assert_run 0 'int main(void){int n=4,a[n];a[3]=7;return sizeof a==16&&a[3]==7?0:1;}'

# Nested blocks restore RSP every iteration instead of leaking dynamic stack.
assert_run 0 'int main(void){long sum=0;for(int i=0;i<6000;i++){int n=512;int a[n];a[0]=i;sum+=a[0]&1;}return sum==3000?0:1;}'

# Continue and break unwind every exited VLA scope before transferring control.
assert_run 0 'int main(void){int hit=0;for(int i=0;i<6000;i++){int n=256;int a[n];a[0]=i;if(i&1)continue;hit+=a[0]>=0;}return hit==3000?0:1;}'
assert_run 0 'int main(void){int hit=0;for(int i=0;i<5000;i++){while(1){int n=256;int a[n];a[0]=i;hit+=a[0]>=0;break;}}return hit==5000?0:1;}'

# A VLA declared in a for-init scope remains alive for the loop and is restored
# once at the common loop exit.
assert_run 0 'int main(void){int out=0;for(int n=4,a[n];n==4;n=0){a[3]=9;out=a[3]+(sizeof a==16);}return out==10?0:1;}'

# Parameter array adjustment accepts runtime bounds, static runtime bounds, and
# prototype-scope [*]. Earlier parameter names are visible in later bounds.
assert_run 0 'int last(int n,int a[n]){return a[n-1];}int main(void){int a[4]={1,2,3,9};return last(4,a)==9?0:1;}'
assert_run 0 'int first(int n,int a[static n]){return a[0];}int main(void){int a[3]={8,2,1};return first(3,a)==8?0:1;}'
assert_run 0 'int sum(int n,int a[*]);int sum(int n,int a[]){int s=0;for(int i=0;i<n;i++)s+=a[i];return s;}int main(void){int a[3]={2,3,4};return sum(3,a)==9?0:1;}'
assert_run 0 'int pick(int n,int a[const restrict n]){return a[n-1];}int main(void){int a[2]={3,7};return pick(2,a)==7?0:1;}'

# Invalid/unsupported VM shapes are diagnosed rather than miscompiled.
assert_reject 'int main(void){int n=3;int a[n]={1,2,3};return a[0];}'
assert_reject 'int main(void){int n=3;static int a[n];return 0;}'
assert_reject 'int main(void){int n=3;extern int a[n];return 0;}'
assert_reject 'int n;int a[n];int main(void){return 0;}'
assert_reject 'int main(void){int n=3;struct S{int a[n];};return 0;}'
assert_reject 'int main(void){int n=3;typedef int A[n];return 0;}'
assert_reject 'int main(void){int n=3;int a[n];goto out;out:return a[0];}'
assert_reject 'int f(int n,int a[static *]);int main(void){return 0;}'

# Existing constant-bound constraints remain strict.
assert_reject 'int main(void){int a[0];return 0;}'
assert_reject 'int main(void){int a[-1];return 0;}'
assert_reject 'int main(void){double n=3;int a[n];return 0;}'

rm -f tmp-vla.c tmp-vla.s tmp-vla tmp-vla-bad.c tmp-vla.err

echo 'All C99 VLA tests passed!'
