import javafx.animation.Animation;
import javafx.animation.KeyFrame;
import javafx.animation.Timeline;
import javafx.application.Application;
import javafx.application.Platform;
import javafx.beans.binding.Bindings;
import javafx.concurrent.Task;
import javafx.geometry.Insets;
import javafx.geometry.Pos;
import javafx.scene.AccessibleRole;
import javafx.scene.Group;
import javafx.scene.Parent;
import javafx.scene.Scene;
import javafx.scene.canvas.Canvas;
import javafx.scene.canvas.GraphicsContext;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.input.KeyCode;
import javafx.scene.input.KeyCodeCombination;
import javafx.scene.layout.HBox;
import javafx.scene.layout.Pane;
import javafx.scene.layout.Priority;
import javafx.scene.layout.StackPane;
import javafx.scene.layout.VBox;
import javafx.scene.paint.Color;
import javafx.scene.shape.Circle;
import javafx.scene.transform.Scale;
import javafx.stage.Stage;
import javafx.util.Duration;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.net.URISyntaxException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.TimeUnit;
import java.util.function.LongConsumer;

public class OthelloGUI extends Application {
    private static final String AI_CLASS = "OthelloAI_final_48";
    private static final int OFFSET = 10;
    private static final int CELL_SIZE = 60;
    private static final int STONE_INSET = 3;
    private static final int BOARD_SIZE = Othello.HW * CELL_SIZE + 2 * OFFSET;
    private static final int SCENE_WIDTH = 900;
    private static final int SCENE_HEIGHT = 560;
    private static final String BACKGROUND = "-fx-background-color: #153b33;";
    private static final String LABEL_STYLE = "-fx-text-fill: white;";

    private Stage stage;
    private Parent titlePane;
    private Parent gamePane;
    private final StackPane content = new StackPane();
    private final Canvas canvas = new Canvas(BOARD_SIZE, BOARD_SIZE);
    private final Pane boardPane = new Pane(canvas);
    private final List<Button> legalButtons = new ArrayList<>();
    private final Label playerLabel = new Label();
    private final Label stoneLabel = new Label();
    private final Label turnLabel = new Label();
    private final Label searchLabel = new Label();
    private final Label valueLabel = new Label();
    private final Button restartButton = new Button();
    private Timeline searchCountdown;

    private Othello othello;
    private int aiPlayer;
    private AiConnection ai;

    @Override
    public void start(Stage primaryStage) {
        stage = primaryStage;
        titlePane = createTitlePane();
        gamePane = createGamePane();
        Button fullScreenButton = new Button();
        fullScreenButton.textProperty().bind(Bindings.when(stage.fullScreenProperty())
                .then("全画面を解除").otherwise("全画面表示"));
        fullScreenButton.setOnAction(e -> toggleFullScreen());
        StackPane.setAlignment(fullScreenButton, Pos.TOP_RIGHT);
        StackPane.setMargin(fullScreenButton, new Insets(16));

        Scene scene = new Scene(new StackPane(content, fullScreenButton), SCENE_WIDTH, SCENE_HEIGHT);
        scene.getAccelerators().put(new KeyCodeCombination(KeyCode.F11), this::toggleFullScreen);
        stage.setScene(scene);
        stage.setTitle("オセロ - " + AI_CLASS);
        stage.setMinWidth(710);
        stage.setMinHeight(490);
        stage.setFullScreenExitHint("Esc キーで全画面を解除");
        showTitle();
        stage.show();
    }

    private void toggleFullScreen() {
        stage.setFullScreen(!stage.isFullScreen());
    }

