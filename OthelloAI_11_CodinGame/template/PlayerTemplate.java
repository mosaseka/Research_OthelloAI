/*
 * OthelloAI_10 CodinGame edition.
 * Derived from original_11 and Egaroucid 7.8.2.
 * Egaroucid portions Copyright (C) Takuto Yamana (Nyanyan),
 * commit 112981e381801a38604f54714d46eb9d90322b80.
 * GPL-3.0-or-later; there is no warranty. See the accompanying LICENSE.
 * Generated Player.java is a single-file, value-only submission.
 */
import java.io.*;
import java.util.*;
import java.util.zip.CRC32;

class Player {
  static final int HW=8,SQ_N=64,LINE_N=6561,INF=1000000,SCALE=6400,STEP=100;
  static final int[] POW=new int[11];
  static final int[] PAT_SIZE={8,8,8,5,6,7,8,10,10,10,10};
  static final int[] CELL_WEIGHT={
    120,-20,20,5,5,20,-20,120,-20,-40,-5,-5,-5,-5,-40,-20,
    20,-5,15,3,3,15,-5,20,5,-5,3,3,3,3,-5,5,
    5,-5,3,3,3,3,-5,5,20,-5,15,3,3,15,-5,20,
    -20,-40,-5,-5,-5,-5,-40,-20,120,-20,20,5,5,20,-20,120
  };
  static final int[][] GP={
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
  static final int[] OFFSET={
    1,1,1,1,1,1,1,1,8,8,8,8,8,8,8,8,
    9,9,9,9,9,9,9,9,9,9,9,7,7,7,7,7,7,7,7,7,7,7
  };
  static final int[][] REVERSE_ORDER={
    {0,4,7,9,1,5,8,2,6,3},
    {5,4,3,2,1,0,9,8,7,6},
    {0,1,2,3,7,8,9,4,5,6}
  };
  static final double[] MODEL_SCALE={/*__MODEL_SCALES__*/};
  static final long MODEL_CRC=/*__MODEL_CRC32__*/;
  static final String MODEL_SHA=/*__MODEL_SHA256__*/;
  static final String[] MODEL_DATA={/*__MODEL_DATA__*/};

  static final byte[] MOVE=new byte[2*LINE_N*8*2];
  static final short[] FLIP=new short[2*LINE_N*8],PUT=new short[2*LINE_N*8];
  static final byte[] DIGIT=new byte[LINE_N*8],SURROUND=new byte[2*LINE_N];
  static final byte[] COUNT=new byte[LINE_N],COUNT_ALL=new byte[LINE_N];
  static final short[] REVERSE=new short[LINE_N];
  static final byte[] LOCAL=new byte[38*64],INCLUDED=new byte[64*4];
  static final float[][][] PATTERN=new float[4][11][];
  static final float[][] DENSE=new float[4][19];
  static final float[][] ADDITION=new float[4][];
  static final double[] BIAS=new double[4];
  static final int[] MPC_DEPTH={0,0,0,1,2,1,2,3,4,3,4};
  static final int[][] MPC_SD={
    {482,512,352,298,474,372,349,323,463,335},
    {312,381,310,261,354,322,291,313,389,371},
    {389,463,392,352,548,402,422,441,530,538},
    {417,490,436,405,570,494,452,438,527,524},
    {486,554,519,463,635,665,555,550,635,581},
    {433,517,430,391,560,556,383,345,567,332}
  };
  static final int[][] MPC=new int[6][11];
  static final long H_MASK=0x7e7e7e7e7e7e7e7eL,CORNERS=0x8100000000000081L;
  static final long[] REGIONS={
    0x000000000f0f0f0fL,0x00000000f0f0f0f0L,
    0x0f0f0f0f00000000L,0xf0f0f0f000000000L
  };

  static final class B {
    final int[] a=new int[38];
    long black,white,empty;
    int p,n,move,order;
  }
  static final B[][] POOL=new B[66][64];
  static final B[] PASS=new B[66];
  static B board(int ply,int i){
    B b=POOL[Math.min(65,ply)][i];
    if(b==null)POOL[Math.min(65,ply)][i]=b=new B();
    return b;
  }
  static B passBoard(int ply){
    B b=PASS[Math.min(65,ply)];
    if(b==null)PASS[Math.min(65,ply)]=b=new B();
    return b;
  }

  static final int TT_BITS=18,TT_SIZE=1<<TT_BITS,TT_MASK=TT_SIZE-1;
  static final long[] T_BLACK=new long[TT_SIZE],T_WHITE=new long[TT_SIZE];
  static final int[] T_VALUE=new int[TT_SIZE];
  static final byte[] T_DEPTH=new byte[TT_SIZE],T_FLAG=new byte[TT_SIZE],
      T_MOVE=new byte[TT_SIZE],T_SIDE=new byte[TT_SIZE],T_SKIP=new byte[TT_SIZE],
      T_GEN=new byte[TT_SIZE];
  static byte generation=1;
  static final int EXACT_BITS=17,EXACT_SIZE=1<<EXACT_BITS,EXACT_MASK=EXACT_SIZE-1;
  static final long[] E_PLAYER=new long[EXACT_SIZE],E_OPPONENT=new long[EXACT_SIZE];
  static final int[] E_VALUE=new int[EXACT_SIZE];
  static final byte[] E_FLAG=new byte[EXACT_SIZE],E_SKIP=new byte[EXACT_SIZE],E_GEN=new byte[EXACT_SIZE];
  static final int[][] E_CELL=new int[66][64],E_SCORE=new int[66][64];
  static final long[][] E_FLIP=new long[66][64];

  static long deadline;
  static int nodes,iterationMove,iterationValue;
  static final Timeout TIMEOUT=new Timeout();
  static final class Timeout extends RuntimeException {
    private static final long serialVersionUID=1L;
    Timeout(){super(null,null,false,false);}
  }
  static void visit(){
    if(((++nodes)&127)==0&&System.nanoTime()>=deadline)throw TIMEOUT;
  }
  static void checkTime(){if(System.nanoTime()>=deadline)throw TIMEOUT;}
  static int digit(int line,int pos){return DIGIT[line*8+pos]&255;}
  static int moveIndex(int p,int line,int place,int dir){return (((p*LINE_N+line)*8+place)*2+dir);}
  static int stateIndex(int p,int line,int place){return (p*LINE_N+line)*8+place;}
  static int local(int line,int cell){return LOCAL[line*64+cell];}
  static int included(int cell,int i){return INCLUDED[cell*4+i];}
  static double relu(double x){return x>=0?x:x*.01;}

  static void init(){
    POW[0]=1;
    for(int i=1;i<POW.length;i++)POW[i]=POW[i-1]*3;
    Arrays.fill(LOCAL,(byte)-1);
    Arrays.fill(INCLUDED,(byte)-1);
    for(int line=0;line<38;line++)for(int pos=0;pos<8;pos++){
      int cell=GP[line][pos];
      if(cell<0)break;
      LOCAL[line*64+cell]=(byte)pos;
      int base=cell*4;
      for(int k=0;k<4;k++)if(INCLUDED[base+k]<0){INCLUDED[base+k]=(byte)line;break;}
    }
    initLines();
    for(int ph=0;ph<6;ph++)for(int d=1;d<=10;d++)
      MPC[ph][d]=(int)(1.5*MPC_SD[ph][d-1]);
    initModel();
  }

  static int colorBits(int idx,int color){
    int r=0;
    for(int i=0;i<8;i++){if(idx%3==color)r|=1<<i;idx/=3;}
    return r;
  }
  static int moveHalf(int p,int o,int place,boolean left){
    int at=1<<(7-place),r=0;
    if(((p|o)&at)!=0)return 0;
    int m=left?at<<1:at>>>1;
    while(m!=0&&(m&o)!=0){r++;m=left?m<<1:m>>>1;if((m&p)!=0)return r;}
    return 0;
  }
  static void initLines(){
    for(int idx=0;idx<LINE_N;idx++){
      int black=colorBits(idx,0),white=colorBits(idx,1),rev=0,c=0,all=0;
      for(int place=0;place<8;place++){
        int bp=(black>>>place)&1,wp=(white>>>place)&1;
        c+=bp-wp;all+=bp+wp;
        rev=rev*3+(bp!=0?0:wp!=0?1:2);
        DIGIT[idx*8+7-place]=(byte)(bp!=0?0:wp!=0?1:2);
        if(place>0&&((black|white)&(1<<(place-1)))==0){
          if(bp!=0)SURROUND[idx]++;else if(wp!=0)SURROUND[LINE_N+idx]++;
        }
        if(place<7&&((black|white)&(1<<(place+1)))==0){
          if(bp!=0)SURROUND[idx]++;else if(wp!=0)SURROUND[LINE_N+idx]++;
        }
      }
      COUNT[idx]=(byte)c;COUNT_ALL[idx]=(byte)all;REVERSE[idx]=(short)rev;
      for(int p=0;p<2;p++)for(int place=0;place<8;place++){
        int mine=p==0?black:white,opp=p==0?white:black;
        MOVE[moveIndex(p,idx,place,0)]=(byte)moveHalf(mine,opp,place,true);
        MOVE[moveIndex(p,idx,place,1)]=(byte)moveHalf(mine,opp,place,false);
        int si=stateIndex(p,idx,place),bit=1<<(7-place),f=idx,put=idx;
        if((mine&bit)!=0){}
        else if((opp&bit)!=0)f+=p==0?-POW[7-place]:POW[7-place];
        else put-=POW[7-place]*(p==0?2:1);
        FLIP[si]=(short)f;PUT[si]=(short)put;
      }
    }
  }

  static double[] decodeModel(){
    double[] w=new double[25436];
    CRC32 crc=new CRC32();
    long acc=0;int bits=0,k=0;
    for(String s:MODEL_DATA)for(int j=0;j<s.length();j++){
      int q=s.charAt(j)-0x3400;
      if(q<0||q>=32768)throw new IllegalStateException("model alphabet");
      acc|=(long)q<<bits;bits+=15;
      while(bits>=16&&k<w.length){
        int u=(int)(acc&65535);acc>>>=16;bits-=16;
        crc.update(u&255);crc.update((u>>>8)&255);
        w[k]=(short)u*MODEL_SCALE[k/6359];k++;
      }
    }
    if(k!=w.length||crc.getValue()!=MODEL_CRC)throw new IllegalStateException("model checksum");
    return w;
  }
  static int weightPos;
  static double[] weights;
  static double nextWeight(){return weights[weightPos++];}
  static void initModel(){
    weights=decodeModel();weightPos=0;
    for(int ph=0;ph<4;ph++){
      for(int pi=0;pi<11;pi++)loadPattern(ph,pi,PAT_SIZE[pi]);
      double[][] a0=new double[8][3],a1=new double[8][8];
      double[] ab0=new double[8],ab1=new double[8];
      for(int i=0;i<3;i++)for(int u=0;u<8;u++)a0[u][i]=nextWeight();
      for(int u=0;u<8;u++)ab0[u]=nextWeight();
      for(int i=0;i<8;i++)for(int u=0;u<8;u++)a1[u][i]=nextWeight();
      for(int u=0;u<8;u++)ab1[u]=nextWeight();
      for(int i=0;i<19;i++)DENSE[ph][i]=(float)nextWeight();
      BIAS[ph]=nextWeight();
      precomputeAddition(ph,a0,ab0,a1,ab1);
    }
    if(weightPos!=25436)throw new IllegalStateException("model length");
    weights=null;
  }
  static void loadPattern(int ph,int pi,int size){
    double[][] d0=new double[16][size*2],d1=new double[16][16];
    double[] b0=new double[16],b1=new double[16],d2=new double[16];
    for(int i=0;i<size*2;i++)for(int u=0;u<16;u++)d0[u][i]=nextWeight();
    for(int u=0;u<16;u++)b0[u]=nextWeight();
    for(int i=0;i<16;i++)for(int u=0;u<16;u++)d1[u][i]=nextWeight();
    for(int u=0;u<16;u++)b1[u]=nextWeight();
    for(int u=0;u<16;u++)d2[u]=nextWeight();
    double b2=nextWeight();
    int count=POW[size];float[] out=new float[count],reverse=new float[count];
    byte[] ds=new byte[size];double[] h0=new double[16];
    for(int idx=0;idx<count;idx++){
      int x=idx;
      for(int i=size-1;i>=0;i--){ds[i]=(byte)(x%3);x/=3;}
      for(int u=0;u<16;u++){
        double v=b0[u];
        for(int i=0;i<size;i++)if(ds[i]<2)v+=d0[u][i+(ds[i]==1?size:0)];
        h0[u]=relu(v);
      }
      double result=b2;
      for(int u=0;u<16;u++){
        double v=b1[u];for(int i=0;i<16;i++)v+=h0[i]*d1[u][i];
        result+=relu(v)*d2[u];
      }
      result=relu(result);out[idx]=(float)result;
      reverse[reverseIndex(pi,size,idx)]=(float)result;
    }
    for(int i=0;i<count;i++)out[i]+=reverse[i];
    PATTERN[ph][pi]=out;
  }
  static int patternDigit(int idx,int pos,int size){return idx/POW[size-1-pos]%3;}
  static int reverseIndex(int pi,int size,int idx){
    int r=0;
    if(pi<=7){for(int i=size-1;i>=0;i--)r=r*3+patternDigit(idx,i,size);return r;}
    for(int i:REVERSE_ORDER[pi-8])r=r*3+patternDigit(idx,i,size);
    return r;
  }
  static void precomputeAddition(int ph,double[][] d0,double[] b0,double[][] d1,double[] b1){
    float[] table=new float[61*51*51];double[] h0=new double[8];
    int k=0;
    for(int mobility=-30;mobility<=30;mobility++)for(int s0=0;s0<=50;s0++)for(int s1=0;s1<=50;s1++){
      double in0=mobility/30.0,in1=(s0-15)/15.0,in2=(s1-15)/15.0;
      for(int u=0;u<8;u++){
        double v=b0[u];v+=in0*d0[u][0];v+=in1*d0[u][1];v+=in2*d0[u][2];h0[u]=relu(v);
      }
      double sum=0;
      for(int u=0;u<8;u++){
        double v=b1[u];for(int i=0;i<8;i++)v+=h0[i]*d1[u][i];
        sum+=relu(v)*DENSE[ph][11+u];
      }
      table[k++]=(float)sum;
    }
    ADDITION[ph]=table;
  }

  static long legal(long player,long opponent){
    long mo=opponent&H_MASK;
    long f1=mo&(player<<1),f7=mo&(player<<7),f9=mo&(player<<9),f8=opponent&(player<<8);
    f1|=mo&(f1<<1);f7|=mo&(f7<<7);f9|=mo&(f9<<9);f8|=opponent&(f8<<8);
    long p1=mo&(mo<<1),p7=mo&(mo<<7),p9=mo&(mo<<9),p8=opponent&(opponent<<8);
    f1|=p1&(f1<<2);f7|=p7&(f7<<14);f9|=p9&(f9<<18);f8|=p8&(f8<<16);
    f1|=p1&(f1<<2);f7|=p7&(f7<<14);f9|=p9&(f9<<18);f8|=p8&(f8<<16);
    long moves=(f1<<1)|(f7<<7)|(f9<<9)|(f8<<8);
    f1=mo&(player>>>1);f7=mo&(player>>>7);f9=mo&(player>>>9);f8=opponent&(player>>>8);
    f1|=mo&(f1>>>1);f7|=mo&(f7>>>7);f9|=mo&(f9>>>9);f8|=opponent&(f8>>>8);
    p1>>>=1;p7>>>=7;p9>>>=9;p8>>>=8;
    f1|=p1&(f1>>>2);f7|=p7&(f7>>>14);f9|=p9&(f9>>>18);f8|=p8&(f8>>>16);
    f1|=p1&(f1>>>2);f7|=p7&(f7>>>14);f9|=p9&(f9>>>18);f8|=p8&(f8>>>16);
    moves|=(f1>>>1)|(f7>>>7)|(f9>>>9)|(f8>>>8);
    return moves&~(player|opponent);
  }
  static long legal(B b){return b.p==0?legal(b.black,b.white):legal(b.white,b.black);}
  static long rayL(long m,long p,long o,int shift,long mask){
    long x=o&mask,c=x&(m<<shift),f=c;
    for(int i=0;i<5;i++){f=x&(f<<shift);c|=f;}
    return ((c<<shift)&p)!=0?c:0;
  }
  static long rayR(long m,long p,long o,int shift,long mask){
    long x=o&mask,c=x&(m>>>shift),f=c;
    for(int i=0;i<5;i++){f=x&(f>>>shift);c|=f;}
    return ((c>>>shift)&p)!=0?c:0;
  }
  static long flips(long p,long o,int cell){
    long m=1L<<cell;if(((p|o)&m)!=0)return 0;
    return rayL(m,p,o,1,H_MASK)|rayR(m,p,o,1,H_MASK)
      |rayL(m,p,o,7,H_MASK)|rayR(m,p,o,7,H_MASK)
      |rayL(m,p,o,9,H_MASK)|rayR(m,p,o,9,H_MASK)
      |rayL(m,p,o,8,-1L)|rayR(m,p,o,8,-1L);
  }
  static void flipCell(B parent,B child,int cell){
    for(int k=0;k<4;k++){
      int line=included(cell,k);if(line<0)break;
      int pos=local(line,cell),idx=stateIndex(parent.p,child.a[line],pos);
      child.a[line]=FLIP[idx]&65535;
    }
  }
  static void moveDirection(B parent,B child,int cell,int line){
    int pos=local(line,cell),off=OFFSET[line];
    int left=MOVE[moveIndex(parent.p,parent.a[line],pos,0)]&255;
    int right=MOVE[moveIndex(parent.p,parent.a[line],pos,1)]&255;
    for(int j=1;j<=left;j++)flipCell(parent,child,cell-off*j);
    for(int j=1;j<=right;j++)flipCell(parent,child,cell+off*j);
  }
  static void moveInto(B parent,int cell,B child){
    long mine=parent.p==0?parent.black:parent.white;
    long opp=parent.p==0?parent.white:parent.black;
    long bit=1L<<cell,f=flips(mine,opp,cell);
    System.arraycopy(parent.a,0,child.a,0,38);
    for(int k=0;k<4;k++){int line=included(cell,k);if(line<0)break;moveDirection(parent,child,cell,line);}
    for(int k=0;k<4;k++){
      int line=included(cell,k);if(line<0)break;
      int idx=stateIndex(parent.p,child.a[line],local(line,cell));child.a[line]=PUT[idx]&65535;
    }
    child.p=1-parent.p;child.n=parent.n+1;child.move=cell;
    if(parent.p==0){child.black=parent.black|bit|f;child.white=parent.white&~f;}
    else{child.white=parent.white|bit|f;child.black=parent.black&~f;}
    child.empty=parent.empty&~bit;
  }
  static void passInto(B parent,B child){
    System.arraycopy(parent.a,0,child.a,0,38);
    child.black=parent.black;child.white=parent.white;child.empty=parent.empty;
    child.p=1-parent.p;child.n=parent.n;child.move=-1;
  }

  static int fillShortLine(int line,int power){return digit(line,7-power)!=2?line-POW[power]+1:line;}
  static int surround(B b,int color){
    int sum=0,base=color*LINE_N;
    for(int i=0;i<16;i++)sum+=SURROUND[base+b.a[i]]&255;
    for(int axis=0;axis<2;axis++)for(int j=0;j<11;j++){
      int len=j<=5?3+j:13-j,power=8-len,line=b.a[16+axis*11+j];
      if(power>0)line=fillShortLine(line,power);
      sum+=SURROUND[base+line]&255;
    }
    return Math.min(50,sum);
  }
  static int mid(int v,int high,int low){return v%POW[high]/POW[low];}
  static int rev(int v){return REVERSE[v]&65535;}
  static double edge2(int ph,int x,int y,int[] a){
    return PATTERN[ph][7][digit(a[x],1)*POW[9]+a[y]*3+digit(a[x],6)];
  }
  static double triangle(int ph,int w,int x,int y,int z,int[] a,boolean reverse){
    int aw=reverse?rev(a[w]):a[w],ax=reverse?rev(a[x]):a[x];
    int ay=reverse?rev(a[y]):a[y],az=reverse?rev(a[z]):a[z];
    int idx=aw/POW[4]*POW[6]+ax/POW[5]*POW[3]+ay/POW[6]*3+az/POW[7];
    return PATTERN[ph][8][idx];
  }
  static double edgeBlock(int ph,int x,int y,int[] a){
    int idx=digit(a[x],0)*POW[9]+mid(a[x],6,2)*POW[5]+digit(a[x],7)*POW[4]+mid(a[y],6,2);
    return PATTERN[ph][9][idx];
  }
  static double cross(int ph,int x,int y,int z,int[] a){
    int one=a[x]/POW[4]*POW[6]+a[y]/POW[5]*POW[3]+a[z]/POW[5];
    int rx=rev(a[x]),ry=rev(a[y]),rz=rev(a[z]);
    int two=rx/POW[4]*POW[6]+mid(ry,7,4)*POW[3]+mid(rz,7,4);
    return PATTERN[ph][10][one]+PATTERN[ph][10][two];
  }
  static double pattern(B b,int ph){
    int[] a=b.a;double r=0;
    r+=DENSE[ph][0]*(PATTERN[ph][0][a[1]]+PATTERN[ph][0][a[6]]+PATTERN[ph][0][a[9]]+PATTERN[ph][0][a[14]]);
    r+=DENSE[ph][1]*(PATTERN[ph][1][a[2]]+PATTERN[ph][1][a[5]]+PATTERN[ph][1][a[10]]+PATTERN[ph][1][a[13]]);
    r+=DENSE[ph][2]*(PATTERN[ph][2][a[3]]+PATTERN[ph][2][a[4]]+PATTERN[ph][2][a[11]]+PATTERN[ph][2][a[12]]);
    r+=DENSE[ph][3]*(PATTERN[ph][3][a[18]/POW[3]]+PATTERN[ph][3][a[24]/POW[3]]+PATTERN[ph][3][a[29]/POW[3]]+PATTERN[ph][3][a[35]/POW[3]]);
    r+=DENSE[ph][4]*(PATTERN[ph][4][a[19]/POW[2]]+PATTERN[ph][4][a[23]/POW[2]]+PATTERN[ph][4][a[30]/POW[2]]+PATTERN[ph][4][a[34]/POW[2]]);
    r+=DENSE[ph][5]*(PATTERN[ph][5][a[20]/3]+PATTERN[ph][5][a[22]/3]+PATTERN[ph][5][a[31]/3]+PATTERN[ph][5][a[33]/3]);
    r+=DENSE[ph][6]*(PATTERN[ph][6][a[21]]+PATTERN[ph][6][a[32]]);
    r+=DENSE[ph][7]*(edge2(ph,1,0,a)+edge2(ph,6,7,a)+edge2(ph,9,8,a)+edge2(ph,14,15,a));
    r+=DENSE[ph][8]*(triangle(ph,0,1,2,3,a,false)+triangle(ph,7,6,5,4,a,false)+triangle(ph,15,14,13,12,a,false)+triangle(ph,15,14,13,12,a,true));
    r+=DENSE[ph][9]*(edgeBlock(ph,0,1,a)+edgeBlock(ph,7,6,a)+edgeBlock(ph,8,9,a)+edgeBlock(ph,15,14,a));
    r+=DENSE[ph][10]*(cross(ph,21,20,22,a)+cross(ph,32,31,33,a));
    return r;
  }
  static double raw(B b){
    int ph=Math.max(0,Math.min(3,(b.n-4)/10-2));
    int mobility=Math.min(30,Long.bitCount(legal(b)))*(b.p==0?1:-1);
    int s0=surround(b,0),s1=surround(b,1);
    int ai=((mobility+30)*51+s0)*51+s1;
    double r=BIAS[ph]+pattern(b,ph)+ADDITION[ph][ai];
    return b.p==0?r:-r;
  }
  static int evaluate(B b){
    double r=Math.max(-1,Math.min(1,raw(b)));return (int)(r*SCALE);
  }
  static int terminal(B b){
    int diff=Long.bitCount(b.black)-Long.bitCount(b.white);
    if(b.p==1)diff=-diff;
    int vacant=Long.bitCount(b.empty);
    if(diff>0)diff+=vacant;else if(diff<0)diff-=vacant;
    return diff*STEP;
  }

  static int hash(long black,long white,int side,boolean skip,int mask){
    long z=black^Long.rotateLeft(white,23);
    if(side!=0)z^=0x9e3779b97f4a7c15L;
    if(skip)z^=0xd1b54a32d192ed03L;
    z^=z>>>33;z*=0xff51afd7ed558ccdL;z^=z>>>33;return (int)z&mask;
  }
  static int ttMove(B b,boolean skip){
    int h=hash(b.black,b.white,b.p,skip,TT_MASK);
    if(T_GEN[h]==generation&&T_BLACK[h]==b.black&&T_WHITE[h]==b.white&&T_SIDE[h]==b.p&&T_SKIP[h]==(skip?1:0))return T_MOVE[h]&255;
    return 255;
  }
  static void store(B b,boolean skip,int depth,int value,int alpha0,int beta0,int best){
    int h=hash(b.black,b.white,b.p,skip,TT_MASK);
    if(T_GEN[h]!=generation||depth>=(T_DEPTH[h]&255)){
      T_GEN[h]=generation;T_BLACK[h]=b.black;T_WHITE[h]=b.white;T_SIDE[h]=(byte)b.p;T_SKIP[h]=(byte)(skip?1:0);
      T_DEPTH[h]=(byte)depth;T_VALUE[h]=value;T_MOVE[h]=(byte)best;
      T_FLAG[h]=(byte)(value<=alpha0?3:value>=beta0?2:1);
    }
  }
  static int probe(B b,boolean skip,int depth,int alpha,int beta){
    int h=hash(b.black,b.white,b.p,skip,TT_MASK);
    if(T_GEN[h]!=generation||T_BLACK[h]!=b.black||T_WHITE[h]!=b.white||T_SIDE[h]!=b.p||T_SKIP[h]!=(skip?1:0)||(T_DEPTH[h]&255)<depth)return INF+1;
    int v=T_VALUE[h],f=T_FLAG[h];
    if(f==1||(f==2&&v>=beta)||(f==3&&v<=alpha))return v;
    return INF+1;
  }
  static int generate(B b,long moves,int ply,boolean endOrder,int preferred){
    int count=0;
    while(moves!=0){
      long bit=moves&-moves;int cell=Long.numberOfTrailingZeros(bit);moves^=bit;
      B child=board(ply,count);moveInto(b,cell,child);
      child.order=-evaluate(child)+CELL_WEIGHT[cell]*2;
      if(endOrder)child.order-=Long.bitCount(legal(child))*100;
      if(cell==preferred)child.order+=2000000;
      int at=count;
      while(at>0&&POOL[ply][at-1].order<child.order){POOL[ply][at]=POOL[ply][at-1];at--;}
      POOL[ply][at]=child;count++;
    }
    return count;
  }
  static int alphaBeta(B b,boolean skipped,int depth,int alpha,int beta,int ply,boolean allowMpc){
    visit();long moves=legal(b);
    if(depth==0){
      if(moves!=0)return evaluate(b);
      if(skipped)return terminal(b);
      B pass=passBoard(ply);passInto(b,pass);
      return -alphaBeta(pass,true,0,-beta,-alpha,ply+1,allowMpc);
    }
    int empties=64-b.n;
    if(depth>=empties&&empties<=10){
      long p=b.p==0?b.black:b.white,o=b.p==0?b.white:b.black;
      return exact(p,o,b.empty,skipped,alpha,beta,ply);
    }
    if(allowMpc&&depth<=10){
      int ph=Math.min(5,Math.max(0,(b.n-4)/10)),bound=beta+MPC[ph][depth];
      if(alphaBeta(b,skipped,MPC_DEPTH[depth],bound-1,bound,ply,true)>=bound)return beta+1;
      bound=alpha-MPC[ph][depth];
      if(alphaBeta(b,skipped,MPC_DEPTH[depth],bound,bound+1,ply,true)<=bound)return alpha-1;
    }
    int cached=probe(b,skipped,depth,alpha,beta);if(cached!=INF+1)return cached;
    if(moves==0){
      if(skipped)return terminal(b);
      B pass=passBoard(ply);passInto(b,pass);
      return -alphaBeta(pass,true,depth,-beta,-alpha,ply+1,allowMpc);
    }
    int alpha0=alpha,beta0=beta,best=-INF,bestMove=255,preferred=ttMove(b,skipped);
    if(depth<=3){
      B child=board(ply,0);
      while(moves!=0){
        long bit=moves&-moves;int cell=Long.numberOfTrailingZeros(bit);moves^=bit;moveInto(b,cell,child);
        int value=-alphaBeta(child,false,depth-1,-beta,-alpha,ply+1,allowMpc);
        if(value>best){best=value;bestMove=cell;}if(value>alpha)alpha=value;if(alpha>=beta)break;
      }
    }else{
      int count=generate(b,moves,ply,false,preferred);
      for(int i=0;i<count;i++){
        B child=POOL[ply][i];int value;
        if(i==0)value=-alphaBeta(child,false,depth-1,-beta,-alpha,ply+1,allowMpc);
        else{
          value=-alphaBeta(child,false,depth-1,-alpha-1,-alpha,ply+1,allowMpc);
          if(value>alpha&&value<beta)value=-alphaBeta(child,false,depth-1,-beta,-alpha,ply+1,allowMpc);
        }
        if(value>best){best=value;bestMove=child.move;}if(value>alpha)alpha=value;if(alpha>=beta)break;
      }
    }
    store(b,skipped,depth,best,alpha0,beta0,bestMove);return best;
  }
  static int root(B b,long moves,int depth,int alpha,int beta){
    int preferred=ttMove(b,false),count=generate(b,moves,0,false,preferred);
    int best=-INF,bestMove=Long.numberOfTrailingZeros(moves),a=alpha;
    for(int i=0;i<count;i++){
      B child=POOL[0][i];int value;
      if(i==0)value=-alphaBeta(child,false,depth-1,-beta,-a,1,true);
      else{
        value=-alphaBeta(child,false,depth-1,-a-1,-a,1,true);
        if(value>a&&value<beta)value=-alphaBeta(child,false,depth-1,-beta,-a,1,true);
      }
      if(value>best){best=value;bestMove=child.move;}if(value>a)a=value;if(a>=beta)break;
    }
    iterationMove=bestMove;iterationValue=best;store(b,false,depth,best,alpha,beta,bestMove);return best;
  }

  static long oddRegions(long empty){
    long r=0;for(long region:REGIONS)if((Long.bitCount(empty&region)&1)!=0)r|=region;return r;
  }
  static long stableEdges(long color){
    int[] corners={0,7,56,63},d1={1,-1,1,-1},d2={8,8,-8,-8};long stable=0;
    for(int i=0;i<4;i++)if((color&(1L<<corners[i]))!=0){
      stable|=1L<<corners[i];
      int cell=corners[i]+d1[i];for(int k=1;k<8;k++,cell+=d1[i]){long bit=1L<<cell;if((color&bit)==0)break;stable|=bit;}
      cell=corners[i]+d2[i];for(int k=1;k<8;k++,cell+=d2[i]){long bit=1L<<cell;if((color&bit)==0)break;stable|=bit;}
    }
    return stable;
  }
  static int exactTerminal(long p,long o,long empty){
    int d=Long.bitCount(p)-Long.bitCount(o),v=Long.bitCount(empty);
    if(d>0)d+=v;else if(d<0)d-=v;return d*STEP;
  }
  static int orderExact(long p,long o,long empty,long moves,int ply){
    int count=0;long odd=oddRegions(empty);
    while(moves!=0){
      long bit=moves&-moves;int cell=Long.numberOfTrailingZeros(bit);moves^=bit;
      long f=flips(p,o,cell);int score;
      if(f==o)score=Integer.MAX_VALUE;
      else{
        int mobility=Long.bitCount(legal(o&~f,p|f|bit));
        score=CELL_WEIGHT[cell]*32-mobility*256;
        if((bit&odd)!=0)score+=16384;if((bit&CORNERS)!=0)score+=32768;
      }
      int at=count;
      while(at>0&&(score>E_SCORE[ply][at-1]||(score==E_SCORE[ply][at-1]&&cell<E_CELL[ply][at-1]))){
        E_SCORE[ply][at]=E_SCORE[ply][at-1];E_CELL[ply][at]=E_CELL[ply][at-1];E_FLIP[ply][at]=E_FLIP[ply][at-1];at--;
      }
      E_SCORE[ply][at]=score;E_CELL[ply][at]=cell;E_FLIP[ply][at]=f;count++;
    }
    return count;
  }
  static int exact(long p,long o,long empty,boolean skipped,int alpha,int beta,int ply){
    visit();int alpha0=alpha,beta0=beta,h=hash(p,o,0,skipped,EXACT_MASK);
    if(E_GEN[h]==generation&&E_PLAYER[h]==p&&E_OPPONENT[h]==o&&E_SKIP[h]==(skipped?1:0)){
      int v=E_VALUE[h],f=E_FLAG[h];if(f==1||(f==2&&v>=beta)||(f==3&&v<=alpha))return v;
    }
    if(Long.bitCount(empty)>=8){
      int low=(2*Long.bitCount(stableEdges(p))-64)*STEP;
      int high=(64-2*Long.bitCount(stableEdges(o)))*STEP;
      if(low>=beta)return low;if(high<=alpha)return high;alpha=Math.max(alpha,low);beta=Math.min(beta,high);
    }
    long moves=legal(p,o)&empty;
    if(moves==0){
      int v=skipped?exactTerminal(p,o,empty):-exact(o,p,empty,true,-beta,-alpha,ply+1);
      storeExact(h,p,o,skipped,v,alpha0,beta0);return v;
    }
    int count=orderExact(p,o,empty,moves,ply),best=-INF;
    for(int i=0;i<count;i++){
      int cell=E_CELL[ply][i];long bit=1L<<cell,f=E_FLIP[ply][i];
      int value=f==o?SCALE:-exact(o&~f,p|f|bit,empty^bit,false,-beta,-alpha,ply+1);
      if(value>best)best=value;if(value>alpha)alpha=value;if(alpha>=beta)break;
    }
    storeExact(h,p,o,skipped,best,alpha0,beta0);return best;
  }
  static void storeExact(int h,long p,long o,boolean skip,int value,int alpha0,int beta0){
    E_GEN[h]=generation;E_PLAYER[h]=p;E_OPPONENT[h]=o;E_SKIP[h]=(byte)(skip?1:0);E_VALUE[h]=value;
    E_FLAG[h]=(byte)(value<=alpha0?3:value>=beta0?2:1);
  }

  static int think(B b,long allowed){
    int fallback=Long.numberOfTrailingZeros(allowed),bestMove=fallback,guess=0,empties=64-b.n;
    nodes=0;generation++;
    if(generation==0){Arrays.fill(T_GEN,(byte)0);Arrays.fill(E_GEN,(byte)0);generation=1;}
    for(int depth=1;depth<=empties;depth++){
      try{
        checkTime();int alpha=-INF,beta=INF;
        if(depth>=4){alpha=Math.max(-INF,guess-500);beta=Math.min(INF,guess+500);}
        int value=root(b,allowed,depth,alpha,beta);
        if(value<=alpha||value>=beta)value=root(b,allowed,depth,-INF,INF);
        bestMove=iterationMove;guess=iterationValue;
        if(depth>=empties)break;
      }catch(Timeout timeout){break;}
    }
    return bestMove;
  }
  static B fromRows(String[] rows,int side){
    B b=new B();Arrays.fill(b.a,LINE_N-1);b.p=side;
    for(int r=0;r<8;r++)for(int c=0;c<8;c++){
      char ch=rows[r].charAt(c);int cell=r*8+c;
      if(ch=='0')b.black|=1L<<cell;else if(ch=='1')b.white|=1L<<cell;
    }
    b.empty=~(b.black|b.white);b.n=Long.bitCount(b.black|b.white);
    for(int line=0;line<38;line++)for(int pos=0;pos<8;pos++){
      int cell=GP[line][pos];if(cell<0)break;long bit=1L<<cell;
      if((b.black&bit)!=0)b.a[line]-=2*POW[7-pos];else if((b.white&bit)!=0)b.a[line]-=POW[7-pos];
    }
    return b;
  }
  static int policy(String move){
    if(move==null||move.length()<2)return -1;
    int c=Character.toLowerCase(move.charAt(0))-'a',r=move.charAt(1)-'1';
    return r>=0&&r<8&&c>=0&&c<8?r*8+c:-1;
  }
  static String coordinate(int cell){return ""+(char)('a'+cell%8)+(char)('1'+cell/8);}
  static void evalMode(BufferedReader in)throws Exception{
    init();String line;
    while((line=in.readLine())!=null){
      line=line.trim();if(line.isEmpty())continue;int side=Integer.parseInt(line);String[] rows=new String[8];
      for(int i=0;i<8;i++)rows[i]=in.readLine();B b=fromRows(rows,side);
      System.out.println(evaluate(b)+" "+Double.toString(raw(b)));
    }
  }
  public static void main(String[] args)throws Exception{
    BufferedReader in=new BufferedReader(new InputStreamReader(System.in));
    if(args.length>0&&args[0].equals("--eval")){evalMode(in);return;}
    String first=in.readLine();if(first==null)return;long firstStart=System.nanoTime();int id=Integer.parseInt(first.trim());
    String sizeLine=in.readLine();if(sizeLine==null||Integer.parseInt(sizeLine.trim())!=8)return;
    boolean initialized=false;
    try{init();initialized=true;}
    catch(Throwable error){System.err.println("model init failed: "+error.getClass().getSimpleName());}
    long initElapsed=System.nanoTime()-firstStart;
    boolean firstTurn=true;String row0;
    while((row0=in.readLine())!=null){
      long start=System.nanoTime();String[] rows=new String[8];rows[0]=row0;
      for(int i=1;i<8;i++){rows[i]=in.readLine();if(rows[i]==null)return;}
      String countLine=in.readLine();if(countLine==null)return;int count=Integer.parseInt(countLine.trim());
      String[] actions=new String[count];long official=0;
      for(int i=0;i<count;i++){
        String action=in.readLine();if(action==null)return;actions[i]=action.trim();
        int p=policy(actions[i]);if(p>=0)official|=1L<<p;
      }
      if(count==0)continue;
      String answer=actions[0];
      try{
        long budget=firstTurn?Math.max(0L,Math.min(1_500_000_000L,1_600_000_000L-initElapsed)):115_000_000L;
        deadline=start+budget;
        if(firstTurn)deadline=Math.min(deadline,firstStart+1_800_000_000L);
        if(initialized){
          B b=fromRows(rows,id);long moves=legal(b)&official;
          if(moves!=0&&System.nanoTime()<deadline){
            int chosen=firstTurn&&id==0&&b.n==4?Long.numberOfTrailingZeros(moves):think(b,moves);
            if((official&(1L<<chosen))!=0)answer=coordinate(chosen);
          }
        }
      }catch(Throwable error){
        if(error!=TIMEOUT)System.err.println("fallback: "+error.getClass().getSimpleName());
      }
      System.out.println(answer);System.out.flush();firstTurn=false;
    }
  }
}
