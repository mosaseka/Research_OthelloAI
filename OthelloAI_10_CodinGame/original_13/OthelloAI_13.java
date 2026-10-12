/*
 * OthelloAI_13
 *
 * Portions of the bitboard mobility, endgame ordering and search design are
 * derived from Egaroucid 7.8.2, Copyright (C) Takuto Yamana (Nyanyan)
 * (commit 112981e381801a38604f54714d46eb9d90322b80).
 * The generic mobility algorithm also retains Egaroucid's notice that it was
 * based on work by Toshihiko Okuhara. Translated and modified for Java on
 * 2026-07-18. This combined work is licensed under GPL-3.0-or-later; see
 * LICENSE in this directory. There is no warranty.
 */
import java.io.BufferedReader;
import java.io.File;
import java.io.FileReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.Random;
import java.util.concurrent.*;

public class OthelloAI_13 {

  static final String ENGINE_ID = "original_13";

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
  // The initial four-disc position is handled before the book gate. Therefore
  // a limit of four effectively disables book play, while preserving that
  // deterministic initial-position special case. A book entry is eligible
  // only when stoneCount < BOOK_STONES and the independent 44-disc safety
  // gate allows it.
  static final int MIN_BOOK_STONES = 4;
  // Screening on harvested book-hit positions showed that the inherited book
  // was harmful. Keep the gate configurable for controlled A/B tests, but use
  // the effective-off setting by default.
  static final int DEFAULT_BOOK_STONES = 4;
  static final int MAX_BOOK_STONES = 64;
  static final int BOOK_STONES = (int) readLongSetting(
      "othello.bookStones", "OTHELLO_BOOK_STONES",
      DEFAULT_BOOK_STONES, MIN_BOOK_STONES, MAX_BOOK_STONES);
  static final int BOOK_HARD_STOP_STONES = 44;
  static final boolean DEFAULT_BOOK_HARD_STOP_44 = true;
  static final boolean DEFAULT_BOOK_DIAGNOSTIC = false;
  static final boolean BOOK_HARD_STOP_44 = readBooleanSetting(
      "othello.bookHardStop44", "OTHELLO_BOOK_HARD_STOP_44",
      DEFAULT_BOOK_HARD_STOP_44);
  static final boolean BOOK_DIAGNOSTIC = readBooleanSetting(
      "othello.bookDiagnostic", "OTHELLO_BOOK_DIAGNOSTIC",
      DEFAULT_BOOK_DIAGNOSTIC);

  static final int search_hash_table_size = 1_048_576;
  static final int search_hash_mask = search_hash_table_size - 1;

  static final int n_phases = 4;
  static final int n_patterns = 11;
  // original_13 value model: 2*patternLength -> 48 -> 48 -> 1.
  static final int n_dense0 = 48;
  static final int n_dense1 = 48;
  static final int n_add_input = 3;
  static final int n_add_dense0 = 8;
  static final int n_add_dense1 = 8;
  static final int n_all_input = 19;
  static final int evaluation_parameter_count = 142_812;
  static final int max_canput = 30;
  static final int max_surround = 50;

  static final int epsilon = 1;
  static final int sc_w = 6400;
  static final int step = 100;
  static final int cache_hit = 10_000;
  static final int cache_both = 1_000;
  static final int mtd_threshold = 400;
  static final int BOUND_NONE = 0;
  static final int BOUND_UPPER = 1;
  static final int BOUND_LOWER = 2;
  static final int BOUND_EXACT = 3;
  static final int midgame_scout_width = epsilon;
  // Keep the proven original_06 handoff at nine empties. The exact-kernel
  // threshold and fallback horizon are deliberately independent so a future
  // experiment cannot silently make the safety search shallower.
  static final int exact_kernel_depth = (int) readLongSetting(
      "othello.exactDepth", "OTHELLO_EXACT_DEPTH", 9L, 1L, 12L);
  static final int final_fallback_margin = 9;
  static final int final_fallback_percent = (int) readLongSetting(
      "othello.finalFallbackPercent", "OTHELLO_FINAL_FALLBACK_PERCENT",
      25L, 0L, 90L);
  static final int exact_tt_size = 1 << 17;
  static final int exact_tt_mask = exact_tt_size - 1;
  static final long HORIZONTAL_MASK = 0x7e7e7e7e7e7e7e7eL;
  static final long[] PARITY_REGIONS = {
    0x000000000f0f0f0fL, 0x00000000f0f0f0f0L,
    0x0f0f0f0f00000000L, 0xf0f0f0f000000000L
  };
  static final int[] EDGE_CORNERS = {0, 7, 56, 63};
  static final int[][] EDGE_DIRECTIONS = {
    {1, 8}, {-1, 8}, {1, -8}, {-1, -8}
  };
  static final long move_time_limit_ms = readLongSetting(
      "othello.moveTimeMs", "OTHELLO_MOVE_TIME_MS", 9_500L, 10L, 600_000L);
  static final int configured_midgame_depth = (int) readLongSetting(
      "othello.maxDepth", "OTHELLO_MAX_DEPTH", hw2, 1L, hw2);
  static final long time_check_interval = 2_048L;
  static final boolean EMIT_METRICS = readBooleanSetting(
      "othello.metrics", "OTHELLO_METRICS", false);

  enum ValueFeatureMode {
    LEGACY,
    EXACT_MOBILITY
  }

  enum PolicyMode {
    OFF,
    AUTO,
    REQUIRED
  }

  enum MpcMode {
    LEGACY,
    OFF,
    NON_NESTED,
    RETUNED
  }

  static final String REQUESTED_VALUE_FEATURE_MODE = readStringSetting(
      "othello.valueFeatureMode", "OTHELLO_VALUE_FEATURE_MODE", "");
  static final PolicyMode POLICY_MODE = readPolicyMode();
  static final String MODEL_BUNDLE_FILE = readStringSetting(
      "othello.modelBundle", "OTHELLO_MODEL_BUNDLE",
      "resources" + File.separator + "model.properties");
  static final boolean MODEL_BUNDLE_EXPLICIT =
      settingValue("othello.modelBundle", "OTHELLO_MODEL_BUNDLE") != null;

  static final MpcMode MPC_MODE = readMpcMode();
  static final String MPC_RETUNED_FILE = readStringSetting(
      "othello.mpcRetunedFile", "OTHELLO_MPC_RETUNED_FILE",
      "resources" + File.separator + "mpc_retuned.txt");
  static final double MPC_MID_SCALE = readDoubleSetting(
      "othello.mpcMidScale", "OTHELLO_MPC_MID_SCALE", 1.0, 0.5, 2.5);
  static final double MPC_FINAL_SCALE = readDoubleSetting(
      "othello.mpcFinalScale", "OTHELLO_MPC_FINAL_SCALE", 1.0, 0.5, 2.5);
  static String mpc_profile_id =
      MPC_MODE == MpcMode.RETUNED
          ? "uninitialized"
          : (MPC_MODE == MpcMode.OFF ? "off" : "legacy-builtin");

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

  static final int NUM_THREADS = (int) readLongSetting(
      "othello.threads", "OTHELLO_THREADS",
      Runtime.getRuntime().availableProcessors(), 1L, 256L);
  // NUM_THREADS is the total search-thread budget, including the caller thread.
  // A value of one is a genuinely single-threaded search.
  static final ForkJoinPool forkJoinPool =
      NUM_THREADS > 1 ? new ForkJoinPool(NUM_THREADS - 1) : null;
  
  static final class Board implements Comparable<Board> {
    final int[] b = new int[b_idx_num]; // C++: int b[b_idx_num];
    long blackBits;
    long whiteBits;
    long emptyMask;
    boolean hasBitboards;
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
        this.blackBits = other.blackBits;
        this.whiteBits = other.whiteBits;
        this.emptyMask = other.emptyMask;
        this.hasBitboards = other.hasBitboards;
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

  static final class BookChoice {
    final int policy;
    final int candidateCount;

    BookChoice(int policy, int candidateCount) {
      this.policy = policy;
      this.candidateCount = candidateCount;
    }

    boolean hit() {
      return policy >= 0;
    }
  }

  static final class SearchNode {
    boolean reg;
    final int[] k = new int[4];
    int p;
    int l;
    int u;
    int generation;
    volatile int stamp;

    SearchNode() {}

    SearchNode(SearchNode other) {
      this.reg = other.reg;
      System.arraycopy(other.k, 0, this.k, 0, k.length);
      this.p = other.p;
      this.l = other.l;
      this.u = other.u;
      this.generation = other.generation;
      this.stamp = other.stamp;
    }
  }

  static final class SearchResult {
    int policy;
    int value;
    int depth;
    int nps;
    int rootIndex = -1;
    int rootFirstPolicy = -1;
    int rootResearchCount;
    int rootRescoutCount;
    int rootResearchDepth = -1;
    int alphaAtStart;
    int boundType = BOUND_NONE;
    int fallbackDepth;
    boolean exactStarted;
    boolean exactCompleted;
    boolean timedOut;

    SearchResult() {}

    SearchResult(SearchResult other) {
      this.policy = other.policy;
      this.value = other.value;
      this.depth = other.depth;
      this.nps = other.nps;
      this.rootIndex = other.rootIndex;
      this.rootFirstPolicy = other.rootFirstPolicy;
      this.rootResearchCount = other.rootResearchCount;
      this.rootRescoutCount = other.rootRescoutCount;
      this.rootResearchDepth = other.rootResearchDepth;
      this.alphaAtStart = other.alphaAtStart;
      this.boundType = other.boundType;
      this.fallbackDepth = other.fallbackDepth;
      this.exactStarted = other.exactStarted;
      this.exactCompleted = other.exactCompleted;
      this.timedOut = other.timedOut;
    }
  }

  /**
   * Immutable outcome of resolving a book hit after an optional comparison
   * search.  Keeping this decision in one pure helper makes two invariants
   * explicit: diagnostics never replace the selected book move, and a
   * diagnostic timeout is not a timeout of the already selected move.
   */
  static final class BookTurnResolution {
    final int selectedPolicy;
    final int diagnosticPolicy;
    final int diagnosticValue;
    final int diagnosticDepth;
    final boolean diagnosticAgrees;
    final boolean diagnosticTimedOut;
    final boolean productionTimedOut;

    BookTurnResolution(
        int selectedPolicy,
        int diagnosticPolicy,
        int diagnosticValue,
        int diagnosticDepth,
        boolean diagnosticAgrees,
        boolean diagnosticTimedOut,
        boolean productionTimedOut
    ) {
      this.selectedPolicy = selectedPolicy;
      this.diagnosticPolicy = diagnosticPolicy;
      this.diagnosticValue = diagnosticValue;
      this.diagnosticDepth = diagnosticDepth;
      this.diagnosticAgrees = diagnosticAgrees;
      this.diagnosticTimedOut = diagnosticTimedOut;
      this.productionTimedOut = productionTimedOut;
    }
  }

  static BookTurnResolution resolveBookTurn(
      BookChoice choice,
      SearchResult diagnosticResult,
      boolean diagnosticExceptionTimeout
  ) {
    if (choice == null || !choice.hit()) {
      throw new IllegalArgumentException("resolveBookTurn requires a book hit");
    }
    int diagnosticPolicy =
        diagnosticResult == null ? -1 : diagnosticResult.policy;
    int diagnosticValue =
        diagnosticResult == null ? 0 : diagnosticResult.value;
    int diagnosticDepth =
        diagnosticResult == null ? 0 : diagnosticResult.depth;
    boolean diagnosticTimedOut = diagnosticExceptionTimeout ||
        (diagnosticResult != null && diagnosticResult.timedOut);
    boolean diagnosticAgrees = diagnosticResult != null &&
        diagnosticPolicy == choice.policy;
    return new BookTurnResolution(
        choice.policy,
        diagnosticPolicy,
        diagnosticValue,
        diagnosticDepth,
        diagnosticAgrees,
        diagnosticTimedOut,
        false);
  }

  static final class EvaluatorTables {
    final ValueFeatureMode featureMode;
    final double[][][] pattern =
        new double[n_phases][n_patterns][max_evaluate_idx];
    final double[][][][][] additions =
        new double[n_phases][max_canput * 2 + 1]
            [max_surround + 1][max_surround + 1][n_add_dense1];
    final double[][] dense = new double[n_phases][n_all_input];
    final double[] bias = new double[n_phases];
    String sha256 = "uninitialized";

    EvaluatorTables(ValueFeatureMode featureMode) {
      this.featureMode = featureMode;
    }
  }

  static final class ModelBundle {
    final File manifest;
    final File valueFile;
    final String valueSha256;
    final File policyFile;
    final String policySha256;
    final String manifestSha256;

