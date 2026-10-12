/*
 * Diagnostic-only fixed-depth bridge for OthelloAI_11.
 *
 * Compile this file together with the unmodified OthelloAI_11.java.  It uses
 * package-private engine primitives so move legality, evaluator features and
 * negamax semantics stay identical to the production engine.  No Client
 * protocol output is changed.
 */
import java.io.File;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

public final class JavaRootSearchBridge11 {
  private JavaRootSearchBridge11() {}

  static final int SCORE_STATIC = 0;
  static final int SCORE_SHALLOW = 1;
  static final int SCORE_DEEP = 2;

  static final class MoveScore {
    int cell;
    double staticValue;
    double shallowValue;
    double deepValue;
    int staticRank;
    int shallowRank;
    int deepRank;
  }

  static final class ReplyScore {
    int cell;
    double staticValue;
    double continuationValue;
    int continuationRank;
  }

  static void fail(String message) {
    throw new IllegalArgumentException(message);
  }

  static Map<String, String> arguments(String[] args) {
    Map<String, String> result = new HashMap<>();
    for (int index = 0; index < args.length; index++) {
      String key = args[index];
      if (!key.startsWith("--") || index + 1 >= args.length) {
        fail("arguments must be --name value pairs");
      }
      if (result.put(key.substring(2), args[++index]) != null) {
        fail("duplicate argument: " + key);
      }
    }
    return result;
  }

  static String required(Map<String, String> args, String key) {
    String value = args.get(key);
    if (value == null || value.isBlank()) fail("missing --" + key);
    return value;
  }

  static int integer(Map<String, String> args, String key, int minimum, int maximum) {
    final int value;
    try {
      value = Integer.parseInt(required(args, key));
    } catch (NumberFormatException error) {
      fail("--" + key + " must be an integer");
      return 0;
    }
    if (value < minimum || value > maximum) {
      fail("--" + key + " must be in [" + minimum + "," + maximum + "]");
    }
    return value;
  }

  static Integer optionalInteger(
      Map<String, String> args, String key, int minimum, int maximum) {
    if (!args.containsKey(key)) return null;
    return integer(args, key, minimum, maximum);
  }

  static void initializeEngine(File parameterFile) {
    OthelloAI_11.init_pow();
    OthelloAI_11.init_mod3();
    OthelloAI_11.init_pop_mid();
    OthelloAI_11.init_move();
    OthelloAI_11.init_local_place();
    OthelloAI_11.init_included();
    OthelloAI_11.init_pop_digit();
    OthelloAI_11.value_evaluator = OthelloAI_11.loadEvaluator(
        parameterFile,
        OthelloAI_11.ValueFeatureMode.EXACT_MOBILITY,
        null,
        "diagnostic value");
    OthelloAI_11.value_param_sha256 = OthelloAI_11.value_evaluator.sha256;
    OthelloAI_11.policy_evaluator = null;
    OthelloAI_11.clear_move_timer();
  }

  static OthelloAI_11.Board decodeBoard(String text, int player) {
    String boardText = text.replace("/", "").replaceAll("\\s+", "").toUpperCase(Locale.ROOT);
    if (boardText.length() != 64 || !boardText.matches("[.XO]{64}")) {
      fail("--board must contain exactly 64 characters from '.', 'X', 'O'");
    }
    long black = 0L;
    long white = 0L;
    OthelloAI_11.vacant_count = 0;
    for (int cell = 0; cell < 64; cell++) {
      char value = boardText.charAt(cell);
      if (value == 'X') black |= 1L << cell;
      else if (value == 'O') white |= 1L << cell;
      else OthelloAI_11.vacant_cells[OthelloAI_11.vacant_count++] = cell;
    }
    int stones = Long.bitCount(black | white);
    if (stones < 4) fail("board must contain at least four discs");
    if (stones < 63) OthelloAI_11.sortVacantCells();

    OthelloAI_11.Board board = new OthelloAI_11.Board();
    for (int index = 0; index < OthelloAI_11.b_idx_num; index++) {
      board.b[index] = OthelloAI_11.n_line - 1;
      for (int local = 0; local < OthelloAI_11.idx_n_cell[index]; local++) {
        int cell = OthelloAI_11.global_place[index][local];
        if (((black >>> cell) & 1L) != 0L) {
          board.b[index] -= OthelloAI_11.pow3[OthelloAI_11.hw_m1 - local] * 2;
        } else if (((white >>> cell) & 1L) != 0L) {
          board.b[index] -= OthelloAI_11.pow3[OthelloAI_11.hw_m1 - local];
        }
      }
    }
    board.p = player;
    board.n = stones;
    OthelloAI_11.initializeBitboards(board);
    return board;
  }

