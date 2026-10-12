import java.io.BufferedReader;
import java.io.IOException;
import java.io.StringReader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Random;
import java.util.Set;

public final class OthelloAIRegressionTest {
  private static final String[] INITIAL = {
      "........",
      "........",
      "........",
      "...10...",
      "...01...",
      "........",
      "........",
      "........"
  };

  private static int assertions;

  private OthelloAIRegressionTest() {}

  public static void main(String[] args) throws Exception {
    initializeEngine();
    testInitialLegalMoves();
    testMoveAndFlip();
    testPassAndTerminal();
    testColorSwap();
    testDihedralSymmetry();
    testParameterFile();
    testBook();
    testEvaluationReproducibility();
    testInputValidation();
    testTranspositionTableSeparatesPlayers();
    testFinalRootResearchMatchesExact();
    testFinalSearchMatchesExactAtTenEmpties();
    testTimedSearchReturnsLegalMove();
    System.out.println("OK " + assertions + " assertions");
    OthelloAI_05.forkJoinPool.shutdownNow();
  }

  private static void initializeEngine() {
    OthelloAI_05.init_pow();
    OthelloAI_05.init_mod3();
    OthelloAI_05.init_pop_mid();
    OthelloAI_05.init_move();
    OthelloAI_05.init_local_place();
    OthelloAI_05.init_included();
    OthelloAI_05.init_pop_digit();
    OthelloAI_05.init_mpc();
    OthelloAI_05.init_book();
    OthelloAI_05.init_evaluation();
    OthelloAI_05.f_search_table_idx = 0;
    OthelloAI_05.search_hash_table_init(0);
    OthelloAI_05.search_hash_table_init(1);
  }

  private static OthelloAI_05.Board boardFromRows(String[] rows, int player) {
    check(rows.length == 8, "board must have eight rows");
    OthelloAI_05.Board board = new OthelloAI_05.Board();
    board.p = player;
    board.n = 0;
    OthelloAI_05.vacant_lst.clear();

    for (int y = 0; y < 8; y++) {
      check(rows[y].length() == 8, "row must have eight cells");
      for (int x = 0; x < 8; x++) {
        char cell = rows[y].charAt(x);
        check(cell == '0' || cell == '1' || cell == '.', "invalid board character");
        if (cell == '.') OthelloAI_05.vacant_lst.add(y * 8 + x);
        else board.n++;
      }
    }

    for (int line = 0; line < OthelloAI_05.b_idx_num; line++) {
      int encoded = OthelloAI_05.n_line - 1;
      for (int i = 0; i < OthelloAI_05.idx_n_cell[line]; i++) {
        int cell = OthelloAI_05.global_place[line][i];
        char value = rows[cell / 8].charAt(cell % 8);
        if (value == '0') encoded -= OthelloAI_05.pow3[7 - i] * 2;
        else if (value == '1') encoded -= OthelloAI_05.pow3[7 - i];
      }
      board.b[line] = encoded;
    }
    return board;
  }

  private static String[] rowsOf(OthelloAI_05.Board board) {
    String[] rows = new String[8];
    for (int y = 0; y < 8; y++) {
      StringBuilder row = new StringBuilder(8);
      for (int x = 0; x < 8; x++) {
        int digit = OthelloAI_05.pop_digit[board.b[y]][x];
        row.append(digit == 0 ? '0' : digit == 1 ? '1' : '.');
      }
      rows[y] = row.toString();
    }
    return rows;
  }

  private static boolean isLegal(OthelloAI_05.Board board, int cell) {
    for (int i = 0; i < 4; i++) {
      int line = OthelloAI_05.place_included[cell][i];
      if (line == -1) break;
      int local = OthelloAI_05.local_place[line][cell];
      if (OthelloAI_05.legal_arr[board.p][board.b[line]][local]) return true;
    }
    return false;
  }

  private static List<Integer> legalMoves(OthelloAI_05.Board board) {
    List<Integer> moves = new ArrayList<>();
    for (int cell = 0; cell < 64; cell++) {
      if (isLegal(board, cell)) moves.add(cell);
    }
    return moves;
  }

  private static OthelloAI_05.Board pass(OthelloAI_05.Board board) {
    OthelloAI_05.Board result = new OthelloAI_05.Board(board);
    result.p = 1 - board.p;
    result.policy = -1;
    return result;
  }

  private static OthelloAI_05.Board randomPosition(int plies, long seed) {
    OthelloAI_05.Board board = boardFromRows(INITIAL, 0);
    Random random = new Random(seed);
    int played = 0;
    int passes = 0;
    while (played < plies && passes < 2) {
      List<Integer> moves = legalMoves(board);
      if (moves.isEmpty()) {
        board = pass(board);
        passes++;
      } else {
        board = OthelloAI_05.move(board, moves.get(random.nextInt(moves.size())));
        played++;
        passes = 0;
      }
    }
    OthelloAI_05.vacant_lst.clear();
    String[] rows = rowsOf(board);
    for (int cell = 0; cell < 64; cell++) {
      if (rows[cell / 8].charAt(cell % 8) == '.') OthelloAI_05.vacant_lst.add(cell);
    }
    return board;
  }

