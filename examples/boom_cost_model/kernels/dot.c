float dot(const float *a, const float *b, int n) {
  float s = 0.f;
  for (int i = 0; i < n; ++i)
    s += a[i] * b[i];
  return s;
}