  static int fixedDepthValue(OthelloAI_11.Board board, int depth) {
    OthelloAI_11.clear_move_timer();
    OthelloAI_11.resetNodeCounters();
    return OthelloAI_11.negaAlphaInternal(
        board, false, depth, -OthelloAI_11.inf, OthelloAI_11.inf, false);
  }

  static List<Integer> legalCells(OthelloAI_11.Board board) {
    long moves = OthelloAI_11.legalMoves(board);
    List<Integer> result = new ArrayList<>();
    while (moves != 0L) {
      int cell = Long.numberOfTrailingZeros(moves);
      result.add(cell);
      moves &= moves - 1L;
    }
    return result;
  }

  static List<MoveScore> rootScores(OthelloAI_11.Board board, int shallow, int deep) {
    List<MoveScore> scores = new ArrayList<>();
    for (int cell : legalCells(board)) {
      OthelloAI_11.Board child = new OthelloAI_11.Board();
      OthelloAI_11.moveInto(board, cell, child);
      MoveScore score = new MoveScore();
      score.cell = cell;
      score.staticValue = OthelloAI_11.calcResultValue(-OthelloAI_11.evaluate(child));
      score.shallowValue = OthelloAI_11.calcResultValue(
          -fixedDepthValue(child, Math.max(0, shallow - 1)));
      score.deepValue = OthelloAI_11.calcResultValue(
          -fixedDepthValue(child, Math.max(0, deep - 1)));
      scores.add(score);
    }
    assignStaticRanks(scores);
    assignRootRanks(scores, true);
    assignRootRanks(scores, false);
    scores.sort(Comparator.comparingInt(value -> value.cell));
    return scores;
  }

  static void assignStaticRanks(List<MoveScore> scores) {
    List<MoveScore> ordered = new ArrayList<>(scores);
    ordered.sort((left, right) -> {
      int valueOrder = Double.compare(right.staticValue, left.staticValue);
      return valueOrder != 0 ? valueOrder : Integer.compare(left.cell, right.cell);
    });
    for (int index = 0; index < ordered.size(); index++) {
      ordered.get(index).staticRank = index + 1;
    }
  }

  static void assignRootRanks(List<MoveScore> scores, boolean shallow) {
    List<MoveScore> ordered = new ArrayList<>(scores);
    ordered.sort((left, right) -> {
      double lv = shallow ? left.shallowValue : left.deepValue;
      double rv = shallow ? right.shallowValue : right.deepValue;
      int valueOrder = Double.compare(rv, lv);
      return valueOrder != 0 ? valueOrder : Integer.compare(left.cell, right.cell);
    });
    for (int index = 0; index < ordered.size(); index++) {
      if (shallow) ordered.get(index).shallowRank = index + 1;
      else ordered.get(index).deepRank = index + 1;
    }
  }

  static List<ReplyScore> replyScores(
      OthelloAI_11.Board board, int observedCell, int deepDepth) {
    OthelloAI_11.Board child = new OthelloAI_11.Board();
    OthelloAI_11.moveInto(board, observedCell, child);
    List<ReplyScore> scores = new ArrayList<>();
    for (int cell : legalCells(child)) {
      OthelloAI_11.Board reply = new OthelloAI_11.Board();
      OthelloAI_11.moveInto(child, cell, reply);
      ReplyScore score = new ReplyScore();
      score.cell = cell;
      // After two plies it is the root player's turn, so no sign inversion.
      score.staticValue = OthelloAI_11.calcResultValue(OthelloAI_11.evaluate(reply));
      score.continuationValue = OthelloAI_11.calcResultValue(
          fixedDepthValue(reply, Math.max(0, deepDepth - 2)));
      scores.add(score);
    }
    List<ReplyScore> ordered = new ArrayList<>(scores);
    // The opponent chooses the smallest value from the root player's view.
    ordered.sort((left, right) -> {
      int valueOrder = Double.compare(left.continuationValue, right.continuationValue);
      return valueOrder != 0 ? valueOrder : Integer.compare(left.cell, right.cell);
    });
    for (int index = 0; index < ordered.size(); index++) {
      ordered.get(index).continuationRank = index + 1;
    }
    scores.sort(Comparator.comparingInt(value -> value.cell));
    return scores;
  }

  static MoveScore findMove(List<MoveScore> values, int cell) {
    for (MoveScore value : values) if (value.cell == cell) return value;
    return null;
  }

  static ReplyScore findReply(List<ReplyScore> values, int cell) {
    for (ReplyScore value : values) if (value.cell == cell) return value;
    return null;
  }

  static String number(double value) {
    if (!Double.isFinite(value)) fail("non-finite diagnostic value");
    return String.format(Locale.ROOT, "%.8f", value);
  }

  static String moveName(int cell) {
    return Character.toString((char) ('A' + cell % 8)) + (cell / 8 + 1);
  }

