#!/usr/bin/env python3
"""Build the separately gated width-48 MSE C++17 candidate.

The emitted source carries a tiny self-contained zlib/DEFLATE decoder, so the
CodinGame compiler does not need an external -lz link option.
"""

from __future__ import annotations

import argparse
import hashlib
import math
from pathlib import Path
import struct
import zlib

from build_submission import BuildError, CODINGAME_CODE_LIMIT, pack_15bit, replace_once


PARAMETER_COUNT=142_812
PATTERN_SIZES=(8,8,8,5,6,7,8,10,10,10,10)
QMAX=1_023
DECODER_START="/*__MODEL_DECODER_BEGIN__*/"
DECODER_END="/*__MODEL_DECODER_END__*/"


CPP_DECODER=r'''/*__MODEL_DECODER_BEGIN__*/
struct Bits{const std::vector<std::uint8_t>&d;std::size_t p=2;std::uint64_t h=0;int n=0;unsigned get(int k){while(n<k){if(p>=d.size())throw std::runtime_error("deflate eof");h|=std::uint64_t(d[p++])<<n;n+=8;}unsigned v=unsigned(h&((1ULL<<k)-1));h>>=k;n-=k;return v;}void align(){int k=n&7;h>>=k;n-=k;}};
struct Huff{int count[16]{},symbol[288]{};void build(const int*l,int n){int off[16]{};for(int i=0;i<n;i++){if(l[i]<0||l[i]>15)throw std::runtime_error("deflate lengths");count[l[i]]++;}if(count[0]==n)throw std::runtime_error("empty huffman");off[1]=0;for(int i=1;i<15;i++)off[i+1]=off[i]+count[i];for(int i=0;i<n;i++)if(l[i])symbol[off[l[i]]++]=i;}int decode(Bits&b)const{int code=0,first=0,index=0;for(int len=1;len<=15;len++){code|=int(b.get(1));int c=count[len];if(code-first<c)return symbol[index+code-first];index+=c;first=(first+c)<<1;code<<=1;}throw std::runtime_error("bad huffman");}};
std::vector<std::uint8_t> inflateZlib(const std::vector<std::uint8_t>&in,std::size_t wanted){
  if(in.size()<6||(in[0]&15)!=8||((int(in[0])<<8)+in[1])%31)throw std::runtime_error("zlib header");
  Bits b{in};std::vector<std::uint8_t>out;out.reserve(wanted);bool final=false;
  static constexpr int LB[29]={3,4,5,6,7,8,9,10,11,13,15,17,19,23,27,31,35,43,51,59,67,83,99,115,131,163,195,227,258};
  static constexpr int LE[29]={0,0,0,0,0,0,0,0,1,1,1,1,2,2,2,2,3,3,3,3,4,4,4,4,5,5,5,5,0};
  static constexpr int DB[30]={1,2,3,4,5,7,9,13,17,25,33,49,65,97,129,193,257,385,513,769,1025,1537,2049,3073,4097,6145,8193,12289,16385,24577};
  static constexpr int DE[30]={0,0,0,0,1,1,2,2,3,3,4,4,5,5,6,6,7,7,8,8,9,9,10,10,11,11,12,12,13,13};
  while(!final){final=b.get(1);int type=b.get(2);if(type==0){b.align();unsigned len=b.get(16),nlen=b.get(16);if((len^0xffffU)!=nlen)throw std::runtime_error("stored block");while(len--)out.push_back(std::uint8_t(b.get(8)));continue;}if(type==3)throw std::runtime_error("reserved block");
    int ll[288]{},dd[32]{};Huff lh,dh;if(type==1){for(int i=0;i<=143;i++)ll[i]=8;for(int i=144;i<=255;i++)ll[i]=9;for(int i=256;i<=279;i++)ll[i]=7;for(int i=280;i<288;i++)ll[i]=8;for(int&i:dd)i=5;lh.build(ll,288);dh.build(dd,32);}else{
      int nl=int(b.get(5))+257,nd=int(b.get(5))+1,nc=int(b.get(4))+4,cl[19]{},lens[320]{},order[19]={16,17,18,0,8,7,9,6,10,5,11,4,12,3,13,2,14,1,15};for(int i=0;i<nc;i++)cl[order[i]]=int(b.get(3));Huff ch;ch.build(cl,19);int at=0,prev=0,total=nl+nd;while(at<total){int s=ch.decode(b),rep=1,val=s;if(s==16){if(at==0)throw std::runtime_error("repeat");rep=int(b.get(2))+3;val=prev;}else if(s==17){rep=int(b.get(3))+3;val=0;}else if(s==18){rep=int(b.get(7))+11;val=0;}else if(s>15)throw std::runtime_error("code length");if(at+rep>total)throw std::runtime_error("repeat length");while(rep--)lens[at++]=val;prev=val;}std::copy(lens,lens+nl,ll);std::copy(lens+nl,lens+total,dd);lh.build(ll,nl);dh.build(dd,nd);}
    for(;;){int s=lh.decode(b);if(s<256){out.push_back(std::uint8_t(s));continue;}if(s==256)break;if(s<257||s>285)throw std::runtime_error("length symbol");int li=s-257,len=LB[li]+int(b.get(LE[li])),ds=dh.decode(b);if(ds<0||ds>=30)throw std::runtime_error("distance symbol");int dist=DB[ds]+int(b.get(DE[ds]));if(dist>int(out.size()))throw std::runtime_error("distance");while(len--){out.push_back(out[out.size()-dist]);if(out.size()>wanted)throw std::runtime_error("inflate overflow");}}
  }if(out.size()!=wanted)throw std::runtime_error("inflate length");return out;
}
std::vector<double> decodeModel(){
  constexpr std::size_t COMPRESSED=/*__COMPRESSED_BYTES__*/;constexpr std::size_t RAW=/*__RAW_BYTES__*/;std::vector<std::uint8_t>compressed;compressed.reserve(COMPRESSED);std::uint64_t acc=0;int bits=0;
  for(auto s:MODEL_DATA)for(char16_t ch:s){int q=int(ch)-0x3400;if(q<0||q>=32768)throw std::runtime_error("model alphabet");acc|=std::uint64_t(q)<<bits;bits+=15;while(bits>=8&&compressed.size()<COMPRESSED){compressed.push_back(std::uint8_t(acc&255));acc>>=8;bits-=8;}}
  if(compressed.size()!=COMPRESSED)throw std::runtime_error("packed length");
  auto raw=inflateZlib(compressed,RAW);if(crc32(raw)!=MODEL_CRC)throw std::runtime_error("model checksum");
  constexpr int SEGMENTS=288;float scales[SEGMENTS]{};std::size_t p=0;for(float&scale:scales){std::uint32_t u=raw[p]|(std::uint32_t(raw[p+1])<<8)|(std::uint32_t(raw[p+2])<<16)|(std::uint32_t(raw[p+3])<<24);std::memcpy(&scale,&u,4);p+=4;}
  std::vector<int>lengths;lengths.reserve(SEGMENTS);for(int ph=0;ph<4;ph++){for(int size:PAT_SIZE){lengths.push_back(size*2*48);lengths.push_back(48);lengths.push_back(48*48);lengths.push_back(48);lengths.push_back(48);lengths.push_back(1);}int add[]={24,8,64,8,19,1};lengths.insert(lengths.end(),std::begin(add),std::end(add));}
  std::vector<double>w(PARAMETER_COUNT);int k=0;for(int s=0;s<SEGMENTS;s++)for(int end=k+lengths[s];k<end;k++){std::uint16_t u=raw[p]|(std::uint16_t(raw[p+1])<<8);p+=2;w[k]=std::int16_t(u)*scales[s];}if(k!=PARAMETER_COUNT||p!=raw.size())throw std::runtime_error("model length");return w;
}
/*__MODEL_DECODER_END__*/'''