    ModelBundle(
        File manifest,
        File valueFile,
        String valueSha256,
        File policyFile,
        String policySha256,
        String manifestSha256
    ) {
      this.manifest = manifest;
      this.valueFile = valueFile;
      this.valueSha256 = valueSha256;
      this.policyFile = policyFile;
      this.policySha256 = policySha256;
      this.manifestSha256 = manifestSha256;
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

  static final int[] vacant_cells = new int[hw2];
  static int vacant_count;
  static final BookNode[] book = new BookNode[book_hash_table_size];
  static final SearchNode[][] search_replace_table = new SearchNode[2][search_hash_table_size];
  static volatile long active_move_generation;
  static final class SearchStats {
    volatile long generation;
    long nodes;
    long mpcAttempts;
    long mpcCuts;
    long mpcNestedSuppressed;
    long generalTtHits;
    long exactTtHits;
    long exactNodes;
    long stabilityCuts;
    long policyEvaluations;
  }
  static final class ExactTranspositionTable {
    final long[] players = new long[exact_tt_size];
    final long[] opponents = new long[exact_tt_size];
    final int[] lower = new int[exact_tt_size];
    final int[] upper = new int[exact_tt_size];
    final boolean[] skipped = new boolean[exact_tt_size];
    // 0: unused, 1: lower only, 2: upper only, 3: exact/both.
    final byte[] flags = new byte[exact_tt_size];
    final int[][] orderedCells = new int[hw2 * 2 + 2][hw2];
    final long[][] orderedFlips = new long[hw2 * 2 + 2][hw2];
    final int[][] orderedScores = new int[hw2 * 2 + 2][hw2];
  }
  static final ThreadLocal<ExactTranspositionTable> exact_tt =
      ThreadLocal.withInitial(ExactTranspositionTable::new);
  static final ConcurrentLinkedQueue<SearchStats> all_search_stats =
      new ConcurrentLinkedQueue<>();
  static final ThreadLocal<SearchStats> local_search_stats =
      ThreadLocal.withInitial(() -> {
        SearchStats stats = new SearchStats();
        stats.generation = active_move_generation;
        all_search_stats.add(stats);
        return stats;
      });
  static volatile long search_deadline_nanos = Long.MAX_VALUE;
  static int f_search_table_idx;
  static EvaluatorTables value_evaluator;
  static EvaluatorTables policy_evaluator;
  static String value_param_sha256 = "uninitialized";
  static String policy_param_sha256 = "off";
  static String active_policy_mode = "off";
  static String model_bundle_sha256 = "none";

  static final Random raw_myrandom = new Random(readLongSetting(
      "othello.seed", "OTHELLO_SEED", System.currentTimeMillis(), Long.MIN_VALUE, Long.MAX_VALUE));

  static long readLongSetting(
      String propertyName,
      String environmentName,
      long defaultValue,
      long minValue,
      long maxValue
  ) {
    return resolveLongSetting(
        propertyName,
        System.getProperty(propertyName),
        System.getenv(environmentName),
        defaultValue,
        minValue,
        maxValue);
  }

  // Pure resolver used by readLongSetting and by regression tests. Keeping
  // environment access outside this method makes property > environment >
  // default precedence testable without mutating the caller's process.
  static long resolveLongSetting(
      String propertyName,
      String propertyValue,
      String environmentValue,
      long defaultValue,
      long minValue,
      long maxValue
  ) {
    String value = propertyValue;
    if (value == null || value.isBlank()) value = environmentValue;
    if (value == null || value.isBlank()) return defaultValue;
    try {
      long parsed = Long.parseLong(value.trim());
      if (parsed < minValue || parsed > maxValue) {
        throw new IllegalArgumentException(
            propertyName + " must be in [" + minValue + ", " + maxValue + "]: " + parsed);
      }
      return parsed;
    } catch (NumberFormatException e) {
      throw new IllegalArgumentException(propertyName + " must be an integer: " + value, e);
    }
  }

  static double readDoubleSetting(
      String propertyName,
      String environmentName,
      double defaultValue,
      double minValue,
      double maxValue
  ) {
    String value = settingValue(propertyName, environmentName);
    if (value == null) return defaultValue;
    try {
      double parsed = Double.parseDouble(value);
      if (!Double.isFinite(parsed) || parsed < minValue || parsed > maxValue) {
        throw new IllegalArgumentException(
            propertyName + " must be finite and in [" + minValue + ", " +
            maxValue + "]: " + value);
      }
      return parsed;
    } catch (NumberFormatException e) {
      throw new IllegalArgumentException(
          propertyName + " must be a floating-point number: " + value, e);
    }
  }

  static String settingValue(String propertyName, String environmentName) {
    String value = System.getProperty(propertyName);
    if (value == null || value.isBlank()) value = System.getenv(environmentName);
    return value == null || value.isBlank() ? null : value.trim();
  }

  static String readStringSetting(
      String propertyName,
      String environmentName,
      String defaultValue
  ) {
    String value = settingValue(propertyName, environmentName);
    return value == null ? defaultValue : value;
  }

  static ValueFeatureMode parseValueFeatureMode(String value) {
    switch (value.trim().toLowerCase()) {
      case "legacy":
        return ValueFeatureMode.LEGACY;
      case "exactmobility":
      case "exact-mobility":
      case "exact_mobility":
        return ValueFeatureMode.EXACT_MOBILITY;
      default:
        throw new IllegalArgumentException(
            "value feature mode must be legacy/exactMobility: " + value);
    }
  }

  static PolicyMode readPolicyMode() {
    String value = readStringSetting(
        "othello.policyMode", "OTHELLO_POLICY_MODE", "auto");
    switch (value.trim().toLowerCase()) {
      case "off":
        return PolicyMode.OFF;
      case "auto":
        return PolicyMode.AUTO;
      case "required":
        return PolicyMode.REQUIRED;
      default:
        throw new IllegalArgumentException(
            "othello.policyMode must be off/auto/required: " + value);
    }
  }

  static MpcMode readMpcMode() {
    String value = readStringSetting(
        "othello.mpcMode", "OTHELLO_MPC_MODE", "legacy");
    switch (value.trim().toLowerCase()) {
      case "legacy":
        return MpcMode.LEGACY;
      case "off":
        return MpcMode.OFF;
      case "nonnested":
      case "non-nested":
      case "non_nested":
        return MpcMode.NON_NESTED;
      case "retuned":
        return MpcMode.RETUNED;
      default:
        throw new IllegalArgumentException(
            "othello.mpcMode must be legacy/off/nonNested/retuned: " + value);
    }
  }

  static final class SearchWorkspace {
    final Board[][] boardsByDepth = new Board[hw2 + 1][];
    final Board[] passBoardsByDepth = new Board[hw2 + 1];

    Board board(int depth, int index) {
      int safeDepth = Math.max(0, Math.min(hw2, depth));
      Board[] boards = boardsByDepth[safeDepth];
      if (boards == null) {
        boards = new Board[hw2];
        boardsByDepth[safeDepth] = boards;
      }
      Board board = boards[index];
      if (board == null) {
        board = new Board();
        boards[index] = board;
      }
      return board;
    }

    Board[] boards(int depth) {
      int safeDepth = Math.max(0, Math.min(hw2, depth));
      Board[] boards = boardsByDepth[safeDepth];
      if (boards == null) {
        boards = new Board[hw2];
        boardsByDepth[safeDepth] = boards;
      }
      return boards;
    }

    Board passBoard(int depth) {
      int safeDepth = Math.max(0, Math.min(hw2, depth));
      Board board = passBoardsByDepth[safeDepth];
      if (board == null) {
        board = new Board();
        passBoardsByDepth[safeDepth] = board;
      }
      return board;
    }
  }

  static final ThreadLocal<SearchWorkspace> search_workspace =
      ThreadLocal.withInitial(SearchWorkspace::new);

  static void stableSortBoards(Board[] boards, int size) {
    for (int i = 1; i < size; i++) {
      Board value = boards[i];
      int j = i - 1;
      while (j >= 0 && boards[j].v < value.v) {
        boards[j + 1] = boards[j];
        j--;
      }
      boards[j + 1] = value;
    }
  }

  static boolean readBooleanSetting(
      String propertyName,
      String environmentName,
      boolean defaultValue
  ) {
    return resolveBooleanSetting(
        propertyName,
        System.getProperty(propertyName),
        System.getenv(environmentName),
        defaultValue);
  }

  // Boolean counterpart of resolveLongSetting; see that method for the
  // precedence contract.
  static boolean resolveBooleanSetting(
      String propertyName,
      String propertyValue,
      String environmentValue,
      boolean defaultValue
  ) {
    String value = propertyValue;
    if (value == null || value.isBlank()) value = environmentValue;
    if (value == null || value.isBlank()) return defaultValue;
    String normalized = value.trim().toLowerCase();
    if (normalized.equals("1") || normalized.equals("true") ||
        normalized.equals("yes") || normalized.equals("on")) {
      return true;
    }
    if (normalized.equals("0") || normalized.equals("false") ||
        normalized.equals("no") || normalized.equals("off")) {
      return false;
    }
    throw new IllegalArgumentException(
        propertyName + " must be true/false: " + value);
  }

  static boolean isBookEligible(
      int stoneCount,
      int bookStones,
      boolean hardStop44
  ) {
    if (bookStones < MIN_BOOK_STONES || bookStones > MAX_BOOK_STONES) {
      throw new IllegalArgumentException(
          "bookStones must be in [" + MIN_BOOK_STONES + ", " +
          MAX_BOOK_STONES + "]: " + bookStones);
    }
    return stoneCount < bookStones &&
        (!hardStop44 || stoneCount < BOOK_HARD_STOP_STONES);
  }

  static boolean isBookEligible(int stoneCount) {
    return isBookEligible(stoneCount, BOOK_STONES, BOOK_HARD_STOP_44);
  }

  static File configuredFile(
      String propertyName,
      String environmentName,
      String defaultPath
  ) {
    return new File(readStringSetting(
        propertyName, environmentName, defaultPath));
  }

  static double myrandom() {
    // JavaのRandom#nextDouble() は [0.0, 1.0) の一様分布を返す
    return raw_myrandom.nextDouble();
  }

  static int myrandrange(int s, int e) {
    return s + (int) ((e - s) * myrandom());
  }

  static long tim() {
    return System.nanoTime() / 1_000_000L;
  }

  static final class SearchTimeout extends RuntimeException {
    private static final long serialVersionUID = 1L;

    SearchTimeout() {
      super(null, null, false, false);
    }
  }

  static final SearchTimeout search_timeout = new SearchTimeout();

  static void begin_move_timer(long strt) {
    long safetyMargin = Math.min(75L, Math.max(1L, move_time_limit_ms / 20L));
    long generation = ++active_move_generation;
    prepareWorker(generation);
    resetNodeCounters();
    search_deadline_nanos =
        System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(move_time_limit_ms - safetyMargin);
  }

  static void clear_move_timer() {
    long generation = ++active_move_generation;
    search_deadline_nanos = Long.MAX_VALUE;
    prepareWorker(generation);
  }

  static long remaining_time_ms() {
    long deadline = search_deadline_nanos;
    if (deadline == Long.MAX_VALUE) return Long.MAX_VALUE;
    long remainingNanos = deadline - System.nanoTime();
    if (remainingNanos <= 0L) return 0L;
    return Math.max(1L, TimeUnit.NANOSECONDS.toMillis(remainingNanos));
  }

  static void prepareWorker(long generation) {
    if (generation != active_move_generation) throw search_timeout;
    SearchStats stats = local_search_stats.get();
    if (stats.generation != generation) {
      stats.generation = generation;
      stats.nodes = 0L;
      stats.mpcAttempts = 0L;
      stats.mpcCuts = 0L;
      stats.mpcNestedSuppressed = 0L;
      stats.generalTtHits = 0L;
      stats.exactTtHits = 0L;
      stats.exactNodes = 0L;
      stats.stabilityCuts = 0L;
      stats.policyEvaluations = 0L;
    }
  }

  static void visitNode() {
    SearchStats stats = local_search_stats.get();
    long nodes = ++stats.nodes;
    if ((nodes & (time_check_interval - 1L)) != 0L) return;
    if ((stats.generation != active_move_generation) ||
        Thread.currentThread().isInterrupted() ||
        (search_deadline_nanos != Long.MAX_VALUE &&
         System.nanoTime() >= search_deadline_nanos)) {
      throw search_timeout;
    }
  }

  static long searchedNodes() {
    long generation = active_move_generation;
    long total = 0L;
    for (SearchStats stats : all_search_stats) {
      if (stats.generation == generation) total += stats.nodes;
    }
    return total;
  }

  static void resetNodeCounters() {
    long generation = active_move_generation;
    for (SearchStats stats : all_search_stats) {
      if (stats.generation == generation) {
        stats.nodes = 0L;
        stats.mpcAttempts = 0L;
        stats.mpcCuts = 0L;
        stats.mpcNestedSuppressed = 0L;
        stats.generalTtHits = 0L;
        stats.exactTtHits = 0L;
        stats.exactNodes = 0L;
        stats.stabilityCuts = 0L;
        stats.policyEvaluations = 0L;
      }
    }
    SearchStats current = local_search_stats.get();
    current.generation = generation;
    current.nodes = 0L;
    current.mpcAttempts = 0L;
    current.mpcCuts = 0L;
    current.mpcNestedSuppressed = 0L;
    current.generalTtHits = 0L;
    current.exactTtHits = 0L;
    current.exactNodes = 0L;
    current.stabilityCuts = 0L;
    current.policyEvaluations = 0L;
  }

  static long currentGeneration() {
    return active_move_generation;
  }

  static void checkTime() {
    SearchStats stats = local_search_stats.get();
    if ((stats.generation != active_move_generation) ||
        Thread.currentThread().isInterrupted() ||
        (search_deadline_nanos != Long.MAX_VALUE &&
         System.nanoTime() >= search_deadline_nanos)) {
      throw search_timeout;
    }
  }

  static long metricMpcAttempts() {
    return sumMetric(0);
  }

  static long metricMpcCuts() {
    return sumMetric(1);
  }

  static long metricGeneralTtHits() {
    return sumMetric(2);
  }

  static long metricMpcNestedSuppressed() {
    return sumMetric(5);
  }

  static long metricExactTtHits() {
    return sumMetric(3);
  }

  static long metricStabilityCuts() {
    return sumMetric(4);
  }

  static long metricExactNodes() {
    return sumMetric(6);
  }

  static long metricPolicyEvaluations() {
    return sumMetric(7);
  }

  static long sumMetric(int metric) {
    long generation = active_move_generation;
    long total = 0L;
    for (SearchStats stats : all_search_stats) {
      if (stats.generation != generation) continue;
      switch (metric) {
        case 0:
          total += stats.mpcAttempts;
          break;
        case 1:
          total += stats.mpcCuts;
          break;
        case 2:
          total += stats.generalTtHits;
          break;
        case 3:
          total += stats.exactTtHits;
          break;
        case 4:
          total += stats.stabilityCuts;
          break;
        case 5:
          total += stats.mpcNestedSuppressed;
          break;
        case 6:
          total += stats.exactNodes;
          break;
        case 7:
          total += stats.policyEvaluations;
          break;
        default:
          throw new IllegalArgumentException("unknown metric: " + metric);
      }
    }
    return total;
  }

  static SearchStats snapshotSearchStats(SearchStats source) {
    SearchStats snapshot = new SearchStats();
    snapshot.nodes = source.nodes;
    snapshot.mpcAttempts = source.mpcAttempts;
    snapshot.mpcCuts = source.mpcCuts;
    snapshot.mpcNestedSuppressed = source.mpcNestedSuppressed;
    snapshot.generalTtHits = source.generalTtHits;
    snapshot.exactTtHits = source.exactTtHits;
    snapshot.exactNodes = source.exactNodes;
    snapshot.stabilityCuts = source.stabilityCuts;
    snapshot.policyEvaluations = source.policyEvaluations;
    return snapshot;
  }

  static void addSearchStats(SearchStats target, SearchStats source) {
    target.nodes += source.nodes;
    target.mpcAttempts += source.mpcAttempts;
    target.mpcCuts += source.mpcCuts;
    target.mpcNestedSuppressed += source.mpcNestedSuppressed;
    target.generalTtHits += source.generalTtHits;
    target.exactTtHits += source.exactTtHits;
    target.exactNodes += source.exactNodes;
    target.stabilityCuts += source.stabilityCuts;
    target.policyEvaluations += source.policyEvaluations;
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
    if (MPC_MODE == MpcMode.RETUNED) loadRetunedMpc();
    if (MPC_MID_SCALE != 1.0) {
      for (int phase = 0; phase < 6; phase++) {
        for (int depth = mpc_min_depth; depth <= mpc_max_depth; depth++) {
          mpctsd[phase][depth] =
              (int) Math.round(mpctsd[phase][depth] * MPC_MID_SCALE);
        }
      }
    }
    if (MPC_FINAL_SCALE != 1.0) {
      for (int depth = mpc_min_depth_final;
           depth <= mpc_max_depth_final;
           depth++) {
        mpctsd_final[depth] =
            (int) Math.round(mpctsd_final[depth] * MPC_FINAL_SCALE);
      }
    }
  }

  static void loadRetunedMpc() {
    File file = new File(MPC_RETUNED_FILE);
    if (!file.isFile()) {
      throw new IllegalStateException(
          "retuned MPC mode requires " + file.getPath() +
          " (60 midgame thresholds followed by 19 final thresholds)");
    }

    List<Integer> values = new ArrayList<>();
    String format = null;
    String profileId = null;
    String parameterHash = null;
    String probeMode = null;
    try (BufferedReader reader = new BufferedReader(new FileReader(file))) {
      String line;
      while ((line = reader.readLine()) != null) {
        String metadataLine = line.trim();
        if (metadataLine.startsWith("#")) {
          metadataLine = metadataLine.substring(1).trim();
          int equals = metadataLine.indexOf('=');
          if (equals > 0) {
            String key =
                metadataLine.substring(0, equals).trim().toLowerCase();
            String metadataValue =
                metadataLine.substring(equals + 1).trim();
            switch (key) {
              case "format":
                format = metadataValue;
                break;
              case "profile":
                profileId = metadataValue;
                break;
              case "param-sha256":
                parameterHash = metadataValue;
                break;
              case "probe-mode":
                probeMode = metadataValue;
                break;
              default:
                // Unknown comment metadata is forward-compatible.
                break;
            }
          }
          continue;
        }
        int comment = line.indexOf('#');
        if (comment >= 0) line = line.substring(0, comment);
        String trimmed = line.trim();
        if (trimmed.isEmpty()) continue;
        for (String token : trimmed.split("\\s+")) {
          int value = Integer.parseInt(token);
          if (value < 0 || value > 100_000) {
            throw new IllegalArgumentException(
                "MPC threshold must be in [0, 100000]: " + value);
          }
          values.add(value);
        }
      }
    } catch (IOException | NumberFormatException e) {
      throw new IllegalStateException(
          "failed to read retuned MPC thresholds from " + file.getPath(), e);
    }

    if (!"othello-mpc-v1".equals(format)) {
      throw new IllegalStateException(
          "retuned MPC profile requires '# format=othello-mpc-v1'");
    }
    if (profileId == null ||
        !profileId.matches("[A-Za-z0-9._-]{1,64}")) {
      throw new IllegalStateException(
          "retuned MPC profile requires a safe '# profile=<id>'");
    }
    if (parameterHash == null ||
        !value_param_sha256.equalsIgnoreCase(parameterHash)) {
      throw new IllegalStateException(
          "retuned MPC profile param-sha256 does not match loaded value parameter");
    }
    if (probeMode == null ||
        !probeMode.replace("-", "").replace("_", "")
            .equalsIgnoreCase("nonnested")) {
      throw new IllegalStateException(
          "retuned MPC profile must declare '# probe-mode=nonNested'");
    }

    int expected =
        6 * (mpc_max_depth - mpc_min_depth + 1) +
        (mpc_max_depth_final - mpc_min_depth_final + 1);
    if (values.size() != expected) {
      throw new IllegalStateException(
          "retuned MPC file must contain exactly " + expected +
          " integer thresholds, got " + values.size());
    }

    int index = 0;
    for (int phase = 0; phase < 6; phase++) {
      for (int depth = mpc_min_depth; depth <= mpc_max_depth; depth++) {
        mpctsd[phase][depth] = values.get(index++);
      }
    }
    for (int depth = mpc_min_depth_final;
         depth <= mpc_max_depth_final;
         depth++) {
      mpctsd_final[depth] = values.get(index++);
    }
    mpc_profile_id = profileId;
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

  static void moveInto(Board b, int g_place, Board res) {
    ensureBitboards(b);
    long player = b.p == 0 ? b.blackBits : b.whiteBits;
    long opponent = b.p == 0 ? b.whiteBits : b.blackBits;
    long moveBit = 1L << g_place;
    long flips = bitboardFlips(player, opponent, g_place);

    System.arraycopy(b.b, 0, res.b, 0, b_idx_num);

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
    if (b.p == 0) {
      res.blackBits = b.blackBits | moveBit | flips;
      res.whiteBits = b.whiteBits & ~flips;
    } else {
      res.whiteBits = b.whiteBits | moveBit | flips;
      res.blackBits = b.blackBits & ~flips;
    }
    res.emptyMask = b.emptyMask & ~moveBit;
    res.hasBitboards = true;
  }

  static Board move(Board b, int g_place) {
    Board res = new Board();
    moveInto(b, g_place, res);
    return res;
  }

  static void passInto(Board board, Board result) {
    ensureBitboards(board);
    System.arraycopy(board.b, 0, result.b, 0, b_idx_num);
    result.p = 1 - board.p;
    result.n = board.n;
    result.policy = -1;
    result.blackBits = board.blackBits;
    result.whiteBits = board.whiteBits;
    result.emptyMask = board.emptyMask;
    result.hasBitboards = board.hasBitboards;
  }

  static void initializeBitboards(Board board) {
    long black = 0L;
    long white = 0L;
    for (int row = 0; row < hw; row++) {
      int line = board.b[row];
      for (int col = 0; col < hw; col++) {
        int disk = pop_digit[line][col];
        long bit = 1L << (row * hw + col);
        if (disk == 0) black |= bit;
        else if (disk == 1) white |= bit;
      }
    }
    board.blackBits = black;
    board.whiteBits = white;
    board.emptyMask = ~(black | white);
    board.hasBitboards = true;
  }

  static void ensureBitboards(Board board) {
    if (!board.hasBitboards) initializeBitboards(board);
  }

  static boolean isCandidateEmpty(Board board, int cell) {
    return !board.hasBitboards || (board.emptyMask & (1L << cell)) != 0L;
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

  static BookChoice get_book(int[] key) {
    BookNode p_node = book[(int) (calc_hash(key) & book_hash_mask)];
    while (p_node != null) {
      if (compare_key(key, p_node.k)) {
        // Preserve original_10's behaviour: if the same position contains
        // multiple book moves, select one uniformly at random. No value,
        // win-rate, or visit-count weighting is available in this book format.
        int selected = p_node.policies[myrandrange(0, p_node.size)];
        return new BookChoice(selected, p_node.size);
      }
      p_node = p_node.p_n_node;
    }
    return new BookChoice(-1, 0);
  }

  static void init_book() {
    Map<Character, Integer> char_keys = new HashMap<>();
    final String book_chars = "!#$&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]^_`abc";
    for (int i = 0; i < hw2; i++) {
      char_keys.put(book_chars.charAt(i), i);
    }

    File file = configuredFile(
        "othello.book", "OTHELLO_BOOK",
        "resources" + File.separator + "book.txt");
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
      initializeBitboards(fb);

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
    EvaluatorTables tables,
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
      tables.pattern[phase_idx][evaluate_idx][idx] =
        predict(pattern_size, arr, dense0, bias0, dense1, bias1, dense2, bias2);
      tmp_pattern_arr[calc_rev_idx(pattern_idx, pattern_size, idx)] =
        tables.pattern[phase_idx][evaluate_idx][idx];
    }
    for (int idx = 0; idx < pow3[pattern_size]; idx++) {
      tables.pattern[phase_idx][evaluate_idx][idx] += tmp_pattern_arr[idx];
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
    EvaluatorTables tables,
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
            tables.additions[phase_idx][canput + max_canput][sur0][sur1]
          );
        }
      }
    }
  }

