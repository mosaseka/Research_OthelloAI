import javafx.application.Application;
import javafx.application.Platform;
import javafx.scene.Scene;
import javafx.scene.canvas.Canvas;
import javafx.scene.canvas.GraphicsContext;
import javafx.scene.control.Alert;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.control.TextInputDialog;
import javafx.scene.layout.Pane;
import javafx.scene.paint.Color;
import javafx.stage.Stage;
import java.io.*;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

public class OthelloGUI extends Application {
    private static final String AI_CLASS = "OthelloAI_final_48";
    private static final int OFFSET_Y = 10;
    private static final int OFFSET_X = 10;
    private static final int RECT_SIZE = 60;
    private static final int CIRCLE_OFFSET = 3;

    private Othello othello;
    private Process aiProcess;
    private BufferedReader aiOutput;
    private BufferedWriter aiInput;
    private int aiPlayer;
    private List<Button> legalButtons = new ArrayList<>();
    
    private Canvas canvas;
    private Label stoneLabel;
    private Label valLabel;
    private Button startButton;
    private Pane root;

    @Override
    public void start(Stage primaryStage) {
        TextInputDialog dialog = new TextInputDialog("0");
        dialog.setTitle("AI Player Selection");
        dialog.setHeaderText("Select AI player");
        dialog.setContentText("AI moves (0: black, 1: white):");
        
        Optional<String> result = dialog.showAndWait();
        if (!result.isPresent()) {
            Platform.exit();
            return;
        }
        
        try {
            aiPlayer = Integer.parseInt(result.get());
            if (aiPlayer != 0 && aiPlayer != 1) {
                throw new NumberFormatException();
            }
            initAI();
        } catch (NumberFormatException | IOException e) {
            System.err.println("Error initializing AI: " + e.getMessage());
            String message = e instanceof NumberFormatException
                    ? "Select 0 (black) or 1 (white) for the AI."
                    : "Could not start " + AI_CLASS + ": " + e.getMessage();
            new Alert(Alert.AlertType.ERROR, message).showAndWait();
            Platform.exit();
            return;
        }

        root = new Pane();
        canvas = new Canvas(1000, 700);
        
        stoneLabel = new Label("*Black 2 - 2 White ");
        stoneLabel.setStyle("-fx-font-size: 30px;");
        stoneLabel.setLayoutX(250);
        stoneLabel.setLayoutY(600);
        
        valLabel = new Label();
        valLabel.setStyle("-fx-font-size: 20px;");
        valLabel.setLayoutX(10);
        valLabel.setLayoutY(650);
        
        startButton = new Button("Start");
        startButton.setLayoutX(600);
        startButton.setLayoutY(10);
        startButton.setOnAction(e -> startGame());
        
        root.getChildren().addAll(canvas, stoneLabel, valLabel, startButton);
        
        Scene scene = new Scene(root, 1000, 700);
        primaryStage.setTitle("OthelloGUI - " + AI_CLASS);
        primaryStage.setScene(scene);
        primaryStage.show();
        
        startGame();
    }

    @Override
    public void stop() {
        if (aiProcess != null) {
            aiProcess.destroy();
        }
    }

    private void initAI() throws IOException {
        String javaCommand = ProcessHandle.current().info().command().orElse("java");
        // The launcher supplies an absolute classpath for the AI's working directory.
        aiProcess = new ProcessBuilder(javaCommand, "-cp", System.getProperty("java.class.path"), AI_CLASS)
                .directory(Path.of("original_final_48").toAbsolutePath().toFile())
                .redirectError(ProcessBuilder.Redirect.INHERIT)
                .start();
        aiOutput = new BufferedReader(new InputStreamReader(aiProcess.getInputStream()));
        aiInput = new BufferedWriter(new OutputStreamWriter(aiProcess.getOutputStream()));

        if (!"READY".equals(aiOutput.readLine())) {
            throw new IOException("The AI did not finish initialization. Check the console for details.");
        }
        aiInput.write(aiPlayer + "\n");
        aiInput.flush();
    }

    private void startGame() {
        othello = new Othello();
        valLabel.setText("value: —");
        othello.checkLegal();
        showGrid();
        requestAIMove();
    }

    private void drawBoard() {
        GraphicsContext gc = canvas.getGraphicsContext2D();
        gc.setFill(Color.web("#16a085"));
        gc.fillRect(0, 0, 1000, 700);
        
        gc.setStroke(Color.BLACK);
        gc.setLineWidth(2);
        for (int y = 0; y < Othello.HW; y++) {
            for (int x = 0; x < Othello.HW; x++) {
                gc.strokeRect(OFFSET_X + RECT_SIZE * x, OFFSET_Y + RECT_SIZE * y, 
                            RECT_SIZE, RECT_SIZE);
            }
        }
    }