  private static void testInitialLegalMoves() {
    OthelloAI_05.Board initial = boardFromRows(INITIAL, 0);
    Set<Integer> expected = Set.of(2 * 8 + 3, 3 * 8 + 2, 4 * 8 + 5, 5 * 8 + 4);
    check(new HashSet<>(legalMoves(initial)).equals(expected), "initial black legal moves");

    initial.p = 1;
    expected = Set.of(2 * 8 + 4, 3 * 8 + 5, 4 * 8 + 2, 5 * 8 + 3);
    check(new HashSet<>(legalMoves(initial)).equals(expected), "initial white legal moves");
  }

  private static void testMoveAndFlip() {
    OthelloAI_05.Board initial = boardFromRows(INITIAL, 0);
    OthelloAI_05.Board moved = OthelloAI_05.move(initial, 2 * 8 + 3);
    String[] expected = INITIAL.clone();
    expected[2] = "...0....";
    expected[3] = "...00...";
    check(Arrays.equals(rowsOf(moved), expected), "move must place and flip");
    check(moved.p == 1 && moved.n == 5, "move must switch player and increment stones");
  }

  private static void testPassAndTerminal() {
    OthelloAI_05.Board passBoard = null;
    for (long seed = 0; seed < 500 && passBoard == null; seed++) {
      OthelloAI_05.Board board = boardFromRows(INITIAL, 0);
      Random random = new Random(seed);
      int consecutivePasses = 0;
      while (consecutivePasses < 2 && board.n < 64) {
        List<Integer> moves = legalMoves(board);
        if (moves.isEmpty()) {
          OthelloAI_05.Board opponent = pass(board);
          if (!legalMoves(opponent).isEmpty()) {
            passBoard = board;
            break;
          }
          board = opponent;
          consecutivePasses++;
        } else {
          board = OthelloAI_05.move(board, moves.get(random.nextInt(moves.size())));
          consecutivePasses = 0;
        }
      }
    }
    check(passBoard != null, "deterministic search must find a pass position");
    check(legalMoves(passBoard).isEmpty(), "passing player has no move");
    OthelloAI_05.Board afterPass = pass(passBoard);
    check(!legalMoves(afterPass).isEmpty(), "opponent can move after pass");
    check(afterPass.n == passBoard.n, "pass must not change stone count");
    OthelloAI_05.SearchResult passResult = OthelloAI_05.search(passBoard, OthelloAI_05.tim(), 1);
    check(passResult.policy == -1, "root no-move result uses pass policy -1");

    String[] full = new String[8];
    Arrays.fill(full, "00000000");
    OthelloAI_05.Board terminal = boardFromRows(full, 0);
    check(legalMoves(terminal).isEmpty(), "full board has no move");
    check(OthelloAI_05.end_game(terminal) == 6400, "black full-board score");
    terminal.p = 1;
    check(OthelloAI_05.end_game(terminal) == -6400, "white full-board score");
  }

  private static String[] swapColors(String[] rows) {
    String[] swapped = new String[8];
    for (int y = 0; y < 8; y++) {
      StringBuilder row = new StringBuilder(8);
      for (int x = 0; x < 8; x++) {
        char cell = rows[y].charAt(x);
        row.append(cell == '0' ? '1' : cell == '1' ? '0' : '.');
      }
      swapped[y] = row.toString();
    }
    return swapped;
  }

  private static void testColorSwap() {
    OthelloAI_05.Board original = randomPosition(24, 4096L);
    String[] swappedRows = swapColors(rowsOf(original));
    OthelloAI_05.Board swapped = boardFromRows(swappedRows, 1 - original.p);
    check(legalMoves(original).equals(legalMoves(swapped)), "color/player swap preserves legal cells");

    int move = legalMoves(original).get(0);
    String[] movedThenSwapped = swapColors(rowsOf(OthelloAI_05.move(original, move)));
    String[] swappedThenMoved = rowsOf(OthelloAI_05.move(swapped, move));
    check(Arrays.equals(movedThenSwapped, swappedThenMoved), "color swap commutes with move");
  }

  private static int transformCell(int cell, int transform) {
    int y = cell / 8;
    int x = cell % 8;
    int tx;
    int ty;
    switch (transform) {
      case 0: tx = x; ty = y; break;
      case 1: tx = 7 - y; ty = x; break;
      case 2: tx = 7 - x; ty = 7 - y; break;
      case 3: tx = y; ty = 7 - x; break;
      case 4: tx = 7 - x; ty = y; break;
      case 5: tx = x; ty = 7 - y; break;
      case 6: tx = y; ty = x; break;
      case 7: tx = 7 - y; ty = 7 - x; break;
      default: throw new IllegalArgumentException("bad transform");
    }
    return ty * 8 + tx;
  }

