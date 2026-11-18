import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.concurrent.*;

public class OthelloAI_03 {

  static final int hw = 8;
  static final int hw_m1 = 7;
  static final int hw_p1 = 9;
  static final int hw2 = 64;
  static final int hw22 = 128;
  static final int hw2_m1 = 63;
  static final int hw2_mhw = 56;
  static final int hw2_p1 = 65;
  static final int n_line = 6561;
  static final int max_evaluate_idx = 59049;
  static final int inf = 1_000_000;
  static final int b_idx_num = 38;

  static final int book_hash_table_size = 8192;
  static final int book_hash_mask = book_hash_table_size - 1;
  static final int book_stones = 64;

  static final int search_hash_table_size = 1_048_576;
  static final int search_hash_mask = search_hash_table_size - 1;

  static final int n_phases = 4;
  static final int n_patterns = 11;
  static final int n_dense0 = 16;
  static final int n_dense1 = 16;
  static final int n_add_input = 3;
  static final int n_add_dense0 = 8;
  static final int n_add_dense1 = 8;
  static final int n_all_input = 19;
  static final int max_canput = 30;
  static final int max_surround = 50;

  static final int epsilon = 1;
  static final int sc_w = 6400;
  static final int step = 100;
  static final int cache_hit = 10_000;
  static final int cache_both = 1_000;
  static final int mtd_threshold = 400;
  static final long move_time_limit_ms = 9_500L;
  static final long time_check_interval = 2_048L;

  static final int mpc_min_depth = 1;
  static final int mpc_max_depth = 10;
  static final int mpc_min_depth_final = 10;
  static final int mpc_max_depth_final = 28;
  static final double mpct_final = 1.1;

  static final int p31 = 3;
  static final int p32 = 9;
  static final int p33 = 27;
  static final int p34 = 81;
  static final int p35 = 243;
  static final int p36 = 729;
  static final int p37 = 2187;
  static final int p38 = 6561;
  static final int p39 = 19683;
  static final int p310 = 59049;

  static final int NUM_THREADS = Runtime.getRuntime().availableProcessors();
  static final ForkJoinPool forkJoinPool = new ForkJoinPool(NUM_THREADS);
  
  static final class Board implements Comparable<Board> {
    final int[] b = new int[b_idx_num]; // C++: int b[b_idx_num];
    int p;
    int policy;
    int v;
    int n;

    Board() {}

    // C++の暗黙コピー相当
    Board(Board other) {
        System.arraycopy(other.b, 0, this.b, 0, b.length);
        this.p = other.p;
        this.policy = other.policy;
        this.v = other.v;
        this.n = other.n;
    }

    @Override
    public int compareTo(Board another) {
        // C++の operator< は v > another.v（評価値の大きい順）
        return Integer.compare(another.v, this.v);
    }

    @Override
    public String toString() {
        return "Board{v=" + v + ", p=" + p + ", policy=" + policy + ", n=" + n + "}";
    }
  }

  static final class BookNode {
    final int[] k = new int[4];
    final int[] policies = new int[35];
    int size;
    BookNode p_n_node; // ポインタを参照型で表現

    BookNode() {}

    BookNode(BookNode other) {
      System.arraycopy(other.k, 0, this.k, 0, k.length);
      System.arraycopy(other.policies, 0, this.policies, 0, policies.length);
      this.size = other.size;
      this.p_n_node = other.p_n_node; // シャローコピー（深いコピーが必要なら明示的に再帰処理）
    }
  }

  static final class SearchNode {
    boolean reg;
    final int[] k = new int[4];
    int l;
    int u;
    int generation; // 追加

    SearchNode() {}

    SearchNode(SearchNode other) {
      this.reg = other.reg;
      System.arraycopy(other.k, 0, this.k, 0, k.length);
      this.l = other.l;
      this.u = other.u;
      this.generation = other.generation; // 追加
    }
  }

  static final class SearchResult {
    int policy;
    int value;
    int depth;
    int nps;

    SearchResult() {}

    SearchResult(SearchResult other) {
      this.policy = other.policy;
      this.value = other.value;
      this.depth = other.depth;
      this.nps = other.nps;
    }
  }

  static final int[] idx_n_cell = {
    8, 8, 8, 8, 8, 8, 8, 8,
    8, 8, 8, 8, 8, 8, 8, 8,
    3, 4, 5, 6, 7, 8, 7, 6,
    5, 4, 3, 3, 4, 5, 6, 7,
    8, 7, 6, 5, 4, 3
  };
  static final int[] move_offset = {
    1, 1, 1, 1, 1, 1, 1, 1,
    8, 8, 8, 8, 8, 8, 8, 8,
    9, 9, 9, 9, 9, 9, 9, 9,
    9, 9, 9, 7, 7, 7, 7, 7,
    7, 7, 7, 7, 7, 7
  };
  static final int[][] global_place = {
    {0, 1, 2, 3, 4, 5, 6, 7},
    {8, 9, 10, 11, 12, 13, 14, 15},
    {16, 17, 18, 19, 20, 21, 22, 23},
    {24, 25, 26, 27, 28, 29, 30, 31},
    {32, 33, 34, 35, 36, 37, 38, 39},
    {40, 41, 42, 43, 44, 45, 46, 47},
    {48, 49, 50, 51, 52, 53, 54, 55},
    {56, 57, 58, 59, 60, 61, 62, 63},

    {0, 8, 16, 24, 32, 40, 48, 56},
    {1, 9, 17, 25, 33, 41, 49, 57},
    {2, 10, 18, 26, 34, 42, 50, 58},
    {3, 11, 19, 27, 35, 43, 51, 59},
    {4, 12, 20, 28, 36, 44, 52, 60},
    {5, 13, 21, 29, 37, 45, 53, 61},
    {6, 14, 22, 30, 38, 46, 54, 62},
    {7, 15, 23, 31, 39, 47, 55, 63},

    {5, 14, 23, -1, -1, -1, -1, -1},
    {4, 13, 22, 31, -1, -1, -1, -1},
    {3, 12, 21, 30, 39, -1, -1, -1},
    {2, 11, 20, 29, 38, 47, -1, -1},
    {1, 10, 19, 28, 37, 46, 55, -1},
    {0, 9, 18, 27, 36, 45, 54, 63},
    {8, 17, 26, 35, 44, 53, 62, -1},
    {16, 25, 34, 43, 52, 61, -1, -1},
    {24, 33, 42, 51, 60, -1, -1, -1},
    {32, 41, 50, 59, -1, -1, -1, -1},
    {40, 49, 58, -1, -1, -1, -1, -1},

    {2, 9, 16, -1, -1, -1, -1, -1},
    {3, 10, 17, 24, -1, -1, -1, -1},
    {4, 11, 18, 25, 32, -1, -1, -1},
    {5, 12, 19, 26, 33, 40, -1, -1},
    {6, 13, 20, 27, 34, 41, 48, -1},
    {7, 14, 21, 28, 35, 42, 49, 56},
    {15, 22, 29, 36, 43, 50, 57, -1},
    {23, 30, 37, 44, 51, 58, -1, -1},
    {31, 38, 45, 52, 59, -1, -1, -1},
    {39, 46, 53, 60, -1, -1, -1, -1},
    {47, 54, 61, -1, -1, -1, -1, -1}
  };
  static final int[][] place_included = new int[hw2][4];
  static final int[] pow3 = new int[11];
  static final int[][] mod3 = new int[n_line][hw];
  static final int[][][][] move_arr = new int[2][n_line][hw][2];
  static final boolean[][][] legal_arr = new boolean[2][n_line][hw];
  static final int[][][] flip_arr = new int[2][n_line][hw];
  static final int[][][] put_arr = new int[2][n_line][hw];
  static final int[][] local_place = new int[b_idx_num][hw2];
  static final int[] cell_weight = {
    120, -20, 20, 5, 5, 20, -20, 120,
    -20, -40, -5, -5, -5, -5, -40, -20,
    20, -5, 15, 3, 3, 15, -5, 20,
    5, -5, 3, 3, 3, 3, -5, 5,
    5, -5, 3, 3, 3, 3, -5, 5,
    20, -5, 15, 3, 3, 15, -5, 20,
    -20, -40, -5, -5, -5, -5, -40, -20,
    120, -20, 20, 5, 5, 20, -20, 120
  };
  static final int[] count_arr = new int[n_line];
  static final int[] count_all_arr = new int[n_line];
  static final int[][] pop_digit = new int[n_line][hw];
  static final int[][][] pop_mid = new int[n_line][hw][hw];
  static final int[] reverse_board = new int[n_line];
  static final int[][] canput_arr = new int[2][n_line];
  static final int[][] surround_arr = new int[2][n_line];
  static final int[] mpcd = {
    0, 0, 0, 1, 2, 1, 2, 3, 4, 3,
    4, 3, 4, 5, 6, 5, 6, 5, 6, 7,
    6, 7, 8, 9, 8, 9, 10, 11, 10, 11
  };
  static final double[] mpct = {1.5, 1.5, 1.5, 1.5, 1.5, 1.5};
  static final double[][] mpcsd = {
    {482, 512, 352, 298, 474, 372, 349, 323, 463, 335},
    {312, 381, 310, 261, 354, 322, 291, 313, 389, 371},
    {389, 463, 392, 352, 548, 402, 422, 441, 530, 538},
    {417, 490, 436, 405, 570, 494, 452, 438, 527, 524},
    {486, 554, 519, 463, 635, 665, 555, 550, 635, 581},
    {433, 517, 430, 391, 560, 556, 383, 345, 567, 332}
  };
  static final double[] mpcsd_final = {
    1564, 1309, 1440, 1453, 1152, 1580, 1394, 1655, 1381,
    1578, 1660, 1452, 1574, 1725, 1655, 1514, 1378, 1622, 1489
  };
  static final int[][] mpctsd = new int[6][mpc_max_depth + 1];
  static final int[] mpctsd_final = new int[mpc_max_depth_final + 1];

  static final List<Integer> vacant_lst = new ArrayList<>();
  static final BookNode[] book = new BookNode[book_hash_table_size];
  static final SearchNode[][] search_replace_table = new SearchNode[2][search_hash_table_size];
  static long searched_nodes;
  static long hash_conf;
  static long hash_get;
  static long hash_reg;
  static long search_deadline = Long.MAX_VALUE;
  static int f_search_table_idx;
  static final double[][][] pattern_arr = new double[n_phases][n_patterns][max_evaluate_idx];
  static final double[][][][][] add_arr = new double[n_phases][max_canput * 2 + 1][max_surround + 1][max_surround + 1][n_add_dense1];
  static final double[][] all_dense = new double[n_phases][n_all_input];
  static final double[] all_bias = new double[n_phases];

  static final Random raw_myrandom = new Random(System.currentTimeMillis());

  static double myrandom() {
    // JavaのRandom#nextDouble() は [0.0, 1.0) の一様分布を返す
    return raw_myrandom.nextDouble();
  }

  static int myrandrange(int s, int e) {
    return s + (int) ((e - s) * myrandom());
  }

  static long tim() {
    return System.currentTimeMillis();
  }

  static final class SearchTimeout extends RuntimeException {
    SearchTimeout() {
      super(null, null, false, false);
    }
  }

