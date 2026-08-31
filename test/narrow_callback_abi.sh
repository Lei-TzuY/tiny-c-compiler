#!/bin/bash
set -eu

MINICC=${MINICC:-./minicc}

cat > tmp-narrow-callback-host.c <<'EOF'
signed char host_schar_cb(signed char x) { return x - 2; }
unsigned char host_uchar_cb(unsigned char x) { return x + 3; }
short host_short_cb(short x) { return x - 1000; }
unsigned short host_ushort_cb(unsigned short x) { return x + 1000; }
_Bool host_bool_cb(_Bool x) { return x ? 7 : 0; }

signed char host_apply_schar(signed char (*fn)(signed char), signed char x) { return fn(x); }
unsigned char host_apply_uchar(unsigned char (*fn)(unsigned char), unsigned char x) { return fn(x); }
short host_apply_short(short (*fn)(short), short x) { return fn(x); }
unsigned short host_apply_ushort(unsigned short (*fn)(unsigned short), unsigned short x) { return fn(x); }
_Bool host_apply_bool(_Bool (*fn)(_Bool), _Bool x) { return fn(x); }
EOF
cc -std=c11 -c tmp-narrow-callback-host.c -o tmp-narrow-callback-host.o

cat > tmp-narrow-callback-minicc.c <<'EOF'
signed char host_schar_cb(signed char);
unsigned char host_uchar_cb(unsigned char);
short host_short_cb(short);
unsigned short host_ushort_cb(unsigned short);
_Bool host_bool_cb(_Bool);

signed char host_apply_schar(signed char (*)(signed char), signed char);
unsigned char host_apply_uchar(unsigned char (*)(unsigned char), unsigned char);
short host_apply_short(short (*)(short), short);
unsigned short host_apply_ushort(unsigned short (*)(unsigned short), unsigned short);
_Bool host_apply_bool(_Bool (*)(_Bool), _Bool);

signed char local_schar_cb(signed char x) { return x - 4; }
unsigned char local_uchar_cb(unsigned char x) { return x + 5; }
short local_short_cb(short x) { return x - 2000; }
unsigned short local_ushort_cb(unsigned short x) { return x + 2000; }
_Bool local_bool_cb(_Bool x) { return x ? -9 : 0; }

signed char local_apply_schar(signed char (*fn)(signed char), signed char x) { return fn(x); }
unsigned char local_apply_uchar(unsigned char (*fn)(unsigned char), unsigned char x) { return fn(x); }
short local_apply_short(short (*fn)(short), short x) { return fn(x); }
unsigned short local_apply_ushort(unsigned short (*fn)(unsigned short), unsigned short x) { return fn(x); }
_Bool local_apply_bool(_Bool (*fn)(_Bool), _Bool x) { return fn(x); }

int main(void) {
  if (local_apply_schar(host_schar_cb, -120) != -122) return 1;
  if (local_apply_uchar(host_uchar_cb, 250) != 253) return 2;
  if (local_apply_short(host_short_cb, -30000) != -31000) return 3;
  if (local_apply_ushort(host_ushort_cb, 60000) != 61000) return 4;
  if (local_apply_bool(host_bool_cb, 0) != 0) return 5;
  if (local_apply_bool(host_bool_cb, 42) != 1) return 6;

  if (host_apply_schar(local_schar_cb, -100) != -104) return 7;
  if (host_apply_uchar(local_uchar_cb, 240) != 245) return 8;
  if (host_apply_short(local_short_cb, -20000) != -22000) return 9;
  if (host_apply_ushort(local_ushort_cb, 50000) != 52000) return 10;
  if (host_apply_bool(local_bool_cb, 0) != 0) return 11;
  if (host_apply_bool(local_bool_cb, 99) != 1) return 12;
  return 0;
}
EOF

"$MINICC" tmp-narrow-callback-minicc.c > tmp-narrow-callback-minicc.s
cc -o tmp-narrow-callback tmp-narrow-callback-minicc.s tmp-narrow-callback-host.o
set +e
./tmp-narrow-callback
actual="$?"
set -e
if [ "$actual" != 0 ]; then
  echo "FAIL(narrow callback ABI): minicc entrypoint exit $actual"
  exit 1
fi

# Reverse the top-level caller boundary as well. This makes the host compiler
# observe narrow callback results produced by minicc through an indirect call.
cat > tmp-narrow-provider.c <<'EOF'
signed char minicc_cb_schar(signed char x) { return x - 6; }
unsigned char minicc_cb_uchar(unsigned char x) { return x + 7; }
short minicc_cb_short(short x) { return x - 3000; }
unsigned short minicc_cb_ushort(unsigned short x) { return x + 3000; }
_Bool minicc_cb_bool(_Bool x) { return x ? 123 : 0; }
EOF
"$MINICC" tmp-narrow-provider.c > tmp-narrow-provider.s
cc -c tmp-narrow-provider.s -o tmp-narrow-provider.o

cat > tmp-narrow-host-caller.c <<'EOF'
signed char minicc_cb_schar(signed char);
unsigned char minicc_cb_uchar(unsigned char);
short minicc_cb_short(short);
unsigned short minicc_cb_ushort(unsigned short);
_Bool minicc_cb_bool(_Bool);

static signed char call_schar(signed char (*fn)(signed char), signed char x) { return fn(x); }
static unsigned char call_uchar(unsigned char (*fn)(unsigned char), unsigned char x) { return fn(x); }
static short call_short(short (*fn)(short), short x) { return fn(x); }
static unsigned short call_ushort(unsigned short (*fn)(unsigned short), unsigned short x) { return fn(x); }
static _Bool call_bool(_Bool (*fn)(_Bool), _Bool x) { return fn(x); }

int main(void) {
  if (call_schar(minicc_cb_schar, -90) != -96) return 1;
  if (call_uchar(minicc_cb_uchar, 230) != 237) return 2;
  if (call_short(minicc_cb_short, -10000) != -13000) return 3;
  if (call_ushort(minicc_cb_ushort, 40000) != 43000) return 4;
  if (call_bool(minicc_cb_bool, 0) != 0) return 5;
  if (call_bool(minicc_cb_bool, 2) != 1) return 6;
  return 0;
}
EOF
cc -std=c11 -o tmp-narrow-host-caller tmp-narrow-host-caller.c tmp-narrow-provider.o
set +e
./tmp-narrow-host-caller
actual="$?"
set -e
if [ "$actual" != 0 ]; then
  echo "FAIL(narrow callback ABI): host caller exit $actual"
  exit 1
fi

rm -f tmp-narrow-callback-host.c tmp-narrow-callback-host.o \
  tmp-narrow-callback-minicc.c tmp-narrow-callback-minicc.s tmp-narrow-callback \
  tmp-narrow-provider.c tmp-narrow-provider.s tmp-narrow-provider.o \
  tmp-narrow-host-caller.c tmp-narrow-host-caller

echo 'All narrow callback ABI tests passed!'