  private static String[] transformRows(String[] rows, int transform) {
    char[][] result = new char[8][8];
    for (int cell = 0; cell < 64; cell++) {
      int target = transformCell(cell, transform);
      result[target / 8][target % 8] = rows[cell / 8].charAt(cell % 8);
    }
    String[] transformed = new String[8];
    for (int y = 0; y < 8; y++) transformed[y] = new String(result[y]);
    return transformed;
  }

  private static void testDihedralSymmetry() {
    OthelloAI_05.Board original = randomPosition(22, 6324091L);
    String[] originalRows = rowsOf(original);
    List<Integer> originalMoves = legalMoves(original);
    check(!originalMoves.isEmpty(), "symmetry test position must have a move");
    int chosen = originalMoves.get(0);
    int originalEvaluation = OthelloAI_05.evaluate(original);
    int maxEvaluationDifference = 0;

    for (int transform = 0; transform < 8; transform++) {
      OthelloAI_05.Board transformed = boardFromRows(
          transformRows(originalRows, transform), original.p);
      Set<Integer> expectedMoves = new HashSet<>();
      for (int move : originalMoves) expectedMoves.add(transformCell(move, transform));
      check(new HashSet<>(legalMoves(transformed)).equals(expectedMoves),
          "legal moves under transform " + transform);
      int transformedEvaluation = OthelloAI_05.evaluate(transformed);
      maxEvaluationDifference = Math.max(
          maxEvaluationDifference, Math.abs(transformedEvaluation - originalEvaluation));

      OthelloAI_05.Board movedOriginal = OthelloAI_05.move(original, chosen);
      OthelloAI_05.Board movedTransformed = OthelloAI_05.move(
          transformed, transformCell(chosen, transform));
      check(Arrays.equals(
              transformRows(rowsOf(movedOriginal), transform), rowsOf(movedTransformed)),
          "move commutes with transform " + transform);
    }
    check(maxEvaluationDifference <= 100,
        "D4 evaluation drift exceeds one disc-equivalent: " + maxEvaluationDifference);
  }

  private static void testParameterFile() throws IOException {
    int[] sizes = {8, 8, 8, 5, 6, 7, 8, 10, 10, 10, 10};
    int perPhase = 0;
    for (int size : sizes) perPhase += size * 2 * 16 + 16 + 16 * 16 + 16 + 16 + 1;
    perPhase += 3 * 8 + 8 + 8 * 8 + 8 + 19 + 1;
    int expected = 4 * perPhase;
    check(expected == 25_436, "parameter formula");

    Path path = Path.of(System.getProperty("othello.param", "resources/param.txt"));
    int count = 0;
    try (BufferedReader reader = Files.newBufferedReader(path)) {
      String line;
      while ((line = reader.readLine()) != null) {
        check(!line.isBlank(), "parameter line must not be blank");
        double value = Double.parseDouble(line);
        check(Double.isFinite(value), "parameter must be finite");
        count++;
      }
    }
    check(count == expected, "parameter count: " + count);
  }

  private static void testBook() {
    int policies = 0;
    int nodes = 0;
    for (OthelloAI_05.BookNode head : OthelloAI_05.book) {
      for (OthelloAI_05.BookNode node = head; node != null; node = node.p_n_node) {
        nodes++;
        policies += node.size;
      }
    }
    check(nodes == 17_480, "unique book positions: " + nodes);
    check(policies == 19_660, "book registrations: " + policies);

    OthelloAI_05.Board initial = boardFromRows(INITIAL, 0);
    OthelloAI_05.Board canonical = OthelloAI_05.move(initial, 4 * 8 + 5);
    int policy = OthelloAI_05.get_book(canonical.b);
    check(policy >= 0 && isLegal(canonical, policy), "known book position returns legal move");
  }

  private static void testEvaluationReproducibility() {
    OthelloAI_05.Board board = randomPosition(30, 20260715L);
    int expected = OthelloAI_05.evaluate(board);
    for (int i = 0; i < 100; i++) {
      check(OthelloAI_05.evaluate(board) == expected, "evaluation reproducibility");
    }
  }

  private static void testInputValidation() {
    int[] encoded = new int[OthelloAI_05.b_idx_num];
    String shortRow = ".......\n........\n........\n........\n........\n........\n........\n........\n";
    int result = OthelloAI_05.input_board(
        encoded, new BufferedReader(new StringReader(shortRow)));
    check(result == -2, "short board row must be rejected");

    String badCharacter = ".......?\n........\n........\n........\n........\n........\n........\n........\n";
    result = OthelloAI_05.input_board(
        encoded, new BufferedReader(new StringReader(badCharacter)));
    check(result == -2, "invalid board character must be rejected");
  }

