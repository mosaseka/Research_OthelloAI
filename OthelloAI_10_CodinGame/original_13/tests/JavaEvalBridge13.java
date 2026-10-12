import java.io.BufferedReader;
import java.io.File;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/**
 * Test-only batch bridge for Python/Java evaluator parity.
 *
 * Input: player<TAB>64 board characters (0=black, 1=white, .=empty)
 * Output: value transformedRaw logit phase canput surroundBlack surroundWhite
 */
public final class JavaEvalBridge13 {
  private JavaEvalBridge13() {}

  private static OthelloAI_13.Board encode(String rawBoard, int player) {
    if ((player != 0 && player != 1) || rawBoard.length() != 64) {
      throw new IllegalArgumentException("expected player(0/1) and board64");
    }
    OthelloAI_13.Board board = new OthelloAI_13.Board();
    board.p = player;
    long black = 0L;
    long white = 0L;
    int stones = 0;
    for (int i = 0; i < OthelloAI_13.b_idx_num; i++) {
      board.b[i] = OthelloAI_13.n_line - 1;
      for (int j = 0; j < OthelloAI_13.idx_n_cell[i]; j++) {
        int place = OthelloAI_13.global_place[i][j];
        char cell = rawBoard.charAt(place);
        if (cell == '0') {
          board.b[i] -= OthelloAI_13.pow3[OthelloAI_13.hw_m1 - j] * 2;
        } else if (cell == '1') {
          board.b[i] -= OthelloAI_13.pow3[OthelloAI_13.hw_m1 - j];
        } else if (cell != '.') {
          throw new IllegalArgumentException("invalid board character");
        }
      }
    }
    for (int place = 0; place < 64; place++) {
      char cell = rawBoard.charAt(place);
      if (cell == '0') {
        black |= 1L << place;
        stones++;
      } else if (cell == '1') {
        white |= 1L << place;
        stones++;
      }
    }
    board.n = stones;
    board.blackBits = black;
    board.whiteBits = white;
    board.emptyMask = ~(black | white);
    board.hasBitboards = true;
    return board;
  }

  private static void initialize(File candidate) {
    OthelloAI_13.init_pow();
    OthelloAI_13.init_mod3();
    OthelloAI_13.init_pop_mid();
    OthelloAI_13.init_move();
    OthelloAI_13.init_pop_digit();
    OthelloAI_13.value_evaluator = OthelloAI_13.loadEvaluator(
        candidate,
        OthelloAI_13.ValueFeatureMode.EXACT_MOBILITY,
        null,
        "candidate");
  }

  public static void main(String[] args) throws Exception {
    Locale.setDefault(Locale.ROOT);
    if (args.length != 1) {
      throw new IllegalArgumentException(
          "usage: JavaEvalBridge13 <candidate-param.txt>");
    }
    initialize(new File(args[0]));
    try (BufferedReader reader = new BufferedReader(
        new InputStreamReader(System.in, StandardCharsets.UTF_8))) {
      String line;
      while ((line = reader.readLine()) != null) {
        if (line.isBlank()) continue;
        String[] fields = line.trim().split("\\s+", 2);
        OthelloAI_13.Board board =
            encode(fields[1], Integer.parseInt(fields[0]));
        int phase = OthelloAI_13.calc_phase_idx(board);
        int canput = OthelloAI_13.calc_canput(
            board, OthelloAI_13.ValueFeatureMode.EXACT_MOBILITY);
        int surroundBlack = Math.min(
            OthelloAI_13.max_surround, OthelloAI_13.calc_surround(board, 0));
        int surroundWhite = Math.min(
            OthelloAI_13.max_surround, OthelloAI_13.calc_surround(board, 1));
        double logit = OthelloAI_13.rawEvaluate(
            OthelloAI_13.value_evaluator, board);
        double transformed = Math.tanh(logit * 0.5);
        int value = OthelloAI_13.evaluate(board);
        System.out.println(
            value + " " + Double.toString(transformed) + " "
            + Double.toString(logit) + " " + phase + " " + canput + " "
            + surroundBlack + " " + surroundWhite);
      }
    }
  }
}