  static final SearchTimeout search_timeout = new SearchTimeout();

  static void begin_move_timer(long strt) {
    search_deadline = strt + move_time_limit_ms;
  }

  static void clear_move_timer() {
    search_deadline = Long.MAX_VALUE;
  }

  static long remaining_time_ms() {
    if (search_deadline == Long.MAX_VALUE) return Long.MAX_VALUE;
    return search_deadline - tim();
  }

  static void checkTime() {
    if (search_deadline != Long.MAX_VALUE &&
        (searched_nodes & (time_check_interval - 1L)) == 0L &&
        tim() >= search_deadline) {
      throw search_timeout;
    }
  }

  static long calc_hash(int[] p) {
    return (long) p[0]
      + (long) p[1] * 17
      + (long) p[2] * 289
      + (long) p[3] * 4913
      + (long) p[4] * 83521
      + (long) p[5] * 1419857
      + (long) p[6] * 24137549
      + (long) p[7] * 410338673;
  }

  static boolean compare_key(int[] a, int[] b) {
    for (int i = 0; i < 4; i++) {
      if (a[i * 2] + a[i * 2 + 1] * n_line != b[i]) {
        return false;
      }
    }
    return true;
  }

  static void print_board_line(int tmp) {
    StringBuilder res = new StringBuilder();
    for (int j = 0; j < hw; j++) {
      int mod = tmp % 3;
      if (mod == 0)
        res.insert(0, "X ");
      else if (mod == 1)
        res.insert(0, "O ");
      else
        res.insert(0, ". ");
      tmp /= 3;
    }
    System.err.print(res.toString());
  }

  static void print_board(int[] board) {
    for (int i = 0; i < hw; i++) {
      int tmp = board[i];
      StringBuilder res = new StringBuilder();
      for (int j = 0; j < hw; j++) {
        int mod = tmp % 3;
        if (mod == 0)
          res.insert(0, "X ");
        else if (mod == 1)
          res.insert(0, "O ");
        else
          res.insert(0, ". ");
        tmp /= 3;
      }
      System.err.println(res.toString());
    }
    System.err.println();
  }

  static int create_one_color(int idx, int k) {
    int res = 0;
    for (int i = 0; i < hw; i++) {
      if (idx % 3 == k) {
        res |= 1 << i;
      }
      idx /= 3;
    }
    return res;
  }

  static int trans(int pt, int k) {
    if (k == 0)
      return pt << 1;
    else
      return pt >> 1;
  }

  static int move_line_half(int p, int o, int place, int k) {
    int res = 0;
    int pt = 1 << (hw_m1 - place);
    if ((pt & p) != 0 || (pt & o) != 0)
      return res;
    int mask = trans(pt, k);
    while (mask != 0 && (mask & o) != 0) {
      res++;
      mask = trans(mask, k);
      if ((mask & p) != 0)
        return res;
    }
    return 0;
  }

  static void init_pow() {
    pow3[0] = 1;
    for (int idx = 1; idx < 11; idx++) {
      pow3[idx] = pow3[idx - 1] * 3;
    }
  }

  static void init_move() {
    for (int idx = 0; idx < n_line; idx++) {
      int b = create_one_color(idx, 0);
      int w = create_one_color(idx, 1);
      count_arr[idx] = 0;
      count_all_arr[idx] = 0;
      reverse_board[idx] = 0;
      canput_arr[0][idx] = 0;
      canput_arr[1][idx] = 0;
      surround_arr[0][idx] = 0;
      surround_arr[1][idx] = 0;

      for (int place = 0; place < hw; place++) {
        count_arr[idx] += (b >> place) & 1;
        count_arr[idx] -= (w >> place) & 1;
        count_all_arr[idx] += ((b >> place) & 1) + ((w >> place) & 1);

        reverse_board[idx] *= 3;
        if (((b >> place) & 1) != 0)
          reverse_board[idx] += 0;
        else if (((w >> place) & 1) != 0)
          reverse_board[idx] += 1;
        else
          reverse_board[idx] += 2;

        if (place > 0) {
          if (((b >> (place - 1)) & 1) == 0 && ((w >> (place - 1)) & 1) == 0) {
            if (((b >> place) & 1) != 0)
              surround_arr[0][idx]++;
            else if (((w >> place) & 1) != 0)
              surround_arr[1][idx]++;
          }
        }
        if (place < hw_m1) {
          if (((b >> (place + 1)) & 1) == 0 && ((w >> (place + 1)) & 1) == 0) {
            if (((b >> place) & 1) != 0)
              surround_arr[0][idx]++;
            else if (((w >> place) & 1) != 0)
              surround_arr[1][idx]++;
          }
        }
      }

      for (int place = 0; place < hw; place++) {
        move_arr[0][idx][place][0] = move_line_half(b, w, place, 0);
        move_arr[0][idx][place][1] = move_line_half(b, w, place, 1);
        legal_arr[0][idx][place] =
          (move_arr[0][idx][place][0] != 0 || move_arr[0][idx][place][1] != 0);

        move_arr[1][idx][place][0] = move_line_half(w, b, place, 0);
        move_arr[1][idx][place][1] = move_line_half(w, b, place, 1);
        legal_arr[1][idx][place] =
          (move_arr[1][idx][place][0] != 0 || move_arr[1][idx][place][1] != 0);

        if (legal_arr[0][idx][place]) canput_arr[0][idx]++;
        if (legal_arr[1][idx][place]) canput_arr[1][idx]++;
      }

      for (int place = 0; place < hw; place++) {
        flip_arr[0][idx][place] = idx;
        flip_arr[1][idx][place] = idx;
        put_arr[0][idx][place] = idx;
        put_arr[1][idx][place] = idx;

        if ((b & (1 << (hw_m1 - place))) != 0)
          flip_arr[1][idx][place] += pow3[hw_m1 - place];
        else if ((w & (1 << (hw_m1 - place))) != 0)
          flip_arr[0][idx][place] -= pow3[hw_m1 - place];
        else {
          put_arr[0][idx][place] -= pow3[hw_m1 - place] * 2;
          put_arr[1][idx][place] -= pow3[hw_m1 - place];
        }
      }
    }
  }

  static void init_local_place() {
    for (int idx = 0; idx < b_idx_num; idx++) {
      for (int place = 0; place < hw2; place++) {
        local_place[idx][place] = -1;
        for (int l_place = 0; l_place < hw; l_place++) {
          if (global_place[idx][l_place] == place) {
            local_place[idx][place] = l_place;
          }
        }
      }
    }
  }

  static void init_included() {
    for (int place = 0; place < hw2; place++) {
      int inc_idx = 0;
      for (int idx = 0; idx < b_idx_num; idx++) {
        for (int l_place = 0; l_place < hw; l_place++) {
          if (global_place[idx][l_place] == place) {
            place_included[place][inc_idx++] = idx;
          }
        }
      }
      if (inc_idx == 3) {
        place_included[place][inc_idx] = -1;
      }
    }
  }

  static void init_pop_digit() {
    for (int i = 0; i < n_line; i++) {
      for (int j = 0; j < hw; j++) {
        pop_digit[i][j] = (i / pow3[hw_m1 - j]) % 3;
      }
    }
  }

  static void init_mod3() {
    for (int i = 0; i < n_line; i++) {
      for (int j = 0; j < hw; j++) {
        mod3[i][j] = i % pow3[j];
      }
    }
  }

  static void init_pop_mid() {
    for (int i = 0; i < n_line; i++) {
      for (int j = 0; j < hw; j++) {
        for (int k = 0; k < hw; k++) {
          pop_mid[i][j][k] = (i - (i / pow3[j]) * pow3[j]) / pow3[k];
        }
      }
    }
  }

  static void init_mpc() {
    for (int i = 0; i < 6; i++) {
      for (int j = 0; j < mpc_max_depth - mpc_min_depth + 1; j++) {
        mpctsd[i][mpc_min_depth + j] = (int) (mpct[i] * mpcsd[i][j]);
      }
    }
    for (int i = 0; i < mpc_max_depth_final - mpc_min_depth_final + 1; i++) {
      mpctsd_final[mpc_min_depth_final + i] = (int) (mpct_final * mpcsd_final[i]);
    }
  }

  static void flip(Board b, Board res, int g_place) {
    res.b[place_included[g_place][0]] =
      flip_arr[b.p][res.b[place_included[g_place][0]]]
              [local_place[place_included[g_place][0]][g_place]];

    res.b[place_included[g_place][1]] =
      flip_arr[b.p][res.b[place_included[g_place][1]]]
              [local_place[place_included[g_place][1]][g_place]];

    res.b[place_included[g_place][2]] =
      flip_arr[b.p][res.b[place_included[g_place][2]]]
              [local_place[place_included[g_place][2]][g_place]];

    if (place_included[g_place][3] != -1) {
      res.b[place_included[g_place][3]] =
        flip_arr[b.p][res.b[place_included[g_place][3]]]
                [local_place[place_included[g_place][3]][g_place]];
    }
  }

  static void move_p(Board b, Board res, int g_place, int i) {
    int place = local_place[place_included[g_place][i]][g_place];
    for (int j = 1; j <= move_arr[b.p][b.b[place_included[g_place][i]]][place][0]; j++) {
      flip(b, res, g_place - move_offset[place_included[g_place][i]] * j);
    }
    for (int j = 1; j <= move_arr[b.p][b.b[place_included[g_place][i]]][place][1]; j++) {
      flip(b, res, g_place + move_offset[place_included[g_place][i]] * j);
    }
  }

  static Board move(Board b, int g_place) {
    Board res = new Board();
    for (int i = 0; i < b_idx_num; i++) res.b[i] = b.b[i];

    for (int i = 0; i < 3; i++) move_p(b, res, g_place, i);
    if (place_included[g_place][3] != -1) {
      move_p(b, res, g_place, 3);
    }

    for (int i = 0; i < 3; i++) {
      int idx = place_included[g_place][i];
      res.b[idx] = put_arr[b.p][res.b[idx]][local_place[idx][g_place]];
    }
    if (place_included[g_place][3] != -1) {
      int idx = place_included[g_place][3];
      res.b[idx] = put_arr[b.p][res.b[idx]][local_place[idx][g_place]];
    }

    res.p = 1 - b.p;
    res.n = b.n + 1;
    res.policy = g_place;
    return res;
  }

  static void book_hash_table_init(BookNode[] hash_table) {
    for (int i = 0; i < book_hash_table_size; i++) {
      hash_table[i] = null;
    }
  }

  static BookNode book_node_init(int[] key, int policy) {
    BookNode p_node = new BookNode();
    for (int i = 0; i < 4; i++) {
      p_node.k[i] = key[i * 2] + key[i * 2 + 1] * n_line;
    }
    p_node.policies[0] = policy;
    p_node.size = 1;
    p_node.p_n_node = null;
    return p_node;
  }

  static void register_book(BookNode[] hash_table, int[] key, int hash, int policy) {
    if (hash_table[hash] == null) {
      hash_table[hash] = book_node_init(key, policy);
    } else {
      BookNode p_node = hash_table[hash];
      BookNode p_pre_node = p_node;

      while (p_node != null) {
        if (compare_key(key, p_node.k)) {
          p_node.policies[p_node.size++] = policy;
          return;
        }
        p_pre_node = p_node;
        p_node = p_node.p_n_node;
      }
      p_pre_node.p_n_node = book_node_init(key, policy);
    }
  }