def lengths()->list[int]:
    out=[]
    for _ in range(4):
        for size in PATTERN_SIZES:out.extend((size*2*48,48,48*48,48,48,1))
        out.extend((24,8,64,8,19,1))
    assert len(out)==288 and sum(out)==PARAMETER_COUNT
    return out


def read(path:Path)->list[float]:
    values=[float(x) for x in path.read_text(encoding="utf-8-sig").splitlines()]
    if len(values)!=PARAMETER_COUNT or not all(math.isfinite(v) for v in values):raise BuildError("invalid width48 parameter file")
    return values


def strip_disabled_lazy_blocks(source:str)->str:
    """Remove OTHELLO_LAZY_MODEL-only branches from the near-limit candidate."""
    lines=source.splitlines(keepends=True)
    while True:
        start=next((i for i,line in enumerate(lines) if line.strip()=="#if defined(OTHELLO_LAZY_MODEL)"),None)
        if start is None:return "".join(lines)
        depth=0;otherwise=None;end=None
        for i in range(start,len(lines)):
            directive=lines[i].lstrip()
            if directive.startswith(("#if ","#ifdef ","#ifndef ")):depth+=1
            elif directive.startswith("#endif"):
                depth-=1
                if depth==0:end=i;break
            elif depth==1 and directive.startswith("#else"):otherwise=i
        if end is None:raise BuildError("unterminated OTHELLO_LAZY_MODEL block")
        replacement=lines[otherwise+1:end] if otherwise is not None else []
        lines[start:end+1]=replacement