  private static void testTranspositionTableSeparatesPlayers() {
    OthelloAI_05.Board black = randomPosition(20, 17L);
    black.p = 0;
    OthelloAI_05.Board white = new OthelloAI_05.Board(black);
    white.p = 1;
    OthelloAI_05.search_hash_table_init(0);
    int hash = OthelloAI_05.calc_search_hash(black);
    OthelloAI_05.register_search(0, black, hash, -123, 456);

    int[] lower = new int[1];
    int[] upper = new int[1];
    OthelloAI_05.get_search(black, hash, 0, lower, upper);
    check(lower[0] == -123 && upper[0] == 456, "same-player TT hit");
    OthelloAI_05.get_search(white, hash, 0, lower, upper);
    check(lower[0] == -OthelloAI_05.inf && upper[0] == -OthelloAI_05.inf,
        "opposite-player TT miss");
  }

  private static void testFinalSearchMatchesExactAtTenEmpties() {
    OthelloAI_05.Board board = randomPosition(50, 1009L);
    check(64 - board.n == 10, "exact-search test has ten empties");
    OthelloAI_05.searched_nodes = 1;
    int exact = OthelloAI_05.negaAlphaFinal(
        board, false, 10, -OthelloAI_05.inf, OthelloAI_05.inf);
    OthelloAI_05.search_hash_table_init(1 - OthelloAI_05.f_search_table_idx);
    OthelloAI_05.searched_nodes = 1;
    int scout = OthelloAI_05.negaScoutFinal(
        board, OthelloAI_05.tim(), false, 10, -OthelloAI_05.inf, OthelloAI_05.inf);
    check(scout == exact, "final NegaScout must equal exact alpha-beta at ten empties");
  }

  private static void testTimedSearchReturnsLegalMove() {
    OthelloAI_05.Board board = randomPosition(24, 73L);
    List<Integer> legal = legalMoves(board);
    check(!legal.isEmpty(), "timed-search position has legal move");
    long start = OthelloAI_05.tim();
    OthelloAI_05.begin_move_timer(start);
    OthelloAI_05.SearchResult result;
    try {
      result = OthelloAI_05.search(board, start, 64);
    } finally {
      OthelloAI_05.clear_move_timer();
    }
    long elapsed = OthelloAI_05.tim() - start;
    check(legal.contains(result.policy), "timed search returns legal move");
    check(elapsed <= OthelloAI_05.move_time_limit_ms + 1_000L,
        "timed search overrun: " + elapsed + " ms");
  }

  private static void testFinalRootResearchMatchesExact() {
    String[] rows = {
      ".11111.0", ".100000.", "11010000", "10100000",
      "00000000", "..100110", "...11110", ".1111111"
    };
    OthelloAI_05.Board board = boardFromRows(rows, 0);
    check(64 - board.n == 10, "root re-search test has ten empties");
    List<OthelloAI_05.Board> ordered = new ArrayList<>();
    int exact = -OthelloAI_05.inf, policy = -1;
    for (int move : legalMoves(board)) {
      OthelloAI_05.Board child = OthelloAI_05.move(board, move);
      child.v = -OthelloAI_05.evaluate(child);
      ordered.add(child);
      int value = -OthelloAI_05.negaAlphaFinal(
          child, false, 9, -OthelloAI_05.inf, OthelloAI_05.inf);
      if (value > exact) {
        exact = value;
        policy = move;
      }
    }
    java.util.Collections.sort(ordered);
    check(ordered.get(0).policy == 0, "fixed root evaluation order starts at cell 0");
    check(policy == 50 && exact == 1_000,
        "strict root search selects non-first cell 50 with value 1000");
    OthelloAI_05.search_hash_table_init(0);
    OthelloAI_05.search_hash_table_init(1);
    OthelloAI_05.f_search_table_idx = 0;
    OthelloAI_05.SearchResult result = OthelloAI_05.finalSearch(board, OthelloAI_05.tim());
    check(result.rootFirstPolicy == ordered.get(0).policy,
        "final root must start from the fixed evaluation-order leader");
    check(result.rootFirstPolicy != policy,
        "strict best move must come from a non-first root candidate");
    check(result.rootResearchCount > 0, "non-first final candidate must be re-searched");
    check(result.rootResearchDepth == 9, "root re-search must use child depth 9");
    check(result.policy == policy, "final root policy must match strict root search");
    check(result.value == exact, "final root value must match strict root search");
  }

  private static void check(boolean condition, String message) {
    assertions++;
    if (!condition) throw new AssertionError(message);
  }
}
