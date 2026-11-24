import re,subprocess,sys,collections
od,binf=sys.argv[1],sys.argv[2]
txt=subprocess.run([od,'-d',binf],capture_output=True,text=True).stdout
fn=None; has=collections.defaultdict(lambda:[0,0])
for l in txt.splitlines():
    m=re.match(r'^[0-9a-f]+ <(f\d+)>:',l)
    if m: fn=m.group(1); has[fn]; continue
    if re.match(r'^[0-9a-f]+ <',l): fn=None; continue
    if fn and re.search(r'\t(div|divu|divw|divuw|rem|remu|remw|remuw)\s',l): has[fn][0]+=1
    if fn and re.search(r'\tmulhu?\s|\tmul\s|\tmulw\s',l): has[fn][1]+=1
n=len(has); d=sum(1 for v in has.values() if v[0]); m=sum(1 for v in has.values() if v[1] and not v[0])
print(f"{binf}: functions={n} with_div={d} mul_only={m}")