  static void validate_evaluation_file(File file) throws IOException {
    int count = 0;
    try (BufferedReader br = new BufferedReader(new FileReader(file))) {
      String line;
      while ((line = br.readLine()) != null) {
        if (line.isBlank()) {
          throw new IOException("blank evaluation parameter at line " + (count + 1));
        }
        final double value;
        try {
          value = Double.parseDouble(line);
        } catch (NumberFormatException e) {
          throw new IOException("invalid evaluation parameter at line " + (count + 1), e);
        }
        if (!Double.isFinite(value)) {
          throw new IOException("non-finite evaluation parameter at line " + (count + 1));
        }
        count++;
      }
    }
    if (count != evaluation_parameter_count) {
      throw new IOException(
          "evaluation parameter count must be " + evaluation_parameter_count + ", got " + count);
    }
  }

  static String sha256(File file) throws IOException {
    final MessageDigest digest;
    try {
      digest = MessageDigest.getInstance("SHA-256");
    } catch (NoSuchAlgorithmException e) {
      throw new IllegalStateException("SHA-256 is unavailable", e);
    }
    try (InputStream input = Files.newInputStream(file.toPath())) {
      byte[] buffer = new byte[64 * 1024];
      int read;
      while ((read = input.read(buffer)) >= 0) {
        if (read != 0) digest.update(buffer, 0, read);
      }
    }
    StringBuilder result = new StringBuilder(64);
    for (byte value : digest.digest()) {
      result.append(String.format("%02X", value & 0xff));
    }
    return result.toString();
  }

  static String requiredProperty(
      Properties properties,
      String key,
      File manifest
  ) {
    String value = properties.getProperty(key);
    if (value == null || value.isBlank()) {
      throw new IllegalStateException(
          "model bundle " + manifest.getPath() +
          " requires property " + key);
    }
    return value.trim();
  }

  static String normalizedSha256(
      String value,
      String key,
      File manifest
  ) {
    String normalized = value.trim().toUpperCase();
    if (!normalized.matches("[0-9A-F]{64}")) {
      throw new IllegalStateException(
          "model bundle " + manifest.getPath() +
          " has invalid " + key);
    }
    return normalized;
  }

  static File bundleRelativeFile(File manifest, String path) {
    File file = new File(path);
    if (file.isAbsolute()) return file;
    File parent = manifest.getAbsoluteFile().getParentFile();
    return new File(parent, path);
  }

  static ModelBundle loadModelBundle() {
    File manifest = new File(MODEL_BUNDLE_FILE);
    if (!manifest.isFile()) {
      if (MODEL_BUNDLE_EXPLICIT) {
        throw new IllegalStateException(
            "configured model bundle does not exist: " + manifest.getPath());
      }
      return null;
    }

    Properties properties = new Properties();
    try (BufferedReader reader = Files.newBufferedReader(
        manifest.toPath(), StandardCharsets.UTF_8)) {
      properties.load(reader);
    } catch (IOException e) {
      throw new IllegalStateException(
          "failed to read model bundle: " + manifest.getPath(), e);
    }

    String format = requiredProperty(properties, "format", manifest);
    if (!"othello-model-bundle-v2".equals(format)) {
      throw new IllegalStateException(
          "unsupported model bundle format: " + format);
    }
    String schema = requiredProperty(
        properties, "feature.schema", manifest);
    if (!"exact-mobility-v1".equals(schema)) {
      throw new IllegalStateException(
          "unsupported model feature schema: " + schema);
    }
    String architecture = requiredProperty(
        properties, "value.architecture", manifest);
    if (!"pattern-mlp-48x48-add8x8-v1".equals(architecture)) {
      throw new IllegalStateException(
          "unsupported value architecture: " + architecture);
    }
    String output = requiredProperty(
        properties, "value.output", manifest);
    if (!"black-win-logit-v1".equals(output)) {
      throw new IllegalStateException(
          "unsupported value output: " + output);
    }
    String transform = requiredProperty(
        properties, "value.runtime-transform", manifest);
    if (!"tanh-half-logit-v1".equals(transform)) {
      throw new IllegalStateException(
          "unsupported value runtime transform: " + transform);
    }

    File valueFile = bundleRelativeFile(
        manifest, requiredProperty(properties, "value.file", manifest));
    String valueSha = normalizedSha256(
        requiredProperty(properties, "value.sha256", manifest),
        "value.sha256", manifest);

    String policyPath = properties.getProperty("policy.file");
    String policyHash = properties.getProperty("policy.sha256");
    if ((policyPath == null || policyPath.isBlank()) !=
        (policyHash == null || policyHash.isBlank())) {
      throw new IllegalStateException(
          "model bundle policy.file and policy.sha256 must appear together");
    }
    File policyFile = null;
    String policySha = null;
    if (policyPath != null && !policyPath.isBlank()) {
      policyFile = bundleRelativeFile(manifest, policyPath.trim());
      policySha = normalizedSha256(
          policyHash, "policy.sha256", manifest);
    }

    try {
      return new ModelBundle(
          manifest, valueFile, valueSha, policyFile, policySha,
          sha256(manifest));
    } catch (IOException e) {
      throw new IllegalStateException(
          "failed to hash model bundle: " + manifest.getPath(), e);
    }
  }

  static File configuredOverride(
      String propertyName,
      String environmentName,
      File fallback
  ) {
    String override = settingValue(propertyName, environmentName);
    return override == null ? fallback : new File(override);
  }