  static void appendMove(StringBuilder out, int cell) {
    out.append("[" ).append(cell / 8).append(',').append(cell % 8).append(']');
  }

  static void appendRootScores(StringBuilder out, List<MoveScore> scores) {
    out.append('[');
    for (int index = 0; index < scores.size(); index++) {
      if (index != 0) out.append(',');
      MoveScore value = scores.get(index);
      out.append("{\"move\":");
      appendMove(out, value.cell);
      out.append(",\"move_algebraic\":\"").append(moveName(value.cell)).append('"')
          .append(",\"static_value_disc\":").append(number(value.staticValue))
          .append(",\"shallow_value_disc\":").append(number(value.shallowValue))
          .append(",\"deep_value_disc\":").append(number(value.deepValue))
          .append(",\"static_rank\":").append(value.staticRank)
          .append(",\"shallow_rank\":").append(value.shallowRank)
          .append(",\"deep_rank\":").append(value.deepRank).append('}');
    }
    out.append(']');
  }

  static int rootRank(MoveScore score, int scoreType) {
    if (scoreType == SCORE_STATIC) return score.staticRank;
    if (scoreType == SCORE_SHALLOW) return score.shallowRank;
    if (scoreType == SCORE_DEEP) return score.deepRank;
    fail("unknown root score type");
    return 0;
  }

  static double rootValue(MoveScore score, int scoreType) {
    if (scoreType == SCORE_STATIC) return score.staticValue;
    if (scoreType == SCORE_SHALLOW) return score.shallowValue;
    if (scoreType == SCORE_DEEP) return score.deepValue;
    fail("unknown root score type");
    return 0.0;
  }

  static MoveScore findRankedMove(List<MoveScore> scores, int scoreType, int rank) {
    for (MoveScore score : scores) {
      if (rootRank(score, scoreType) == rank) return score;
    }
    return null;
  }

  static void appendRankSummary(
      StringBuilder out, List<MoveScore> scores, int scoreType) {
    MoveScore best = findRankedMove(scores, scoreType, 1);
    if (best == null) fail("root score summary has no best move");
    MoveScore runnerUp = findRankedMove(scores, scoreType, 2);
    out.append("{\"best_move\":");
    appendMove(out, best.cell);
    out.append(",\"best_move_algebraic\":\"").append(moveName(best.cell)).append('"')
        .append(",\"best_value_disc\":").append(number(rootValue(best, scoreType)));
    if (runnerUp == null) {
      out.append(",\"runner_up_move\":null")
          .append(",\"runner_up_move_algebraic\":null")
          .append(",\"runner_up_value_disc\":null")
          .append(",\"best_minus_runner_up_gap_disc\":null}");
    } else {
      out.append(",\"runner_up_move\":");
      appendMove(out, runnerUp.cell);
      out.append(",\"runner_up_move_algebraic\":\"")
          .append(moveName(runnerUp.cell)).append('"')
          .append(",\"runner_up_value_disc\":")
          .append(number(rootValue(runnerUp, scoreType)))
          .append(",\"best_minus_runner_up_gap_disc\":")
          .append(number(rootValue(best, scoreType) - rootValue(runnerUp, scoreType)))
          .append('}');
    }
  }

  static void appendRootRankSummaries(StringBuilder out, List<MoveScore> scores) {
    out.append("{\"viewpoint\":\"root_player\"")
        .append(",\"value_unit\":\"disc\"")
        .append(",\"ordering\":\"larger_is_better\"")
        .append(",\"gap_definition\":\"best_value_disc - runner_up_value_disc\"")
        .append(",\"static\":");
    appendRankSummary(out, scores, SCORE_STATIC);
    out.append(",\"shallow\":");
    appendRankSummary(out, scores, SCORE_SHALLOW);
    out.append(",\"deep\":");
    appendRankSummary(out, scores, SCORE_DEEP);
    out.append('}');
  }

  static void appendReplyScores(StringBuilder out, List<ReplyScore> scores) {
    out.append('[');
    for (int index = 0; index < scores.size(); index++) {
      if (index != 0) out.append(',');
      ReplyScore value = scores.get(index);
      out.append("{\"move\":");
      appendMove(out, value.cell);
      out.append(",\"move_algebraic\":\"").append(moveName(value.cell)).append('"')
          .append(",\"static_value_disc\":").append(number(value.staticValue))
          .append(",\"deep_continuation_value_disc\":")
          .append(number(value.continuationValue))
          .append(",\"opponent_rank\":").append(value.continuationRank).append('}');
    }
    out.append(']');
  }