  static int get_book(int[] key) {
    BookNode p_node = book[(int) (calc_hash(key) & book_hash_mask)];
    while (p_node != null) {
      if (compare_key(key, p_node.k)) {
        return p_node.policies[myrandrange(0, p_node.size)];
      }
      p_node = p_node.p_n_node;
    }
    return -1;
  }

  static void init_book() {
    Map<Character, Integer> char_keys = new HashMap<>();
    final String book_chars = "!#$&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]^_`abc";
    for (int i = 0; i < hw2; i++) {
      char_keys.put(book_chars.charAt(i), i);
    }

    File file = new File("resources/book.txt");
    if (!file.exists()) {
      System.err.println("book file not exist");
      System.exit(1);
    }

    String param_compressed1 = "";
    try (BufferedReader br = new BufferedReader(new FileReader(file))) {
      param_compressed1 = br.readLine();
    } catch (IOException e) {
      e.printStackTrace();
      System.exit(1);
    }

    int ln = param_compressed1.length();
    int data_idx = 0;
    int n_book = 0;
    int[] tmp = new int[16];

    int[] first_board = {
      6560, 6560, 6560, 6425, 6326, 6560, 6560, 6560,
      6560, 6560, 6560, 6425, 6344, 6506, 6560, 6560,
      6560, 6560, 6560, 6560, 6344, 6425, 6398, 6560,
      6560, 6560, 6560, 6560, 6560, 6560, 6560, 6479,
      6344, 6398, 6074, 6560, 6560, 6560
    };

    book_hash_table_init(book);

    while (data_idx < ln) {
      Board fb = new Board();
      fb.p = 1;
      for (int i = 0; i < b_idx_num; i++) fb.b[i] = first_board[i];

      while (true) {
        if (param_compressed1.charAt(data_idx) == ' ') {
          data_idx++;
          break;
        }
        int coord = char_keys.get(param_compressed1.charAt(data_idx++));
        fb = move(fb, coord);
      }

      int coord = char_keys.get(param_compressed1.charAt(data_idx++));
      int y = coord / hw;
      int x = coord % hw;

      register_book(book, fb.b, (int) (calc_hash(fb.b) & book_hash_mask), y * hw + x);

      for (int i = 0; i < 8; i++) {
        int tmpSwap = fb.b[i];
        fb.b[i] = fb.b[8 + i];
        fb.b[8 + i] = tmpSwap;
      }

      register_book(book, fb.b, (int) (calc_hash(fb.b) & book_hash_mask), x * hw + y);

      for (int i = 0; i < 16; i++) tmp[i] = fb.b[i];
      for (int i = 0; i < 8; i++) fb.b[i] = reverse_board[tmp[7 - i]];
      for (int i = 0; i < 8; i++) fb.b[8 + i] = reverse_board[tmp[15 - i]];

      register_book(book, fb.b, (int) (calc_hash(fb.b) & book_hash_mask), (hw_m1 - x) * hw + (hw_m1 - y));

      for (int i = 0; i < 8; i++) {
        int tmpSwap = fb.b[i];
        fb.b[i] = fb.b[8 + i];
        fb.b[8 + i] = tmpSwap;
      }

      register_book(book, fb.b, (int) (calc_hash(fb.b) & book_hash_mask), (hw_m1 - y) * hw + (hw_m1 - x));

      n_book += 4;
    }

    System.err.println(n_book + " boards in book");
  }

  static double leaky_relu(double x) {
    return Math.max(0.01 * x, x);
  }

  static double predict(
    int pattern_size,
    double[] in_arr,
    double[][] dense0,
    double[] bias0,
    double[][] dense1,
    double[] bias1,
    double[] dense2,
    double bias2
  ) {
    double[] hidden0 = new double[n_dense0];
    for (int i = 0; i < n_dense0; i++) {
      hidden0[i] = bias0[i];
      for (int j = 0; j < pattern_size * 2; j++) {
        hidden0[i] += in_arr[j] * dense0[i][j];
      }
      hidden0[i] = leaky_relu(hidden0[i]);
    }

    double res = bias2;
    for (int i = 0; i < n_dense1; i++) {
      double hidden1 = bias1[i];
      for (int j = 0; j < n_dense0; j++) {
        hidden1 += hidden0[j] * dense1[i][j];
      }
      hidden1 = leaky_relu(hidden1);
      res += hidden1 * dense2[i];
    }

    res = leaky_relu(res);
    return res;
  }

  static int calc_pop(int a, int b, int s) {
    return (a / pow3[s - 1 - b]) % 3;
  }

  static int calc_rev_idx(int pattern_idx, int pattern_size, int idx) {
    int res = 0;
    if (pattern_idx <= 7) {
      for (int i = 0; i < pattern_size; i++) {
        res += pow3[i] * calc_pop(idx, i, pattern_size);
      }
    } else if (pattern_idx == 8) {
      res += p39 * calc_pop(idx, 0, pattern_size);
      res += p38 * calc_pop(idx, 4, pattern_size);
      res += p37 * calc_pop(idx, 7, pattern_size);
      res += p36 * calc_pop(idx, 9, pattern_size);
      res += p35 * calc_pop(idx, 1, pattern_size);
      res += p34 * calc_pop(idx, 5, pattern_size);
      res += p33 * calc_pop(idx, 8, pattern_size);
      res += p32 * calc_pop(idx, 2, pattern_size);
      res += p31 * calc_pop(idx, 6, pattern_size);
      res += calc_pop(idx, 3, pattern_size);
    } else if (pattern_idx == 9) {
      res += p39 * calc_pop(idx, 5, pattern_size);
      res += p38 * calc_pop(idx, 4, pattern_size);
      res += p37 * calc_pop(idx, 3, pattern_size);
      res += p36 * calc_pop(idx, 2, pattern_size);
      res += p35 * calc_pop(idx, 1, pattern_size);
      res += p34 * calc_pop(idx, 0, pattern_size);
      res += p33 * calc_pop(idx, 9, pattern_size);
      res += p32 * calc_pop(idx, 8, pattern_size);
      res += p31 * calc_pop(idx, 7, pattern_size);
      res += calc_pop(idx, 6, pattern_size);
    } else if (pattern_idx == 10) {
      res += p39 * calc_pop(idx, 0, pattern_size);
      res += p38 * calc_pop(idx, 1, pattern_size);
      res += p37 * calc_pop(idx, 2, pattern_size);
      res += p36 * calc_pop(idx, 3, pattern_size);
      res += p35 * calc_pop(idx, 7, pattern_size);
      res += p34 * calc_pop(idx, 8, pattern_size);
      res += p33 * calc_pop(idx, 9, pattern_size);
      res += p32 * calc_pop(idx, 4, pattern_size);
      res += p31 * calc_pop(idx, 5, pattern_size);
      res += calc_pop(idx, 6, pattern_size);
    }
    return res;
  }

  static void pre_evaluation(
    int pattern_idx,
    int phase_idx,
    int evaluate_idx,
    int pattern_size,
    double[][] dense0,
    double[] bias0,
    double[][] dense1,
    double[] bias1,
    double[] dense2,
    double bias2
  ) {
    double[] arr = new double[20];
    double[] tmp_pattern_arr = new double[max_evaluate_idx];

    for (int idx = 0; idx < pow3[pattern_size]; idx++) {
      for (int i = 0; i < pattern_size; i++) {
        int digit = (idx / pow3[pattern_size - 1 - i]) % 3;
        if (digit == 0) {
          arr[i] = 1.0;
          arr[pattern_size + i] = 0.0;
        } else if (digit == 1) {
          arr[i] = 0.0;
          arr[pattern_size + i] = 1.0;
        } else {
          arr[i] = 0.0;
          arr[pattern_size + i] = 0.0;
        }
      }
      pattern_arr[phase_idx][evaluate_idx][idx] =
        predict(pattern_size, arr, dense0, bias0, dense1, bias1, dense2, bias2);
      tmp_pattern_arr[calc_rev_idx(pattern_idx, pattern_size, idx)] =
        pattern_arr[phase_idx][evaluate_idx][idx];
    }
    for (int idx = 0; idx < pow3[pattern_size]; idx++) {
      pattern_arr[phase_idx][evaluate_idx][idx] += tmp_pattern_arr[idx];
    }
  }

  static void predict_add(
    int canput,
    int sur0,
    int sur1,
    double[][] dense0,
    double[] bias0,
    double[][] dense1,
    double[] bias1,
    double[] res
  ) {
    double[] hidden0 = new double[n_add_dense0];
    double[] in_arr = new double[n_add_input];

    in_arr[0] = (double) canput / 30.0;
    in_arr[1] = ((double) sur0 - 15.0) / 15.0;
    in_arr[2] = ((double) sur1 - 15.0) / 15.0;

    for (int i = 0; i < n_add_dense0; i++) {
      hidden0[i] = bias0[i];
      for (int j = 0; j < n_add_input; j++) {
        hidden0[i] += in_arr[j] * dense0[i][j];
      }
      hidden0[i] = leaky_relu(hidden0[i]);
    }

    for (int i = 0; i < n_add_dense1; i++) {
      res[i] = bias1[i];
      for (int j = 0; j < n_add_dense0; j++) {
        res[i] += hidden0[j] * dense1[i][j];
      }
      res[i] = leaky_relu(res[i]);
    }
  }

  static void pre_evaluation_add(
    int phase_idx,
    double[][] dense0,
    double[] bias0,
    double[][] dense1,
    double[] bias1
  ) {
    for (int canput = -max_canput; canput <= max_canput; canput++) {
      for (int sur0 = 0; sur0 <= max_surround; sur0++) {
        for (int sur1 = 0; sur1 <= max_surround; sur1++) {
          predict_add(
            canput, sur0, sur1,
            dense0, bias0, dense1, bias1,
            add_arr[phase_idx][canput + max_canput][sur0][sur1]
          );
        }
      }
    }
  }

