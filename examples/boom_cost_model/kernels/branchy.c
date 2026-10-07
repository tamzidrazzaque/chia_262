int branchy(const int *a, int n) {
  int s = 0;
  for (int i = 0; i < n; ++i) {
    int v = a[i];
    if (v > 100)
      s += v * 3;
    else if (v < 0)
      s -= v;
    else
      s += 1;
  }
  return s;
}