def build(template:Path,param:Path,output:Path,budget:int)->dict[str,object]:
    values=read(param);scales=[];quantized=[];at=0
    for n in lengths():
        part=values[at:at+n];at+=n;scale=max(map(abs,part))/QMAX if any(part) else 1.0;scale=struct.unpack("<f",struct.pack("<f",scale))[0];scales.append(scale)
        quantized.extend(max(-QMAX,min(QMAX,round(v/scale))) for v in part)
    raw=struct.pack(f"<{len(scales)}f",*scales)+struct.pack(f"<{len(quantized)}h",*quantized);compressed=zlib.compress(raw,9);packed=pack_15bit(compressed)
    source=template.read_text(encoding="utf-8-sig");start=source.index(DECODER_START);end=source.index(DECODER_END)+len(DECODER_END)
    decoder=CPP_DECODER.replace("/*__COMPRESSED_BYTES__*/",str(len(compressed))).replace("/*__RAW_BYTES__*/",str(len(raw)));source=source[:start]+decoder+source[end:]
    chunks=[packed[i:i+8000] for i in range(0,len(packed),8000)]
    source=replace_once(source,"/*__MODEL_DATA__*/",",\n".join(f'u"{x}"' for x in chunks));source=replace_once(source,"/*__MODEL_SCALES__*/","1.0,1.0,1.0,1.0")
    source=replace_once(source,"/*__MODEL_CRC32__*/",f"0x{zlib.crc32(raw)&0xffffffff:08X}U");source=replace_once(source,"/*__MODEL_SHA256__*/",f'"{hashlib.sha256(param.read_bytes()).hexdigest().upper()}"')
    source=replace_once(source,"/*__VARIANT_DEFINE__*/",'#define OTHELLO_WIDTH48 1\n#define OTHELLO_VARIANT_NAME "cpp48"');source=replace_once(source,"/*__MOVE_BUDGET_MS__*/",str(budget));source=replace_once(source,"/*__HIDDEN__*/","48");source=replace_once(source,"/*__PARAMETER_COUNT__*/",str(PARAMETER_COUNT))
    source=strip_disabled_lazy_blocks(source)
    # Preserve the readable template, but remove indentation from this near-limit
    # generated candidate. Leading whitespace is not semantically significant.
    source="\n".join(line.lstrip() for line in source.splitlines())+"\n"
    units=len(source.encode("utf-16-le"))//2
    if units>CODINGAME_CODE_LIMIT:raise BuildError(f"cpp48 is gated out: {units:,} UTF-16 units exceeds {CODINGAME_CODE_LIMIT:,}")
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(source,encoding="utf-8",newline="\n")
    return {"utf16_units":units,"utf8_bytes":len(source.encode("utf-8")),"compressed_bytes":len(compressed),"packed_chars":len(packed),"raw_bytes":len(raw)}


def main()->int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--template",type=Path,default=Path("template/PlayerTemplate.cpp"));p.add_argument("--param",type=Path,default=Path("model/width48_param.txt"));p.add_argument("--output",type=Path,default=Path("candidates/Player_cpp48.cpp"));p.add_argument("--budget-ms",type=int,default=115);a=p.parse_args()
    try:report=build(a.template,a.param,a.output,a.budget_ms)
    except (BuildError,OSError,ValueError) as e:print(f"ERROR: {e}");return 2
    print(f"Generated: {a.output.resolve()}");print("\n".join(f"{k}: {v}" for k,v in report.items()));return 0


if __name__=="__main__":raise SystemExit(main())
