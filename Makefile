CFLAGS=-std=c11 -g -fno-common
SRCS=$(filter-out tmp.c,$(wildcard *.c))
OBJS=$(SRCS:.c=.o)

minicc: $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

$(OBJS): minicc.h

test: minicc
	./test/test.sh
	bash ./test/preprocessor.sh

clean:
	rm -f minicc *.o *~ tmp*

.PHONY: test clean