  static void init_evaluation() {
    File file = new File("resources/param.txt");
    if (!file.exists()) {
      System.err.println("evaluation file not exist");
      System.exit(1);
    }

    final int[] pattern_sizes = {8, 8, 8, 5, 6, 7, 8, 10, 10, 10, 10};

    try (BufferedReader br = new BufferedReader(new FileReader(file))) {
      String line;

      double[][] dense0 = new double[n_dense0][20];
      double[] bias0 = new double[n_dense0];
      double[][] dense1 = new double[n_dense1][n_dense0];
      double[] bias1 = new double[n_dense1];
      double[] dense2 = new double[n_dense1];
      double bias2;

      double[][] add_dense0 = new double[n_add_dense0][n_add_input];
      double[] add_bias0 = new double[n_add_dense0];
      double[][] add_dense1 = new double[n_add_dense1][n_add_dense0];
      double[] add_bias1 = new double[n_add_dense1];

      for (int phase_idx = 0; phase_idx < n_phases; phase_idx++) {
        for (int pattern_idx = 0; pattern_idx < n_patterns; pattern_idx++) {
          int ps = pattern_sizes[pattern_idx];

          // dense0: file is input-major -> store as [unit][input]
          for (int i = 0; i < ps * 2; i++) {
            for (int j = 0; j < n_dense0; j++) {
              line = br.readLine();
              dense0[j][i] = Double.parseDouble(line);
            }
          }
          // bias0
          for (int i = 0; i < n_dense0; i++) {
            line = br.readLine();
            bias0[i] = Double.parseDouble(line);
          }
          // dense1: file is previous-layer-major -> store as [unit][prev]
          for (int i = 0; i < n_dense0; i++) {
            for (int j = 0; j < n_dense1; j++) {
              line = br.readLine();
              dense1[j][i] = Double.parseDouble(line);
            }
          }
          // bias1
          for (int i = 0; i < n_dense1; i++) {
            line = br.readLine();
            bias1[i] = Double.parseDouble(line);
          }
          // dense2
          for (int i = 0; i < n_dense1; i++) {
            line = br.readLine();
            dense2[i] = Double.parseDouble(line);
          }
          // bias2
          line = br.readLine();
          bias2 = Double.parseDouble(line);

          pre_evaluation(pattern_idx, phase_idx, pattern_idx, ps, dense0, bias0, dense1, bias1, dense2, bias2);
        }

        // add_dense0: input-major
        for (int i = 0; i < n_add_input; i++) {
          for (int j = 0; j < n_add_dense0; j++) {
            line = br.readLine();
            add_dense0[j][i] = Double.parseDouble(line);
          }
        }
        // add_bias0
        for (int i = 0; i < n_add_dense0; i++) {
          line = br.readLine();
          add_bias0[i] = Double.parseDouble(line);
        }
        // add_dense1: previous-layer-major
        for (int i = 0; i < n_add_dense0; i++) {
          for (int j = 0; j < n_add_dense1; j++) {
            line = br.readLine();
            add_dense1[j][i] = Double.parseDouble(line);
          }
        }
        // add_bias1
        for (int i = 0; i < n_add_dense1; i++) {
          line = br.readLine();
          add_bias1[i] = Double.parseDouble(line);
        }

        pre_evaluation_add(phase_idx, add_dense0, add_bias0, add_dense1, add_bias1);

        // all_dense
        for (int i = 0; i < n_all_input; i++) {
          line = br.readLine();
          all_dense[phase_idx][i] = Double.parseDouble(line);
        }
        // all_bias
        line = br.readLine();
        all_bias[phase_idx] = Double.parseDouble(line);
      }
    } catch (IOException e) {
      e.printStackTrace();
      System.exit(1);
    }
  }

  static int search_generation = 0;
  static final int[][] search_table_generation = new int[2][search_hash_table_size];

  static void search_hash_table_init(int table_idx) {
      for (int i = 0; i < search_hash_table_size; i++) {
          SearchNode node = search_replace_table[table_idx][i];
          if (node == null) {
              node = new SearchNode();
              search_replace_table[table_idx][i] = node;
          }
          node.reg = false;
      }
  }


  static void register_search(int table_idx, int[] key, int hash, int l, int u) {
      // ロックフリーな実装に変更
      SearchNode node = search_replace_table[table_idx][hash];
      if (node == null) {
          SearchNode newNode = new SearchNode();
          newNode.reg = true;
          newNode.generation = search_generation;
          for (int i = 0; i < 4; i++) {
              newNode.k[i] = key[i * 2] + key[i * 2 + 1] * n_line;
          }
          newNode.l = l;
          newNode.u = u;
          search_replace_table[table_idx][hash] = newNode;
      } else {
          // 既存ノードを上書き (競合状態を許容)
          node.reg = true;
          node.generation = search_generation;
          for (int i = 0; i < 4; i++) {
              node.k[i] = key[i * 2] + key[i * 2 + 1] * n_line;
          }
          node.l = l;
          node.u = u;
      }
  }

  static void get_search(int[] key, int hash, int table_idx, int[] l, int[] u) {
      SearchNode node = search_replace_table[table_idx][hash];
      if (node != null && node.reg && node.generation == search_generation) {
          if (compare_key(key, node.k)) {
              l[0] = node.l;
              u[0] = node.u;
              hash_get++;
              return;
          }
      }
      l[0] = -inf;
      u[0] = -inf;
  }

  static int calc_canput_exact(Board b) {
    int res = 0;
    for (int global_place : vacant_lst) {
      boolean legal =
        legal_arr[b.p][b.b[place_included[global_place][0]]]
                  [local_place[place_included[global_place][0]][global_place]]
        || legal_arr[b.p][b.b[place_included[global_place][1]]]
                      [local_place[place_included[global_place][1]][global_place]]
        || legal_arr[b.p][b.b[place_included[global_place][2]]]
                      [local_place[place_included[global_place][2]][global_place]];

      if (place_included[global_place][3] != -1) {
        legal |= legal_arr[b.p][b.b[place_included[global_place][3]]]
                          [local_place[place_included[global_place][3]][global_place]];
      }
      if (legal) res++;
    }
    return res;
  }

  static int sfill5(int b) {
    return pop_digit[b][2] != 2 ? b - p35 + 1 : b;
  }

  static int sfill4(int b) {
    return pop_digit[b][3] != 2 ? b - p34 + 1 : b;
  }

  static int sfill3(int b) {
    return pop_digit[b][4] != 2 ? b - p33 + 1 : b;
  }

  static int sfill2(int b) {
    return pop_digit[b][5] != 2 ? b - p32 + 1 : b;
  }

  static int sfill1(int b) {
    return pop_digit[b][6] != 2 ? b - p31 + 1 : b;
  }

  static int calc_canput(Board b) {
    return (b.p != 0 ? -1 : 1) * (
      canput_arr[b.p][b.b[0]] + canput_arr[b.p][b.b[1]] + canput_arr[b.p][b.b[2]] + canput_arr[b.p][b.b[3]] +
      canput_arr[b.p][b.b[4]] + canput_arr[b.p][b.b[5]] + canput_arr[b.p][b.b[6]] + canput_arr[b.p][b.b[7]] +
      canput_arr[b.p][b.b[8]] + canput_arr[b.p][b.b[9]] + canput_arr[b.p][b.b[10]] + canput_arr[b.p][b.b[11]] +
      canput_arr[b.p][b.b[12]] + canput_arr[b.p][b.b[13]] + canput_arr[b.p][b.b[14]] + canput_arr[b.p][b.b[15]] +
      canput_arr[b.p][b.b[16] - p35 + 1] + canput_arr[b.p][b.b[26] - p35 + 1] + canput_arr[b.p][b.b[27] - p35 + 1] + canput_arr[b.p][b.b[37] - p35 + 1] +
      canput_arr[b.p][b.b[17] - p34 + 1] + canput_arr[b.p][b.b[25] - p34 + 1] + canput_arr[b.p][b.b[28] - p34 + 1] + canput_arr[b.p][b.b[36] - p34 + 1] +
      canput_arr[b.p][b.b[18] - p33 + 1] + canput_arr[b.p][b.b[24] - p33 + 1] + canput_arr[b.p][b.b[29] - p33 + 1] + canput_arr[b.p][b.b[35] - p33 + 1] +
      canput_arr[b.p][b.b[19] - p32 + 1] + canput_arr[b.p][b.b[23] - p32 + 1] + canput_arr[b.p][b.b[30] - p32 + 1] + canput_arr[b.p][b.b[34] - p32 + 1] +
      canput_arr[b.p][b.b[20] - p31 + 1] + canput_arr[b.p][b.b[22] - p31 + 1] + canput_arr[b.p][b.b[31] - p31 + 1] + canput_arr[b.p][b.b[33] - p31 + 1] +
      canput_arr[b.p][b.b[21]] + canput_arr[b.p][b.b[32]]
    );
  }

  static int calc_surround(Board b, int p) {
    return surround_arr[p][b.b[0]] + surround_arr[p][b.b[1]] + surround_arr[p][b.b[2]] + surround_arr[p][b.b[3]] +
          surround_arr[p][b.b[4]] + surround_arr[p][b.b[5]] + surround_arr[p][b.b[6]] + surround_arr[p][b.b[7]] +
          surround_arr[p][b.b[8]] + surround_arr[p][b.b[9]] + surround_arr[p][b.b[10]] + surround_arr[p][b.b[11]] +
          surround_arr[p][b.b[12]] + surround_arr[p][b.b[13]] + surround_arr[p][b.b[14]] + surround_arr[p][b.b[15]] +
          surround_arr[p][sfill5(b.b[16])] + surround_arr[p][sfill5(b.b[26])] + surround_arr[p][sfill5(b.b[27])] + surround_arr[p][sfill5(b.b[37])] +
          surround_arr[p][sfill4(b.b[17])] + surround_arr[p][sfill4(b.b[25])] + surround_arr[p][sfill4(b.b[28])] + surround_arr[p][sfill4(b.b[36])] +
          surround_arr[p][sfill3(b.b[18])] + surround_arr[p][sfill3(b.b[24])] + surround_arr[p][sfill3(b.b[29])] + surround_arr[p][sfill3(b.b[35])] +
          surround_arr[p][sfill2(b.b[19])] + surround_arr[p][sfill2(b.b[23])] + surround_arr[p][sfill2(b.b[30])] + surround_arr[p][sfill2(b.b[34])] +
          surround_arr[p][sfill1(b.b[20])] + surround_arr[p][sfill1(b.b[22])] + surround_arr[p][sfill1(b.b[31])] + surround_arr[p][sfill1(b.b[33])] +
          surround_arr[p][b.b[21]] + surround_arr[p][b.b[32]];
  }

  static int calc_phase_idx(Board b) {
    return Math.max(0, Math.min(3, (b.n - 4) / 10 - 2));
  }

  static double edge_2x(int phase_idx, int[] b, int x, int y) {
    return pattern_arr[phase_idx][7]
      [pop_digit[b[x]][1] * p39 + b[y] * p31 + pop_digit[b[x]][6]];
  }

  static double triangle0(int phase_idx, int[] b, int w, int x, int y, int z) {
    return pattern_arr[phase_idx][8]
      [b[w] / p34 * p36 + b[x] / p35 * p33 + b[y] / p36 * p31 + b[z] / p37];
  }

  static double triangle1(int phase_idx, int[] b, int w, int x, int y, int z) {
    return pattern_arr[phase_idx][8]
      [reverse_board[b[w]] / p34 * p36 + reverse_board[b[x]] / p35 * p33 +
      reverse_board[b[y]] / p36 * p31 + reverse_board[b[z]] / p37];
  }

  static double edge_block(int phase_idx, int[] b, int x, int y) {
    return pattern_arr[phase_idx][9]
      [pop_digit[b[x]][0] * p39 +
      pop_mid[b[x]][6][2] * p35 +
      pop_digit[b[x]][7] * p34 +
      pop_mid[b[y]][6][2]];
  }

  static double cross(int phase_idx, int[] b, int x, int y, int z) {
    return pattern_arr[phase_idx][10]
            [b[x] / p34 * p36 + b[y] / p35 * p33 + b[z] / p35]
        + pattern_arr[phase_idx][10]
            [reverse_board[b[x]] / p34 * p36
              + pop_mid[reverse_board[b[y]]][7][4] * p33
              + pop_mid[reverse_board[b[z]]][7][4]];
  }

