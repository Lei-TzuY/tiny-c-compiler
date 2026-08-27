#!/bin/bash
set -eu

assert_run() {
  input="$1"
  printf '%s\n' "$input" > tmp-u64fp.c
  ./minicc tmp-u64fp.c > tmp-u64fp.s
  cc -o tmp-u64fp tmp-u64fp.s
  set +e
  ./tmp-u64fp
  actual="$?"
  set -e
  if [ "$actual" != 0 ]; then
    echo "uint64/floating conversion test failed with exit $actual"
    echo "$input"
    exit 1
  fi
}

# unsigned long -> double: high-half values must not be interpreted as signed.
assert_run 'int main(){unsigned long x=(unsigned long)1<<63;double d=(double)x;return d==9223372036854775808.0?0:1;}'
assert_run 'int main(){unsigned long x=((unsigned long)1<<63)+2048;double d=(double)x;return d==9223372036854777856.0?0:1;}'
assert_run 'int main(){unsigned long x=~(unsigned long)0;double d=(double)x;return d==18446744073709551616.0?0:1;}'

# unsigned long -> float, including one ULP above 2^63.
assert_run 'int main(){unsigned long x=(unsigned long)1<<63;float f=(float)x;return f==9223372036854775808.0f?0:1;}'
assert_run 'int main(){unsigned long x=((unsigned long)1<<63)+((unsigned long)1<<40);float f=(float)x;return f==9223373136366403584.0f?0:1;}'

# double -> unsigned long across the signed boundary and near UINT64_MAX.
assert_run 'int main(){double d=9223372036854775808.0;unsigned long x=(unsigned long)d;return x==((unsigned long)1<<63)?0:1;}'
assert_run 'int main(){double d=9223372036854777856.0;unsigned long x=(unsigned long)d;return x==(((unsigned long)1<<63)+2048)?0:1;}'
assert_run 'int main(){double d=18446744073709549568.0;unsigned long x=(unsigned long)d;return x==(~(unsigned long)0-2047)?0:1;}'

# float -> unsigned long across the same boundary.
assert_run 'int main(){float f=9223372036854775808.0f;unsigned long x=(unsigned long)f;return x==((unsigned long)1<<63)?0:1;}'
assert_run 'int main(){float f=9223373136366403584.0f;unsigned long x=(unsigned long)f;return x==(((unsigned long)1<<63)+((unsigned long)1<<40))?0:1;}'
assert_run 'int main(){float f=18446742974197923840.0f;unsigned long x=(unsigned long)f;return x==(~(unsigned long)0-(((unsigned long)1<<40)-1))?0:1;}'

# Exercise implicit return conversions in both directions, not only explicit casts.
assert_run 'double f(unsigned long x){return x;}int main(){unsigned long x=((unsigned long)1<<63)+2048;return f(x)==9223372036854777856.0?0:1;}'
assert_run 'unsigned long f(double x){return x;}int main(){return f(18446744073709549568.0)==(~(unsigned long)0-2047)?0:1;}'

echo 'All uint64/floating conversion tests passed!'
