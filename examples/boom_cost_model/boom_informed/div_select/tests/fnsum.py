import re,sys
for f in sys.argv[1:]:
    fn=None; d={}
    for l in open(f):
        m=re.match(r'^([A-Za-z_]\w*):',l)
        if m: fn=m.group(1); d[fn]=[]; continue
        m=re.match(r'^\t(div\w*|rem\w*|mulhu?|mulw?)\t',l)
        if m and fn: d[fn].append(m.group(1))
    print(f.split('/')[-1].ljust(18),' '.join(f"{k[2:]}:{'+'.join(v) or '-'}" for k,v in d.items() if k.startswith('k_')))