  static double calc_pattern(int phase_idx, Board b) {
    return all_dense[phase_idx][0] * (pattern_arr[phase_idx][0][b.b[1]] + pattern_arr[phase_idx][0][b.b[6]] +
                                      pattern_arr[phase_idx][0][b.b[9]] + pattern_arr[phase_idx][0][b.b[14]]) +
          all_dense[phase_idx][1] * (pattern_arr[phase_idx][1][b.b[2]] + pattern_arr[phase_idx][1][b.b[5]] +
                                      pattern_arr[phase_idx][1][b.b[10]] + pattern_arr[phase_idx][1][b.b[13]]) +
          all_dense[phase_idx][2] * (pattern_arr[phase_idx][2][b.b[3]] + pattern_arr[phase_idx][2][b.b[4]] +
                                      pattern_arr[phase_idx][2][b.b[11]] + pattern_arr[phase_idx][2][b.b[12]]) +
          all_dense[phase_idx][3] * (pattern_arr[phase_idx][3][b.b[18] / p33] + pattern_arr[phase_idx][3][b.b[24] / p33] +
                                      pattern_arr[phase_idx][3][b.b[29] / p33] + pattern_arr[phase_idx][3][b.b[35] / p33]) +
          all_dense[phase_idx][4] * (pattern_arr[phase_idx][4][b.b[19] / p32] + pattern_arr[phase_idx][4][b.b[23] / p32] +
                                      pattern_arr[phase_idx][4][b.b[30] / p32] + pattern_arr[phase_idx][4][b.b[34] / p32]) +
          all_dense[phase_idx][5] * (pattern_arr[phase_idx][5][b.b[20] / p31] + pattern_arr[phase_idx][5][b.b[22] / p31] +
                                      pattern_arr[phase_idx][5][b.b[31] / p31] + pattern_arr[phase_idx][5][b.b[33] / p31]) +
          all_dense[phase_idx][6] * (pattern_arr[phase_idx][6][b.b[21]] + pattern_arr[phase_idx][6][b.b[32]]) +
          all_dense[phase_idx][7] * (edge_2x(phase_idx, b.b, 1, 0) + edge_2x(phase_idx, b.b, 6, 7) +
                                      edge_2x(phase_idx, b.b, 9, 8) + edge_2x(phase_idx, b.b, 14, 15)) +
          all_dense[phase_idx][8] * (triangle0(phase_idx, b.b, 0, 1, 2, 3) + triangle0(phase_idx, b.b, 7, 6, 5, 4) +
                                      triangle0(phase_idx, b.b, 15, 14, 13, 12) + triangle1(phase_idx, b.b, 15, 14, 13, 12)) +
          all_dense[phase_idx][9] * (edge_block(phase_idx, b.b, 0, 1) + edge_block(phase_idx, b.b, 7, 6) +
                                      edge_block(phase_idx, b.b, 8, 9) + edge_block(phase_idx, b.b, 15, 14)) +
          all_dense[phase_idx][10] * (cross(phase_idx, b.b, 21, 20, 22) + cross(phase_idx, b.b, 32, 31, 33));
  }

  // 頻繁に計算される値をキャッシュ
  static final class BoardCache {
      int canput = Integer.MIN_VALUE;
      int sur0 = -1;
      int sur1 = -1;
      double pattern = Double.NaN;
  }

  static final Map<Long, BoardCache> evalCache = new ConcurrentHashMap<>(10000);

  static int evaluate(Board b) {
      int phase_idx = calc_phase_idx(b);
      int canput = Math.min(max_canput * 2, Math.max(0, max_canput + calc_canput(b)));
      int sur0 = Math.min(max_surround, calc_surround(b, 0));
      int sur1 = Math.min(max_surround, calc_surround(b, 1));
      
      double[] add_values = add_arr[phase_idx][canput][sur0][sur1];
      
      double res = all_bias[phase_idx] + calc_pattern(phase_idx, b)
          + all_dense[phase_idx][11] * add_values[0]
          + all_dense[phase_idx][12] * add_values[1]
          + all_dense[phase_idx][13] * add_values[2]
          + all_dense[phase_idx][14] * add_values[3]
          + all_dense[phase_idx][15] * add_values[4]
          + all_dense[phase_idx][16] * add_values[5]
          + all_dense[phase_idx][17] * add_values[6]
          + all_dense[phase_idx][18] * add_values[7];

      if (b.p != 0) res = -res;
      res = Math.max(-1.0, Math.min(1.0, res));
      return (int) (res * sc_w);
  }

  static int end_game(Board b) {
    int count = (b.p != 0 ? -1 : 1) *
        (count_arr[b.b[0]] + count_arr[b.b[1]] + count_arr[b.b[2]] + count_arr[b.b[3]] +
        count_arr[b.b[4]] + count_arr[b.b[5]] + count_arr[b.b[6]] + count_arr[b.b[7]]);

    int vacant = hw2
        - count_all_arr[b.b[0]] - count_all_arr[b.b[1]] - count_all_arr[b.b[2]] - count_all_arr[b.b[3]]
        - count_all_arr[b.b[4]] - count_all_arr[b.b[5]] - count_all_arr[b.b[6]] - count_all_arr[b.b[7]];

    if (count > 0) count += vacant;
    else if (count < 0) count -= vacant;

    return count * step;
  }

// filepath: [OthelloAI.java](http://_vscodecontentref_/2)
  static boolean mpc_higher(Board b, boolean skipped, int depth, int beta) {
    int phase = Math.min(5, (b.n - 4) / 10); // ★修正: 上限を5に制限
    int bound = beta + mpctsd[phase][depth];
    return nega_alpha(b, skipped, mpcd[depth], bound - epsilon, bound) >= bound;
  }

  static boolean mpc_lower(Board b, boolean skipped, int depth, int alpha) {
    int phase = Math.min(5, (b.n - 4) / 10); // ★修正: 上限を5に制限
    int bound = alpha - mpctsd[phase][depth];
    return nega_alpha(b, skipped, mpcd[depth], bound, bound + epsilon) <= bound;
  }

  static boolean mpc_higher_final(Board b, boolean skipped, int depth, int beta) {
    int bound = beta + mpctsd_final[depth];
    return nega_alpha(b, skipped, mpcd[depth], bound - epsilon, bound) >= bound;
  }

  static boolean mpc_lower_final(Board b, boolean skipped, int depth, int alpha) {
    int bound = alpha - mpctsd_final[depth];
    return nega_alpha(b, skipped, mpcd[depth], bound, bound + epsilon) <= bound;
  }

  static void move_ordering(Board b) {
    int hash = (int)(calc_hash(b.b) & search_hash_mask);
    SearchNode node = search_replace_table[f_search_table_idx][hash];
    
    if (node != null && node.reg && node.generation == search_generation && compare_key(b.b, node.k)) {
      b.v = -Math.max(node.l, node.u);
      if (node.u != -inf && node.l != -inf)
        b.v += cache_both;
      else
        b.v += cache_hit;
    } else {
      b.v = -evaluate(b);
    }
  }

  static int last1(Board b, boolean skipped, int p0) {
    searched_nodes++;
    checkTime();
    int before_score = 0;
    for (int i = 0; i < hw; i++)
      before_score += count_arr[b.b[i]];

    if (b.p != 0)
      before_score = -before_score;

    int score = before_score + 1 +
      (move_arr[b.p][b.b[place_included[p0][0]]][local_place[place_included[p0][0]][p0]][0] +
      move_arr[b.p][b.b[place_included[p0][0]]][local_place[place_included[p0][0]][p0]][1] +
      move_arr[b.p][b.b[place_included[p0][1]]][local_place[place_included[p0][1]][p0]][0] +
      move_arr[b.p][b.b[place_included[p0][1]]][local_place[place_included[p0][1]][p0]][1] +
      move_arr[b.p][b.b[place_included[p0][2]]][local_place[place_included[p0][2]][p0]][0] +
      move_arr[b.p][b.b[place_included[p0][2]]][local_place[place_included[p0][2]][p0]][1]) * 2;

    if (place_included[p0][3] != -1)
      score += (move_arr[b.p][b.b[place_included[p0][3]]][local_place[place_included[p0][3]][p0]][0] +
                move_arr[b.p][b.b[place_included[p0][3]]][local_place[place_included[p0][3]][p0]][1]) * 2;

    if (score == before_score + 1) {
      if (skipped)
        return end_game(b);

      Board rb = new Board();
      for (int i = 0; i < b_idx_num; i++)
        rb.b[i] = b.b[i];
      rb.p = 1 - b.p;
      rb.n = b.n;
      return -last1(rb, true, p0);
    }

    return score * step;
  }

  static int last2(Board b, boolean skipped, int alpha, int beta, int p0, int p1) {
    searched_nodes++;
    checkTime();
    Board nb;
    boolean passed = true;
    int v = -inf;

    boolean legal =
      legal_arr[b.p][b.b[place_included[p0][0]]][local_place[place_included[p0][0]][p0]] ||
      legal_arr[b.p][b.b[place_included[p0][1]]][local_place[place_included[p0][1]][p0]] ||
      legal_arr[b.p][b.b[place_included[p0][2]]][local_place[place_included[p0][2]][p0]];
    if (place_included[p0][3] != -1)
      legal |= legal_arr[b.p][b.b[place_included[p0][3]]][local_place[place_included[p0][3]][p0]];

    if (legal) {
      passed = false;
      nb = move(b, p0);
      int g = -last1(nb, false, p1);
      alpha = Math.max(alpha, g);
      if (beta <= alpha) return alpha;
      v = Math.max(v, g);
    }

    legal =
      legal_arr[b.p][b.b[place_included[p1][0]]][local_place[place_included[p1][0]][p1]] ||
      legal_arr[b.p][b.b[place_included[p1][1]]][local_place[place_included[p1][1]][p1]] ||
      legal_arr[b.p][b.b[place_included[p1][2]]][local_place[place_included[p1][2]][p1]];
    if (place_included[p1][3] != -1)
      legal |= legal_arr[b.p][b.b[place_included[p1][3]]][local_place[place_included[p1][3]][p1]];

    if (legal) {
      passed = false;
      nb = move(b, p1);
      int g = -last1(nb, false, p0);
      alpha = Math.max(alpha, g);
      if (beta <= alpha) return alpha;
      v = Math.max(v, g);
    }

    if (passed) {
      if (skipped) return end_game(b);
      Board rb = new Board();
      for (int i = 0; i < b_idx_num; i++) rb.b[i] = b.b[i];
      rb.p = 1 - b.p;
      rb.n = b.n;
      return -last2(rb, true, -beta, -alpha, p0, p1);
    }
    return v;
  }