    private Parent createTitlePane() {
        Label title = new Label("オセロ");
        title.getStyleClass().add("game-title");
        Label opponent = new Label("対戦相手　" + AI_CLASS);
        opponent.getStyleClass().add("opponent");
        HBox choices = new HBox(10, titleButton("先手（黒）で対戦", Othello.BLACK),
                titleButton("後手（白）で対戦", Othello.WHITE));
        VBox.setMargin(choices, new Insets(18, 0, 0, 0));
        VBox heading = new VBox(6, title, opponent, choices);
        heading.setAlignment(Pos.CENTER_LEFT);
        HBox.setHgrow(heading, Priority.ALWAYS);
        HBox hero = new HBox(24, heading, openingDiagram());
        hero.setAlignment(Pos.CENTER_LEFT);

        Label guideTitle = new Label("操作ガイド");
        guideTitle.getStyleClass().add("guide-title");
        HBox guide = new HBox(24,
                guideColumn("石を置く", "青いマスをクリックします。縦・横・斜めにはさんだ相手の石が裏返ります。"),
                guideColumn("パスと勝敗", "置ける場所がないと自動でパス。両者とも置けなくなったら終局し、石の多い方が勝ちです。"),
                guideColumn("もう一局遊ぶ", "対局中は「最初から」、終局後は「再戦」で同じ色で遊べます。「タイトルへ」で先後を選び直せます。"));
        VBox instructions = new VBox(14, guideTitle, guide);
        instructions.getStyleClass().add("guide");

        VBox content = new VBox(32, hero, instructions);
        content.setMaxWidth(850);
        content.setAlignment(Pos.CENTER_LEFT);
        StackPane page = new StackPane(content);
        page.setPadding(new Insets(24, 38, 24, 38));
        page.getStyleClass().add("title-page");
        var stylesheet = OthelloGUI.class.getResource("/othello-title.css");
        page.getStylesheets().add(stylesheet != null ? stylesheet.toExternalForm()
                : Path.of("othello-title.css").toUri().toString());
        return page;
    }

    private Button titleButton(String text, int color) {
        Button button = new Button(text);
        button.setGraphic(new Circle(7,
                color == Othello.BLACK ? Color.web("#192d27") : Color.web("#faf6e9")));
        button.getStyleClass().add(color == Othello.BLACK ? "black-choice" : "white-choice");
        button.setOnAction(e -> startGame(color));
        return button;
    }

    private VBox guideColumn(String heading, String description) {
        Label name = new Label(heading);
        name.getStyleClass().add("guide-heading");
        Label body = new Label(description);
        body.getStyleClass().add("guide-body");
        body.setWrapText(true);
        VBox column = new VBox(6, name, body);
        column.setPrefWidth(230);
        column.setMinWidth(0);
        HBox.setHgrow(column, Priority.ALWAYS);
        return column;
    }

    private Canvas openingDiagram() {
        int cell = 22;
        int frame = 6;
        int size = 2 * frame + Othello.HW * cell;
        Canvas diagram = new Canvas(size, size);
        diagram.setAccessibleRole(AccessibleRole.IMAGE_VIEW);
        diagram.setAccessibleText("初期盤面。青い4マスに黒を置けます。");
        diagram.getStyleClass().add("opening-diagram");
        GraphicsContext g = diagram.getGraphicsContext2D();
        g.setFill(Color.web("#a8b08b"));
        g.fillRoundRect(0, 0, size, size, 8, 8);
        Othello opening = new Othello();
        opening.checkLegal();
        for (int y = 0; y < Othello.HW; y++) {
            for (int x = 0; x < Othello.HW; x++) {
                int left = frame + x * cell;
                int top = frame + y * cell;
                int square = opening.grid[y][x];
                g.setFill(Color.web(square == Othello.LEGAL ? "#3498db" : "#23604e"));
                g.fillRect(left, top, cell - 1, cell - 1);
                if (square == Othello.BLACK || square == Othello.WHITE) {
                    g.setFill(square == Othello.BLACK ? Color.web("#14251f") : Color.web("#faf6e9"));
                    g.fillOval(left + 2, top + 2, cell - 5, cell - 5);
                }
            }
        }
        return diagram;
    }