  static EvaluatorTables loadEvaluator(
      File file,
      ValueFeatureMode featureMode,
      String expectedSha256,
      String label
  ) {
    if (file == null || !file.isFile()) {
      throw new IllegalStateException(
          label + " evaluation file does not exist: " +
          (file == null ? "<not configured>" : file.getPath()));
    }
    final String actualSha256;
    try {
      validate_evaluation_file(file);
      actualSha256 = sha256(file);
    } catch (IOException e) {
      throw new IllegalStateException(
          "invalid " + label + " evaluation file: " + e.getMessage(), e);
    }
    if (expectedSha256 != null &&
        !expectedSha256.equalsIgnoreCase(actualSha256)) {
      throw new IllegalStateException(
          label + " evaluation SHA-256 does not match model bundle");
    }

    EvaluatorTables tables = new EvaluatorTables(featureMode);
    tables.sha256 = actualSha256;
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

          pre_evaluation(
              tables, pattern_idx, phase_idx, pattern_idx, ps,
              dense0, bias0, dense1, bias1, dense2, bias2);
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

        pre_evaluation_add(
            tables, phase_idx,
            add_dense0, add_bias0, add_dense1, add_bias1);

        // all_dense
        for (int i = 0; i < n_all_input; i++) {
          line = br.readLine();
          tables.dense[phase_idx][i] = Double.parseDouble(line);
        }
        // all_bias
        line = br.readLine();
        tables.bias[phase_idx] = Double.parseDouble(line);
      }
    } catch (IOException e) {
      throw new IllegalStateException(
          "failed to load " + label + " evaluation file: " +
          file.getPath(), e);
    }
    return tables;
  }

  static void init_evaluation() {
    ModelBundle bundle = loadModelBundle();
    ValueFeatureMode requestedFeature =
        REQUESTED_VALUE_FEATURE_MODE.isBlank()
            ? null
            : parseValueFeatureMode(REQUESTED_VALUE_FEATURE_MODE);

    if (bundle == null) {
      throw new IllegalStateException(
          "original_13 requires its validated resources/model.properties");
    }

    if (requestedFeature != null &&
        requestedFeature != ValueFeatureMode.EXACT_MOBILITY) {
      throw new IllegalStateException(
          "model bundle exact-mobility-v1 conflicts with legacy feature mode");
    }
    model_bundle_sha256 = bundle.manifestSha256;
    File valueFile = configuredOverride(
        "othello.param", "OTHELLO_PARAM", bundle.valueFile);
    value_evaluator = loadEvaluator(
        valueFile, ValueFeatureMode.EXACT_MOBILITY,
        bundle.valueSha256, "value");
    value_param_sha256 = value_evaluator.sha256;

    policy_evaluator = null;
    policy_param_sha256 = "off";
    active_policy_mode = "off";
    if (POLICY_MODE == PolicyMode.OFF) return;

    File policyFile = configuredOverride(
        "othello.policy", "OTHELLO_POLICY_FILE", bundle.policyFile);
    if (policyFile == null || !policyFile.isFile()) {
      if (POLICY_MODE == PolicyMode.REQUIRED) {
        throw new IllegalStateException(
            "required policy evaluation file does not exist: " +
            (policyFile == null ? "<not configured>" : policyFile.getPath()));
      }
      return;
    }
    if (bundle.policySha256 == null) {
      throw new IllegalStateException(
          "model bundle must bind policy.sha256 before policy can be loaded");
    }
    policy_evaluator = loadEvaluator(
        policyFile, ValueFeatureMode.EXACT_MOBILITY,
        bundle.policySha256, "policy");
    policy_param_sha256 = policy_evaluator.sha256;
    active_policy_mode = "learned";
  }

  static final int[] search_table_generation = new int[2];

  static void search_hash_table_init(int table_idx) {
      if (search_table_generation[table_idx] == Integer.MAX_VALUE) {
          for (SearchNode node : search_replace_table[table_idx]) {
              if (node != null) node.reg = false;
          }
          search_table_generation[table_idx] = 1;
      } else {
          search_table_generation[table_idx]++;
      }
  }

  static int calc_search_hash(Board b) {
    return (int) ((calc_hash(b.b) * 2L + b.p) & search_hash_mask);
  }


  static void register_search(int table_idx, Board board, int hash, int l, int u) {
      SearchNode node = search_replace_table[table_idx][hash];
      if (node == null) {
          SearchNode newNode = new SearchNode();
          newNode.reg = true;
          newNode.generation = search_table_generation[table_idx];
          for (int i = 0; i < 4; i++) {
              newNode.k[i] = board.b[i * 2] + board.b[i * 2 + 1] * n_line;
          }
          newNode.p = board.p;
          newNode.l = l;
          newNode.u = u;
          newNode.stamp = 2;
          search_replace_table[table_idx][hash] = newNode;
      } else {
          synchronized (node) {
            int writeStamp = node.stamp + 1;
            if ((writeStamp & 1) == 0) writeStamp++;
            node.stamp = writeStamp;
            node.reg = true;
            node.generation = search_table_generation[table_idx];
            for (int i = 0; i < 4; i++) {
                node.k[i] = board.b[i * 2] + board.b[i * 2 + 1] * n_line;
            }
            node.p = board.p;
            node.l = l;
            node.u = u;
            node.stamp = writeStamp + 1;
          }
      }
  }

  static long packBounds(int lower, int upper) {
      return ((long) lower << 32) | (upper & 0xffff_ffffL);
  }

  static int lowerBound(long bounds) {
      return (int) (bounds >> 32);
  }

  static int upperBound(long bounds) {
      return (int) bounds;
  }

  static long get_search(Board board, int hash, int table_idx) {
      SearchNode node = search_replace_table[table_idx][hash];
      if (node != null) {
          int stamp = node.stamp;
          if ((stamp & 1) == 0 && node.reg &&
              node.generation == search_table_generation[table_idx] &&
              node.p == board.p && compare_key(board.b, node.k)) {
              int lower = node.l;
              int upper = node.u;
              if (stamp != node.stamp) {
                return packBounds(-inf, -inf);
              }
              local_search_stats.get().generalTtHits++;
              return packBounds(lower, upper);
          }
      }
      return packBounds(-inf, -inf);
  }

  static int calc_canput_exact(Board b) {
    return Long.bitCount(legalMoves(b));
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

  static int calc_canput_legacy(Board b) {
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

  static int calc_canput(Board b, ValueFeatureMode featureMode) {
    if (featureMode == ValueFeatureMode.LEGACY) {
      return calc_canput_legacy(b);
    }
    int mobility =
        Math.min(max_canput, Long.bitCount(legalMoves(b)));
    return b.p == 0 ? mobility : -mobility;
  }

  static int calc_canput(Board b) {
    return calc_canput(
        b,
        value_evaluator == null
            ? ValueFeatureMode.LEGACY
            : value_evaluator.featureMode);
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

  static double edge_2x(
      EvaluatorTables tables,
      int phase_idx,
      int[] b,
      int x,
      int y
  ) {
    return tables.pattern[phase_idx][7]
      [pop_digit[b[x]][1] * p39 + b[y] * p31 + pop_digit[b[x]][6]];
  }

  static double triangle0(
      EvaluatorTables tables,
      int phase_idx,
      int[] b,
      int w,
      int x,
      int y,
      int z
  ) {
    return tables.pattern[phase_idx][8]
      [b[w] / p34 * p36 + b[x] / p35 * p33 + b[y] / p36 * p31 + b[z] / p37];
  }

  static double triangle1(
      EvaluatorTables tables,
      int phase_idx,
      int[] b,
      int w,
      int x,
      int y,
      int z
  ) {
    return tables.pattern[phase_idx][8]
      [reverse_board[b[w]] / p34 * p36 + reverse_board[b[x]] / p35 * p33 +
      reverse_board[b[y]] / p36 * p31 + reverse_board[b[z]] / p37];
  }

  static double edge_block(
      EvaluatorTables tables,
      int phase_idx,
      int[] b,
      int x,
      int y
  ) {
    return tables.pattern[phase_idx][9]
      [pop_digit[b[x]][0] * p39 +
      pop_mid[b[x]][6][2] * p35 +
      pop_digit[b[x]][7] * p34 +
      pop_mid[b[y]][6][2]];
  }

  static double cross(
      EvaluatorTables tables,
      int phase_idx,
      int[] b,
      int x,
      int y,
      int z
  ) {
    return tables.pattern[phase_idx][10]
            [b[x] / p34 * p36 + b[y] / p35 * p33 + b[z] / p35]
        + tables.pattern[phase_idx][10]
            [reverse_board[b[x]] / p34 * p36
              + pop_mid[reverse_board[b[y]]][7][4] * p33
              + pop_mid[reverse_board[b[z]]][7][4]];
  }

  static double calc_pattern(
      EvaluatorTables tables,
      int phase_idx,
      Board b
  ) {
    return tables.dense[phase_idx][0] * (tables.pattern[phase_idx][0][b.b[1]] + tables.pattern[phase_idx][0][b.b[6]] +
                                      tables.pattern[phase_idx][0][b.b[9]] + tables.pattern[phase_idx][0][b.b[14]]) +
          tables.dense[phase_idx][1] * (tables.pattern[phase_idx][1][b.b[2]] + tables.pattern[phase_idx][1][b.b[5]] +
                                      tables.pattern[phase_idx][1][b.b[10]] + tables.pattern[phase_idx][1][b.b[13]]) +
          tables.dense[phase_idx][2] * (tables.pattern[phase_idx][2][b.b[3]] + tables.pattern[phase_idx][2][b.b[4]] +
                                      tables.pattern[phase_idx][2][b.b[11]] + tables.pattern[phase_idx][2][b.b[12]]) +
          tables.dense[phase_idx][3] * (tables.pattern[phase_idx][3][b.b[18] / p33] + tables.pattern[phase_idx][3][b.b[24] / p33] +
                                      tables.pattern[phase_idx][3][b.b[29] / p33] + tables.pattern[phase_idx][3][b.b[35] / p33]) +
          tables.dense[phase_idx][4] * (tables.pattern[phase_idx][4][b.b[19] / p32] + tables.pattern[phase_idx][4][b.b[23] / p32] +
                                      tables.pattern[phase_idx][4][b.b[30] / p32] + tables.pattern[phase_idx][4][b.b[34] / p32]) +
          tables.dense[phase_idx][5] * (tables.pattern[phase_idx][5][b.b[20] / p31] + tables.pattern[phase_idx][5][b.b[22] / p31] +
                                      tables.pattern[phase_idx][5][b.b[31] / p31] + tables.pattern[phase_idx][5][b.b[33] / p31]) +
          tables.dense[phase_idx][6] * (tables.pattern[phase_idx][6][b.b[21]] + tables.pattern[phase_idx][6][b.b[32]]) +
          tables.dense[phase_idx][7] * (edge_2x(tables, phase_idx, b.b, 1, 0) + edge_2x(tables, phase_idx, b.b, 6, 7) +
                                      edge_2x(tables, phase_idx, b.b, 9, 8) + edge_2x(tables, phase_idx, b.b, 14, 15)) +
          tables.dense[phase_idx][8] * (triangle0(tables, phase_idx, b.b, 0, 1, 2, 3) + triangle0(tables, phase_idx, b.b, 7, 6, 5, 4) +
                                      triangle0(tables, phase_idx, b.b, 15, 14, 13, 12) + triangle1(tables, phase_idx, b.b, 15, 14, 13, 12)) +
          tables.dense[phase_idx][9] * (edge_block(tables, phase_idx, b.b, 0, 1) + edge_block(tables, phase_idx, b.b, 7, 6) +
                                      edge_block(tables, phase_idx, b.b, 8, 9) + edge_block(tables, phase_idx, b.b, 15, 14)) +
          tables.dense[phase_idx][10] * (cross(tables, phase_idx, b.b, 21, 20, 22) + cross(tables, phase_idx, b.b, 32, 31, 33));
  }

  static double rawEvaluate(EvaluatorTables tables, Board b) {
      int phase_idx = calc_phase_idx(b);
      int canput = Math.min(
          max_canput * 2,
          Math.max(0, max_canput + calc_canput(b, tables.featureMode)));
      int sur0 = Math.min(max_surround, calc_surround(b, 0));
      int sur1 = Math.min(max_surround, calc_surround(b, 1));
      
      double[] add_values =
          tables.additions[phase_idx][canput][sur0][sur1];
      
      double res = tables.bias[phase_idx] + calc_pattern(tables, phase_idx, b)
          + tables.dense[phase_idx][11] * add_values[0]
          + tables.dense[phase_idx][12] * add_values[1]
          + tables.dense[phase_idx][13] * add_values[2]
          + tables.dense[phase_idx][14] * add_values[3]
          + tables.dense[phase_idx][15] * add_values[4]
          + tables.dense[phase_idx][16] * add_values[5]
          + tables.dense[phase_idx][17] * add_values[6]
          + tables.dense[phase_idx][18] * add_values[7];

      if (b.p != 0) res = -res;
      return res;
  }

  static int evaluate(Board b) {
      double logit = rawEvaluate(value_evaluator, b);
      // BCE trains an unbounded win-probability logit. Convert it to the
      // engine's signed [-1,+1] score domain:
      // 2*sigmoid(logit)-1 == tanh(logit/2).
      return (int) (Math.tanh(logit * 0.5) * sc_w);
  }

  static int policyEvaluate(Board b) {
    if (policy_evaluator == null) return evaluate(b);
    local_search_stats.get().policyEvaluations++;
    double raw = rawEvaluate(policy_evaluator, b);
    return (int) Math.round(Math.tanh(raw) * sc_w);
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

  static boolean mpcEnabled() {
    return MPC_MODE != MpcMode.OFF;
  }

  static boolean nestedMpcEnabled() {
    return MPC_MODE == MpcMode.LEGACY;
  }

  static boolean mpc_higher(Board b, boolean skipped, int depth, int beta) {
    int phase = Math.min(5, (b.n - 4) / 10); // ★修正: 上限を5に制限
    int bound = beta + mpctsd[phase][depth];
    SearchStats stats = local_search_stats.get();
    stats.mpcAttempts++;
    boolean cut = negaAlphaInternal(
        b, skipped, mpcd[depth], bound - epsilon, bound,
        nestedMpcEnabled()) >= bound;
    if (cut) stats.mpcCuts++;
    return cut;
  }

  static boolean mpc_lower(Board b, boolean skipped, int depth, int alpha) {
    int phase = Math.min(5, (b.n - 4) / 10); // ★修正: 上限を5に制限
    int bound = alpha - mpctsd[phase][depth];
    SearchStats stats = local_search_stats.get();
    stats.mpcAttempts++;
    boolean cut = negaAlphaInternal(
        b, skipped, mpcd[depth], bound, bound + epsilon,
        nestedMpcEnabled()) <= bound;
    if (cut) stats.mpcCuts++;
    return cut;
  }

  static boolean mpc_higher_final(Board b, boolean skipped, int depth, int beta) {
    int bound = beta + mpctsd_final[depth];
    SearchStats stats = local_search_stats.get();
    stats.mpcAttempts++;
    boolean cut = negaAlphaInternal(
        b, skipped, mpcd[depth], bound - epsilon, bound,
        nestedMpcEnabled()) >= bound;
    if (cut) stats.mpcCuts++;
    return cut;
  }

  static boolean mpc_lower_final(Board b, boolean skipped, int depth, int alpha) {
    int bound = alpha - mpctsd_final[depth];
    SearchStats stats = local_search_stats.get();
    stats.mpcAttempts++;
    boolean cut = negaAlphaInternal(
        b, skipped, mpcd[depth], bound, bound + epsilon,
        nestedMpcEnabled()) <= bound;
    if (cut) stats.mpcCuts++;
    return cut;
  }

  static void move_ordering(Board b) {
    int hash = calc_search_hash(b);
    SearchNode node = search_replace_table[f_search_table_idx][hash];
    if (node != null) {
      int stamp = node.stamp;
      if ((stamp & 1) == 0 && node.reg &&
          node.generation == search_table_generation[f_search_table_idx] &&
          node.p == b.p && compare_key(b.b, node.k)) {
        int lower = node.l;
        int upper = node.u;
        if (stamp == node.stamp) {
          b.v = -Math.max(lower, upper);
          b.v += cache_hit;
          if (upper != -inf && lower != -inf) b.v += cache_both;
          return;
        }
      }
    }
    // Preserve original_06's learned-evaluation ordering. Extra mobility
    // weights must be tuned independently instead of being mixed into the
    // bitboard speed change.
    b.v = -policyEvaluate(b);
  }

  static int generateOrderedChildren(
      Board board,
      int depth,
      Board[] children,
      boolean finalOrdering
  ) {
    SearchWorkspace workspace = search_workspace.get();
    int count = 0;
    long moves = legalMoves(board);
    // vacant_cells is sorted by original_06's static square preference. Testing
    // membership against one bulk bitboard keeps that ordering without
    // returning to four line-table legality probes per square.
    for (int vacantIndex = 0; vacantIndex < vacant_count; vacantIndex++) {
      int cell = vacant_cells[vacantIndex];
      long moveBit = 1L << cell;
      if ((moves & moveBit) == 0L) continue;
      Board next = workspace.board(depth, count);
      moveInto(board, cell, next);
      move_ordering(next);
      if (finalOrdering) {
        next.v -= 100 * Long.bitCount(legalMoves(next));
      }
      children[count++] = next;
    }
    return count;
  }

  static int last1(Board b, boolean skipped, int p0) {
    visitNode();
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
    visitNode();
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
    visitNode();
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
    long empty = b.hasBitboards ? b.emptyMask : 0L;
    if (!b.hasBitboards) {
      ensureBitboards(b);
      empty = b.emptyMask;
    }
    while (empty != 0L) {
      long bit = empty & -empty;
      cells[idx++] = Long.numberOfTrailingZeros(bit);
      empty ^= bit;
    }
  }

  static final int[] BIT_DR = {-1, -1, -1, 0, 0, 1, 1, 1};
  static final int[] BIT_DC = {-1, 0, 1, -1, 1, -1, 0, 1};

  /**
   * Egaroucid's generic Kogge-Stone mobility generator, translated to Java.
   * Every unsigned C++ right shift is deliberately represented by >>>.
   */
  static long bitboardLegalMoves(long player, long opponent) {
    long maskedOpponent = opponent & HORIZONTAL_MASK;
    long flip1 = maskedOpponent & (player << 1);
    long flip7 = maskedOpponent & (player << 7);
    long flip9 = maskedOpponent & (player << 9);
    long flip8 = opponent & (player << 8);

    flip1 |= maskedOpponent & (flip1 << 1);
    flip7 |= maskedOpponent & (flip7 << 7);
    flip9 |= maskedOpponent & (flip9 << 9);
    flip8 |= opponent & (flip8 << 8);

    long pre1 = maskedOpponent & (maskedOpponent << 1);
    long pre7 = maskedOpponent & (maskedOpponent << 7);
    long pre9 = maskedOpponent & (maskedOpponent << 9);
    long pre8 = opponent & (opponent << 8);

    flip1 |= pre1 & (flip1 << 2);
    flip7 |= pre7 & (flip7 << 14);
    flip9 |= pre9 & (flip9 << 18);
    flip8 |= pre8 & (flip8 << 16);
    flip1 |= pre1 & (flip1 << 2);
    flip7 |= pre7 & (flip7 << 14);
    flip9 |= pre9 & (flip9 << 18);
    flip8 |= pre8 & (flip8 << 16);

    long moves = (flip1 << 1) | (flip7 << 7) | (flip9 << 9) | (flip8 << 8);

    flip1 = maskedOpponent & (player >>> 1);
    flip7 = maskedOpponent & (player >>> 7);
    flip9 = maskedOpponent & (player >>> 9);
    flip8 = opponent & (player >>> 8);

    flip1 |= maskedOpponent & (flip1 >>> 1);
    flip7 |= maskedOpponent & (flip7 >>> 7);
    flip9 |= maskedOpponent & (flip9 >>> 9);
    flip8 |= opponent & (flip8 >>> 8);

    pre1 >>>= 1;
    pre7 >>>= 7;
    pre9 >>>= 9;
    pre8 >>>= 8;

    flip1 |= pre1 & (flip1 >>> 2);
    flip7 |= pre7 & (flip7 >>> 14);
    flip9 |= pre9 & (flip9 >>> 18);
    flip8 |= pre8 & (flip8 >>> 16);
    flip1 |= pre1 & (flip1 >>> 2);
    flip7 |= pre7 & (flip7 >>> 14);
    flip9 |= pre9 & (flip9 >>> 18);
    flip8 |= pre8 & (flip8 >>> 16);

    moves |= (flip1 >>> 1) | (flip7 >>> 7) | (flip9 >>> 9) | (flip8 >>> 8);
    return moves & ~(player | opponent);
  }

  static long rayFlipsLeft(long move, long player, long opponent, int shift, long mask) {
    long maskedOpponent = opponent & mask;
    long captured = maskedOpponent & (move << shift);
    long frontier = captured;
    for (int i = 0; i < 5; i++) {
      frontier = maskedOpponent & (frontier << shift);
      captured |= frontier;
    }
    return ((captured << shift) & player) != 0L ? captured : 0L;
  }

  static long rayFlipsRight(long move, long player, long opponent, int shift, long mask) {
    long maskedOpponent = opponent & mask;
    long captured = maskedOpponent & (move >>> shift);
    long frontier = captured;
    for (int i = 0; i < 5; i++) {
      frontier = maskedOpponent & (frontier >>> shift);
      captured |= frontier;
    }
    return ((captured >>> shift) & player) != 0L ? captured : 0L;
  }

  /**
   * Returns every opponent disc flipped by {@code cell}, or zero for an
   * occupied/illegal move. The propagation is branch-free per direction and
   * avoids the eight row/column walks used by original_06.
   */
  static long bitboardFlips(long player, long opponent, int cell) {
    long move = 1L << cell;
    if (((player | opponent) & move) != 0L) return 0L;
    return rayFlipsLeft(move, player, opponent, 1, HORIZONTAL_MASK)
        | rayFlipsRight(move, player, opponent, 1, HORIZONTAL_MASK)
        | rayFlipsLeft(move, player, opponent, 7, HORIZONTAL_MASK)
        | rayFlipsRight(move, player, opponent, 7, HORIZONTAL_MASK)
        | rayFlipsLeft(move, player, opponent, 9, HORIZONTAL_MASK)
        | rayFlipsRight(move, player, opponent, 9, HORIZONTAL_MASK)
        | rayFlipsLeft(move, player, opponent, 8, -1L)
        | rayFlipsRight(move, player, opponent, 8, -1L);
  }

  static long boardBits(Board board, int disk) {
    ensureBitboards(board);
    return disk == 0 ? board.blackBits : board.whiteBits;
  }

  static long boardBitsFromLines(Board board, int disk) {
    long bits = 0L;
    for (int row = 0; row < hw; row++) {
      int line = board.b[row];
      for (int col = 0; col < hw; col++) {
        if (pop_digit[line][col] == disk) bits |= 1L << (row * hw + col);
      }
    }
    return bits;
  }

  static long boardPlayerBits(Board board) {
    ensureBitboards(board);
    return board.p == 0 ? board.blackBits : board.whiteBits;
  }

  static long boardOpponentBits(Board board) {
    ensureBitboards(board);
    return board.p == 0 ? board.whiteBits : board.blackBits;
  }

  static long legalMoves(Board board) {
    return bitboardLegalMoves(boardPlayerBits(board), boardOpponentBits(board));
  }

  static int bitboardTerminalScore(long player, long opponent, long empty) {
    int score = Long.bitCount(player) - Long.bitCount(opponent);
    int vacant = Long.bitCount(empty);
    if (score > 0) score += vacant;
    else if (score < 0) score -= vacant;
    return score * step;
  }

  static int exactHash(long player, long opponent, boolean skipped) {
    long z = player ^ Long.rotateLeft(opponent, 23);
    if (skipped) z ^= 0x9e3779b97f4a7c15L;
    z ^= z >>> 33;
    z *= 0xff51afd7ed558ccdL;
    z ^= z >>> 33;
    return (int) z & exact_tt_mask;
  }

  static long oddParityRegions(long empty) {
    long odd = 0L;
    for (long region : PARITY_REGIONS) {
      if ((Long.bitCount(empty & region) & 1) != 0) odd |= region;
    }
    return odd;
  }

  static long stableEdgeBits(long color) {
    long stable = 0L;
    for (int i = 0; i < EDGE_CORNERS.length; i++) {
      int corner = EDGE_CORNERS[i];
      long cornerBit = 1L << corner;
      if ((color & cornerBit) == 0L) continue;
      stable |= cornerBit;
      for (int direction : EDGE_DIRECTIONS[i]) {
        int cell = corner + direction;
        for (int length = 1; length < 8; length++, cell += direction) {
          long bit = 1L << cell;
          if ((color & bit) == 0L) break;
          stable |= bit;
        }
      }
    }
    return stable;
  }

  /**
   * Egaroucid-style endgame ordering: odd-region moves first, then corners,
   * low opponent mobility and the static square preference. Selection is done
   * directly from a bit set, so no Board/List allocation occurs in exact play.
   */
  static int selectExactMove(long player, long opponent, long empty, long moves) {
    long oddRegions = oddParityRegions(empty);
    int bestCell = Long.numberOfTrailingZeros(moves);
    int bestScore = Integer.MIN_VALUE;
    long remaining = moves;
    while (remaining != 0L) {
      long move = remaining & -remaining;
      int cell = Long.numberOfTrailingZeros(move);
      long flips = bitboardFlips(player, opponent, cell);
      int score;
      if (flips == opponent) {
        score = Integer.MAX_VALUE;
      } else {
        long nextPlayer = opponent & ~flips;
        long nextOpponent = player | flips | move;
        int opponentMobility =
            Long.bitCount(bitboardLegalMoves(nextPlayer, nextOpponent));
        score = cell_weight[cell] * 32 - opponentMobility * 256;
        if ((move & oddRegions) != 0L) score += 16_384;
        if ((move & 0x8100000000000081L) != 0L) score += 32_768;
      }
      if (score > bestScore || (score == bestScore && cell < bestCell)) {
        bestScore = score;
        bestCell = cell;
      }
      remaining ^= move;
    }
    return bestCell;
  }

  static int orderExactMoves(
      long player,
      long opponent,
      long empty,
      long moves,
      ExactTranspositionTable table,
      int ply
  ) {
    int[] cells = table.orderedCells[ply];
    long[] flipsByMove = table.orderedFlips[ply];
    int[] scores = table.orderedScores[ply];
    long oddRegions = oddParityRegions(empty);
    int count = 0;
    long remaining = moves;
    while (remaining != 0L) {
      long move = remaining & -remaining;
      int cell = Long.numberOfTrailingZeros(move);
      long flips = bitboardFlips(player, opponent, cell);
      int score;
      if (flips == opponent) {
        score = Integer.MAX_VALUE;
      } else {
        long nextPlayer = opponent & ~flips;
        long nextOpponent = player | flips | move;
        int opponentMobility =
            Long.bitCount(bitboardLegalMoves(nextPlayer, nextOpponent));
        score = cell_weight[cell] * 32 - opponentMobility * 256;
        if ((move & oddRegions) != 0L) score += 16_384;
        if ((move & 0x8100000000000081L) != 0L) score += 32_768;
      }

      int insertion = count;
      while (insertion > 0 &&
             (score > scores[insertion - 1] ||
              (score == scores[insertion - 1] &&
               cell < cells[insertion - 1]))) {
        cells[insertion] = cells[insertion - 1];
        flipsByMove[insertion] = flipsByMove[insertion - 1];
        scores[insertion] = scores[insertion - 1];
        insertion--;
      }
      cells[insertion] = cell;
      flipsByMove[insertion] = flips;
      scores[insertion] = score;
      count++;
      remaining ^= move;
    }
    return count;
  }

  static void storeExact(
      ExactTranspositionTable table,
      int index,
      long player,
      long opponent,
      boolean skipped,
      int value,
      int originalAlpha,
      int originalBeta
  ) {
    boolean same =
        table.flags[index] != 0 &&
        table.players[index] == player &&
        table.opponents[index] == opponent &&
        table.skipped[index] == skipped;
    if (!same) {
      table.players[index] = player;
      table.opponents[index] = opponent;
      table.skipped[index] = skipped;
      table.flags[index] = 0;
    }
    if (value <= originalAlpha) {
      table.upper[index] = value;
      table.flags[index] |= 2;
    } else if (value >= originalBeta) {
      table.lower[index] = value;
      table.flags[index] |= 1;
    } else {
      table.lower[index] = value;
      table.upper[index] = value;
      table.flags[index] = 3;
    }
  }

  /**
   * Exact allocation-free endgame search. The score is from the current
   * {@code player}'s perspective. Passing does not consume an empty square.
   */
  static int bitboardExact(
      long player,
      long opponent,
      long empty,
      boolean skipped,
      int alpha,
      int beta
  ) {
    return bitboardExactImpl(
        player, opponent, empty, skipped, alpha, beta, exact_tt.get(), 0);
  }

  static int bitboardExactImpl(
      long player,
      long opponent,
      long empty,
      boolean skipped,
      int alpha,
      int beta,
      ExactTranspositionTable table,
      int ply
  ) {
    visitNode();
    local_search_stats.get().exactNodes++;
    int originalAlpha = alpha;
    int originalBeta = beta;
    int tableIndex = exactHash(player, opponent, skipped);
    byte flags = table.flags[tableIndex];
    if (flags != 0 &&
        table.players[tableIndex] == player &&
        table.opponents[tableIndex] == opponent &&
        table.skipped[tableIndex] == skipped) {
      local_search_stats.get().exactTtHits++;
      if ((flags & 1) != 0) {
        int lower = table.lower[tableIndex];
        if (lower >= beta) return lower;
        alpha = Math.max(alpha, lower);
      }
      if ((flags & 2) != 0) {
        int upper = table.upper[tableIndex];
        if (upper <= alpha) return upper;
        beta = Math.min(beta, upper);
      }
      if ((flags & 3) == 3 &&
          table.lower[tableIndex] == table.upper[tableIndex]) {
        return table.lower[tableIndex];
      }
    }

    // Conservative stability cutoff: only same-colour edge chains anchored
    // at occupied corners are classified as stable.
    if (Long.bitCount(empty) >= 8) {
      int stableLower =
          (2 * Long.bitCount(stableEdgeBits(player)) - hw2) * step;
      int stableUpper =
          (hw2 - 2 * Long.bitCount(stableEdgeBits(opponent))) * step;
      if (stableLower >= beta) {
        local_search_stats.get().stabilityCuts++;
        return stableLower;
      }
      if (stableUpper <= alpha) {
        local_search_stats.get().stabilityCuts++;
        return stableUpper;
      }
      alpha = Math.max(alpha, stableLower);
      beta = Math.min(beta, stableUpper);
    }

    long legalMoves = bitboardLegalMoves(player, opponent) & empty;
    if (legalMoves == 0L) {
      int value = skipped
          ? bitboardTerminalScore(player, opponent, empty)
          : -bitboardExactImpl(
              opponent, player, empty, true, -beta, -alpha, table, ply + 1);
      storeExact(
          table, tableIndex, player, opponent, skipped,
          value, originalAlpha, originalBeta);
      return value;
    }

    int moveCount =
        orderExactMoves(player, opponent, empty, legalMoves, table, ply);
    int[] orderedCells = table.orderedCells[ply];
    long[] orderedFlips = table.orderedFlips[ply];
    int best = -inf;
    for (int moveIndex = 0; moveIndex < moveCount; moveIndex++) {
      int cell = orderedCells[moveIndex];
      long moveBit = 1L << cell;
      long flips = orderedFlips[moveIndex];
      if (flips == opponent) {
        storeExact(
            table, tableIndex, player, opponent, skipped,
            sc_w, originalAlpha, originalBeta);
        return sc_w;
      }
      long nextPlayer = opponent & ~flips;
      long nextOpponent = player | flips | moveBit;
      int score = -bitboardExactImpl(
          nextPlayer, nextOpponent, empty ^ moveBit, false,
          -beta, -alpha, table, ply + 1);
      if (score > best) best = score;
      if (score > alpha) alpha = score;
      if (alpha >= beta) {
        storeExact(
            table, tableIndex, player, opponent, skipped,
            alpha, originalAlpha, originalBeta);
        return alpha;
      }
    }
    storeExact(
        table, tableIndex, player, opponent, skipped,
        best, originalAlpha, originalBeta);
    return best;
  }

  static int negaAlphaFinal(Board b, boolean skipped, int depth, int alpha, int beta) {
    long player = boardPlayerBits(b);
    long opponent = boardOpponentBits(b);
    return bitboardExact(player, opponent, b.emptyMask, skipped, alpha, beta);
  }

  static int negaAlphaOrderingFinal(Board b, long strt, boolean skipped, int depth, int alpha, int beta) {
    visitNode();
    if (depth <= exact_kernel_depth) {
      return negaAlphaFinal(b, skipped, depth, alpha, beta);
    }
    if (mpcEnabled() &&
        mpc_min_depth_final <= depth && depth <= mpc_max_depth_final) {
      if (mpc_higher_final(b, skipped, depth, beta)) return beta + step;
      if (mpc_lower_final(b, skipped, depth, alpha)) return alpha - step;
    }

    int hash = calc_search_hash(b);
    long bounds = get_search(b, hash, 1 - f_search_table_idx);
    int l = lowerBound(bounds);
    int u = upperBound(bounds);
    if (l != -inf) {
      if (l == u) return l;
      alpha = Math.max(alpha, l);
      if (alpha >= beta) return alpha;
    }
    if (u != -inf) {
      beta = Math.min(beta, u);
      if (alpha >= beta) return alpha;
    }

    SearchWorkspace workspace = search_workspace.get();
    Board[] nb = workspace.boards(depth);
    int canput = generateOrderedChildren(b, depth, nb, true);

    if (canput == 0) {
      if (skipped) return end_game(b);
      Board rb = workspace.passBoard(depth);
      passInto(b, rb);
      return -negaAlphaOrderingFinal(rb, strt, true, depth, -beta, -alpha);
    }

    if (canput >= 2) stableSortBoards(nb, canput);

    int v = -inf;
    int first_alpha = alpha;
    for (int idx = 0; idx < canput; idx++) {
      Board nnb = nb[idx];
      int g = -negaAlphaOrderingFinal(nnb, strt, false, depth - 1, -beta, -alpha);
      alpha = Math.max(alpha, g);
      if (beta <= alpha) {
        if (l < g) register_search(1 - f_search_table_idx, b, hash, alpha, u);
        return alpha;
      }
      v = Math.max(v, g);
    }

    if (v <= first_alpha)
      register_search(1 - f_search_table_idx, b, hash, l, v);
    else
      register_search(1 - f_search_table_idx, b, hash, v, v);

    return v;
  }

  static int negaScoutFinal(Board b, long strt, boolean skipped, int depth, int alpha, int beta) {
    visitNode();
    if (depth <= exact_kernel_depth) {
      return negaAlphaFinal(b, skipped, depth, alpha, beta);
    }

    int hash = calc_search_hash(b);
    long bounds = get_search(b, hash, 1 - f_search_table_idx);
    int l = lowerBound(bounds);
    int u = upperBound(bounds);
    if (l != -inf) {
      if (l == u) return l;
      alpha = Math.max(alpha, l);
      if (alpha >= beta) return alpha;
    }
    if (u != -inf) {
      beta = Math.min(beta, u);
      if (alpha >= beta) return alpha;
    }

    SearchWorkspace workspace = search_workspace.get();
    Board[] nb = workspace.boards(depth);
    int canput = generateOrderedChildren(b, depth, nb, true);

    if (canput == 0) {
      if (skipped) return end_game(b);
      Board rb = workspace.passBoard(depth);
      passInto(b, rb);
      return -negaScoutFinal(rb, strt, true, depth, -beta, -alpha);
    }

    if (canput >= 2) stableSortBoards(nb, canput);

    int g = alpha, v = -inf, first_alpha = alpha;
    for (int idx = 0; idx < canput; idx++) {
      Board nnb = nb[idx];
      if (idx != 0) {
        g = -negaAlphaOrderingFinal(nnb, strt, false, depth - 1, -alpha - step, -alpha);
        if (beta <= g) {
          if (l < g) register_search(1 - f_search_table_idx, b, hash, g, u);
          return g;
        }
        v = Math.max(v, g);
      }
      if (alpha <= g) {
        g = -negaScoutFinal(nnb, strt, false, depth - 1, -beta, -g);
        if (beta <= g) {
          if (l < g) register_search(1 - f_search_table_idx, b, hash, g, u);
          return g;
        }
        alpha = Math.max(alpha, g);
        v = Math.max(v, g);
      }
    }

    if (v <= first_alpha)
      register_search(1 - f_search_table_idx, b, hash, l, v);
    else
      register_search(1 - f_search_table_idx, b, hash, v, v);

    return v;
  }

  static int nega_alpha(Board b, boolean skipped, int depth, int alpha, int beta) {
    return negaAlphaInternal(
        b, skipped, depth, alpha, beta, mpcEnabled());
  }

  static int negaAlphaInternal(
      Board b,
      boolean skipped,
      int depth,
      int alpha,
      int beta,
      boolean allowMpc
  ) {
    visitNode();
    long moves = legalMoves(b);
    if (depth == 0) {
      if (moves != 0L) return evaluate(b);
      if (b.n >= hw2 || skipped) return end_game(b);
      Board passedBoard = search_workspace.get().passBoard(0);
      passInto(b, passedBoard);
      return -negaAlphaInternal(
          passedBoard, true, 0, -beta, -alpha, allowMpc);
    }
    if (allowMpc && mpcEnabled() &&
        mpc_min_depth <= depth && depth <= mpc_max_depth) {
      if (mpc_higher(b, skipped, depth, beta + epsilon)) return beta + epsilon;
      if (mpc_lower(b, skipped, depth, alpha - epsilon)) return alpha - epsilon;
    } else if (!allowMpc && mpcEnabled() &&
               mpc_min_depth <= depth && depth <= mpc_max_depth) {
      local_search_stats.get().mpcNestedSuppressed++;
    }

    Board nb = search_workspace.get().board(depth, 0);
    boolean passed = true;
    int v = -inf;

    for (int vacantIndex = 0; vacantIndex < vacant_count; vacantIndex++) {
      int cell = vacant_cells[vacantIndex];
      long moveBit = 1L << cell;
      if ((moves & moveBit) == 0L) continue;
      passed = false;
      moveInto(b, cell, nb);
      int g = -negaAlphaInternal(
          nb, false, depth - 1, -beta, -alpha, allowMpc);
      alpha = Math.max(alpha, g);
      if (beta <= alpha) return alpha;
      v = Math.max(v, g);
    }

    if (passed) {
      if (skipped) return end_game(b);
      Board rb = search_workspace.get().passBoard(depth);
      passInto(b, rb);
      return -negaAlphaInternal(
          rb, true, depth, -beta, -alpha, allowMpc);
    }
    return v;
  }

  static int negaAlphaOrdering(Board b, long strt, boolean skipped, int depth, int alpha, int beta) {
    visitNode();
    if (mpcEnabled() &&
        mpc_min_depth <= depth && depth <= mpc_max_depth) {
      if (mpc_higher(b, skipped, depth, beta + epsilon)) return beta + epsilon;
      if (mpc_lower(b, skipped, depth, alpha - epsilon)) return alpha - epsilon;
    }
    if (depth <= 3) return nega_alpha(b, skipped, depth, alpha, beta);

    int hash = calc_search_hash(b);
    long bounds = get_search(b, hash, 1 - f_search_table_idx);
    int l = lowerBound(bounds);
    int u = upperBound(bounds);
    if (l != -inf) {
      if (l == u) return l;
      alpha = Math.max(alpha, l);
      if (alpha >= beta) return alpha;
    }
    if (u != -inf) {
      beta = Math.min(beta, u);
      if (alpha >= beta) return alpha;
    }

    SearchWorkspace workspace = search_workspace.get();
    Board[] nb = workspace.boards(depth);
    int canput = generateOrderedChildren(b, depth, nb, false);

    if (canput == 0) {
      if (skipped) return end_game(b);
      Board rb = workspace.passBoard(depth);
      passInto(b, rb);
      return -negaAlphaOrdering(rb, strt, true, depth, -beta, -alpha);
    }

    if (canput >= 2) stableSortBoards(nb, canput);

    int first_alpha = alpha;
    int v = -inf;
    for (int idx = 0; idx < canput; idx++) {
      Board nnb = nb[idx];
      int g = -negaAlphaOrdering(nnb, strt, false, depth - 1, -beta, -alpha);
      if (beta <= g) {
        if (l < g) register_search(1 - f_search_table_idx, b, hash, g, u);
        return g;
      }
      alpha = Math.max(alpha, g);
      v = Math.max(v, g);
    }

    if (v <= first_alpha)
      register_search(1 - f_search_table_idx, b, hash, l, v);
    else
      register_search(1 - f_search_table_idx, b, hash, v, v);

    return v;
  }

  static int negaScout(Board b, long strt, boolean skipped, int depth, int alpha, int beta) {
    visitNode();
    if (depth <= 3) return nega_alpha(b, skipped, depth, alpha, beta);

    int hash = calc_search_hash(b);
    long bounds = get_search(b, hash, 1 - f_search_table_idx);
    int l = lowerBound(bounds);
    int u = upperBound(bounds);
    if (l != -inf) {
      if (l == u) return l;
      alpha = Math.max(alpha, l);
      if (alpha >= beta) return alpha;
    }
    if (u != -inf) {
      beta = Math.min(beta, u);
      if (alpha >= beta) return alpha;
    }

    SearchWorkspace workspace = search_workspace.get();
    Board[] nb = workspace.boards(depth);
    int canput = generateOrderedChildren(b, depth, nb, false);

    if (canput == 0) {
      if (skipped) return end_game(b);
      Board rb = workspace.passBoard(depth);
      passInto(b, rb);
      return -negaScout(rb, strt, true, depth, -beta, -alpha);
    }

    if (canput >= 2) stableSortBoards(nb, canput);

    int g = alpha, v = -inf, first_alpha = alpha;
    for (int idx = 0; idx < canput; idx++) {
      Board nnb = nb[idx];
      if (idx != 0) {
        g = -negaAlphaOrdering(
            nnb, strt, false, depth - 1,
            -alpha - midgame_scout_width, -alpha);
        if (beta <= g) {
          if (l < g) register_search(1 - f_search_table_idx, b, hash, g, u);
          return g;
        }
        v = Math.max(v, g);
      }
      if (alpha <= g) {
        g = -negaScout(nnb, strt, false, depth - 1, -beta, -g);
        if (beta <= g) {
          if (l < g) register_search(1 - f_search_table_idx, b, hash, g, u);
          return g;
        }
        alpha = Math.max(alpha, g);
        v = Math.max(v, g);
      }
    }

    if (v <= first_alpha)
      register_search(1 - f_search_table_idx, b, hash, l, v);
    else
      register_search(1 - f_search_table_idx, b, hash, v, v);

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
      res.nps = (int) (searchedNodes() * 1000 / Math.max(1L, tim() - strt));
      return res;
    }

    for (Board bi : nb) move_ordering(bi);
    if (nb.size() >= 2) Collections.sort(nb);

    Board best = nb.get(0);
    res.policy = best.policy;
    // best.v is an ordering score.  With a learned policy enabled it is not
    // the value evaluator's game score, so do not expose it as the protocol's
    // third field.  The child is from the opponent's point of view.
    res.value = -evaluate(best);
    res.depth = Math.max(1, depth);
    res.fallbackDepth = res.depth;
    res.nps = (int) (searchedNodes() * 1000 / Math.max(1L, tim() - strt));
    return res;
  }

  static void emitMetric(
      String mode,
      SearchResult result,
      long strt,
      boolean timeout
  ) {
    if (!EMIT_METRICS) return;
    long elapsed = Math.max(1L, tim() - strt);
    long nodes = searchedNodes();
    long nps = nodes * 1000L / elapsed;
    System.err.println(
        "METRIC {\"engine\":\"" + ENGINE_ID +
        "\",\"mode\":\"" + mode +
        "\",\"depth\":" + result.depth +
        ",\"policy\":" + result.policy +
        ",\"value\":" + result.value +
        ",\"nodes\":" + nodes +
        ",\"elapsedMs\":" + elapsed +
        ",\"nps\":" + nps +
        ",\"threads\":" + NUM_THREADS +
        ",\"valueFeatureSchema\":\"" +
            (value_evaluator.featureMode == ValueFeatureMode.EXACT_MOBILITY
                ? "exact-mobility-v1" : "legacy-v1") + "\"" +
        ",\"valueParamSha256\":\"" + value_param_sha256 + "\"" +
        ",\"policyMode\":\"" +
            POLICY_MODE.name().toLowerCase() + "\"" +
        ",\"policyActive\":\"" + active_policy_mode + "\"" +
        ",\"policyParamSha256\":\"" + policy_param_sha256 + "\"" +
        ",\"modelBundleSha256\":\"" + model_bundle_sha256 + "\"" +
        ",\"policyEvaluations\":" + metricPolicyEvaluations() +
        ",\"mpcMode\":\"" +
            MPC_MODE.name().toLowerCase().replace("_", "") + "\"" +
        ",\"mpcProfile\":\"" + mpc_profile_id + "\"" +
        ",\"mpcMidScale\":" + MPC_MID_SCALE +
        ",\"mpcFinalScale\":" + MPC_FINAL_SCALE +
        ",\"mpcAttempts\":" + metricMpcAttempts() +
        ",\"mpcCuts\":" + metricMpcCuts() +
        ",\"mpcNestedSuppressed\":" + metricMpcNestedSuppressed() +
        ",\"generalTtHits\":" + metricGeneralTtHits() +
        ",\"exactTtHits\":" + metricExactTtHits() +
        ",\"exactNodes\":" + metricExactNodes() +
        ",\"stabilityCuts\":" + metricStabilityCuts() +
        ",\"exactDepth\":" + exact_kernel_depth +
        ",\"maxDepth\":" + configured_midgame_depth +
        ",\"finalFallbackPercent\":" + final_fallback_percent +
        ",\"rootFirstPolicy\":" + result.rootFirstPolicy +
        ",\"rootResearchCount\":" + result.rootResearchCount +
        ",\"rootRescoutCount\":" + result.rootRescoutCount +
        ",\"rootResearchDepth\":" + result.rootResearchDepth +
        ",\"fallbackDepth\":" + result.fallbackDepth +
        ",\"exactStarted\":" + result.exactStarted +
        ",\"exactCompleted\":" + result.exactCompleted +
        ",\"book_hit\":false" +
        ",\"book_stones\":" + BOOK_STONES +
        ",\"book_hard_stop_44\":" + BOOK_HARD_STOP_44 +
        ",\"book_hard_stop_stones\":" + BOOK_HARD_STOP_STONES +
        ",\"book_diagnostic\":" + BOOK_DIAGNOSTIC +
        ",\"book_precedes_search\":true" +
        ",\"timeout\":" + timeout + "}");
  }

  static void emitBookMetric(
      BookChoice choice,
      int stoneCount,
      long strt,
      String diagnosticMode,
      BookTurnResolution resolution
  ) {
    // Diagnostic mode is itself an explicit request for this comparison
    // record, so it emits the book METRIC even if general metrics are off.
    if (!EMIT_METRICS && !BOOK_DIAGNOSTIC) return;
    long elapsed = Math.max(0L, tim() - strt);
    int selectedRow = resolution.selectedPolicy / hw;
    int selectedCol = resolution.selectedPolicy % hw;
    int searchPolicy = resolution.diagnosticPolicy;
    int searchRow = searchPolicy < 0 ? -1 : searchPolicy / hw;
    int searchCol = searchPolicy < 0 ? -1 : searchPolicy % hw;
    System.err.println(
        "METRIC {\"engine\":\"" + ENGINE_ID +
        "\",\"mode\":\"book\"" +
        ",\"book_hit\":true" +
        ",\"book_stone_count\":" + stoneCount +
        ",\"book_candidate_count\":" + choice.candidateCount +
        ",\"book_selected_policy\":" + resolution.selectedPolicy +
        ",\"book_selected_row\":" + selectedRow +
        ",\"book_selected_col\":" + selectedCol +
        ",\"book_stones\":" + BOOK_STONES +
        ",\"book_hard_stop_44\":" + BOOK_HARD_STOP_44 +
        ",\"book_hard_stop_stones\":" + BOOK_HARD_STOP_STONES +
        ",\"book_diagnostic\":" + BOOK_DIAGNOSTIC +
        ",\"book_precedes_search\":true" +
        ",\"diagnostic_search_mode\":\"" + diagnosticMode + "\"" +
        ",\"diagnostic_search_policy\":" + searchPolicy +
        ",\"diagnostic_search_row\":" + searchRow +
        ",\"diagnostic_search_col\":" + searchCol +
        ",\"diagnostic_search_value\":" + resolution.diagnosticValue +
        ",\"diagnostic_search_depth\":" + resolution.diagnosticDepth +
        ",\"diagnostic_search_agrees\":" + resolution.diagnosticAgrees +
        ",\"diagnostic_search_timeout\":" + resolution.diagnosticTimedOut +
        ",\"elapsedMs\":" + elapsed +
        ",\"threads\":" + NUM_THREADS +
        ",\"valueFeatureSchema\":\"" +
            (value_evaluator.featureMode == ValueFeatureMode.EXACT_MOBILITY
                ? "exact-mobility-v1" : "legacy-v1") + "\"" +
        ",\"valueParamSha256\":\"" + value_param_sha256 + "\"" +
        ",\"policyMode\":\"" +
            POLICY_MODE.name().toLowerCase() + "\"" +
        ",\"policyActive\":\"" + active_policy_mode + "\"" +
        ",\"policyParamSha256\":\"" + policy_param_sha256 + "\"" +
        ",\"modelBundleSha256\":\"" + model_bundle_sha256 + "\"" +
        ",\"mpcMode\":\"" +
            MPC_MODE.name().toLowerCase().replace("_", "") + "\"" +
        ",\"mpcProfile\":\"" + mpc_profile_id + "\"" +
        ",\"mpcMidScale\":" + MPC_MID_SCALE +
        ",\"mpcFinalScale\":" + MPC_FINAL_SCALE +
        // A diagnostic timeout does not make the selected book move a
        // production search timeout; it has its own field above.
        ",\"timeout\":" + resolution.productionTimedOut + "}");
  }

  static long invalidateParallelWorkers() {
    long oldGeneration = active_move_generation;
    long newGeneration = ++active_move_generation;
    prepareWorker(newGeneration);
    return oldGeneration;
  }

  static boolean awaitSearchWorkersIdle(long timeoutMillis) {
    return forkJoinPool == null ||
        forkJoinPool.awaitQuiescence(timeoutMillis, TimeUnit.MILLISECONDS);
  }

  static void cancelAndAwaitFutures(
      List<? extends Future<?>> futures,
      boolean invalidateGeneration
  ) {
    SearchStats callerBeforeInvalidation = null;
    long invalidatedGeneration = -1L;
    if (invalidateGeneration) {
      callerBeforeInvalidation =
          snapshotSearchStats(local_search_stats.get());
      invalidatedGeneration = invalidateParallelWorkers();
    }
    for (Future<?> future : futures) future.cancel(true);
    for (Future<?> future : futures) {
      try {
        future.get();
      } catch (CancellationException | ExecutionException ignored) {
        // Expected while unwinding a timed-out or failed parallel root search.
      } catch (InterruptedException e) {
        Thread.currentThread().interrupt();
        break;
      }
    }
    int waits = 0;
    while (!awaitSearchWorkersIdle(250L)) {
      // Old workers must become quiescent before the next position starts:
      // otherwise they could publish a stale TT entry after a generation reset.
      if (++waits == 4) {
        System.err.println(
            "warning: waiting for cancelled search workers to become idle");
      }
    }
    if (invalidateGeneration) {
      SearchStats current = local_search_stats.get();
      addSearchStats(current, callerBeforeInvalidation);
      for (SearchStats stats : all_search_stats) {
        if (stats != current && stats.generation == invalidatedGeneration) {
          addSearchStats(current, stats);
        }
      }
    }
  }

  static void cancelFutures(List<Future<SearchResult>> futures) {
    cancelAndAwaitFutures(futures, true);
  }

  static SearchResult waitSearchResult(
      Future<SearchResult> future,
      List<Future<SearchResult>> futures
  ) {
    try {
      long remain = remaining_time_ms();
      if (remain <= 0) {
        cancelAndAwaitFutures(futures, true);
        throw search_timeout;
      }
      if (remain == Long.MAX_VALUE) return future.get();
      return future.get(remain, TimeUnit.MILLISECONDS);
    } catch (TimeoutException e) {
      cancelAndAwaitFutures(futures, true);
      throw search_timeout;
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      cancelAndAwaitFutures(futures, true);
      throw search_timeout;
    } catch (ExecutionException e) {
      cancelAndAwaitFutures(futures, true);
      if (e.getCause() instanceof SearchTimeout) throw search_timeout;
      throw new RuntimeException(e.getCause());
    }
  }

  static SearchResult waitCompletedSearchResult(
      CompletionService<SearchResult> completion,
      List<Future<SearchResult>> futures
  ) {
    try {
      long remain = remaining_time_ms();
      if (remain <= 0L) {
        cancelAndAwaitFutures(futures, true);
        throw search_timeout;
      }
      Future<SearchResult> completed =
          remain == Long.MAX_VALUE
              ? completion.take()
              : completion.poll(remain, TimeUnit.MILLISECONDS);
      if (completed == null) {
        cancelAndAwaitFutures(futures, true);
        throw search_timeout;
      }
      return waitSearchResult(completed, futures);
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      cancelAndAwaitFutures(futures, true);
      throw search_timeout;
    }
  }

  static SearchResult search(Board b, long strt, int max_depth) {
      List<Board> nb = new ArrayList<>();
      long rootMoves = legalMoves(b);
      for (int vacantIndex = 0; vacantIndex < vacant_count; vacantIndex++) {
          int cell = vacant_cells[vacantIndex];
          if ((rootMoves & (1L << cell)) == 0L) continue;
          nb.add(move(b, cell));
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

      resetNodeCounters();
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
              Board bi = nb.get(i);
              long orderBounds =
                  get_search(bi, calc_search_hash(bi), f_search_table_idx);
              int orderLower = lowerBound(orderBounds);
              int orderUpper = upperBound(orderBounds);
              bi.v = -Math.max(orderLower, orderUpper);
              if (orderLower != -inf && orderUpper != -inf) bi.v += cache_both;
              if (orderLower == -inf && orderUpper == -inf) {
                bi.v = -policyEvaluate(bi);
              }
              else bi.v += cache_hit;
          }

          if (canput >= 2) Collections.sort(nb);

          // 最善手は通常探索
          alpha = -mtd(nb.get(0), strt, false, depth, -beta, -alpha);
          int tmp_policy = nb.get(0).policy;
          int tmpRootIndex = 0;
          int rootResearchCount = 0;
          int rootRescoutCount = 0;
          int rootResearchDepth = -1;

          // 候補が多い場合のみ並列化 (オーバーヘッド削減)
          if (NUM_THREADS > 1 && canput > 4) {
              final int currentDepth = depth;
              final int currentAlpha = alpha;
              final long currentMoveGeneration = active_move_generation;
              
              CompletionService<SearchResult> completion =
                  new ExecutorCompletionService<>(forkJoinPool);
              List<Future<SearchResult>> futures = new ArrayList<>();
              for (int i = 1; i < canput; i++) {
                  final int rootIndex = i;
                  final Board nextBoard = nb.get(i);
                  final int finalAlpha = currentAlpha;
                  futures.add(completion.submit(() -> {
                      prepareWorker(currentMoveGeneration);
                      SearchResult result = new SearchResult();
                      int g = -negaAlphaOrdering(
                          nextBoard, strt, false, currentDepth,
                          -finalAlpha - midgame_scout_width, -finalAlpha);
                      result.value = g;
                      result.policy = nextBoard.policy;
                      result.rootIndex = rootIndex;
                      result.alphaAtStart = finalAlpha;
                      result.boundType =
                          g > finalAlpha ? BOUND_LOWER : BOUND_UPPER;
                      return result;
                  }));
              }

              boolean collectedAll = false;
              try {
                  for (int i = 0; i < futures.size(); i++) {
                      SearchResult result =
                          waitCompletedSearchResult(completion, futures);
                      if (result.boundType == BOUND_LOWER) {
                          Board candidate = nb.get(result.rootIndex);
                          int scoutValue = result.value;
                          if (alpha != result.alphaAtStart) {
                              rootRescoutCount++;
                              scoutValue = -negaAlphaOrdering(
                                  candidate, strt, false, depth,
                                  -alpha - midgame_scout_width, -alpha);
                          }
                          boolean improves = scoutValue > alpha;
                          boolean resolveEarlierTie =
                              result.rootIndex < tmpRootIndex;
                          if (improves || resolveEarlierTie) {
                              rootResearchCount++;
                              rootResearchDepth = depth;
                              int childUpper = improves ? -alpha : beta;
                              int g = -mtd(
                                  candidate, strt, false, depth,
                                  -beta, childUpper);
                              if (alpha < g ||
                                  (alpha == g &&
                                   result.rootIndex < tmpRootIndex)) {
                                  alpha = g;
                                  tmp_policy = candidate.policy;
                                  tmpRootIndex = result.rootIndex;
                              }
                          }
                      }
                  }
                  collectedAll = true;
              } finally {
                  if (!collectedAll) {
                      cancelAndAwaitFutures(
                          futures, active_move_generation == currentMoveGeneration);
                  }
              }
          } else {
              // 候補が少ない場合は通常探索
              for (int i = 1; i < canput; i++) {
                  int g = -negaAlphaOrdering(
                      nb.get(i), strt, false, depth,
                      -alpha - midgame_scout_width, -alpha);
                  if (alpha < g) {
                      rootResearchCount++;
                      rootResearchDepth = depth;
                      g = -mtd(
                          nb.get(i), strt, false, depth, -beta, -alpha);
                      if (alpha < g) {
                          alpha = g;
                          tmp_policy = nb.get(i).policy;
                          tmpRootIndex = i;
                      }
                  }
              }
          }

          f_search_table_idx = 1 - f_search_table_idx;

          SearchResult completed = new SearchResult();
          completed.policy = tmp_policy;
          completed.value = alpha;
          completed.depth = depth + 1;
          completed.rootFirstPolicy = nb.get(0).policy;
          completed.rootResearchCount = rootResearchCount;
          completed.rootRescoutCount = rootRescoutCount;
          completed.rootResearchDepth = rootResearchDepth;
          long completedNodes = searchedNodes();
          completed.nps = (int)(completedNodes * 1000 / Math.max(1L, tim() - strt));
          best = completed;
          System.err.println("completed depth: " + completed.depth +
              " time: " + (tim() - strt) + " ms" +
              " policy: " + completed.policy +
              " value: " + completed.value +
              " nodes: " + completedNodes +
              " nps: " + completed.nps);
        } catch (SearchTimeout e) {
          System.err.println("time up during depth " + (depth + 1) +
              ", using depth " + best.depth);
          best.timedOut = true;
          return best;
        }
      }

      return best;
  }

  static SearchResult finalSearch(Board b, long strt) {
      List<Board> nb = new ArrayList<>();
      long rootMoves = legalMoves(b);
      for (int vacantIndex = 0; vacantIndex < vacant_count; vacantIndex++) {
        int cell = vacant_cells[vacantIndex];
        if ((rootMoves & (1L << cell)) == 0L) continue;
        System.err.print(cell + " ");
        nb.add(move(b, cell));
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

      resetNodeCounters();

      if (max_depth - final_fallback_margin > 0 &&
          final_fallback_percent > 0) {
        long fullDeadline = search_deadline_nanos;
        if (fullDeadline != Long.MAX_VALUE) {
          long now = System.nanoTime();
          long remaining = Math.max(0L, fullDeadline - now);
          long fallbackBudget =
              remaining * final_fallback_percent / 100L;
          search_deadline_nanos =
              Math.min(fullDeadline, now + Math.max(1L, fallbackBudget));
        }
        try {
          fallback = search(b, strt, max_depth - final_fallback_margin);
        } finally {
          search_deadline_nanos = fullDeadline;
        }
      }
      fallback.fallbackDepth = fallback.depth;

      try {
      checkTime();
      System.err.println("start final search (parallel)");
      alpha = -sc_w;
      beta = sc_w;

      search_hash_table_init(1 - f_search_table_idx);

      for (int i = 0; i < canput; i++) {
        Board bi = nb.get(i);
        long orderBounds =
            get_search(bi, calc_search_hash(bi), f_search_table_idx);
        int orderLower = lowerBound(orderBounds);
        int orderUpper = upperBound(orderBounds);
        bi.v = -Math.max(orderLower, orderUpper);
        if (orderLower != -inf && orderUpper != -inf) bi.v += cache_both;
        if (orderLower == -inf && orderUpper == -inf) {
          bi.v = -policyEvaluate(bi);
        }
        else bi.v += cache_hit;
      }

      if (canput >= 2) Collections.sort(nb);

      final int childDepth = max_depth - 1;
      int rootResearchCount = 0;
      int rootRescoutCount = 0;
      int rootResearchDepth = -1;

      // まず最善手を探索
      alpha = -negaScoutFinal(nb.get(0), strt, false, childDepth, -beta, -alpha);
      tmp_policy = nb.get(0).policy;
      int tmpRootIndex = 0;

      // 残りの手を並列探索
      if (NUM_THREADS > 1 && canput > 1) {
          final int currentMaxDepth = childDepth;
          final int currentAlpha = alpha;
          final long currentMoveGeneration = active_move_generation;
          
          CompletionService<SearchResult> completion =
              new ExecutorCompletionService<>(forkJoinPool);
          List<Future<SearchResult>> futures = new ArrayList<>();
          for (int i = 1; i < canput; i++) {
              final int rootIndex = i;
              final Board nextBoard = nb.get(i);
              final int finalAlpha = currentAlpha;
              futures.add(completion.submit(() -> {
                  prepareWorker(currentMoveGeneration);
                  SearchResult result = new SearchResult();
                  int tempG = -negaAlphaOrderingFinal(
                      nextBoard, strt, false, currentMaxDepth,
                      -finalAlpha - step, -finalAlpha);
                  result.value = tempG;
                  result.policy = nextBoard.policy;
                  result.rootIndex = rootIndex;
                  result.alphaAtStart = finalAlpha;
                  result.boundType =
                      tempG > finalAlpha ? BOUND_LOWER : BOUND_UPPER;
                  return result;
              }));
          }

          boolean collectedAll = false;
          try {
              for (int i = 0; i < futures.size(); i++) {
                  SearchResult result =
                      waitCompletedSearchResult(completion, futures);
                  if (result.boundType == BOUND_LOWER) {
                      Board candidate = nb.get(result.rootIndex);
                      int scoutValue = result.value;
                      if (alpha != result.alphaAtStart) {
                          rootRescoutCount++;
                          scoutValue = -negaAlphaOrderingFinal(
                              candidate, strt, false, childDepth,
                              -alpha - step, -alpha);
                      }
                      boolean improves = scoutValue > alpha;
                      boolean resolveEarlierTie =
                          result.rootIndex < tmpRootIndex;
                      if (improves || resolveEarlierTie) {
                          rootResearchCount++;
                          rootResearchDepth = childDepth;
                          int childUpper = improves ? -alpha : beta;
                          g = -negaScoutFinal(
                              candidate, strt, false, childDepth,
                              -beta, childUpper);
                          if (alpha < g ||
                              (alpha == g &&
                               result.rootIndex < tmpRootIndex)) {
                              alpha = g;
                              tmp_policy = candidate.policy;
                              tmpRootIndex = result.rootIndex;
                          }
                      }
                  }
              }
              collectedAll = true;
          } finally {
              if (!collectedAll) {
                  cancelAndAwaitFutures(
                      futures, active_move_generation == currentMoveGeneration);
              }
          }
      } else {
          // With a total thread budget of one, search every sibling on the
          // caller thread. This is both deterministic and genuinely serial.
          for (int i = 1; i < canput; i++) {
              g = -negaAlphaOrderingFinal(
                  nb.get(i), strt, false, childDepth, -alpha - step, -alpha);
              if (alpha < g) {
                  rootResearchCount++;
                  rootResearchDepth = childDepth;
                  g = -negaScoutFinal(
                      nb.get(i), strt, false, childDepth, -beta, -alpha);
                  if (alpha < g) {
                      alpha = g;
                      tmp_policy = nb.get(i).policy;
                      tmpRootIndex = i;
                  }
              }
          }
      }

      f_search_table_idx = 1 - f_search_table_idx;
      policy = tmp_policy;
      value = alpha;
      
      long elapsed = tim() - strt;
      long finalNodes = searchedNodes();
      long nps = finalNodes * 1000 / Math.max(1L, elapsed);
      /**
      System.err.println("final depth: " + max_depth + " time: " + elapsed +
                        " policy: " + policy + " value: " + value +
                        " nodes: " + finalNodes + " nps: " + nps);
      */

      SearchResult res = new SearchResult();
      res.policy = policy;
      res.value = value;
      res.depth = max_depth;
      res.nps = (int) (searchedNodes() * 1000 / Math.max(1L, tim() - strt));
      res.rootFirstPolicy = nb.get(0).policy;
      res.rootResearchCount = rootResearchCount;
      res.rootRescoutCount = rootRescoutCount;
      res.rootResearchDepth = rootResearchDepth;
      res.fallbackDepth = fallback.depth;
      res.exactStarted = metricExactNodes() > 0L;
      res.exactCompleted = true;
      return res;
      } catch (SearchTimeout e) {
        System.err.println("time up during final search, using depth " + fallback.depth);
        fallback.timedOut = true;
        fallback.exactStarted = metricExactNodes() > 0L;
        fallback.exactCompleted = false;
        return fallback;
      }
    }

  static double calcResultValue(int v) {
    return (double) v * hw2 / sc_w;
  }

  static void printResult(int policy, int value) {
    if (policy < 0) {
      System.err.println("Pass");
      System.out.println("-1 -1 " + calcResultValue(value));
      return;
    }
    int y = policy / hw;
    int x = policy % hw;
    System.err.println("Placed at: (" + y + ", " + x + ")");
    System.out.println(y + " " + x + " " + calcResultValue(value));  // ★修正: 評価値を追加
  }

  static void printResult(SearchResult result) {
    if (result.policy < 0) {
      printResult(result.policy, result.value);
      return;
    }
    int y = result.policy / hw;
    int x = result.policy % hw;
    System.err.println("Placed at: (" + y + ", " + x + ") [depth: " + result.depth + ", value: " + result.value + "]");
    System.out.println(y + " " + x + " " + calcResultValue(result.value));  // ★修正: 評価値を追加
  }

  static void sortVacantCells() {
    // Stable insertion sort preserves the old List.sort tie order: cells were
    // collected in row-major order and equal-weight cells stay in that order.
    for (int i = 1; i < vacant_count; i++) {
      int cell = vacant_cells[i];
      int j = i - 1;
      while (j >= 0 && cell_weight[vacant_cells[j]] < cell_weight[cell]) {
        vacant_cells[j + 1] = vacant_cells[j];
        j--;
      }
      vacant_cells[j + 1] = cell;
    }
  }

  // ★追加: 標準入力からボードを読み込むメソッド
  static int input_board(int[] board, BufferedReader br) {
    int n_stones = 0;
    long b = 0L, w = 0L;

    vacant_count = 0;

    try {
      for (int i = 0; i < hw; i++) {
        String line = br.readLine();
        if (line == null) {
          return -1; // 入力終了
        }
        String raw_board = line.trim();
        System.err.println(raw_board);

        if (raw_board.length() != hw) {
          System.err.println("Invalid board row length at row " + i + ": " + raw_board.length());
          return -2;
        }

        for (int j = 0; j < hw; j++) {
          char elem = raw_board.charAt(j);
          if (elem != '.' && elem != '0' && elem != '1') {
            System.err.println("Invalid board character at (" + i + ", " + j + "): " + elem);
            return -2;
          }
          if (elem != '.') {
            b |= ((elem == '0') ? 1L : 0L) << (i * hw + j);
            w |= ((elem == '1') ? 1L : 0L) << (i * hw + j);
            n_stones++;
          } else {
            vacant_cells[vacant_count++] = i * hw + j;
          }
        }
      }
    } catch (IOException e) {
      System.err.println("Error reading board input");
      return -1;
    }

    if (n_stones < hw2_m1) sortVacantCells();

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

    depth = configured_midgame_depth;
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
    init_book();
    System.err.println("book initialized in " + (tim() - strt) + " ms");
    init_evaluation();
    init_mpc();

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
      if (ai_player != 0 && ai_player != 1) {
        System.err.println("AI player must be 0 or 1");
        return;
      }
      System.err.println("AI player: " + ai_player);
    } catch (Exception e) {
      return;
    }

    while (true) {
      System.err.println("Waiting for board input...");
      n_stones = input_board(b.b, br);
      
      if (n_stones < 0) {
        break;
      }

      initializeBitboards(b);
      
      strt = tim();
      begin_move_timer(strt);
      System.err.println("n_stones: " + n_stones);
      System.err.println((n_stones - 4) + " moves");
      b.n = n_stones;
      b.p = ai_player;
      System.err.println("value: " + evaluate(b));

      try {
        if (n_stones == 4) {
          result = search(b, strt, 1);
          emitMetric("midgame", result, strt, result.timedOut);
          printResult(result);
          System.out.flush();
          continue;
        }

        // Deliberate precedence, retained from original_10: after the special
        // four-disc case above, an eligible book hit is used before either
        // finalSearch or the normal midgame search. Only BOOK_DIAGNOSTIC runs
        // a comparison search on a hit; it never replaces the selected move.
        if (isBookEligible(n_stones)) {
          BookChoice bookChoice = get_book(b.b);
          final int selectedBookPolicy = bookChoice.policy;
          policy = selectedBookPolicy;
          System.err.println(
              "book policy " + policy +
              " candidates " + bookChoice.candidateCount);
          if (bookChoice.hit()) {
            SearchResult diagnosticResult = null;
            String diagnosticMode = "off";
            boolean diagnosticTimeout = false;
            if (BOOK_DIAGNOSTIC) {
              boolean diagnosticFinalMode = n_stones >= hw2 - final_depth;
              diagnosticMode = diagnosticFinalMode ? "final" : "midgame";
              try {
                diagnosticResult = diagnosticFinalMode
                    ? finalSearch(b, strt)
                    : search(b, strt, depth);
              } catch (SearchTimeout e) {
                diagnosticTimeout = true;
              }
            }
            BookTurnResolution bookTurn = resolveBookTurn(
                bookChoice,
                diagnosticResult,
                diagnosticTimeout);
            emitBookMetric(
                bookChoice,
                n_stones,
                strt,
                diagnosticMode,
                bookTurn);
            // finalSearch updates the legacy global policy as an implementation
            // detail. Diagnostics must never change the move sent to Client.
            policy = bookTurn.selectedPolicy;
            b = move(b, bookTurn.selectedPolicy);
            printResult(bookTurn.selectedPolicy, -evaluate(b));
            System.out.flush();
            continue;
          }
        }

        boolean finalMode = n_stones >= hw2 - final_depth;
        if (finalMode)
          result = finalSearch(b, strt);
        else
          result = search(b, strt, depth);

        emitMetric(finalMode ? "final" : "midgame", result, strt, result.timedOut);
        printResult(result);
        System.out.flush();
      } catch (SearchTimeout e) {
        result = search(b, strt, 1);
        result.timedOut = true;
        emitMetric("fallback", result, strt, true);
        printResult(result);
        System.out.flush();
      } finally {
        clear_move_timer();
      }
    }
    if (forkJoinPool != null) forkJoinPool.shutdown();
  }
}
