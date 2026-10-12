import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.Locale;

/**
 * Batch bridge exposing the package-private OthelloAI_05 evaluator to the
 * Python parity test.  This is test-only and does not change the AI protocol.
 *
 * Input, one position per line:  player<TAB>64 board characters
 * Output: value raw phase canput surroundBlack surroundWhite
 */
public final class JavaEvalBridge {
  private JavaEvalBridge() {}

  private static OthelloAI_05.Board encode(String rawBoard, int player) {
    if (rawBoard.length() != OthelloAI_05.hw2) {
      throw new IllegalArgumentException("board length must be 64: " + rawBoard.length());
    }

    OthelloAI_05.Board board = new OthelloAI_05.Board();
    board.p = player;
    board.n = 0;
    for (int i = 0; i < OthelloAI_05.b_idx_num; i++) {
      board.b[i] = OthelloAI_05.n_line - 1;
      for (int j = 0; j < OthelloAI_05.idx_n_cell[i]; j++) {
        char cell = rawBoard.charAt(OthelloAI_05.global_place[i][j]);
        if (cell == '0') {
          board.b[i] -= OthelloAI_05.pow3[OthelloAI_05.hw_m1 - j] * 2;
          board.n++;
        } else if (cell == '1') {
          board.b[i] -= OthelloAI_05.pow3[OthelloAI_05.hw_m1 - j];
          board.n++;
        } else if (cell != '.') {
          throw new IllegalArgumentException("invalid board symbol: " + cell);
        }
      }
    }

    // Every occupied square occurs in multiple lines, so recount using rows.
    board.n = 0;
    for (int i = 0; i < rawBoard.length(); i++) {
      if (rawBoard.charAt(i) != '.') board.n++;
    }
    return board;
  }

  private static double evaluateRaw(
      OthelloAI_05.Board board,
      int phase,
      int canputIndex,
      int surroundBlack,
      int surroundWhite
  ) {
    double[] addValues = OthelloAI_05.add_arr[phase][canputIndex][surroundBlack][surroundWhite];
    double[] dense = OthelloAI_05.all_dense[phase];
    double result = OthelloAI_05.all_bias[phase] + OthelloAI_05.calc_pattern(phase, board)
        + dense[11] * addValues[0]
        + dense[12] * addValues[1]
        + dense[13] * addValues[2]
        + dense[14] * addValues[3]
        + dense[15] * addValues[4]
        + dense[16] * addValues[5]
        + dense[17] * addValues[6]
        + dense[18] * addValues[7];
    if (board.p != 0) result = -result;
    return Math.max(-1.0, Math.min(1.0, result));
  }

  public static void main(String[] args) throws Exception {
    Locale.setDefault(Locale.ROOT);
    OthelloAI_05.init_pow();
    OthelloAI_05.init_mod3();
    OthelloAI_05.init_pop_mid();
    OthelloAI_05.init_move();
    OthelloAI_05.init_pop_digit();
    OthelloAI_05.init_evaluation();

    try (BufferedReader reader = new BufferedReader(new InputStreamReader(System.in))) {
      String line;
      while ((line = reader.readLine()) != null) {
        line = line.trim();
        if (line.isEmpty()) continue;
        String[] fields = line.split("\\s+", 2);
        if (fields.length != 2) {
          throw new IllegalArgumentException("expected: player board64");
        }
        int player = Integer.parseInt(fields[0]);
        OthelloAI_05.Board board = encode(fields[1], player);
        int phase = OthelloAI_05.calc_phase_idx(board);
        int signedCanput = OthelloAI_05.calc_canput(board);
        int canputIndex = Math.min(
            OthelloAI_05.max_canput * 2,
            Math.max(0, OthelloAI_05.max_canput + signedCanput));
        int surroundBlack = Math.min(OthelloAI_05.max_surround, OthelloAI_05.calc_surround(board, 0));
        int surroundWhite = Math.min(OthelloAI_05.max_surround, OthelloAI_05.calc_surround(board, 1));
        int value = OthelloAI_05.evaluate(board);
        double raw = evaluateRaw(board, phase, canputIndex, surroundBlack, surroundWhite);
        int clampedCanput = canputIndex - OthelloAI_05.max_canput;
        System.out.println(
            value + " " + Double.toString(raw) + " " + phase + " " + clampedCanput
            + " " + surroundBlack + " " + surroundWhite);
      }
    }
  }
}