    private Parent createGamePane() {
        boardPane.setMinSize(BOARD_SIZE, BOARD_SIZE);
        boardPane.setPrefSize(BOARD_SIZE, BOARD_SIZE);
        boardPane.setMaxSize(BOARD_SIZE, BOARD_SIZE);
        Scale boardScale = new Scale(1, 1, 0, 0);
        boardPane.getTransforms().add(boardScale);
        for (Label label : List.of(playerLabel, stoneLabel, turnLabel, searchLabel, valueLabel)) {
            label.setStyle(LABEL_STYLE + "-fx-font-size: 17px;");
        }
        stoneLabel.setStyle(LABEL_STYLE + "-fx-font-size: 30px;");
        turnLabel.setWrapText(true);
        Label valueGuide = new Label("＋はAI有利、−はあなた有利");
        valueGuide.setStyle(LABEL_STYLE + "-fx-font-size: 13px;");
        VBox evaluation = new VBox(4, valueLabel, valueGuide);

        restartButton.setOnAction(e -> startGame(1 - aiPlayer));
        Button titleButton = new Button("タイトルへ");
        titleButton.setOnAction(e -> showTitle());

        HBox actions = new HBox(10, restartButton, titleButton);
        VBox turn = new VBox(4, turnLabel, searchLabel);
        VBox sidebar = new VBox(16, playerLabel, stoneLabel, turn, evaluation, actions);
        double sidebarWidth = 305;
        sidebar.setMinWidth(sidebarWidth);
        sidebar.setPrefWidth(sidebarWidth);
        sidebar.setAlignment(Pos.CENTER_LEFT);
        double gap = 28;
        double padding = 20;
        HBox layout = new HBox(gap, new Group(boardPane), sidebar);
        // Let the window shrink before the board scale is recalculated.
        layout.setMinSize(0, 0);
        layout.setAlignment(Pos.CENTER);
        layout.setPadding(new Insets(padding));
        layout.setStyle(BACKGROUND);
        var scale = Bindings.createDoubleBinding(() -> {
            double availableWidth = layout.getWidth() - sidebarWidth - gap - 2 * padding;
            double availableHeight = layout.getHeight() - 2 * padding;
            return Math.max(1, Math.min(availableWidth, availableHeight)) / BOARD_SIZE;
        }, layout.widthProperty(), layout.heightProperty());
        boardScale.xProperty().bind(scale);
        boardScale.yProperty().bind(scale);
        return layout;
    }

    private void showTitle() {
        stopAI();
        content.getChildren().setAll(titlePane);
    }

    private void startGame(int humanPlayer) {
        stopAI();
        aiPlayer = 1 - humanPlayer;
        othello = new Othello();
        othello.checkLegal();
        playerLabel.setText(humanPlayer == Othello.BLACK ? "あなたは黒（先手）" : "あなたは白（後手）");
        restartButton.setText("最初から");
        valueLabel.setText("終局の予想石差（AI視点）  —");
        content.getChildren().setAll(gamePane);

        try {
            ai = new AiConnection(aiPlayer);
            playTurn("");
        } catch (IOException e) {
            showAIError(e);
        }
    }

    @Override
    public void stop() {
        stopAI();
    }

    private void stopAI() {
        clearSearchCountdown();
        if (ai != null) {
            ai.process.destroy();
            ai = null;
        }
    }

    private void drawBoard() {
        GraphicsContext gc = canvas.getGraphicsContext2D();
        gc.setFill(Color.web("#16866d"));
        gc.fillRect(0, 0, BOARD_SIZE, BOARD_SIZE);

        gc.setStroke(Color.web("#103a30"));
        gc.setLineWidth(2);
        for (int y = 0; y < Othello.HW; y++) {
            for (int x = 0; x < Othello.HW; x++) {
                gc.strokeRect(OFFSET + CELL_SIZE * x, OFFSET + CELL_SIZE * y, CELL_SIZE, CELL_SIZE);
            }
        }
    }