  static int last3(Board b, boolean skipped, int alpha, int beta, int p0, int p1, int p2) {
    searched_nodes++;
    checkTime();
    Board nb;
    boolean passed = true;
    int v = -inf;

    boolean legal =
      legal_arr[b.p][b.b[place_included[p0][0]]][local_place[place_included[p0][0]][p0]] ||
      legal_arr[b.p][b.b[place_included[p0][1]]][local_place[place_included[p0][1]][p0]] ||
      legal_arr[b.p][b.b[place_included[p0][2]]][local_place[place_included[p0][2]][p0]];
    if (place_included[p0][3] != -1)
      legal |= legal_arr[b.p][b.b[place_included[p0][3]]][local_place[place_included[p0][3]][p0]];
    if (legal) {
      passed = false;
      nb = move(b, p0);
      int g = -last2(nb, false, -beta, -alpha, p1, p2);
      alpha = Math.max(alpha, g);
      if (beta <= alpha) return alpha;
      v = Math.max(v, g);
    }

    legal =
      legal_arr[b.p][b.b[place_included[p1][0]]][local_place[place_included[p1][0]][p1]] ||
      legal_arr[b.p][b.b[place_included[p1][1]]][local_place[place_included[p1][1]][p1]] ||
      legal_arr[b.p][b.b[place_included[p1][2]]][local_place[place_included[p1][2]][p1]];
    if (place_included[p1][3] != -1)
      legal |= legal_arr[b.p][b.b[place_included[p1][3]]][local_place[place_included[p1][3]][p1]];
    if (legal) {
      passed = false;
      nb = move(b, p1);
      int g = -last2(nb, false, -beta, -alpha, p0, p2);
      alpha = Math.max(alpha, g);
      if (beta <= alpha) return alpha;
      v = Math.max(v, g);
    }

    legal =
      legal_arr[b.p][b.b[place_included[p2][0]]][local_place[place_included[p2][0]][p2]] ||
      legal_arr[b.p][b.b[place_included[p2][1]]][local_place[place_included[p2][1]][p2]] ||
      legal_arr[b.p][b.b[place_included[p2][2]]][local_place[place_included[p2][2]][p2]];
    if (place_included[p2][3] != -1)
      legal |= legal_arr[b.p][b.b[place_included[p2][3]]][local_place[place_included[p2][3]][p2]];
    if (legal) {
      passed = false;
      nb = move(b, p2);
      int g = -last2(nb, false, -beta, -alpha, p0, p1);
      alpha = Math.max(alpha, g);
      if (beta <= alpha) return alpha;
      v = Math.max(v, g);
    }

    if (passed) {
      if (skipped) return end_game(b);
      Board rb = new Board();
      for (int i = 0; i < b_idx_num; i++) rb.b[i] = b.b[i];
      rb.p = 1 - b.p;
      rb.n = b.n;
      return -last3(rb, true, -beta, -alpha, p0, p1, p2);
    }
    return v;
  }

  static void pickVacant(Board b, int[] cells) {
    int idx = 0;
    for (int cell : vacant_lst) {
      if (pop_digit[b.b[cell / hw]][cell % hw] == 2)
        cells[idx++] = cell;
    }
  }

  static int negaAlphaFinal(Board b, boolean skipped, int depth, int alpha, int beta) {
    searched_nodes++;
    checkTime();
    if (b.n >= hw2 - 3) {
      int[] cells = new int[3];
      pickVacant(b, cells);
      if (b.n == hw2 - 3)
        return last3(b, skipped, alpha, beta, cells[0], cells[1], cells[2]);
      if (b.n == hw2 - 2)
        return last2(b, skipped, alpha, beta, cells[0], cells[1]);
      if (b.n == hw2 - 1)
        return last1(b, skipped, cells[0]);
      return end_game(b);
    }

    Board nb = new Board();
    boolean passed = true;
    int v = -inf;

    for (int cell : vacant_lst) {
      boolean legal =
        legal_arr[b.p][b.b[place_included[cell][0]]][local_place[place_included[cell][0]][cell]] ||
        legal_arr[b.p][b.b[place_included[cell][1]]][local_place[place_included[cell][1]][cell]] ||
        legal_arr[b.p][b.b[place_included[cell][2]]][local_place[place_included[cell][2]][cell]];
      if (place_included[cell][3] != -1)
        legal |= legal_arr[b.p][b.b[place_included[cell][3]]][local_place[place_included[cell][3]][cell]];

      if (legal) {
        passed = false;
        nb = move(b, cell);
        int g = -negaAlphaFinal(nb, false, depth - 1, -beta, -alpha);
        alpha = Math.max(alpha, g);
        if (beta <= alpha)
          return alpha;
        v = Math.max(v, g);
      }
    }

    if (passed) {
      if (skipped) return end_game(b);
      for (int i = 0; i < b_idx_num; i++)
        nb.b[i] = b.b[i];
      nb.p = 1 - b.p;
      nb.n = b.n;
      return -negaAlphaFinal(nb, true, depth, -beta, -alpha);
    }
    return v;
  }

  static int negaAlphaOrderingFinal(Board b, long strt, boolean skipped, int depth, int alpha, int beta) {
    searched_nodes++;
    checkTime();
    if (mpc_min_depth_final <= depth && depth <= mpc_max_depth_final) {
      if (mpc_higher_final(b, skipped, depth, beta)) return beta + step;
      if (mpc_lower_final(b, skipped, depth, alpha)) return alpha - step;
    }
    if (depth <= 9) return negaAlphaFinal(b, skipped, depth, alpha, beta);

    List<Board> nb = new ArrayList<>();
    int canput = 0;

    for (int cell : vacant_lst) {
      boolean legal =
        legal_arr[b.p][b.b[place_included[cell][0]]][local_place[place_included[cell][0]][cell]] ||
        legal_arr[b.p][b.b[place_included[cell][1]]][local_place[place_included[cell][1]][cell]] ||
        legal_arr[b.p][b.b[place_included[cell][2]]][local_place[place_included[cell][2]][cell]];
      if (place_included[cell][3] != -1)
        legal |= legal_arr[b.p][b.b[place_included[cell][3]]][local_place[place_included[cell][3]][cell]];

      if (legal) {
        Board next = move(b, cell);
        move_ordering(next);
        next.v -= 100 * calc_canput_exact(next);
        nb.add(next);
        canput++;
      }
    }

    if (canput == 0) {
      if (skipped) return end_game(b);
      Board rb = new Board();
      for (int i = 0; i < b_idx_num; i++) rb.b[i] = b.b[i];
      rb.p = 1 - b.p;
      rb.n = b.n;
      return -negaAlphaOrderingFinal(rb, strt, true, depth, -beta, -alpha);
    }

    if (canput >= 2) Collections.sort(nb);

    int hash = (int) (calc_hash(b.b) & search_hash_mask);
    int[] l = new int[1];
    int[] u = new int[1];
    get_search(b.b, hash, 1 - f_search_table_idx, l, u);
    if (l[0] != -inf) {
      if (l[0] == u[0]) return l[0];
      alpha = Math.max(alpha, l[0]);
      if (alpha >= beta) return alpha;
    }
    if (u[0] != -inf) {
      beta = Math.min(beta, u[0]);
      if (alpha >= beta) return alpha;
    }

    int v = -inf;
    int first_alpha = alpha;
    for (Board nnb : nb) {
      int g = -negaAlphaOrderingFinal(nnb, strt, false, depth - 1, -beta, -alpha);
      alpha = Math.max(alpha, g);
      if (beta <= alpha) {
        if (l[0] < g) register_search(1 - f_search_table_idx, b.b, hash, alpha, u[0]);
        return alpha;
      }
      v = Math.max(v, g);
    }

    if (v <= first_alpha)
      register_search(1 - f_search_table_idx, b.b, hash, l[0], v);
    else
      register_search(1 - f_search_table_idx, b.b, hash, v, v);

    return v;
  }

  static int negaScoutFinal(Board b, long strt, boolean skipped, int depth, int alpha, int beta) {
    searched_nodes++;
    checkTime();
    if (depth <= 9) return negaAlphaFinal(b, skipped, depth, alpha, beta);

    int hash = (int) (calc_hash(b.b) & search_hash_mask);
    int[] l = new int[1];
    int[] u = new int[1];
    get_search(b.b, hash, 1 - f_search_table_idx, l, u);
    if (l[0] != -inf) {
      if (l[0] == u[0]) return l[0];
      alpha = Math.max(alpha, l[0]);
      if (alpha >= beta) return alpha;
    }
    if (u[0] != -inf) {
      beta = Math.min(beta, u[0]);
      if (alpha >= beta) return alpha;
    }

    List<Board> nb = new ArrayList<>();
    int canput = 0;

    for (int cell : vacant_lst) {
      boolean legal =
        legal_arr[b.p][b.b[place_included[cell][0]]][local_place[place_included[cell][0]][cell]] ||
        legal_arr[b.p][b.b[place_included[cell][1]]][local_place[place_included[cell][1]][cell]] ||
        legal_arr[b.p][b.b[place_included[cell][2]]][local_place[place_included[cell][2]][cell]];
      if (place_included[cell][3] != -1)
        legal |= legal_arr[b.p][b.b[place_included[cell][3]]][local_place[place_included[cell][3]][cell]];

      if (legal) {
        Board next = move(b, cell);
        move_ordering(next);
        next.v -= 100 * calc_canput_exact(next);
        nb.add(next);
        canput++;
      }
    }

    if (canput == 0) {
      if (skipped) return end_game(b);
      Board rb = new Board();
      for (int i = 0; i < b_idx_num; i++) rb.b[i] = b.b[i];
      rb.p = 1 - b.p;
      rb.n = b.n;
      return -negaScoutFinal(rb, strt, true, depth, -beta, -alpha);
    }

    if (canput >= 2) Collections.sort(nb);

    int g = alpha, v = -inf, first_alpha = alpha;
    for (int idx = 0; idx < nb.size(); idx++) {
      Board nnb = nb.get(idx);
      if (idx != 0) {
        g = -negaAlphaOrdering(nnb, strt, false, depth - 1, -alpha - step, -alpha);
        if (beta <= g) {
          if (l[0] < g) register_search(1 - f_search_table_idx, b.b, hash, g, u[0]);
          return g;
        }
        v = Math.max(v, g);
      }
      if (alpha <= g) {
        g = -negaScout(nnb, strt, false, depth - 1, -beta, -g);
        if (beta <= g) {
          if (l[0] < g) register_search(1 - f_search_table_idx, b.b, hash, g, u[0]);
          return g;
        }
        alpha = Math.max(alpha, g);
        v = Math.max(v, g);
      }
    }

    if (v <= first_alpha)
      register_search(1 - f_search_table_idx, b.b, hash, l[0], v);
    else
      register_search(1 - f_search_table_idx, b.b, hash, v, v);

    return v;
  }

