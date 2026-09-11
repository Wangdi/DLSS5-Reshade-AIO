#pragma once
/*
 * Ada DLSS-G MFG helper for DLSS5 ReShade AIO.
 * SPDX-License-Identifier: MIT
 *
 * Runtime-only patching of the mapped DLSS-G image. No NVIDIA binary is
 * modified or redistributed. Layout checks are intentionally fail-closed.
 *
 * Integration note: this helper is consumed by the AIO standalone Direct-NGX
 * path; Streamline's sl.dlss_g frame-count hook is deliberately not used.
 */
#include <windows.h>
#include <cstdint>
#include <cstring>
#include <sstream>
#include <string>
#include <vector>

namespace dlss5_aio_mfg {
constexpr unsigned char kArchOld = 0xB0;
constexpr unsigned char kArchNew = 0x90;
constexpr uint32_t kFatbinMagic = 0xBA55ED50u;
constexpr size_t kOuterHeader = 16;
constexpr uint32_t kPtxKind = 1;
constexpr uint32_t kAdaArch = 89;
constexpr uint64_t kUncompressedFlags = 0x41;
constexpr size_t kExpectedPtxBytes = 99362;
constexpr size_t kExpectedMidpoints = 104;
constexpr char kJoinLabel[] = "$L__BB0_3:";
constexpr char kMidpointBits[] = "0f3F000000";
constexpr char kMulPrefix[] = "mul.ftz.f32 ";
constexpr char kCurrToPrev[] = "%f136";
constexpr char kPrevToCurr[] = "%f134";
constexpr char kTemporalInput[] = "ld.param.f32 %f134, [main_kernel_param_0+32];\r\nmov.f32 %f135, 0f3F800000;\r\nsub.ftz.f32 %f136, %f135, %f134;\r\n";
constexpr char kEntryName[] = "main_kernel";
constexpr char kDescriptorName[] = "dlfg_kernel";
constexpr size_t kEntryNameOffset = 0x10;
constexpr size_t kDescriptorNameOffset = 0x28;
struct PatchSite { unsigned char *address=nullptr; unsigned char original=0; };
struct DescriptorPatch { uint64_t *slot=nullptr; uint64_t original=0; };
struct State { bool gates_patched=false; bool temporal_patched=false; size_t gate_sites=0; size_t descriptor_sites=0; std::vector<PatchSite> gates; std::vector<DescriptorPatch> descriptors; void *allocation=nullptr; };
inline State g_state;
inline uint16_t U16(const uint8_t*p){uint16_t v;std::memcpy(&v,p,2);return v;}
inline uint32_t U32(const uint8_t*p){uint32_t v;std::memcpy(&v,p,4);return v;}
inline uint64_t U64(const uint8_t*p){uint64_t v;std::memcpy(&v,p,8);return v;}
inline bool Lz4(const uint8_t*s,size_t ss,uint8_t*d,size_t ds){size_t i=0,o=0;while(i<ss){uint8_t t=s[i++];size_t l=t>>4;if(l==15){uint8_t e;do{if(i>=ss)return false;e=s[i++];l+=e;}while(e==255);}if(l>ss-i||l>ds-o)return false;std::memcpy(d+o,s+i,l);i+=l;o+=l;if(i==ss)break;if(ss-i<2)return false;size_t b=s[i]|(size_t(s[i+1])<<8);i+=2;if(!b||b>o)return false;size_t m=4+(t&15);if((t&15)==15){uint8_t e;do{if(i>=ss)return false;e=s[i++];m+=e;}while(e==255);}if(m>ds-o)return false;for(size_t j=0;j<m;++j)d[o+j]=d[o+j-b];o+=m;}return i==ss&&o==ds;}
inline bool Entry(const uint8_t*f,size_t fs,size_t&eo){if(fs<16||U32(f)!=kFatbinMagic||U16(f+6)!=16)return false;uint64_t dec=U64(f+8);if(dec+16!=fs)return false;for(size_t p=16;p+64<=fs;){uint32_t kind=U16(f+p),hdr=U32(f+p+4);uint64_t pay=U64(f+p+8);if(hdr<64||!pay||p+hdr+pay>fs)return false;if(kind==kPtxKind&&U32(f+p+28)==kAdaArch){eo=p;return true;}p+=hdr+pay;}return false;}
inline bool CString(const uint8_t*b,size_t sz,uint64_t v,const char*e){uintptr_t st=(uintptr_t)b;if(v<st||v>=st+sz)return false;size_t n=std::strlen(e);return v+n+1<=st+sz&&std::memcmp((const char*)v,e,n+1)==0;}
inline bool Build(const uint8_t*f,size_t fs,std::vector<uint8_t>&out,std::string&why){size_t e;if(!Entry(f,fs,e)){why="no sm_89 PTX entry";return false;}uint32_t h=U32(f+e+4),c=U32(f+e+16);uint64_t raw=U64(f+e+56);if(!c||raw!=kExpectedPtxBytes){std::ostringstream s;s<<"unsupported PTX layout (raw="<<raw<<")";why=s.str();return false;}std::vector<uint8_t>p(raw);if(!Lz4(f+e+h,c,p.data(),p.size())){why="LZ4 decompression failed";return false;}const char*b=(const char*)p.data();size_t n=p.size(),ll=sizeof(kJoinLabel)-1;size_t lab=SIZE_MAX;for(size_t i=0;i+ll<=n;++i)if(!std::memcmp(b+i,kJoinLabel,ll)){if(lab!=SIZE_MAX){why="join label not unique";return false;}lab=i;}if(lab==SIZE_MAX){why="join label missing";return false;}size_t ins=lab+ll;while(ins<n&&b[ins]!='\n')++ins;if(ins>=n){why="join label has no newline";return false;}++ins;size_t ml=sizeof(kMidpointBits)-1,mpl=sizeof(kMulPrefix)-1;std::vector<size_t>marks;for(size_t i=0;i+ml<n;++i){if(std::memcmp(b+i,kMidpointBits,ml)||b[i+ml]!=';')continue;size_t l=i;while(l&&b[l-1]!='\n')--l;if(i-l>=mpl&&!std::memcmp(b+l,kMulPrefix,mpl))marks.push_back(i);}if(marks.size()!=kExpectedMidpoints){std::ostringstream s;s<<"expected "<<kExpectedMidpoints<<" midpoint multiplies, got "<<marks.size();why=s.str();return false;}std::vector<uint8_t>q;q.reserve(n+sizeof(kTemporalInput));auto A=[&](const void*x,size_t z){auto*bb=(const uint8_t*)x;q.insert(q.end(),bb,bb+z);};A(p.data(),ins);A(kTemporalInput,sizeof(kTemporalInput)-1);size_t src=ins,half=marks.size()/2;for(size_t i=0;i<marks.size();++i){A(p.data()+src,marks[i]-src);A(i<half?kCurrToPrev:kPrevToCurr,5);src=marks[i]+ml;}A(p.data()+src,n-src);size_t pad=(q.size()+7)&~size_t(7),fin=e+h+pad;out.assign(f,f+e+h);out.resize(fin,0);std::memcpy(out.data()+e+h,q.data(),q.size());uint64_t pay=pad,z64=0,outer=fin-16;uint32_t z32=0;std::memcpy(out.data()+e+8,&pay,8);std::memcpy(out.data()+e+16,&z32,4);std::memcpy(out.data()+e+40,&kUncompressedFlags,8);std::memcpy(out.data()+e+56,&z64,8);std::memcpy(out.data()+8,&outer,8);return true;}
inline bool ModuleImage(HMODULE m,uint8_t*&b,const IMAGE_NT_HEADERS64*&nt){if(!m)return false;b=(uint8_t*)m;auto*d=(IMAGE_DOS_HEADER*)b;if(d->e_magic!=IMAGE_DOS_SIGNATURE)return false;nt=(IMAGE_NT_HEADERS64*)(b+d->e_lfanew);return nt->Signature==IMAGE_NT_SIGNATURE&&nt->OptionalHeader.Magic==IMAGE_NT_OPTIONAL_HDR64_MAGIC;}
inline size_t PatchGates(HMODULE m){if(g_state.gates_patched)return g_state.gate_sites;uint8_t*b;const IMAGE_NT_HEADERS64*nt;if(!ModuleImage(m,b,nt))return 0;std::vector<unsigned char*>f;auto*s=IMAGE_FIRST_SECTION(nt);for(WORD si=0;si<nt->FileHeader.NumberOfSections;++si,++s){if(!(s->Characteristics&IMAGE_SCN_MEM_EXECUTE))continue;auto*x=b+s->VirtualAddress;size_t z=s->Misc.VirtualSize;for(size_t o=0;o+6<=z;++o){if(x[o]==0x3D&&x[o+1]==kArchOld&&x[o+2]==1&&x[o+3]==0&&x[o+4]==0){f.push_back(x+o+1);continue;}if(x[o]==0x81&&x[o+1]>=0xF8&&x[o+1]<=0xFF&&x[o+2]==kArchOld&&x[o+3]==1&&x[o+4]==0&&x[o+5]==0)f.push_back(x+o+2);}}if(f.empty()||f.size()>4)return 0;for(auto*p:f){DWORD old;if(!VirtualProtect(p,1,PAGE_READWRITE,&old))return 0;g_state.gates.push_back({p,*p});*p=kArchNew;DWORD q;VirtualProtect(p,1,old,&q);FlushInstructionCache(GetCurrentProcess(),p,1);}g_state.gates_patched=true;g_state.gate_sites=f.size();return g_state.gate_sites;}
inline size_t PatchTemporal(HMODULE m,std::string&why){if(g_state.temporal_patched)return g_state.descriptor_sites;uint8_t*b;const IMAGE_NT_HEADERS64*nt;if(!ModuleImage(m,b,nt)){why="invalid PE";return 0;}uintptr_t st=(uintptr_t)b;size_t sz=nt->OptionalHeader.SizeOfImage;std::vector<uint64_t*>slots;const uint8_t*fat=nullptr;size_t fs=0;auto*s=IMAGE_FIRST_SECTION(nt);for(WORD si=0;si<nt->FileHeader.NumberOfSections;++si,++s){if(!(s->Characteristics&IMAGE_SCN_MEM_READ)||(s->Characteristics&IMAGE_SCN_MEM_EXECUTE))continue;auto*x=b+s->VirtualAddress;size_t z=s->Misc.VirtualSize;for(size_t o=0;o+kDescriptorNameOffset+8<=z;o+=8){uint64_t v;std::memcpy(&v,x+o,8);if(v<st||v>=st+sz)continue;auto*c=(const uint8_t*)v;if(U32(c)!=kFatbinMagic)continue;uint64_t en=0,dn=0;std::memcpy(&en,x+o+kEntryNameOffset,8);std::memcpy(&dn,x+o+kDescriptorNameOffset,8);if(!CString(b,sz,en,kEntryName)||!CString(b,sz,dn,kDescriptorName))continue;uint64_t total=U64(c+8)+16;if(total<1024||total>(16u<<20)||v+total>st+sz||!([](const uint8_t*f,size_t n){size_t e=0;return Entry(f,n,e)&&U64(f+e+56)==kExpectedPtxBytes;})(c,total))continue;if(!fat){fat=c;fs=total;}else if(c!=fat)continue;slots.push_back((uint64_t*)(x+o));}}if(!fat||slots.empty()){why="no matching dlfg_kernel descriptor";return 0;}std::vector<uint8_t>rebuilt;if(!Build(fat,fs,rebuilt,why))return 0;void*mem=VirtualAlloc(nullptr,rebuilt.size(),MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);if(!mem){why="VirtualAlloc failed";return 0;}std::memcpy(mem,rebuilt.data(),rebuilt.size());for(auto*p:slots){DWORD old;if(!VirtualProtect(p,8,PAGE_READWRITE,&old))continue;g_state.descriptors.push_back({p,*p});*p=(uint64_t)mem;DWORD q;VirtualProtect(p,8,old,&q);}if(g_state.descriptors.empty()){VirtualFree(mem,0,MEM_RELEASE);why="no writable descriptor";return 0;}g_state.temporal_patched=true;g_state.descriptor_sites=g_state.descriptors.size();g_state.allocation=mem;return g_state.descriptor_sites;}
inline bool Apply(HMODULE m,size_t&g,size_t&t,std::string&d){g=PatchGates(m);if(!g_state.gates_patched){d="Ada MFG arch gates not found";return false;}if(!t){std::string why;t=PatchTemporal(m,why);if(!t){d="temporal patch unavailable: "+why;return false;}}std::ostringstream s;s<<"Ada MFG unlock active (gates="<<g<<", temporal="<<t<<")";d=s.str();return true;}
inline bool IsReady(){return g_state.gates_patched&&g_state.temporal_patched;}
}