    private void showGrid() {
        boardPane.getChildren().removeAll(legalButtons);
        legalButtons.clear();
        drawBoard();
        GraphicsContext gc = canvas.getGraphicsContext2D();
        int stoneSize = CELL_SIZE - STONE_INSET * 2;

        for (int y = 0; y < Othello.HW; y++) {
            for (int x = 0; x < Othello.HW; x++) {
                int cell = othello.grid[y][x];
                int left = OFFSET + CELL_SIZE * x + STONE_INSET;
                int top = OFFSET + CELL_SIZE * y + STONE_INSET;
                if (cell == Othello.BLACK || cell == Othello.WHITE) {
                    gc.setFill(cell == Othello.BLACK ? Color.BLACK : Color.WHITE);
                    gc.fillOval(left, top, stoneSize, stoneSize);
                } else if (cell == Othello.LEGAL && ai != null && othello.player != aiPlayer) {
                    Button button = new Button();
                    button.setPrefSize(stoneSize, stoneSize);
                    button.setStyle("-fx-background-color: #3498db;");
                    button.setLayoutX(left);
                    button.setLayoutY(top);
                    button.setAccessibleText("" + (char) ('A' + x) + (y + 1));
                    final int row = y;
                    final int column = x;
                    button.setOnAction(e -> handleMove(row, column));
                    legalButtons.add(button);
                    boardPane.getChildren().add(button);
                }
            }
        }

        stoneLabel.setText("黒 " + othello.nStones[Othello.BLACK] + "  ・  白 " + othello.nStones[Othello.WHITE]);
    }

    private void handleMove(int y, int x) {
        othello.move(y, x);
        String passMessage = "";
        if (!othello.checkLegal()) {
            int passedPlayer = othello.player;
            othello.player = 1 - passedPlayer;
            if (othello.checkLegal()) {
                passMessage = passedPlayer == aiPlayer ? "AIはパスしました。 " : "あなたはパスです。 ";
            } else {
                othello.player = -1;
            }
        }
        playTurn(passMessage);
    }

    private void playTurn(String passMessage) {
        showGrid();
        if (othello.player == -1) {
            stopAI();
            int comparison = Integer.compare(othello.nStones[1 - aiPlayer], othello.nStones[aiPlayer]);
            turnLabel.setText(comparison > 0 ? "あなたの勝ち" : comparison < 0 ? "AIの勝ち" : "引き分け");
            restartButton.setText("再戦");
        } else if (othello.player == aiPlayer) {
            turnLabel.setText(passMessage + "AI思考中…");
            requestAIMove();
        } else {
            turnLabel.setText(passMessage + "あなたの番");
        }
    }

    private void requestAIMove() {
        StringBuilder board = new StringBuilder();
        for (int[] row : othello.grid) {
            for (int cell : row) {
                switch (cell) {
                    case Othello.BLACK -> board.append('0');
                    case Othello.WHITE -> board.append('1');
                    default -> board.append('.');
                }
            }
            board.append('\n');
        }

        String position = board.toString();
        AiConnection connection = ai;
        searchLabel.setText("探索開始を待っています…");
        Task<AiMove> task = new Task<>() {
            @Override
            protected AiMove call() throws IOException {
                return connection.play(position, deadline -> Platform.runLater(() -> {
                    if (ai == connection) {
                        startSearchCountdown(deadline);
                    }
                }));
            }
        };
        task.setOnSucceeded(e -> {
            // A return to the title or a restart may have replaced this game.
            if (ai != connection) {
                return;
            }
            clearSearchCountdown();
            AiMove move = task.getValue();
            if (!Othello.inside(move.y(), move.x()) || othello.grid[move.y()][move.x()] != Othello.LEGAL) {
                showAIError(new IOException("Illegal move from AI: " + move));
                return;
            }
            valueLabel.setText(String.format(Locale.ROOT, "終局の予想石差（AI視点）  %+.2f 石", move.value()));
            handleMove(move.y(), move.x());
        });
        task.setOnFailed(e -> {
            if (ai == connection) {
                showAIError(task.getException());
            }
        });

        Thread worker = new Thread(task, "othello-ai-move");
        worker.setDaemon(true);
        worker.start();
    }

