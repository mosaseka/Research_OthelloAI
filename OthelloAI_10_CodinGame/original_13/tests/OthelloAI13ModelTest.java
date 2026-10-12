import java.io.File;

/** Dependency-free checks for original_13's BCE runtime contract. */
public final class OthelloAI13ModelTest {
  private static void check(boolean condition, String message) {
    if (!condition) throw new AssertionError(message);
  }

  private static void checkEquals(int expected, int actual, String message) {
    if (expected != actual) {
      throw new AssertionError(
          message + ": expected=" + expected + ", actual=" + actual);
    }
  }

  public static void main(String[] args) throws Exception {
    checkEquals(48, OthelloAI_13.n_dense0, "dense0 width");
    checkEquals(48, OthelloAI_13.n_dense1, "dense1 width");
    checkEquals(142_812, OthelloAI_13.evaluation_parameter_count,
        "parameter count");
    checkEquals(4, OthelloAI_13.DEFAULT_BOOK_STONES,
        "book must be off by default");

    File parameterFile = new File("resources", "value_param.txt");
    OthelloAI_13.validate_evaluation_file(parameterFile);
    check(
        "B1DE15DEB14CAD293F916B2AF4EE177D631F0D5EAE0664E3E8986ED81ACFAD7B"
            .equalsIgnoreCase(OthelloAI_13.sha256(parameterFile)),
        "value parameter hash");

    OthelloAI_13.ModelBundle bundle = OthelloAI_13.loadModelBundle();
    check(bundle != null, "model bundle");
    check(bundle.valueFile.getCanonicalFile().equals(
        parameterFile.getCanonicalFile()), "bundle value path");

    // tanh(logit/2) is antisymmetric and remains inside the engine range.
    for (double logit : new double[] {-20.0, -2.0, -0.25, 0.0, 0.25, 2.0, 20.0}) {
      int positive = (int) (Math.tanh(logit * 0.5) * OthelloAI_13.sc_w);
      int negative = (int) (Math.tanh(-logit * 0.5) * OthelloAI_13.sc_w);
      checkEquals(-positive, negative, "BCE transform antisymmetry");
      check(Math.abs(positive) < OthelloAI_13.sc_w,
          "BCE transform must remain strictly bounded");
    }

    System.out.println("OthelloAI13ModelTest: PASS");
  }
}
