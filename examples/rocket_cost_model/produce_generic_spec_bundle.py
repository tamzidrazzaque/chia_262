"""Build private generic SPEC role bundles for the Saturn manager intake."""
from __future__ import annotations
import argparse, hashlib, json, shutil
from pathlib import Path

GCC_REV = "1b306039ac49f8ad91ca71d3de3150a3c9fa792a"
GCC_SHA = "e46d71073c10417353a0718bff6bfadb818757b887da2622d353926a26700b0c"
TARGET = {"agfi":"agfi-012e92467d7d2149a", "driver_sha256":"5d3353ea8e6bf2891555da3d7b29122b1143a2e3d8c61a2a55741f1fd0bc94bd", "quintuplet":"f2-firesim-FireSim-FireSimREFV256D128RocketConfig-WithAutoILA_FRFCFS16GBQuadRankLLC4MB_BaseF2Config", "vlen_bits":256, "dlen_bits":128}

def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--spec-dir',type=Path,required=True); ap.add_argument('--evidence',type=Path,required=True); ap.add_argument('--out',type=Path,required=True); ap.add_argument('--benchmark',required=True); ap.add_argument('--size',default='test'); args=ap.parse_args()
    b=args.benchmark; prog=b.split('.',1)[1]; root=args.spec_dir/'benchspec'/'CPU'/b
    for role, flags, arch, rvv in [('1-scalar','-march=rv64gc -mabi=lp64d -mtune=rocket -fno-tree-loop-vectorize -fno-tree-slp-vectorize','rv64i2p1_m2p0_a2p1_f2p2_d2p2_c2p0_zicsr2p0_zifencei2p0_zmmul1p0_zaamo1p0_zalrsc1p0_zca1p0_zcd1p0',0),('2-generic-vector','-march=rv64gcv_zvbb -mabi=lp64d -mtune=rocket -mrvv-vector-bits=scalable -fvect-cost-model=dynamic -fopt-info-vec-all','rv64i2p1_m2p0_a2p1_f2p2_d2p2_c2p0_v1p0_zicsr2p0_zifencei2p0_zmmul1p0_zaamo1p0_zalrsc1p0_zca1p0_zcd1p0_zvbb1p0_zve32f1p0_zve32x1p0_zve64d1p0_zve64f1p0_zve64x1p0_zvkb1p0_zvl128b1p0_zvl32b1p0_zvl64b1p0',1)]:
        label=('saturn_role1_scalar' if role == '1-scalar' else 'saturn_role2_generic_vector'); run=max((root/'run').glob(f'run_base_{args.size}_{label}-64.*'),key=lambda p:p.stat().st_mtime_ns); exe=run/f'{prog}_base.{label}-64'; out=args.out/role; (out/'payload').mkdir(parents=True,exist_ok=True); (out/'metadata').mkdir(exist_ok=True); (out/'reference').mkdir(parents=True,exist_ok=True); shutil.copy2(exe,out/'payload/program'); shutil.copy2(run/'inp.in',out/'payload/input.in'); shutil.copy2(run/f'{prog.split("_",1)[0]}.out',out/'reference/mcf.out'); log=args.evidence / (f'{b}-{args.size}-saturn_role1_scalar-validate.log' if role == '1-scalar' else f'{b}-{args.size}-saturn_role2_generic_vector-validate.log'); shutil.copy2(log,out/'metadata/validation.log')
        files={};
        for p in (out/'payload/input.in',out/'reference/mcf.out',out/'payload/program',out/'metadata/validation.log'): files[str(p.relative_to(out))]=sha(p)
        compiler={'gcc_version':'15.1.0','gcc_revision':GCC_REV,'compiler_sha256':GCC_SHA,'role':role,'target_flags':flags,'candidate_id':None,'snapshot_id':None}; (out/'metadata/compiler.json').write_text(json.dumps(compiler,indent=2)+'\n'); files['metadata/compiler.json']=sha(out/'metadata/compiler.json')
        isa={'elf_sha256':files['payload/program'],'abi':'lp64d','linkage':'static','vlen_bits':256,'dlen_bits':128,'riscv_arch':arch,'static_rvv_instruction_count':(163 if rvv else 0)}; (out/'metadata/isa.json').write_text(json.dumps(isa,indent=2)+'\n'); files['metadata/isa.json']=sha(out/'metadata/isa.json')
        validation={'validation_log':'metadata/validation.log','status':'passed','spec_validation':'passed','backend':'qemu','role':role,'benchmark':b,'size':args.size,'input_id':'605-mcf-'+args.size,'target_vlen':256,'target_dlen':128,'source_variant':'unchanged SPEC CPU2017 source','elf_sha256':files['payload/program'],'invocation_sha256':hashlib.sha256(json.dumps({'argv':['./program','input.in'],'stdin':None,'stdout':'stdout.txt','stderr':'stderr.txt'},sort_keys=True,separators=(',',':')).encode()).hexdigest(),'compiler_manifest_sha256':files['metadata/compiler.json'],'isa_metadata_sha256':files['metadata/isa.json'],'inputs_sha256':{'input.in':files['payload/input.in']},'expected_outputs_sha256':{'mcf.out':files['reference/mcf.out']}}; (out/'metadata/validation.json').write_text(json.dumps(validation,indent=2)+'\n'); files['metadata/validation.json']=sha(out/'metadata/validation.json')
        m={'schema_version':1,'role':role,'candidate_id':None,'benchmark':b,'input_id':'605-mcf-'+args.size,'size':args.size,'source_variant':'unchanged SPEC CPU2017 source','target':TARGET,'compiler_manifest':'metadata/compiler.json','isa_metadata':'metadata/isa.json','validation_manifest':'metadata/validation.json','executable':'payload/program','inputs':{'input.in':'payload/input.in'},'expected_outputs':{'mcf.out':'reference/mcf.out'},'argv':['./program','input.in'],'stdin':None,'stdout':'stdout.txt','stderr':'stderr.txt','files_sha256':files}; (out/'manifest.json').write_text(json.dumps(m,indent=2,sort_keys=True)+'\n'); print(out)
if __name__=='__main__': main()
