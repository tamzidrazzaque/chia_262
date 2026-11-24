/* (a) qsort-like: generic byte-array quicksort with median-of-3, element
   counts computed as (pointer difference) / es with es a runtime parameter
   (= 8).  Written from scratch; pattern only. */
#include "rk.h"
typedef int (*cmp_fn)(const void *, const void *);

static int cmp_key(const void *a, const void *b) {
  u64 x = *(const u64 *)a, y = *(const u64 *)b;
  return (x > y) - (x < y);
}

static inline void swap_es(char *a, char *b, size_t es) {
  if (((es | (size_t)a | (size_t)b) & 7) == 0) {
    u64 *p = (u64 *)a, *q = (u64 *)b;
    for (size_t k = es >> 3; k; k--) { u64 t = *p; *p++ = *q; *q++ = t; }
  } else {
    for (size_t k = es; k; k--) { char t = *a; *a++ = *b; *b++ = t; }
  }
}

static char *median3(char *a, char *b, char *c, cmp_fn cmp) {
  if (cmp(a, b) < 0) return cmp(b, c) < 0 ? b : (cmp(a, c) < 0 ? c : a);
  return cmp(b, c) > 0 ? b : (cmp(a, c) < 0 ? a : c);
}

static void __attribute__((noipa)) F(qsort_es)(char *base, size_t n, size_t es, cmp_fn cmp) {
  while (n > 6) {
    char *last = base + (n - 1) * es;
    char *piv = median3(base, base + (n >> 1) * es, last, cmp);
    swap_es(base, piv, es);
    char *i = base + es, *j = last;
    for (;;) {
      while (i <= j && cmp(i, base) < 0) i += es;
      while (i <= j && cmp(j, base) > 0) j -= es;
      if (i >= j) break;
      swap_es(i, j, es);
      i += es;
      j -= es;
    }
    swap_es(base, j, es);
    /* element counts of the two parts from pointer differences */
    size_t nl = (size_t)(j - base) / es;
    size_t nr = (size_t)(last - j) / es;
    if (nl < nr) {
      F(qsort_es)(base, nl, es, cmp);
      base = j + es;
      n = nr;
    } else {
      F(qsort_es)(j + es, nr, es, cmp);
      n = nl;
    }
  }
  char *end = base + n * es;
  for (char *m = base + es; m < end; m += es)
    for (char *l = m; l > base && cmp(l - es, l) > 0; l -= es) swap_es(l, l - es, es);
}

static u64 work[QS_N];

u64 F(ka_qsort)(u64 *tm) {
  size_t es = qs_es;
  for (int i = 0; i < QS_N; i++) work[i] = qs_src[i];
  TSTART(tm);
  F(qsort_es)((char *)work, (size_t)QS_N * 8 / es, es, cmp_key);
  TSTOP(tm);
  u64 h = 0xcbf29ce484222325ULL;
  for (int i = 0; i < QS_N; i++) {
    h = rk_mix(h, work[i]);
    if (i && work[i - 1] > work[i]) h ^= 0xdead; /* not sorted */
  }
  return h;
}
