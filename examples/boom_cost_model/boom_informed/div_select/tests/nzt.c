int f(int x) { int y = (x & 15); if (y >= 10) return y / 10; return 0; }
int g(int x) { int y = (x & 15) | 8; return y % 10; }