  public static void main(String[] rawArgs) throws Exception {
    Map<String, String> args = arguments(rawArgs);
    File parameterFile = new File(required(args, "param")).getCanonicalFile();
    if (!parameterFile.isFile()) fail("parameter file does not exist: " + parameterFile);
    int player = integer(args, "player", 0, 1);
    int shallow = integer(args, "shallow-depth", 1, 12);
    int deep = integer(args, "deep-depth", shallow, 16);
    Integer observedRow = optionalInteger(args, "observed-row", 0, 7);
    Integer observedCol = optionalInteger(args, "observed-col", 0, 7);
    if ((observedRow == null) != (observedCol == null)) {
      fail("--observed-row and --observed-col must appear together");
    }
    Integer replyRow = optionalInteger(args, "observed-reply-row", 0, 7);
    Integer replyCol = optionalInteger(args, "observed-reply-col", 0, 7);
    if ((replyRow == null) != (replyCol == null)) {
      fail("--observed-reply-row and --observed-reply-col must appear together");
    }
    if (replyRow != null && observedRow == null) {
      fail("observed reply requires an observed root move");
    }

    initializeEngine(parameterFile);
    OthelloAI_11.Board board = decodeBoard(required(args, "board"), player);
    List<MoveScore> roots = rootScores(board, shallow, deep);
    if (roots.isEmpty()) fail("diagnostic position has no legal root move");

    MoveScore observed = null;
    List<ReplyScore> replies = new ArrayList<>();
    ReplyScore observedReply = null;
    int observedCell = -1;
    if (observedRow != null) {
      observedCell = observedRow * 8 + observedCol;
      observed = findMove(roots, observedCell);
      if (observed == null) fail("observed root move is illegal");
      replies = replyScores(board, observedCell, deep);
      if (replyRow != null) {
        observedReply = findReply(replies, replyRow * 8 + replyCol);
        if (observedReply == null) fail("observed opponent reply is illegal");
      }
    }
    MoveScore deepBest = roots.stream().min(
        Comparator.comparingInt(value -> value.deepRank)).orElseThrow();
    ReplyScore bestReply = replies.stream().min(
        Comparator.comparingInt(value -> value.continuationRank)).orElse(null);

    StringBuilder out = new StringBuilder(8192);
    out.append('{')
        .append("\"schema\":\"original-11-fixed-depth-root-diagnostic-v1\"")
        .append(",\"feature_schema\":\"exact-mobility-v1\"")
        .append(",\"parameter_sha256\":\"")
        .append(OthelloAI_11.value_param_sha256.toLowerCase(Locale.ROOT)).append('"')
        .append(",\"player\":").append(player)
        .append(",\"stones\":").append(board.n)
        .append(",\"shallow_depth\":").append(shallow)
        .append(",\"deep_depth\":").append(deep)
        .append(",\"current_value_disc\":")
        .append(number(OthelloAI_11.calcResultValue(OthelloAI_11.evaluate(board))))
        .append(",\"legal_moves\":");
    appendRootScores(out, roots);
    out.append(",\"root_rank_summaries\":");
    appendRootRankSummaries(out, roots);
    out.append(",\"deep_best_move\":");
    appendMove(out, deepBest.cell);
    out.append(",\"deep_best_value_disc\":").append(number(deepBest.deepValue));
    if (observed == null) {
      out.append(",\"observed\":null,\"opponent_replies\":[]")
          .append(",\"deep_best_opponent_reply\":null")
          .append(",\"observed_opponent_reply\":null");
    } else {
      out.append(",\"observed\":{\"move\":");
      appendMove(out, observed.cell);
      out.append(",\"shallow_rank\":").append(observed.shallowRank)
          .append(",\"deep_rank\":").append(observed.deepRank)
          .append(",\"shallow_value_disc\":").append(number(observed.shallowValue))
          .append(",\"deep_value_disc\":").append(number(observed.deepValue))
          .append(",\"deep_best_gap_disc\":")
          .append(number(deepBest.deepValue - observed.deepValue)).append('}')
          .append(",\"opponent_replies\":");
      appendReplyScores(out, replies);
      if (bestReply == null) {
        out.append(",\"deep_best_opponent_reply\":null");
      } else {
        out.append(",\"deep_best_opponent_reply\":{\"move\":");
        appendMove(out, bestReply.cell);
        out.append(",\"deep_continuation_value_disc\":")
            .append(number(bestReply.continuationValue)).append('}');
      }
      if (observedReply == null) {
        out.append(",\"observed_opponent_reply\":null");
      } else {
        out.append(",\"observed_opponent_reply\":{\"move\":");
        appendMove(out, observedReply.cell);
        out.append(",\"opponent_rank\":").append(observedReply.continuationRank)
            .append(",\"deep_continuation_value_disc\":")
            .append(number(observedReply.continuationValue)).append('}');
      }
    }
    out.append(",\"mpc_used\":false")
        .append(",\"diagnostic_only\":true")
        .append(",\"training_eligible\":false")
        .append(",\"adoption_gate_eligible\":false}");
    System.out.println(out);
  }
}