    private void startSearchCountdown(long deadline) {
        clearSearchCountdown();
        updateSearchCountdown(deadline);
        searchCountdown = new Timeline(new KeyFrame(Duration.millis(100),
                e -> updateSearchCountdown(deadline)));
        searchCountdown.setCycleCount(Animation.INDEFINITE);
        searchCountdown.play();
    }

    private void updateSearchCountdown(long deadline) {
        double remainingSeconds = Math.max(0L, deadline - System.nanoTime()) / 1_000_000_000.0;
        searchLabel.setText(String.format(Locale.ROOT, "探索上限まで 約 %.1f 秒", remainingSeconds));
    }

    private void clearSearchCountdown() {
        if (searchCountdown != null) {
            searchCountdown.stop();
            searchCountdown = null;
        }
        searchLabel.setText("");
    }

    private void showAIError(Throwable error) {
        System.err.println("AI error: " + error.getMessage());
        stopAI();
        showGrid();
        turnLabel.setText("AIとの通信に失敗しました。「最初から」で対戦をやり直せます。");
    }

    private record AiMove(int y, int x, double value) {}

    private static class AiConnection {
        private final Process process;
        private final BufferedReader output;
        private final BufferedWriter input;
        private final int player;
        private boolean ready;

        AiConnection(int player) throws IOException {
            this.player = player;
            Path javaw = Path.of(System.getProperty("java.home"), "bin", "javaw.exe");
            String javaCommand = Files.isRegularFile(javaw) ? javaw.toString()
                    : Path.of(System.getProperty("java.home"), "bin", "java").toString();
            Path applicationPath;
            try {
                applicationPath = Path.of(OthelloGUI.class.getProtectionDomain()
                        .getCodeSource().getLocation().toURI());
            } catch (URISyntaxException e) {
                throw new IOException("Could not locate the Othello application.", e);
            }
            Path modelRoot = Files.isDirectory(applicationPath) ? Path.of("") : applicationPath.getParent();
            Path engineDirectory = modelRoot.resolve("original_final_48").toAbsolutePath();
            Path engineClassPath = applicationPath;
            String engineClassFile = AI_CLASS + ".class";
            if (Files.isDirectory(applicationPath) && !Files.isRegularFile(applicationPath.resolve(engineClassFile))) {
                // javac without -d writes the engine classes beside the engine source.
                engineClassPath = engineDirectory;
                if (!Files.isRegularFile(engineClassPath.resolve(engineClassFile))) {
                    throw new IOException("Compile original_final_48/" + AI_CLASS + ".java before starting the GUI.");
                }
            }
            process = new ProcessBuilder(javaCommand, "-Dothello.reportSearchBudget=true",
                    "-cp", engineClassPath.toString(), AI_CLASS)
                    .directory(engineDirectory.toFile())
                    .redirectError(ProcessBuilder.Redirect.INHERIT)
                    .start();
            output = new BufferedReader(new InputStreamReader(process.getInputStream()));
            input = new BufferedWriter(new OutputStreamWriter(process.getOutputStream()));
        }

        AiMove play(String position, LongConsumer onSearchStarted) throws IOException {
            if (!ready) {
                if (!"READY".equals(output.readLine())) {
                    throw new IOException("The AI did not finish initialization.");
                }
                input.write(player + "\n");
                input.flush();
                ready = true;
            }

            input.write(position);
            input.flush();
            String line = output.readLine();
            String budgetPrefix = "SEARCH_MS ";
            if (line != null && line.startsWith(budgetPrefix)) {
                long remainingMillis = Long.parseLong(line.substring(budgetPrefix.length()));
                onSearchStarted.accept(System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(remainingMillis));
                line = output.readLine();
            }
            if (line == null) {
                throw new IOException("The AI process exited.");
            }
            String[] parts = line.trim().split("\\s+");
            if (parts.length != 3) {
                throw new IOException("Invalid AI response: " + line);
            }
            return new AiMove(Integer.parseInt(parts[0]), Integer.parseInt(parts[1]), Double.parseDouble(parts[2]));
        }
    }

    public static void main(String[] args) {
        launch(args);
    }
}
