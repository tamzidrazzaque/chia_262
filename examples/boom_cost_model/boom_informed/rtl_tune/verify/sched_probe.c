/* identity probe: scheduling of mul/load/fp latencies and const-division expansion */
long mulsched(long *p, long a, long b, long c) {
  long x = a * b;          /* mul latency: A=3, B=6 */
  long y = p[0] + p[1];    /* load latency: A=3, B=4 */
  long z = p[2] ^ c;
  long w = p[3] - c;
  return (x + y) ^ (z * w);
}
double fpsched(double *d, double a) {
  double x = d[0] * a + d[1];
  double y = d[2] + d[3];
  double z = d[4] * d[5];
  return x * y + z;
}
int sdiv80(int x) { return x / 80; }
int smod1280(int x) { return x % 1280; }
long sdiv13(long x) { return x / 13; }
unsigned udiv10(unsigned x) { return x / 10; }
long mul37(long x) { return x * 37; }
long mul11(long x) { return x * 11; }
long divmod(long a, long b, long *r) { *r = a % b; return a / b; }
