/*
 * OthelloAI CodinGame C++17 edition.
 * Derived from original_11/OthelloAI_10 and Egaroucid 7.8.2.
 * Egaroucid portions Copyright (C) Takuto Yamana (Nyanyan),
 * commit 112981e381801a38604f54714d46eb9d90322b80.
 * GPL-3.0-or-later; there is no warranty. See the accompanying LICENSE.
 * Generated Player.cpp is a single-file, value-only submission.
 */
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cctype>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

/*__VARIANT_DEFINE__*/

namespace othello {
using U64 = std::uint64_t;
using Clock = std::chrono::steady_clock;

constexpr int HW=8, SQ_N=64, LINE_N=6561, INF=1000000, SCALE=6400, STEP=100;
constexpr int HIDDEN=/*__HIDDEN__*/;
constexpr int PARAMETER_COUNT=/*__PARAMETER_COUNT__*/;
constexpr int PAT_SIZE[11]={8,8,8,5,6,7,8,10,10,10,10};
constexpr int CELL_WEIGHT[64]={
  120,-20,20,5,5,20,-20,120,-20,-40,-5,-5,-5,-5,-40,-20,
  20,-5,15,3,3,15,-5,20,5,-5,3,3,3,3,-5,5,
  5,-5,3,3,3,3,-5,5,20,-5,15,3,3,15,-5,20,
  -20,-40,-5,-5,-5,-5,-40,-20,120,-20,20,5,5,20,-20,120
};
constexpr int GP[38][8]={
  {0,1,2,3,4,5,6,7},{8,9,10,11,12,13,14,15},
  {16,17,18,19,20,21,22,23},{24,25,26,27,28,29,30,31},
  {32,33,34,35,36,37,38,39},{40,41,42,43,44,45,46,47},
  {48,49,50,51,52,53,54,55},{56,57,58,59,60,61,62,63},
  {0,8,16,24,32,40,48,56},{1,9,17,25,33,41,49,57},
  {2,10,18,26,34,42,50,58},{3,11,19,27,35,43,51,59},
  {4,12,20,28,36,44,52,60},{5,13,21,29,37,45,53,61},
  {6,14,22,30,38,46,54,62},{7,15,23,31,39,47,55,63},
  {5,14,23,-1,-1,-1,-1,-1},{4,13,22,31,-1,-1,-1,-1},
  {3,12,21,30,39,-1,-1,-1},{2,11,20,29,38,47,-1,-1},
  {1,10,19,28,37,46,55,-1},{0,9,18,27,36,45,54,63},
  {8,17,26,35,44,53,62,-1},{16,25,34,43,52,61,-1,-1},
  {24,33,42,51,60,-1,-1,-1},{32,41,50,59,-1,-1,-1,-1},
  {40,49,58,-1,-1,-1,-1,-1},{2,9,16,-1,-1,-1,-1,-1},
  {3,10,17,24,-1,-1,-1,-1},{4,11,18,25,32,-1,-1,-1},
  {5,12,19,26,33,40,-1,-1},{6,13,20,27,34,41,48,-1},
  {7,14,21,28,35,42,49,56},{15,22,29,36,43,50,57,-1},
  {23,30,37,44,51,58,-1,-1},{31,38,45,52,59,-1,-1,-1},
  {39,46,53,60,-1,-1,-1,-1},{47,54,61,-1,-1,-1,-1,-1}
};
constexpr int OFFSET[38]={
  1,1,1,1,1,1,1,1,8,8,8,8,8,8,8,8,
  9,9,9,9,9,9,9,9,9,9,9,7,7,7,7,7,7,7,7,7,7,7
};
constexpr int REVERSE_ORDER[3][10]={
  {0,4,7,9,1,5,8,2,6,3},
  {5,4,3,2,1,0,9,8,7,6},
  {0,1,2,3,7,8,9,4,5,6}
};
constexpr double MODEL_SCALE[4]={/*__MODEL_SCALES__*/};
constexpr std::uint32_t MODEL_CRC=/*__MODEL_CRC32__*/;
constexpr std::string_view MODEL_SHA=/*__MODEL_SHA256__*/;
constexpr std::u16string_view MODEL_DATA[]={/*__MODEL_DATA__*/};
constexpr int MOVE_BUDGET_MS=/*__MOVE_BUDGET_MS__*/;

int POW3[11];
std::array<std::uint8_t,2*LINE_N*8*2> MOVE{};
std::array<std::uint16_t,2*LINE_N*8> FLIP{},PUT{};
std::array<std::uint8_t,LINE_N*8> DIGIT{};
std::array<std::uint8_t,2*LINE_N> SURROUND{};
std::array<std::int8_t,LINE_N> COUNT{},COUNT_ALL{};
std::array<std::uint16_t,LINE_N> REVERSE{};
std::array<std::int8_t,38*64> LOCAL{};
std::array<std::int8_t,64*4> INCLUDED{};

#if defined(OTHELLO_OPTIMIZED)
constexpr std::int64_t EVAL_Q=1LL<<20;
using EvalTable=std::vector<std::int32_t>;
std::array<std::array<EvalTable,11>,4> PATTERN;
std::array<std::vector<std::int32_t>,4> ADDITION;
std::int64_t BIAS_Q[4]{};
#else
using EvalTable=std::vector<float>;
std::array<std::array<EvalTable,11>,4> PATTERN;
std::array<std::vector<float>,4> ADDITION;
#endif
float DENSE[4][19]{};
double BIAS[4]{};
#if defined(OTHELLO_LAZY_MODEL)
struct PatternNetwork {
  int size=0;
  double d0[HIDDEN][20]{},d1[HIDDEN][HIDDEN]{},b0[HIDDEN]{},b1[HIDDEN]{},d2[HIDDEN]{},b2=0;
  std::vector<float> cache;
};
struct AdditionNetwork {double d0[8][3]{},d1[8][8]{},b0[8]{},b1[8]{};};
PatternNetwork PATTERN_NET[4][11];
AdditionNetwork ADDITION_NET[4];
#endif

constexpr int MPC_DEPTH[11]={0,0,0,1,2,1,2,3,4,3,4};
constexpr int MPC_SD[6][10]={
  {482,512,352,298,474,372,349,323,463,335},
  {312,381,310,261,354,322,291,313,389,371},
  {389,463,392,352,548,402,422,441,530,538},
  {417,490,436,405,570,494,452,438,527,524},
  {486,554,519,463,635,665,555,550,635,581},
  {433,517,430,391,560,556,383,345,567,332}
};
int MPC[6][11]{};
constexpr U64 H_MASK=0x7e7e7e7e7e7e7e7eULL;
constexpr U64 CORNERS=0x8100000000000081ULL;
constexpr U64 REGIONS[4]={
  0x000000000f0f0f0fULL,0x00000000f0f0f0f0ULL,
  0x0f0f0f0f00000000ULL,0xf0f0f0f000000000ULL
};
constexpr int EDGE_CORNERS[4]={0,7,56,63};
constexpr int EDGE_D1[4]={1,-1,1,-1};
constexpr int EDGE_D2[4]={8,8,-8,-8};

struct Board {
  int a[38]{};
  U64 black=0,white=0,empty=0;
  int p=0,n=0,move=-1,order=0;
};
Board POOL[66][64],PASS[66];
Board* ORDERED[66][64]{};

constexpr int TT_BITS=18,TT_SIZE=1<<TT_BITS,TT_MASK=TT_SIZE-1;
std::array<U64,TT_SIZE> T_BLACK{},T_WHITE{};
std::array<int,TT_SIZE> T_VALUE{};
std::array<std::uint8_t,TT_SIZE> T_DEPTH{},T_MOVE{},T_GEN{};
#if defined(OTHELLO_OPTIMIZED)
std::array<std::uint8_t,TT_SIZE> T_META{};
#else
std::array<std::uint8_t,TT_SIZE> T_FLAG{},T_SIDE{},T_SKIP{};
#endif
std::uint8_t generation=1;
constexpr int EXACT_BITS=17,EXACT_SIZE=1<<EXACT_BITS,EXACT_MASK=EXACT_SIZE-1;
std::array<U64,EXACT_SIZE> E_PLAYER{},E_OPPONENT{};
std::array<int,EXACT_SIZE> E_VALUE{};
std::array<std::uint8_t,EXACT_SIZE> E_GEN{},E_MOVE{};
#if defined(OTHELLO_OPTIMIZED)
std::array<std::uint8_t,EXACT_SIZE> E_META{};
#else
std::array<std::uint8_t,EXACT_SIZE> E_FLAG{},E_SKIP{};
#endif
int E_CELL[66][64]{},E_SCORE[66][64]{};
U64 E_FLIP[66][64]{};

Clock::time_point deadline;
std::uint64_t nodes=0,evaluations=0,ttHits=0;
int iterationMove=0,iterationValue=0,completedDepth=0;
struct Timeout final {};

inline int popcount(U64 x){return __builtin_popcountll(x);}
inline int first(U64 x){return __builtin_ctzll(x);}
inline U64 rotl23(U64 x){return (x<<23)|(x>>41);}
inline void visit(){
#if defined(OTHELLO_OPTIMIZED)
  if(((++nodes)&511ULL)==0&&Clock::now()>=deadline)throw Timeout{};
#else
  if(((++nodes)&127ULL)==0&&Clock::now()>=deadline)throw Timeout{};
#endif
}
inline void checkTime(){if(Clock::now()>=deadline)throw Timeout{};}
inline int digit(int line,int pos){return DIGIT[line*8+pos];}
inline int moveIndex(int p,int line,int place,int dir){return (((p*LINE_N+line)*8+place)*2+dir);}
inline int stateIndex(int p,int line,int place){return (p*LINE_N+line)*8+place;}
inline int local(int line,int cell){return LOCAL[line*64+cell];}
inline int included(int cell,int i){return INCLUDED[cell*4+i];}
inline double relu(double x){return x>=0?x:x*.01;}

int colorBits(int idx,int color){
  int r=0;
  for(int i=0;i<8;i++){if(idx%3==color)r|=1<<i;idx/=3;}
  return r;
}
int moveHalf(int p,int o,int place,bool left){
  int at=1<<(7-place),r=0;
  if(((p|o)&at)!=0)return 0;
  unsigned m=left?unsigned(at<<1):unsigned(at)>>1;
  while(m!=0&&(m&unsigned(o))!=0){r++;m=left?m<<1:m>>1;if((m&unsigned(p))!=0)return r;}
  return 0;
}
void initLines(){
  for(int idx=0;idx<LINE_N;idx++){
    int black=colorBits(idx,0),white=colorBits(idx,1),rev=0,c=0,all=0;
    for(int place=0;place<8;place++){
      int bp=(unsigned(black)>>place)&1,wp=(unsigned(white)>>place)&1;
      c+=bp-wp;all+=bp+wp;rev=rev*3+(bp?0:wp?1:2);
      DIGIT[idx*8+7-place]=std::uint8_t(bp?0:wp?1:2);
      if(place>0&&((black|white)&(1<<(place-1)))==0){if(bp)SURROUND[idx]++;else if(wp)SURROUND[LINE_N+idx]++;}
      if(place<7&&((black|white)&(1<<(place+1)))==0){if(bp)SURROUND[idx]++;else if(wp)SURROUND[LINE_N+idx]++;}
    }
    COUNT[idx]=std::int8_t(c);COUNT_ALL[idx]=std::int8_t(all);REVERSE[idx]=std::uint16_t(rev);
    for(int p=0;p<2;p++)for(int place=0;place<8;place++){
      int mine=p==0?black:white,opp=p==0?white:black;
      MOVE[moveIndex(p,idx,place,0)]=std::uint8_t(moveHalf(mine,opp,place,true));
      MOVE[moveIndex(p,idx,place,1)]=std::uint8_t(moveHalf(mine,opp,place,false));
      int si=stateIndex(p,idx,place),bit=1<<(7-place),f=idx,put=idx;
      if((mine&bit)!=0){}
      else if((opp&bit)!=0)f+=p==0?-POW3[7-place]:POW3[7-place];
      else put-=POW3[7-place]*(p==0?2:1);
      FLIP[si]=std::uint16_t(f);PUT[si]=std::uint16_t(put);
    }
  }
}

std::uint32_t crc32(const std::vector<std::uint8_t>& data){
  std::uint32_t crc=0xffffffffU;
  for(std::uint8_t b:data){crc^=b;for(int k=0;k<8;k++)crc=(crc>>1)^(0xedb88320U&std::uint32_t(-int(crc&1)));}
  return ~crc;
}
/*__MODEL_DECODER_BEGIN__*/
std::vector<double> decodeModel(){
  std::vector<std::uint8_t> raw;raw.reserve(PARAMETER_COUNT*2);
  std::uint64_t acc=0;int bits=0;
  for(auto s:MODEL_DATA)for(char16_t ch:s){
    int q=int(ch)-0x3400;if(q<0||q>=32768)throw std::runtime_error("model alphabet");
    acc|=std::uint64_t(q)<<bits;bits+=15;
    while(bits>=8&&int(raw.size())<PARAMETER_COUNT*2){raw.push_back(std::uint8_t(acc&255));acc>>=8;bits-=8;}
  }
  if(int(raw.size())!=PARAMETER_COUNT*2||crc32(raw)!=MODEL_CRC)throw std::runtime_error("model checksum");
  std::vector<double> w(PARAMETER_COUNT);
  for(int i=0;i<PARAMETER_COUNT;i++){
    std::uint16_t u=std::uint16_t(raw[2*i])|(std::uint16_t(raw[2*i+1])<<8);
    w[i]=std::int16_t(u)*MODEL_SCALE[i/6359];
  }
  return w;
}
/*__MODEL_DECODER_END__*/

std::vector<double> weights;
std::size_t weightPos=0;
inline double nextWeight(){return weights[weightPos++];}
int patternDigit(int idx,int pos,int size){return idx/POW3[size-1-pos]%3;}
int reverseIndex(int pi,int size,int idx){
  int r=0;
  if(pi<=7){for(int i=size-1;i>=0;i--)r=r*3+patternDigit(idx,i,size);return r;}
  for(int i:REVERSE_ORDER[pi-8])r=r*3+patternDigit(idx,i,size);
  return r;
}
void loadPattern(int ph,int pi,int size){
#if defined(OTHELLO_LAZY_MODEL)
  PatternNetwork& net=PATTERN_NET[ph][pi];net.size=size;
  for(int i=0;i<size*2;i++)for(int u=0;u<HIDDEN;u++)net.d0[u][i]=nextWeight();
  for(double& v:net.b0)v=nextWeight();
  for(int i=0;i<HIDDEN;i++)for(int u=0;u<HIDDEN;u++)net.d1[u][i]=nextWeight();
  for(double& v:net.b1)v=nextWeight();
  for(double& v:net.d2)v=nextWeight();
  net.b2=nextWeight();net.cache.assign(POW3[size],std::numeric_limits<float>::quiet_NaN());
#else
  double d0[HIDDEN][20]{},d1[HIDDEN][HIDDEN]{},b0[HIDDEN]{},b1[HIDDEN]{},d2[HIDDEN]{};
  for(int i=0;i<size*2;i++)for(int u=0;u<HIDDEN;u++)d0[u][i]=nextWeight();
  for(double& v:b0)v=nextWeight();
  for(int i=0;i<HIDDEN;i++)for(int u=0;u<HIDDEN;u++)d1[u][i]=nextWeight();
  for(double& v:b1)v=nextWeight();
  for(double& v:d2)v=nextWeight();
  double b2=nextWeight();
  int count=POW3[size];std::vector<float> out(count),reverse(count);int ds[10]{};double h0[HIDDEN]{};
  for(int idx=0;idx<count;idx++){
    int x=idx;for(int i=size-1;i>=0;i--){ds[i]=x%3;x/=3;}
    for(int u=0;u<HIDDEN;u++){
      double v=b0[u];for(int i=0;i<size;i++)if(ds[i]<2)v+=d0[u][i+(ds[i]==1?size:0)];h0[u]=relu(v);
    }
    double result=b2;
    for(int u=0;u<HIDDEN;u++){double v=b1[u];for(int i=0;i<HIDDEN;i++)v+=h0[i]*d1[u][i];result+=relu(v)*d2[u];}
    result=relu(result);out[idx]=float(result);reverse[reverseIndex(pi,size,idx)]=float(result);
  }
#if defined(OTHELLO_OPTIMIZED)
  PATTERN[ph][pi].resize(count);
  for(int i=0;i<count;i++)PATTERN[ph][pi][i]=std::int32_t(std::llround((out[i]+reverse[i])*EVAL_Q));
#else
  PATTERN[ph][pi].resize(count);
  for(int i=0;i<count;i++)PATTERN[ph][pi][i]=out[i]+reverse[i];
#endif
#endif
}
void precomputeAddition(int ph,double d0[8][3],double b0[8],double d1[8][8],double b1[8]){
#if defined(OTHELLO_LAZY_MODEL)
  AdditionNetwork& net=ADDITION_NET[ph];
  std::memcpy(net.d0,d0,sizeof(net.d0));std::memcpy(net.b0,b0,sizeof(net.b0));
  std::memcpy(net.d1,d1,sizeof(net.d1));std::memcpy(net.b1,b1,sizeof(net.b1));
#else
  constexpr int N=61*51*51;ADDITION[ph].resize(N);double h0[8]{};int k=0;
  for(int mobility=-30;mobility<=30;mobility++)for(int s0=0;s0<=50;s0++)for(int s1=0;s1<=50;s1++){
    double in0=mobility/30.0,in1=(s0-15)/15.0,in2=(s1-15)/15.0;
    for(int u=0;u<8;u++){double v=b0[u]+in0*d0[u][0]+in1*d0[u][1]+in2*d0[u][2];h0[u]=relu(v);}
    double sum=0;for(int u=0;u<8;u++){double v=b1[u];for(int i=0;i<8;i++)v+=h0[i]*d1[u][i];sum+=relu(v)*DENSE[ph][11+u];}
#if defined(OTHELLO_OPTIMIZED)
    ADDITION[ph][k++]=std::int32_t(std::llround(sum*EVAL_Q));
#else
    ADDITION[ph][k++]=float(sum);
#endif
  }
#endif
}
void finalizeFixedPattern(int ph){
#if defined(OTHELLO_OPTIMIZED)
  for(int pi=0;pi<11;pi++)for(auto& v:PATTERN[ph][pi])v=std::int32_t(std::llround(double(v)*DENSE[ph][pi]));
  BIAS_Q[ph]=std::llround(BIAS[ph]*EVAL_Q);
#else
  (void)ph;
#endif
}
void initModelPhase(int ph){
  for(int pi=0;pi<11;pi++)loadPattern(ph,pi,PAT_SIZE[pi]);
  double a0[8][3]{},a1[8][8]{},ab0[8]{},ab1[8]{};
  for(int i=0;i<3;i++)for(int u=0;u<8;u++)a0[u][i]=nextWeight();
  for(double& v:ab0)v=nextWeight();
  for(int i=0;i<8;i++)for(int u=0;u<8;u++)a1[u][i]=nextWeight();
  for(double& v:ab1)v=nextWeight();
  for(float& v:DENSE[ph])v=float(nextWeight());
  BIAS[ph]=nextWeight();precomputeAddition(ph,a0,ab0,a1,ab1);finalizeFixedPattern(ph);
}
void initModel(){
  weights=decodeModel();weightPos=0;
  for(int ph=0;ph<4;ph++)initModelPhase(ph);
  if(weightPos!=PARAMETER_COUNT)throw std::runtime_error("model length");
  weights.clear();weights.shrink_to_fit();
}
#if defined(OTHELLO_LAZY_MODEL)
float runPatternNetwork(const PatternNetwork& net,int idx){
  int ds[10]{},x=idx;double h0[HIDDEN]{};
  for(int i=net.size-1;i>=0;i--){ds[i]=x%3;x/=3;}
  for(int u=0;u<HIDDEN;u++){
    double v=net.b0[u];for(int i=0;i<net.size;i++)if(ds[i]<2)v+=net.d0[u][i+(ds[i]==1?net.size:0)];h0[u]=relu(v);
  }
  double result=net.b2;
  for(int u=0;u<HIDDEN;u++){double v=net.b1[u];for(int i=0;i<HIDDEN;i++)v+=h0[i]*net.d1[u][i];result+=relu(v)*net.d2[u];}
  return float(relu(result));
}
float lazyPattern(int ph,int pi,int idx){
  PatternNetwork& net=PATTERN_NET[ph][pi];float& cached=net.cache[idx];if(!std::isnan(cached))return cached;
  float one=runPatternNetwork(net,idx),two=runPatternNetwork(net,reverseIndex(pi,net.size,idx));cached=one+two;return cached;
}
float lazyAddition(int ph,int mobility,int s0,int s1){
  const AdditionNetwork& net=ADDITION_NET[ph];double in[3]={mobility/30.0,(s0-15)/15.0,(s1-15)/15.0},h0[8]{};
  for(int u=0;u<8;u++){double v=net.b0[u];for(int i=0;i<3;i++)v+=in[i]*net.d0[u][i];h0[u]=relu(v);}
  double sum=0;for(int u=0;u<8;u++){double v=net.b1[u];for(int i=0;i<8;i++)v+=h0[i]*net.d1[u][i];sum+=relu(v)*DENSE[ph][11+u];}
  return float(sum);
}
#endif
template<class T> inline T patternAt(int ph,int pi,int idx){
#if defined(OTHELLO_LAZY_MODEL)
  return T(lazyPattern(ph,pi,idx));
#else
  return PATTERN[ph][pi][idx];
#endif
}
void initCore(){
  POW3[0]=1;for(int i=1;i<11;i++)POW3[i]=POW3[i-1]*3;
  LOCAL.fill(-1);INCLUDED.fill(-1);
  for(int line=0;line<38;line++)for(int pos=0;pos<8;pos++){
    int cell=GP[line][pos];if(cell<0)break;LOCAL[line*64+cell]=std::int8_t(pos);
    int base=cell*4;for(int k=0;k<4;k++)if(INCLUDED[base+k]<0){INCLUDED[base+k]=std::int8_t(line);break;}
  }
  initLines();for(int ph=0;ph<6;ph++)for(int d=1;d<=10;d++)MPC[ph][d]=int(1.5*MPC_SD[ph][d-1]);
}

inline U64 legal(U64 player,U64 opponent){
  U64 mo=opponent&H_MASK;
  U64 f1=mo&(player<<1),f7=mo&(player<<7),f9=mo&(player<<9),f8=opponent&(player<<8);
  f1|=mo&(f1<<1);f7|=mo&(f7<<7);f9|=mo&(f9<<9);f8|=opponent&(f8<<8);
  U64 p1=mo&(mo<<1),p7=mo&(mo<<7),p9=mo&(mo<<9),p8=opponent&(opponent<<8);
  f1|=p1&(f1<<2);f7|=p7&(f7<<14);f9|=p9&(f9<<18);f8|=p8&(f8<<16);
  f1|=p1&(f1<<2);f7|=p7&(f7<<14);f9|=p9&(f9<<18);f8|=p8&(f8<<16);
  U64 moves=(f1<<1)|(f7<<7)|(f9<<9)|(f8<<8);
  f1=mo&(player>>1);f7=mo&(player>>7);f9=mo&(player>>9);f8=opponent&(player>>8);
  f1|=mo&(f1>>1);f7|=mo&(f7>>7);f9|=mo&(f9>>9);f8|=opponent&(f8>>8);
  p1>>=1;p7>>=7;p9>>=9;p8>>=8;
  f1|=p1&(f1>>2);f7|=p7&(f7>>14);f9|=p9&(f9>>18);f8|=p8&(f8>>16);
  f1|=p1&(f1>>2);f7|=p7&(f7>>14);f9|=p9&(f9>>18);f8|=p8&(f8>>16);
  moves|=(f1>>1)|(f7>>7)|(f9>>9)|(f8>>8);return moves&~(player|opponent);
}
inline U64 legal(const Board& b){return b.p==0?legal(b.black,b.white):legal(b.white,b.black);}
inline U64 rayL(U64 m,U64 p,U64 o,int shift,U64 mask){U64 x=o&mask,c=x&(m<<shift),f=c;for(int i=0;i<5;i++){f=x&(f<<shift);c|=f;}return ((c<<shift)&p)?c:0;}
inline U64 rayR(U64 m,U64 p,U64 o,int shift,U64 mask){U64 x=o&mask,c=x&(m>>shift),f=c;for(int i=0;i<5;i++){f=x&(f>>shift);c|=f;}return ((c>>shift)&p)?c:0;}
inline U64 flips(U64 p,U64 o,int cell){
  U64 m=1ULL<<cell;if((p|o)&m)return 0;
  return rayL(m,p,o,1,H_MASK)|rayR(m,p,o,1,H_MASK)|rayL(m,p,o,7,H_MASK)|rayR(m,p,o,7,H_MASK)
    |rayL(m,p,o,9,H_MASK)|rayR(m,p,o,9,H_MASK)|rayL(m,p,o,8,~0ULL)|rayR(m,p,o,8,~0ULL);
}
inline void flipCell(const Board& parent,Board& child,int cell){
  for(int k=0;k<4;k++){int line=included(cell,k);if(line<0)break;int pos=local(line,cell);child.a[line]=FLIP[stateIndex(parent.p,child.a[line],pos)];}
}
void moveInto(const Board& parent,int cell,Board& child){
  U64 mine=parent.p==0?parent.black:parent.white,opp=parent.p==0?parent.white:parent.black,bit=1ULL<<cell,f=flips(mine,opp,cell);
  std::memcpy(child.a,parent.a,sizeof(parent.a));
  for(int k=0;k<4;k++){
    int line=included(cell,k);if(line<0)break;int pos=local(line,cell),off=OFFSET[line];
    int left=MOVE[moveIndex(parent.p,parent.a[line],pos,0)],right=MOVE[moveIndex(parent.p,parent.a[line],pos,1)];
    for(int j=1;j<=left;j++)flipCell(parent,child,cell-off*j);
    for(int j=1;j<=right;j++)flipCell(parent,child,cell+off*j);
  }
  for(int k=0;k<4;k++){int line=included(cell,k);if(line<0)break;child.a[line]=PUT[stateIndex(parent.p,child.a[line],local(line,cell))];}
  child.p=1-parent.p;child.n=parent.n+1;child.move=cell;
  if(parent.p==0){child.black=parent.black|bit|f;child.white=parent.white&~f;}else{child.white=parent.white|bit|f;child.black=parent.black&~f;}
  child.empty=parent.empty&~bit;
}
inline void passInto(const Board& parent,Board& child){
  std::memcpy(child.a,parent.a,sizeof(parent.a));child.black=parent.black;child.white=parent.white;child.empty=parent.empty;
  child.p=1-parent.p;child.n=parent.n;child.move=-1;
}

inline int fillShortLine(int line,int power){return digit(line,7-power)!=2?line-POW3[power]+1:line;}
int surround(const Board& b,int color){
  int sum=0,base=color*LINE_N;for(int i=0;i<16;i++)sum+=SURROUND[base+b.a[i]];
  for(int axis=0;axis<2;axis++)for(int j=0;j<11;j++){
    int len=j<=5?3+j:13-j,power=8-len,line=b.a[16+axis*11+j];if(power>0)line=fillShortLine(line,power);sum+=SURROUND[base+line];
  }
  return std::min(50,sum);
}
inline int mid(int v,int high,int low){return v%POW3[high]/POW3[low];}
inline int rev(int v){return REVERSE[v];}
template<class T> inline T edge2(int ph,int x,int y,const int* a){return patternAt<T>(ph,7,digit(a[x],1)*POW3[9]+a[y]*3+digit(a[x],6));}
template<class T> inline T triangle(int ph,int w,int x,int y,int z,const int* a,bool reverse){
  int aw=reverse?rev(a[w]):a[w],ax=reverse?rev(a[x]):a[x],ay=reverse?rev(a[y]):a[y],az=reverse?rev(a[z]):a[z];
  int idx=aw/POW3[4]*POW3[6]+ax/POW3[5]*POW3[3]+ay/POW3[6]*3+az/POW3[7];return patternAt<T>(ph,8,idx);
}
template<class T> inline T edgeBlock(int ph,int x,int y,const int* a){int idx=digit(a[x],0)*POW3[9]+mid(a[x],6,2)*POW3[5]+digit(a[x],7)*POW3[4]+mid(a[y],6,2);return patternAt<T>(ph,9,idx);}
template<class T> inline T crossPattern(int ph,int x,int y,int z,const int* a){
  int one=a[x]/POW3[4]*POW3[6]+a[y]/POW3[5]*POW3[3]+a[z]/POW3[5],rx=rev(a[x]),ry=rev(a[y]),rz=rev(a[z]);
  int two=rx/POW3[4]*POW3[6]+mid(ry,7,4)*POW3[3]+mid(rz,7,4);return patternAt<T>(ph,10,one)+patternAt<T>(ph,10,two);
}

#if defined(OTHELLO_OPTIMIZED)
std::int64_t patternScore(const Board& b,int ph){
  const int* a=b.a;std::int64_t r=0;
  r+=patternAt<std::int64_t>(ph,0,a[1])+patternAt<std::int64_t>(ph,0,a[6])+patternAt<std::int64_t>(ph,0,a[9])+patternAt<std::int64_t>(ph,0,a[14]);
  r+=patternAt<std::int64_t>(ph,1,a[2])+patternAt<std::int64_t>(ph,1,a[5])+patternAt<std::int64_t>(ph,1,a[10])+patternAt<std::int64_t>(ph,1,a[13]);
  r+=patternAt<std::int64_t>(ph,2,a[3])+patternAt<std::int64_t>(ph,2,a[4])+patternAt<std::int64_t>(ph,2,a[11])+patternAt<std::int64_t>(ph,2,a[12]);
  r+=patternAt<std::int64_t>(ph,3,a[18]/POW3[3])+patternAt<std::int64_t>(ph,3,a[24]/POW3[3])+patternAt<std::int64_t>(ph,3,a[29]/POW3[3])+patternAt<std::int64_t>(ph,3,a[35]/POW3[3]);
  r+=patternAt<std::int64_t>(ph,4,a[19]/POW3[2])+patternAt<std::int64_t>(ph,4,a[23]/POW3[2])+patternAt<std::int64_t>(ph,4,a[30]/POW3[2])+patternAt<std::int64_t>(ph,4,a[34]/POW3[2]);
  r+=patternAt<std::int64_t>(ph,5,a[20]/3)+patternAt<std::int64_t>(ph,5,a[22]/3)+patternAt<std::int64_t>(ph,5,a[31]/3)+patternAt<std::int64_t>(ph,5,a[33]/3);
  r+=patternAt<std::int64_t>(ph,6,a[21])+patternAt<std::int64_t>(ph,6,a[32]);
  r+=edge2<std::int64_t>(ph,1,0,a)+edge2<std::int64_t>(ph,6,7,a)+edge2<std::int64_t>(ph,9,8,a)+edge2<std::int64_t>(ph,14,15,a);
  r+=triangle<std::int64_t>(ph,0,1,2,3,a,false)+triangle<std::int64_t>(ph,7,6,5,4,a,false)+triangle<std::int64_t>(ph,15,14,13,12,a,false)+triangle<std::int64_t>(ph,15,14,13,12,a,true);
  r+=edgeBlock<std::int64_t>(ph,0,1,a)+edgeBlock<std::int64_t>(ph,7,6,a)+edgeBlock<std::int64_t>(ph,8,9,a)+edgeBlock<std::int64_t>(ph,15,14,a);
  r+=crossPattern<std::int64_t>(ph,21,20,22,a)+crossPattern<std::int64_t>(ph,32,31,33,a);return r;
}
#else
double patternScore(const Board& b,int ph){
  const int* a=b.a;double r=0;
  r+=DENSE[ph][0]*(patternAt<double>(ph,0,a[1])+patternAt<double>(ph,0,a[6])+patternAt<double>(ph,0,a[9])+patternAt<double>(ph,0,a[14]));
  r+=DENSE[ph][1]*(patternAt<double>(ph,1,a[2])+patternAt<double>(ph,1,a[5])+patternAt<double>(ph,1,a[10])+patternAt<double>(ph,1,a[13]));
  r+=DENSE[ph][2]*(patternAt<double>(ph,2,a[3])+patternAt<double>(ph,2,a[4])+patternAt<double>(ph,2,a[11])+patternAt<double>(ph,2,a[12]));
  r+=DENSE[ph][3]*(patternAt<double>(ph,3,a[18]/POW3[3])+patternAt<double>(ph,3,a[24]/POW3[3])+patternAt<double>(ph,3,a[29]/POW3[3])+patternAt<double>(ph,3,a[35]/POW3[3]));
  r+=DENSE[ph][4]*(patternAt<double>(ph,4,a[19]/POW3[2])+patternAt<double>(ph,4,a[23]/POW3[2])+patternAt<double>(ph,4,a[30]/POW3[2])+patternAt<double>(ph,4,a[34]/POW3[2]));
  r+=DENSE[ph][5]*(patternAt<double>(ph,5,a[20]/3)+patternAt<double>(ph,5,a[22]/3)+patternAt<double>(ph,5,a[31]/3)+patternAt<double>(ph,5,a[33]/3));
  r+=DENSE[ph][6]*(patternAt<double>(ph,6,a[21])+patternAt<double>(ph,6,a[32]));
  r+=DENSE[ph][7]*(edge2<double>(ph,1,0,a)+edge2<double>(ph,6,7,a)+edge2<double>(ph,9,8,a)+edge2<double>(ph,14,15,a));
  r+=DENSE[ph][8]*(triangle<double>(ph,0,1,2,3,a,false)+triangle<double>(ph,7,6,5,4,a,false)+triangle<double>(ph,15,14,13,12,a,false)+triangle<double>(ph,15,14,13,12,a,true));
  r+=DENSE[ph][9]*(edgeBlock<double>(ph,0,1,a)+edgeBlock<double>(ph,7,6,a)+edgeBlock<double>(ph,8,9,a)+edgeBlock<double>(ph,15,14,a));
  r+=DENSE[ph][10]*(crossPattern<double>(ph,21,20,22,a)+crossPattern<double>(ph,32,31,33,a));return r;
}
#endif
double raw(const Board& b){
  int ph=std::clamp((b.n-4)/10-2,0,3),mobility=std::min(30,popcount(legal(b)))*(b.p==0?1:-1),s0=surround(b,0),s1=surround(b,1);
#if !defined(OTHELLO_LAZY_MODEL)
  int ai=((mobility+30)*51+s0)*51+s1;
#endif
#if defined(OTHELLO_OPTIMIZED)
  std::int64_t q=BIAS_Q[ph]+patternScore(b,ph)+ADDITION[ph][ai];double r=double(q)/EVAL_Q;
#elif defined(OTHELLO_LAZY_MODEL)
  double r=BIAS[ph]+patternScore(b,ph)+lazyAddition(ph,mobility,s0,s1);
#else
  double r=BIAS[ph]+patternScore(b,ph)+ADDITION[ph][ai];
#endif
  return b.p==0?r:-r;
}
int evaluate(const Board& b){evaluations++;double r=std::clamp(raw(b),-1.0,1.0);return int(r*SCALE);}
int terminal(const Board& b){int diff=popcount(b.black)-popcount(b.white);if(b.p==1)diff=-diff;int vacant=popcount(b.empty);if(diff>0)diff+=vacant;else if(diff<0)diff-=vacant;return diff*STEP;}

inline int hash(U64 black,U64 white,int side,bool skip,int mask){
  U64 z=black^rotl23(white);if(side)z^=0x9e3779b97f4a7c15ULL;if(skip)z^=0xd1b54a32d192ed03ULL;z^=z>>33;z*=0xff51afd7ed558ccdULL;z^=z>>33;return int(z)&mask;
}
int ttMove(const Board& b,bool skip){int h=hash(b.black,b.white,b.p,skip,TT_MASK);
#if defined(OTHELLO_OPTIMIZED)
  bool match=((T_META[h]>>2)&1)==b.p&&((T_META[h]>>3)&1)==skip;
#else
  bool match=T_SIDE[h]==b.p&&T_SKIP[h]==skip;
#endif
  if(T_GEN[h]==generation&&T_BLACK[h]==b.black&&T_WHITE[h]==b.white&&match)return T_MOVE[h];
  return 255;}
void store(const Board& b,bool skip,int depth,int value,int alpha0,int beta0,int best){
  int h=hash(b.black,b.white,b.p,skip,TT_MASK);if(T_GEN[h]!=generation||depth>=T_DEPTH[h]){
    T_GEN[h]=generation;T_BLACK[h]=b.black;T_WHITE[h]=b.white;int flag=value<=alpha0?3:value>=beta0?2:1;
#if defined(OTHELLO_OPTIMIZED)
    T_META[h]=std::uint8_t(flag|(b.p<<2)|(int(skip)<<3));
#else
    T_SIDE[h]=std::uint8_t(b.p);T_SKIP[h]=std::uint8_t(skip);T_FLAG[h]=std::uint8_t(flag);
#endif
    T_DEPTH[h]=std::uint8_t(depth);T_VALUE[h]=value;T_MOVE[h]=std::uint8_t(best);
  }
}
int probe(const Board& b,bool skip,int depth,int alpha,int beta){
  int h=hash(b.black,b.white,b.p,skip,TT_MASK);
#if defined(OTHELLO_OPTIMIZED)
  int meta=T_META[h],f=meta&3;bool match=((meta>>2)&1)==b.p&&((meta>>3)&1)==skip;
#else
  int f=T_FLAG[h];bool match=T_SIDE[h]==b.p&&T_SKIP[h]==skip;
#endif
  if(T_GEN[h]!=generation||T_BLACK[h]!=b.black||T_WHITE[h]!=b.white||!match||T_DEPTH[h]<depth)return INF+1;
  int v=T_VALUE[h];if(f==1||(f==2&&v>=beta)||(f==3&&v<=alpha)){ttHits++;return v;}return INF+1;
}
int generate(const Board& b,U64 moves,int ply,bool endOrder,int preferred){
  int count=0;while(moves){U64 bit=moves&-moves;int cell=first(bit);moves^=bit;Board* child=&POOL[ply][count];moveInto(b,cell,*child);
    child->order=-evaluate(*child)+CELL_WEIGHT[cell]*2;if(endOrder)child->order-=popcount(legal(*child))*100;
#if defined(OTHELLO_OPTIMIZED)
    else child->order-=popcount(legal(*child))*8;
#endif
    if(cell==preferred)child->order+=2000000;
    int at=count;while(at>0&&ORDERED[ply][at-1]->order<child->order){ORDERED[ply][at]=ORDERED[ply][at-1];at--;}ORDERED[ply][at]=child;count++;}
  return count;
}

U64 stableEdges(U64 color){
  U64 stable=0;for(int i=0;i<4;i++)if(color&(1ULL<<EDGE_CORNERS[i])){stable|=1ULL<<EDGE_CORNERS[i];
    int cell=EDGE_CORNERS[i]+EDGE_D1[i];for(int k=1;k<8;k++,cell+=EDGE_D1[i]){U64 bit=1ULL<<cell;if(!(color&bit))break;stable|=bit;}
    cell=EDGE_CORNERS[i]+EDGE_D2[i];for(int k=1;k<8;k++,cell+=EDGE_D2[i]){U64 bit=1ULL<<cell;if(!(color&bit))break;stable|=bit;}}
  return stable;
}
inline U64 oddRegions(U64 empty){U64 r=0;for(U64 region:REGIONS)if(popcount(empty&region)&1)r|=region;return r;}
inline int exactTerminal(U64 p,U64 o,U64 empty){int d=popcount(p)-popcount(o),v=popcount(empty);if(d>0)d+=v;else if(d<0)d-=v;return d*STEP;}
int orderExact(U64 p,U64 o,U64 empty,U64 moves,int ply,int preferred){
  int count=0;U64 odd=oddRegions(empty);while(moves){U64 bit=moves&-moves;int cell=first(bit);moves^=bit;U64 f=flips(p,o,cell);int score;
    if(f==o)score=std::numeric_limits<int>::max();else{int mobility=popcount(legal(o&~f,p|f|bit));score=CELL_WEIGHT[cell]*32-mobility*256;if(bit&odd)score+=16384;if(bit&CORNERS)score+=32768;}
#if defined(OTHELLO_ENHANCED)
    if(cell==preferred)score=std::numeric_limits<int>::max();
#else
    (void)preferred;
#endif
    int at=count;while(at>0&&(score>E_SCORE[ply][at-1]||(score==E_SCORE[ply][at-1]&&cell<E_CELL[ply][at-1]))){E_SCORE[ply][at]=E_SCORE[ply][at-1];E_CELL[ply][at]=E_CELL[ply][at-1];E_FLIP[ply][at]=E_FLIP[ply][at-1];at--;}
    E_SCORE[ply][at]=score;E_CELL[ply][at]=cell;E_FLIP[ply][at]=f;count++;}
  return count;
}
void storeExact(int h,U64 p,U64 o,bool skip,int value,int alpha0,int beta0,int best){E_GEN[h]=generation;E_PLAYER[h]=p;E_OPPONENT[h]=o;E_VALUE[h]=value;E_MOVE[h]=std::uint8_t(best);int flag=value<=alpha0?3:value>=beta0?2:1;
#if defined(OTHELLO_OPTIMIZED)
  E_META[h]=std::uint8_t(flag|(int(skip)<<2));
#else
  E_SKIP[h]=std::uint8_t(skip);E_FLAG[h]=std::uint8_t(flag);
#endif
}
int exact(U64 p,U64 o,U64 empty,bool skipped,int alpha,int beta,int ply){
  visit();int alpha0=alpha,beta0=beta,h=hash(p,o,0,skipped,EXACT_MASK),preferred=255;
#if defined(OTHELLO_OPTIMIZED)
  int exactMeta=E_META[h],exactFlag=exactMeta&3;bool exactSkip=((exactMeta>>2)&1)==skipped;
#else
  int exactFlag=E_FLAG[h];bool exactSkip=E_SKIP[h]==skipped;
#endif
  if(E_GEN[h]==generation&&E_PLAYER[h]==p&&E_OPPONENT[h]==o&&exactSkip){preferred=E_MOVE[h];int v=E_VALUE[h],f=exactFlag;if(f==1||(f==2&&v>=beta)||(f==3&&v<=alpha)){ttHits++;return v;}}
  int empties=popcount(empty);
#if defined(OTHELLO_ENHANCED)
  if(empties==1){int cell=first(empty);U64 f=flips(p,o,cell);if(f)return -exactTerminal(o&~f,p|f|(1ULL<<cell),0);return skipped?exactTerminal(p,o,empty):-exact(o,p,empty,true,-beta,-alpha,ply+1);}
#endif
  if(empties>=8){int low=(2*popcount(stableEdges(p))-64)*STEP,high=(64-2*popcount(stableEdges(o)))*STEP;if(low>=beta)return low;if(high<=alpha)return high;alpha=std::max(alpha,low);beta=std::min(beta,high);}
  U64 moves=legal(p,o)&empty;if(!moves){int v=skipped?exactTerminal(p,o,empty):-exact(o,p,empty,true,-beta,-alpha,ply+1);storeExact(h,p,o,skipped,v,alpha0,beta0,255);return v;}
  int count=orderExact(p,o,empty,moves,ply,preferred),best=-INF,bestMove=255;
  for(int i=0;i<count;i++){int cell=E_CELL[ply][i];U64 bit=1ULL<<cell,f=E_FLIP[ply][i];int value=f==o?SCALE:-exact(o&~f,p|f|bit,empty^bit,false,-beta,-alpha,ply+1);
    if(value>best){best=value;bestMove=cell;}if(value>alpha)alpha=value;if(alpha>=beta)break;}
  storeExact(h,p,o,skipped,best,alpha0,beta0,bestMove);return best;
}
int alphaBeta(const Board& b,bool skipped,int depth,int alpha,int beta,int ply,bool allowMpc){
  visit();U64 moves=legal(b);if(depth==0){if(moves)return evaluate(b);if(skipped)return terminal(b);Board& pass=PASS[ply];passInto(b,pass);return -alphaBeta(pass,true,0,-beta,-alpha,ply+1,allowMpc);}
  int empties=64-b.n;if(depth>=empties&&empties<=10){U64 p=b.p==0?b.black:b.white,o=b.p==0?b.white:b.black;return exact(p,o,b.empty,skipped,alpha,beta,ply);}
  if(allowMpc&&depth<=10){int ph=std::clamp((b.n-4)/10,0,5),bound=beta+MPC[ph][depth];if(alphaBeta(b,skipped,MPC_DEPTH[depth],bound-1,bound,ply,true)>=bound)return beta+1;
    bound=alpha-MPC[ph][depth];if(alphaBeta(b,skipped,MPC_DEPTH[depth],bound,bound+1,ply,true)<=bound)return alpha-1;}
  int cached=probe(b,skipped,depth,alpha,beta);if(cached!=INF+1)return cached;
  if(!moves){if(skipped)return terminal(b);Board& pass=PASS[ply];passInto(b,pass);return -alphaBeta(pass,true,depth,-beta,-alpha,ply+1,allowMpc);}
  int alpha0=alpha,beta0=beta,best=-INF,bestMove=255,preferred=ttMove(b,skipped);
  if(depth<=3){Board& child=POOL[ply][0];while(moves){U64 bit=moves&-moves;int cell=first(bit);moves^=bit;moveInto(b,cell,child);int value=-alphaBeta(child,false,depth-1,-beta,-alpha,ply+1,allowMpc);
      if(value>best){best=value;bestMove=cell;}if(value>alpha)alpha=value;if(alpha>=beta)break;}}
  else{int count=generate(b,moves,ply,false,preferred);for(int i=0;i<count;i++){Board& child=*ORDERED[ply][i];int value;
      if(i==0)value=-alphaBeta(child,false,depth-1,-beta,-alpha,ply+1,allowMpc);else{value=-alphaBeta(child,false,depth-1,-alpha-1,-alpha,ply+1,allowMpc);if(value>alpha&&value<beta)value=-alphaBeta(child,false,depth-1,-beta,-alpha,ply+1,allowMpc);}
      if(value>best){best=value;bestMove=child.move;}if(value>alpha)alpha=value;if(alpha>=beta)break;}}
  store(b,skipped,depth,best,alpha0,beta0,bestMove);return best;
}
int root(const Board& b,U64 moves,int depth,int alpha,int beta){
  int preferred=ttMove(b,false),count=generate(b,moves,0,false,preferred),best=-INF,bestMove=first(moves),a=alpha;
  for(int i=0;i<count;i++){Board& child=*ORDERED[0][i];int value;if(i==0)value=-alphaBeta(child,false,depth-1,-beta,-a,1,true);else{value=-alphaBeta(child,false,depth-1,-a-1,-a,1,true);if(value>a&&value<beta)value=-alphaBeta(child,false,depth-1,-beta,-a,1,true);}
    if(value>best){best=value;bestMove=child.move;}if(value>a)a=value;if(a>=beta)break;}
  iterationMove=bestMove;iterationValue=best;store(b,false,depth,best,alpha,beta,bestMove);return best;
}
int think(const Board& b,U64 allowed){
  int bestMove=first(allowed),guess=0,empties=64-b.n;nodes=evaluations=ttHits=0;completedDepth=0;
  generation++;if(generation==0){T_GEN.fill(0);E_GEN.fill(0);generation=1;}
  for(int depth=1;depth<=empties;depth++)try{
    checkTime();int alpha=-INF,beta=INF;if(depth>=4){alpha=std::max(-INF,guess-500);beta=std::min(INF,guess+500);}int value=root(b,allowed,depth,alpha,beta);
    if(value<=alpha||value>=beta)value=root(b,allowed,depth,-INF,INF);
    bestMove=iterationMove;guess=iterationValue;completedDepth=depth;if(depth>=empties)break;
  }catch(const Timeout&){break;}
  return bestMove;
}

Board fromRows(const std::array<std::string,8>& rows,int side){
  Board b;std::fill(std::begin(b.a),std::end(b.a),LINE_N-1);b.p=side;
  for(int r=0;r<8;r++)for(int c=0;c<8;c++){char ch=rows[r][c];int cell=r*8+c;if(ch=='0')b.black|=1ULL<<cell;else if(ch=='1')b.white|=1ULL<<cell;}
  b.empty=~(b.black|b.white);b.n=popcount(b.black|b.white);
  for(int line=0;line<38;line++)for(int pos=0;pos<8;pos++){int cell=GP[line][pos];if(cell<0)break;U64 bit=1ULL<<cell;if(b.black&bit)b.a[line]-=2*POW3[7-pos];else if(b.white&bit)b.a[line]-=POW3[7-pos];}
  return b;
}
int coordinateCell(std::string_view move){if(move.size()<2)return -1;int c=std::tolower(static_cast<unsigned char>(move[0]))-'a',r=move[1]-'1';return r>=0&&r<8&&c>=0&&c<8?r*8+c:-1;}
std::string coordinate(int cell){std::string s(2,' ');s[0]=char('a'+cell%8);s[1]=char('1'+cell/8);return s;}

void evalMode(){
  initCore();initModel();
  int side;while(std::cin>>side){std::array<std::string,8> rows;for(auto& row:rows)std::cin>>row;Board b=fromRows(rows,side);std::cout<<evaluate(b)<<' '<<std::setprecision(17)<<raw(b)<<'\n';}
}
void legalMode(){
  int side;while(std::cin>>side){std::array<std::string,8> rows;for(auto& row:rows)std::cin>>row;Board b=fromRows(rows,side);std::cout<<std::hex<<std::setw(16)<<std::setfill('0')<<legal(b)<<std::dec<<'\n';}
}
std::uint64_t perft(U64 p,U64 o,int depth,bool skipped=false){
  if(depth==0)return 1;
  U64 moves=legal(p,o);if(!moves)return skipped?1:perft(o,p,depth,true);std::uint64_t total=0;
  while(moves){U64 bit=moves&-moves;int cell=first(bit);moves^=bit;U64 f=flips(p,o,cell);total+=perft(o&~f,p|f|bit,depth-1,false);}return total;
}
void perftMode(){int side,depth;while(std::cin>>side>>depth){std::array<std::string,8> rows;for(auto& row:rows)std::cin>>row;Board b=fromRows(rows,side);U64 p=side==0?b.black:b.white,o=side==0?b.white:b.black;std::cout<<perft(p,o,depth)<<'\n';}}
void solveMode(){
  int side;while(std::cin>>side){
    std::array<std::string,8> rows;for(auto& row:rows)std::cin>>row;Board b=fromRows(rows,side);
    U64 p=side==0?b.black:b.white,o=side==0?b.white:b.black,empty=~(p|o),moves=legal(p,o);
    deadline=Clock::now()+std::chrono::hours(24);nodes=ttHits=0;generation++;
    int best=-INF,bestMove=-1;
    if(!moves)best=legal(o,p)?-exact(o,p,empty,true,-INF,INF,1):exactTerminal(p,o,empty);
    while(moves){U64 bit=moves&-moves;int cell=first(bit);moves^=bit;U64 f=flips(p,o,cell);int value=f==o?SCALE:-exact(o&~f,p|f|bit,empty^bit,false,-INF,INF,1);if(value>best){best=value;bestMove=cell;}}
    std::cout<<best/STEP<<' '<<(bestMove<0?"pass":coordinate(bestMove))<<'\n';
  }
}

int play(){
  int id,size;if(!(std::cin>>id))return 0;if(!(std::cin>>size)||size!=8)return 0;
  bool initialized=false;try{initCore();initModel();initialized=true;}catch(const std::exception& e){std::cerr<<"initialization failed: "<<e.what()<<'\n';}
  for(;;){std::array<std::string,8> rows;if(!(std::cin>>rows[0]))break;for(int i=1;i<8;i++)if(!(std::cin>>rows[i]))return 0;int count;if(!(std::cin>>count))return 0;
    std::vector<std::string> actions(count);U64 official=0;for(auto& action:actions){std::cin>>action;int p=coordinateCell(action);if(p>=0)official|=1ULL<<p;}if(count==0)continue;
    std::string answer=actions[0];auto start=Clock::now();
    try{
      deadline=start+std::chrono::milliseconds(MOVE_BUDGET_MS);
      if(initialized){Board b=fromRows(rows,id);U64 moves=legal(b)&official;if(moves){int chosen=first(moves);if(b.n!=4&&Clock::now()<deadline)chosen=think(b,moves);if(official&(1ULL<<chosen))answer=coordinate(chosen);}}
    }catch(const Timeout&){}catch(const std::exception& e){std::cerr<<"fallback: "<<e.what()<<'\n';}
    std::cout<<answer<<'\n'<<std::flush;
#if defined(OTHELLO_DIAGNOSTICS)
    std::cerr<<"METRIC variant="<<OTHELLO_VARIANT_NAME<<" depth="<<completedDepth<<" nodes="<<nodes<<" evals="<<evaluations<<" tt_hits="<<ttHits<<'\n';
#endif
  }
  return 0;
}
} // namespace othello

int main(int argc,char** argv){
  std::ios::sync_with_stdio(false);std::cin.tie(nullptr);
  if(argc>1&&std::string_view(argv[1])=="--eval"){othello::evalMode();return 0;}
  if(argc>1&&std::string_view(argv[1])=="--legal"){othello::initCore();othello::legalMode();return 0;}
  if(argc>1&&std::string_view(argv[1])=="--perft"){othello::initCore();othello::perftMode();return 0;}
  if(argc>1&&std::string_view(argv[1])=="--solve"){othello::initCore();othello::solveMode();return 0;}
  return othello::play();
}
