#!/bin/bash
set -eu

cat > tmp-digraphs.c <<'EOF'
struct Pair <% int x; int y; %>;

int sum(int a<:3:>) <%
  return a<:0:> + a<:1:> + a<:2:>;
%>

int main(void) <%
  int values<:3:> = <% 4, 5, 6 %>;
  struct Pair p = <% 7, 8 %>;
  int matrix<:2:><:2:> = <% <%1, 2%>, <%3, 4%> %>;

  if (sum(values) != 15)
    return 1;
  if (p.x != 7 || p.y != 8)
    return 2;
  if (matrix<:1:><:0:> != 3 || matrix<:1:><:1:> != 4)
    return 3;
  return 0;
%>
EOF

./minicc tmp-digraphs.c > tmp-digraphs.s
cc -o tmp-digraphs tmp-digraphs.s
./tmp-digraphs

rm -f tmp-digraphs.c tmp-digraphs.s tmp-digraphs

echo 'All C11 bracket/brace digraph tests passed!'