  static int nega_alpha(Board b, boolean skipped, int depth, int alpha, int beta) {
    searched_nodes++;
    checkTime();
    if (depth == 0) {
      if (b.n < hw2) return evaluate(b);
      else return end_game(b);
    }
    if (mpc_min_depth <= depth && depth <= mpc_max_depth) {
      if (mpc_higher(b, skipped, depth, beta + epsilon)) return beta + epsilon;
      if (mpc_lower(b, skipped, depth, alpha - epsilon)) return alpha - epsilon;
    }

    Board nb = new Board();
    boolean passed = true;
    int v = -inf;

    for (int cell : vacant_lst) {
      boolean legal =
        legal_arr[b.p][b.b[place_included[cell][0]]][local_place[place_included[cell][0]][cell]] ||
        legal_arr[b.p][b.b[place_included[cell][1]]][local_place[place_included[cell][1]][cell]] ||
        legal_arr[b.p][b.b[place_included[cell][2]]][local_place[place_included[cell][2]][cell]];
      if (place_included[cell][3] != -1)
        legal |= legal_arr[b.p][b.b[place_included[cell][3]]][local_place[place_included[cell][3]][cell]];

      if (legal) {
        passed = false;
        nb = move(b, cell);
        int g = -nega_alpha(nb, false, depth - 1, -beta, -alpha);
        alpha = Math.max(alpha, g);
        if (beta <= alpha) return alpha;
        v = Math.max(v, g);
      }
    }

    if (passed) {
      if (skipped) return end_game(b);
      Board rb = new Board();
      for (int i = 0; i < b_idx_num; i++) rb.b[i] = b.b[i];
      rb.p = 1 - b.p;
      rb.n = b.n;
      return -nega_alpha(rb, true, depth, -beta, -alpha);
    }
    return v;
  }

  static int negaAlphaOrdering(Board b, long strt, boolean skipped, int depth, int alpha, int beta) {
    searched_nodes++;
    checkTime();
    if (mpc_min_depth <= depth && depth <= mpc_max_depth) {
      if (mpc_higher(b, skipped, depth, beta + epsilon)) return beta + epsilon;
      if (mpc_lower(b, skipped, depth, alpha - epsilon)) return alpha - epsilon;
    }
    if (depth <= 3) return nega_alpha(b, skipped, depth, alpha, beta);

    int hash = (int) (calc_hash(b.b) & search_hash_mask);
    int[] l = new int[1];
    int[] u = new int[1];
    get_search(b.b, hash, 1 - f_search_table_idx, l, u);
    if (l[0] != -inf) {
      if (l[0] == u[0]) return l[0];
      alpha = Math.max(alpha, l[0]);
      if (alpha >= beta) return alpha;
    }
    if (u[0] != -inf) {
      beta = Math.min(beta, u[0]);
      if (alpha >= beta) return alpha;
    }

    List<Board> nb = new ArrayList<>(hw2); // 容量を事前確保
    int canput = 0;
    for (int cell : vacant_lst) {
      boolean legal =
        legal_arr[b.p][b.b[place_included[cell][0]]][local_place[place_included[cell][0]][cell]] ||
        legal_arr[b.p][b.b[place_included[cell][1]]][local_place[place_included[cell][1]][cell]] ||
        legal_arr[b.p][b.b[place_included[cell][2]]][local_place[place_included[cell][2]][cell]];
      if (place_included[cell][3] != -1)
        legal |= legal_arr[b.p][b.b[place_included[cell][3]]][local_place[place_included[cell][3]][cell]];

      if (legal) {
        Board next = move(b, cell);
        move_ordering(next);
        nb.add(next);
        canput++;
      }
    }

    if (canput == 0) {
      if (skipped) return end_game(b);
      Board rb = new Board();
      for (int i = 0; i < b_idx_num; i++) rb.b[i] = b.b[i];
      rb.p = 1 - b.p;
      rb.n = b.n;
      return -negaAlphaOrdering(rb, strt, true, depth, -beta, -alpha);
    }

    if (canput >= 2) Collections.sort(nb);

    int first_alpha = alpha;
    int v = -inf;
    for (Board nnb : nb) {
      int g = -negaAlphaOrdering(nnb, strt, false, depth - 1, -beta, -alpha);
      if (beta <= g) {
        if (l[0] < g) register_search(1 - f_search_table_idx, b.b, hash, g, u[0]);
        return g;
      }
      alpha = Math.max(alpha, g);
      v = Math.max(v, g);
    }

    if (v <= first_alpha)
      register_search(1 - f_search_table_idx, b.b, hash, l[0], v);
    else
      register_search(1 - f_search_table_idx, b.b, hash, v, v);

    return v;
  }

  static int negaScout(Board b, long strt, boolean skipped, int depth, int alpha, int beta) {
    searched_nodes++;
    checkTime();
    if (depth <= 3) return nega_alpha(b, skipped, depth, alpha, beta);

    int hash = (int) (calc_hash(b.b) & search_hash_mask);
    int[] l = new int[1];
    int[] u = new int[1];
    get_search(b.b, hash, 1 - f_search_table_idx, l, u);
    if (l[0] != -inf) {
      if (l[0] == u[0]) return l[0];
      alpha = Math.max(alpha, l[0]);
      if (alpha >= beta) return alpha;
    }
    if (u[0] != -inf) {
      beta = Math.min(beta, u[0]);
      if (alpha >= beta) return alpha;
    }

    List<Board> nb = new ArrayList<>();
    int canput = 0;

    for (int cell : vacant_lst) {
      boolean legal =
        legal_arr[b.p][b.b[place_included[cell][0]]][local_place[place_included[cell][0]][cell]] ||
        legal_arr[b.p][b.b[place_included[cell][1]]][local_place[place_included[cell][1]][cell]] ||
        legal_arr[b.p][b.b[place_included[cell][2]]][local_place[place_included[cell][2]][cell]];
      if (place_included[cell][3] != -1)
        legal |= legal_arr[b.p][b.b[place_included[cell][3]]][local_place[place_included[cell][3]][cell]];

      if (legal) {
        Board next = move(b, cell);
        move_ordering(next);
        nb.add(next);
        canput++;
      }
    }

    if (canput == 0) {
      if (skipped) return end_game(b);
      Board rb = new Board();
      for (int i = 0; i < b_idx_num; i++) rb.b[i] = b.b[i];
      rb.p = 1 - b.p;
      rb.n = b.n;
      return -negaScout(rb, strt, true, depth, -beta, -alpha);
    }

    if (canput >= 2) Collections.sort(nb);

    int g = alpha, v = -inf, first_alpha = alpha;
    for (int idx = 0; idx < nb.size(); idx++) {
      Board nnb = nb.get(idx);
      if (idx != 0) {
        g = -negaAlphaOrdering(nnb, strt, false, depth - 1, -alpha - step, -alpha);
        if (beta <= g) {
          if (l[0] < g) register_search(1 - f_search_table_idx, b.b, hash, g, u[0]);
          return g;
        }
        v = Math.max(v, g);
      }
      if (alpha <= g) {
        g = -negaScout(nnb, strt, false, depth - 1, -beta, -g);
        if (beta <= g) {
          if (l[0] < g) register_search(1 - f_search_table_idx, b.b, hash, g, u[0]);
          return g;
        }
        alpha = Math.max(alpha, g);
        v = Math.max(v, g);
      }
    }

    if (v <= first_alpha)
      register_search(1 - f_search_table_idx, b.b, hash, l[0], v);
    else
      register_search(1 - f_search_table_idx, b.b, hash, v, v);

    return v;
  }

  static int mtd(Board b, long strt, boolean skipped, int depth, int l, int u) {
    int g = evaluate(b);
    while (u - l > mtd_threshold) {
      int beta = g;
      g = negaAlphaOrdering(b, strt, skipped, depth, beta - epsilon, beta);
      if (g < beta) u = g;
      else l = g;
      g = (l + u) / 2;
    }
    return negaScout(b, strt, skipped, depth, l, u);
  }

  static int mtdFinal(Board b, long strt, boolean skipped, int depth, int max_beta) {
    int l = -hw2, u = hw2;
    max_beta /= step;
    int g = evaluate(b) / step;

    while (u - l > 0) {
      int beta = Math.max(l + 1, g);
      g = negaAlphaOrderingFinal(b, strt, skipped, depth, beta * step - epsilon, beta * step);

      if (g < beta * step) u = g / step;
      else l = g / step;

      // System.err.println(l + " " + u + "  " + max_beta);
      if (g / step >= max_beta) return g;

      g = (l + u) / 2;
    }
    return l * step;
  }

  static SearchResult makeFallbackResult(List<Board> nb, long strt, int depth) {
    SearchResult res = new SearchResult();
    if (nb.isEmpty()) {
      res.policy = -1;
      res.value = 0;
      res.depth = depth;
      res.nps = (int) ((long) searched_nodes * 1000 / Math.max(1L, tim() - strt));
      return res;
    }

    for (Board bi : nb) move_ordering(bi);
    if (nb.size() >= 2) Collections.sort(nb);

    Board best = nb.get(0);
    res.policy = best.policy;
    res.value = best.v;
    res.depth = depth;
    res.nps = (int) ((long) searched_nodes * 1000 / Math.max(1L, tim() - strt));
    return res;
  }

  static void cancelFutures(List<Future<SearchResult>> futures) {
    for (Future<SearchResult> future : futures) future.cancel(true);
  }

  static SearchResult waitSearchResult(Future<SearchResult> future, List<Future<SearchResult>> futures) {
    try {
      long remain = remaining_time_ms();
      if (remain <= 0) {
        cancelFutures(futures);
        throw search_timeout;
      }
      if (remain == Long.MAX_VALUE) return future.get();
      return future.get(remain, TimeUnit.MILLISECONDS);
    } catch (TimeoutException e) {
      cancelFutures(futures);
      throw search_timeout;
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      cancelFutures(futures);
      throw search_timeout;
    } catch (ExecutionException e) {
      if (e.getCause() instanceof SearchTimeout) {
        cancelFutures(futures);
        throw search_timeout;
      }
      throw new RuntimeException(e.getCause());
    }
  }

