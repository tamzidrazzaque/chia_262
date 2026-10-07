int int_mix(const int *a, int n) {
  int s = 0;
  for (int i = 0; i < n; ++i) {
    int v = a[i];
    s += (v * 13) / (v | 1);
  }
  return s;
}