    private void showGrid() {
        for (Button button : legalButtons) {
            root.getChildren().remove(button);
        }
        legalButtons.clear();
        
        drawBoard();
        GraphicsContext gc = canvas.getGraphicsContext2D();
        
        for (int y = 0; y < Othello.HW; y++) {
            for (int x = 0; x < Othello.HW; x++) {
                if (othello.grid[y][x] == Othello.VACANT) {
                    continue;
                }
                
                if (othello.grid[y][x] == Othello.BLACK) {
                    gc.setFill(Color.BLACK);
                    gc.fillOval(OFFSET_X + RECT_SIZE * x + CIRCLE_OFFSET,
                              OFFSET_Y + RECT_SIZE * y + CIRCLE_OFFSET,
                              RECT_SIZE - CIRCLE_OFFSET * 2,
                              RECT_SIZE - CIRCLE_OFFSET * 2);
                } else if (othello.grid[y][x] == Othello.WHITE) {
                    gc.setFill(Color.WHITE);
                    gc.fillOval(OFFSET_X + RECT_SIZE * x + CIRCLE_OFFSET,
                              OFFSET_Y + RECT_SIZE * y + CIRCLE_OFFSET,
                              RECT_SIZE - CIRCLE_OFFSET * 2,
                              RECT_SIZE - CIRCLE_OFFSET * 2);
                } else if (othello.grid[y][x] == Othello.LEGAL && othello.player != aiPlayer) {
                    Button btn = new Button();
                    btn.setPrefSize(RECT_SIZE - CIRCLE_OFFSET * 2, RECT_SIZE - CIRCLE_OFFSET * 2);
                    btn.setStyle("-fx-background-color: #3498db;");
                    btn.setLayoutX(OFFSET_X + RECT_SIZE * x + CIRCLE_OFFSET);
                    btn.setLayoutY(OFFSET_Y + RECT_SIZE * y + CIRCLE_OFFSET);
                    
                    final int fy = y;
                    final int fx = x;
                    btn.setOnAction(e -> handleMove(fy, fx));
                    
                    legalButtons.add(btn);
                    root.getChildren().add(btn);
                }
            }
        }
        
        updateStoneLabel();
    }

    private void handleMove(int y, int x) {
        othello.move(y, x);
        if (!othello.checkLegal()) {
            othello.player = 1 - othello.player;
            if (!othello.checkLegal()) {
                othello.printInfo();
                othello.player = -1;
            }
        }
        showGrid();
        requestAIMove();
    }

    private void requestAIMove() {
        if (othello.player != aiPlayer) {
            return;
        }

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

        valLabel.setText("AI thinking...");
        startButton.setDisable(true);
        String position = board.toString();
        Thread worker = new Thread(() -> executeAIMove(position), "othello-ai-move");
        worker.setDaemon(true);
        worker.start();
    }

    private void executeAIMove(String position) {
        try {
            aiInput.write(position);
            aiInput.flush();
            String line = aiOutput.readLine();
            if (line == null) {
                throw new IOException("The AI process exited. Relaunch the game to try again.");
            }
            String[] parts = line.trim().split("\\s+");
            if (parts.length != 3) {
                throw new IOException("Invalid AI response: " + line);
            }
            int y = Integer.parseInt(parts[0]);
            int x = Integer.parseInt(parts[1]);
            double val = Double.parseDouble(parts[2]);

            Platform.runLater(() -> {
                startButton.setDisable(false);
                if (!Othello.inside(y, x) || othello.grid[y][x] != Othello.LEGAL) {
                    valLabel.setText("Illegal move from AI: " + line);
                    return;
                }
                valLabel.setText("value: " + val);
                handleMove(y, x);
            });
        } catch (IOException | NumberFormatException e) {
            System.err.println("Error reading AI move: " + e.getMessage());
            Platform.runLater(() -> {
                startButton.setDisable(false);
                valLabel.setText("AI error: " + e.getMessage());
            });
        }
    }

    private void updateStoneLabel() {
        StringBuilder s = new StringBuilder();
        if (othello.player == Othello.BLACK) {
            s.append("*");
        } else {
            s.append(" ");
        }
        s.append("Black ");
        s.append(othello.nStones[0]);
        s.append(" - ");
        s.append(othello.nStones[1]);
        s.append(" White");
        if (othello.player == Othello.WHITE) {
            s.append("*");
        } else {
            s.append(" ");
        }
        stoneLabel.setText(s.toString());
    }

    public static void main(String[] args) {
        launch(args);
    }
}
