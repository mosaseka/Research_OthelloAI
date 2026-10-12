import java.io.BufferedReader;
import java.io.File;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/**
 * Batch bridge for exact-mobility-v1 candidate validation.
 *
 * <p>This test-only class deliberately bypasses OthelloAI_11.init_evaluation():
 * the candidate is loaded directly as EXACT_MOBILITY, so a permanent model
 * bundle is neither read nor required.
 *
 * <p>Input, one position per line:
 *
 * <pre>player&lt;TAB&gt;64 board characters</pre>
 *
 * <p>Output:
 *
 * <pre>value raw phase canput surroundBlack surroundWhite</pre>
 *
 * <p>{@code raw} is the clamped pre-cast value used to produce {@code value}.
 */
public final class JavaEvalBridge11 {
  private JavaEvalBridge11() {}

  private static OthelloAI_11.Board encode(String rawBoard, int player) {
    if (player != 0 && player != 1) {
      throw new IllegalArgumentException("player must be 0 or 1: " + player);
    }
    if (rawBoard.length() != OthelloAI_11.hw2) {
      throw new IllegalArgumentException(
          "board length must be 64: " + rawBoard.length());
    }

    OthelloAI_11.Board board = new OthelloAI_11.Board();
    board.p = player;
    long black = 0L;
    long white = 0L;
    int stones = 0;

    for (int i = 0; i < OthelloAI_11.b_idx_num; i++) {
      board.b[i] = OthelloAI_11.n_line - 1;
      for (int j = 0; j < OthelloAI_11.idx_n_cell[i]; j++) {
        int globalPlace = OthelloAI_11.global_place[i][j];
        char cell = rawBoard.charAt(globalPlace);
        if (cell == '0') {
          board.b[i] -= OthelloAI_11.pow3[OthelloAI_11.hw_m1 - j] * 2;
        } else if (cell == '1') {
          board.b[i] -= OthelloAI_11.pow3[OthelloAI_11.hw_m1 - j];
        } else if (cell != '.') {
          throw new IllegalArgumentException(
              "invalid board symbol at cell " + globalPlace + ": " + cell);
        }
      }
    }

    for (int place = 0; place < rawBoard.length(); place++) {
      char cell = rawBoard.charAt(place);
      if (cell == '0') {
        black |= 1L << place;
        stones++;
      } else if (cell == '1') {
        white |= 1L << place;
        stones++;
      }
    }
    if (stones < 4) {
      throw new IllegalArgumentException(
          "reachable evaluator positions must contain at least four stones");
    }

    board.n = stones;
    board.blackBits = black;
    board.whiteBits = white;
    board.emptyMask = ~(black | white);
    board.hasBitboards = true;
    return board;
  }

  private static void initializeEvaluator(File candidate) {
    OthelloAI_11.init_pow();
    OthelloAI_11.init_mod3();
    OthelloAI_11.init_pop_mid();
    OthelloAI_11.init_move();
    OthelloAI_11.init_pop_digit();

    OthelloAI_11.value_evaluator = OthelloAI_11.loadEvaluator(
        candidate,
        OthelloAI_11.ValueFeatureMode.EXACT_MOBILITY,
        null,
        "candidate");
    OthelloAI_11.value_param_sha256 =
        OthelloAI_11.value_evaluator.sha256;
    OthelloAI_11.policy_evaluator = null;
  }

  public static void main(String[] args) throws Exception {
    Locale.setDefault(Locale.ROOT);
    if (args.length != 1) {
      throw new IllegalArgumentException(
          "usage: JavaEvalBridge11 <candidate-param.txt>");
    }
    initializeEvaluator(new File(args[0]));

    try (BufferedReader reader = new BufferedReader(
        new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
      String line;
      while ((line = reader.readLine()) != null) {
        line = line.trim();
        if (line.isEmpty()) continue;
        String[] fields = line.split("\\s+", 2);
        if (fields.length != 2) {
          throw new IllegalArgumentException("expected: player board64");
        }

        int player = Integer.parseInt(fields[0]);
        OthelloAI_11.Board board = encode(fields[1], player);
        int phase = OthelloAI_11.calc_phase_idx(board);
        int canput = OthelloAI_11.calc_canput(
            board, OthelloAI_11.ValueFeatureMode.EXACT_MOBILITY);
        int surroundBlack = Math.min(
            OthelloAI_11.max_surround,
            OthelloAI_11.calc_surround(board, 0));
        int surroundWhite = Math.min(
            OthelloAI_11.max_surround,
            OthelloAI_11.calc_surround(board, 1));
        double raw = OthelloAI_11.rawEvaluate(
            OthelloAI_11.value_evaluator, board);
        raw = Math.max(-1.0, Math.min(1.0, raw));
        int value = OthelloAI_11.evaluate(board);

        System.out.println(
            value + " " + Double.toString(raw) + " " + phase + " "
            + canput + " " + surroundBlack + " " + surroundWhite);
      }
    }
  }
}