  static SearchResult search(Board b, long strt, int max_depth) {
      List<Board> nb = new ArrayList<>();
      for (int cell : vacant_lst) {
          for (int i = 0; i < 4; i++) {
              if (place_included[cell][i] == -1) break;
              if (legal_arr[b.p][b.b[place_included[cell][i]]][local_place[place_included[cell][i]][cell]]) {
                  nb.add(move(b, cell));
                  break;
              }
          }
      }
      int canput = nb.size();

      if (canput == 0) {
          return makeFallbackResult(nb, strt, 0);
      }

      if (canput == 1) {
          SearchResult res = new SearchResult();
          res.policy = nb.get(0).policy;
          res.value = -evaluate(nb.get(0));
          res.depth = 1;
          res.nps = 0;
          return res;
      }

      int alpha, beta;

      searched_nodes = 0;
      SearchResult best = makeFallbackResult(nb, strt, 0);
      int depthLimit = Math.min(hw2 - b.n, max_depth);

      for (int depth = 1; depth < depthLimit; depth++) {
        try {
          checkTime();

          alpha = -sc_w - epsilon;
          beta = sc_w + epsilon;

          search_hash_table_init(1 - f_search_table_idx);

          // 評価値でソート
          for (int i = 0; i < canput; i++) {
              int[] order_l = new int[1];
              int[] order_u = new int[1];
              get_search(nb.get(i).b, (int) (calc_hash(nb.get(i).b) & search_hash_mask), f_search_table_idx, order_l, order_u);
              Board bi = nb.get(i);
              bi.v = -Math.max(order_l[0], order_u[0]);
              if (order_l[0] != -inf && order_u[0] != -inf) bi.v += cache_both;
              if (order_l[0] == -inf && order_u[0] == -inf) bi.v = -evaluate(bi);
              else bi.v += cache_hit;
          }

          if (canput >= 2) Collections.sort(nb);

          // 最善手は通常探索
          alpha = -mtd(nb.get(0), strt, false, depth, -beta, -alpha);
          int tmp_policy = nb.get(0).policy;

          // 候補が多い場合のみ並列化 (オーバーヘッド削減)
          if (canput > 4) {
              final int currentDepth = depth;
              final int currentAlpha = alpha;
              
              List<Future<SearchResult>> futures = new ArrayList<>();
              for (int i = 1; i < canput; i++) {
                  final Board nextBoard = new Board(nb.get(i));
                  final int finalAlpha = currentAlpha;
                  futures.add(forkJoinPool.submit(() -> {
                      SearchResult result = new SearchResult();
                      int g = -negaAlphaOrdering(nextBoard, strt, false, currentDepth, -finalAlpha - step, -finalAlpha);
                      result.value = g;
                      result.policy = nextBoard.policy;
                      return result;
                  }));
              }

              // 結果を収集
              for (int i = 0; i < futures.size(); i++) {
                  SearchResult result = waitSearchResult(futures.get(i), futures);
                  if (alpha < result.value) {
                      int g = -mtd(nb.get(i + 1), strt, false, depth, -beta, -result.value);
                      if (alpha <= g) {
                          alpha = g;
                          tmp_policy = nb.get(i + 1).policy;
                      }
                  }
              }
          } else {
              // 候補が少ない場合は通常探索
              for (int i = 1; i < canput; i++) {
                  int g = -negaAlphaOrdering(nb.get(i), strt, false, depth, -alpha - step, -alpha);
                  if (alpha < g) {
                      g = -mtd(nb.get(i), strt, false, depth, -beta, -g);
                      if (alpha <= g) {
                          alpha = g;
                          tmp_policy = nb.get(i).policy;
                      }
                  }
              }
          }

          f_search_table_idx = 1 - f_search_table_idx;

          SearchResult completed = new SearchResult();
          completed.policy = tmp_policy;
          completed.value = alpha;
          completed.depth = depth + 1;
          completed.nps = (int)((long) searched_nodes * 1000 / Math.max(1L, tim() - strt));
          best = completed;
          System.err.println("completed depth: " + completed.depth +
              " time: " + (tim() - strt) + " ms" +
              " policy: " + completed.policy +
              " value: " + completed.value +
              " nodes: " + searched_nodes +
              " nps: " + completed.nps);
        } catch (SearchTimeout e) {
          System.err.println("time up during depth " + (depth + 1) +
              ", using depth " + best.depth);
          return best;
        }
      }

      return best;
  }

  static SearchResult finalSearch(Board b, long strt) {
      List<Board> nb = new ArrayList<>();
      for (int cell : vacant_lst) {
        for (int i = 0; i < 4; i++) {
          if (place_included[cell][i] == -1) break;
          if (legal_arr[b.p][b.b[place_included[cell][i]]][local_place[place_included[cell][i]][cell]]) {
            System.err.print(cell + " ");
            nb.add(move(b, cell));
            break;
          }
        }
      }
      System.err.println();
      int canput = nb.size();
      System.err.println("canput: " + canput);

      if (canput <= 1) {
        return search(b, strt, Math.max(1, hw2 - b.n));
      }

      int policy = -1;
      int tmp_policy = -1;
      int alpha, beta, g, value;
      int max_depth = hw2 - b.n;
      SearchResult fallback = makeFallbackResult(nb, strt, 0);

      searched_nodes = 0;
      hash_conf = 0;
      hash_get = 0;
      hash_reg = 0;

      if (max_depth - 9 > 0) {
        fallback = search(b, strt, max_depth - 9);
      }

      try {
      checkTime();
      System.err.println("start final search (parallel)");
      alpha = -sc_w;
      beta = sc_w;

      search_hash_table_init(1 - f_search_table_idx);

      for (int i = 0; i < canput; i++) {
        int[] order_l = new int[1];
        int[] order_u = new int[1];
        get_search(nb.get(i).b, (int) (calc_hash(nb.get(i).b) & search_hash_mask), f_search_table_idx, order_l, order_u);
        Board bi = nb.get(i);
        bi.v = -Math.max(order_l[0], order_u[0]);
        if (order_l[0] != -inf && order_u[0] != -inf) bi.v += cache_both;
        if (order_l[0] == -inf && order_u[0] == -inf) bi.v = -evaluate(bi);
        else bi.v += cache_hit;
      }

      if (canput >= 2) Collections.sort(nb);

      // まず最善手を探索
      alpha = -negaScoutFinal(nb.get(0), strt, false, max_depth, -beta, -alpha);
      tmp_policy = nb.get(0).policy;

      // 残りの手を並列探索
      if (canput > 1) {
          final int currentMaxDepth = max_depth;
          final int currentAlpha = alpha;
          final int currentBeta = beta;
          
          List<Future<SearchResult>> futures = new ArrayList<>();
          for (int i = 1; i < canput; i++) {
              final Board nextBoard = new Board(nb.get(i));
              final int finalAlpha = currentAlpha;
              futures.add(forkJoinPool.submit(() -> {
                  SearchResult result = new SearchResult();
                  int tempG = -negaAlphaOrderingFinal(nextBoard, strt, false, currentMaxDepth, -finalAlpha - step, -finalAlpha);
                  result.value = tempG;
                  result.policy = nextBoard.policy;
                  return result;
              }));
          }

          // 結果を収集
          for (int i = 0; i < futures.size(); i++) {
              SearchResult result = waitSearchResult(futures.get(i), futures);
              if (alpha < result.value) {
                  g = -negaScoutFinal(nb.get(i + 1), strt, false, max_depth, -beta, -result.value);
                  if (alpha <= g) {
                      alpha = g;
                      tmp_policy = nb.get(i + 1).policy;
                  }
              }
          }
      }

      f_search_table_idx = 1 - f_search_table_idx;
      policy = tmp_policy;
      value = alpha;
      
      long elapsed = tim() - strt;
      long nps = (long) searched_nodes * 1000 / Math.max(1L, elapsed);
      /**
      System.err.println("final depth: " + max_depth + " time: " + elapsed +
                        " policy: " + policy + " value: " + value +
                        " nodes: " + searched_nodes + " nps: " + nps +
                        " get: " + hash_get + " reg: " + hash_reg);
      */

      SearchResult res = new SearchResult();
      res.policy = policy;
      res.value = value;
      res.depth = max_depth;
      res.nps = (int) ((long) searched_nodes * 1000 / Math.max(1L, tim() - strt));
      return res;
      } catch (SearchTimeout e) {
        System.err.println("time up during final search, using depth " + fallback.depth);
        return fallback;
      }
    }

  static double calcResultValue(int v) {
    return (double) v * hw2 / sc_w;
  }

  static void printResult(int policy, int value) {
    int y = policy / hw;
    int x = policy % hw;
    System.err.println("Placed at: (" + y + ", " + x + ")");
    System.out.println(y + " " + x + " " + calcResultValue(value));  // ★修正: 評価値を追加
  }

  static void printResult(SearchResult result) {
    int y = result.policy / hw;
    int x = result.policy % hw;
    System.err.println("Placed at: (" + y + ", " + x + ") [depth: " + result.depth + ", value: " + result.value + "]");
    System.out.println(y + " " + x + " " + calcResultValue(result.value));  // ★修正: 評価値を追加
  }

  // ★追加: 標準入力からボードを読み込むメソッド
  static int input_board(int[] board) {
    int n_stones = 0;
    long b = 0L, w = 0L;

    vacant_lst.clear();

    BufferedReader br = new BufferedReader(new InputStreamReader(System.in));
    try {
      for (int i = 0; i < hw; i++) {
        String line = br.readLine();
        if (line == null) {
          return -1; // 入力終了
        }
        String raw_board = line.trim();
        System.err.println(raw_board);

        for (int j = 0; j < hw; j++) {
          char elem = raw_board.charAt(j);
          if (elem != '.') {
            b |= ((elem == '0') ? 1L : 0L) << (i * hw + j);
            w |= ((elem == '1') ? 1L : 0L) << (i * hw + j);
            n_stones++;
          } else {
            vacant_lst.add(i * hw + j);
          }
        }
      }
    } catch (IOException e) {
      System.err.println("Error reading board input");
      return -1;
    }

    if (n_stones < hw2_m1) {
      vacant_lst.sort((p, q) -> Integer.compare(cell_weight[q], cell_weight[p]));
    }

    for (int i = 0; i < b_idx_num; i++) {
      board[i] = n_line - 1;
      for (int j = 0; j < idx_n_cell[i]; j++) {
        int gp = global_place[i][j];
        if (((b >>> gp) & 1L) == 1L) {
          board[i] -= pow3[hw_m1 - j] * 2;
        } else if (((w >>> gp) & 1L) == 1L) {
          board[i] -= pow3[hw_m1 - j];
        }
      }
    }
    return n_stones;
  }

  public static void main(String[] args) {
    int policy, n_stones, ai_player, depth, final_depth;
    Board b = new Board();
    final int[] first_moves = {19, 26, 37, 44};

    depth = hw2;
    final_depth = 20;
    long strt = tim();
    SearchResult result;

    System.err.println("initializing");
    init_pow();
    init_mod3();
    init_pop_mid();
    init_move();
    init_local_place();
    init_included();
    init_pop_digit();
    init_mpc();
    init_book();
    System.err.println("book initialized in " + (tim() - strt) + " ms");
    init_evaluation();

    f_search_table_idx = 0;
    search_hash_table_init(f_search_table_idx);
    search_hash_table_init(1 - f_search_table_idx);
    System.err.println("initialized in " + (tim() - strt) + " ms");
    
    System.out.println("READY");
    System.out.flush();
    System.err.println("READY sent");

    BufferedReader br = new BufferedReader(new InputStreamReader(System.in));
    try {
      String line = br.readLine();
      if (line == null) return;
      ai_player = Integer.parseInt(line.trim());
      System.err.println("AI player: " + ai_player);
    } catch (Exception e) {
      return;
    }

    while (true) {
      System.err.println("Waiting for board input...");
      n_stones = input_board(b.b);
      
      if (n_stones == -1) {
        break;
      }
      
      strt = tim();
      begin_move_timer(strt);
      System.err.println("n_stones: " + n_stones);
      System.err.println((n_stones - 4) + " moves");
      b.n = n_stones;
      b.p = ai_player;
      System.err.println("value: " + evaluate(b));

      try {
        if (n_stones == 4) {
          policy = first_moves[myrandrange(0, 4)];
          printResult(policy, 0);
          System.out.flush();
          continue;
        }

        if (n_stones < book_stones) {
          policy = get_book(b.b);
          System.err.println("book policy " + policy);
          if (policy != -1) {
            b = move(b, policy);
            ++n_stones;
            result = search(b, strt, 10);
            printResult(policy, -result.value);
            System.out.flush();
            continue;
          }
        }

        if (n_stones >= hw2 - final_depth)
          result = finalSearch(b, strt);
        else
          result = search(b, strt, depth);

        printResult(result);
        System.out.flush();
      } catch (SearchTimeout e) {
        result = search(b, strt, 1);
        printResult(result);
        System.out.flush();
      } finally {
        clear_move_timer();
      }
    }
    forkJoinPool.shutdown();
  }
}
