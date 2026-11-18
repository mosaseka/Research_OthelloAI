import javafx.application.Application;
import javafx.application.Platform;
import javafx.scene.Scene;
import javafx.scene.canvas.Canvas;
import javafx.scene.canvas.GraphicsContext;
import javafx.scene.control.Button;
import javafx.scene.control.Label;
import javafx.scene.control.TextInputDialog;
import javafx.scene.layout.Pane;
import javafx.scene.paint.Color;
import javafx.stage.Stage;
import java.io.*;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

public class OthelloGUI extends Application {
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
        } catch (Exception e) {
            System.err.println("Error initializing AI: " + e.getMessage());
            e.printStackTrace();
            Platform.exit();
            return;
        }

        root = new Pane();
        canvas = new Canvas(1000, 700);
        
        stoneLabel = new Label("*Black 2 - 2 White ");
        stoneLabel.setStyle("-fx-font-size: 30px;");
        stoneLabel.setLayoutX(250);
        stoneLabel.setLayoutY(600);
        
        valLabel = new Label("value: 0");
        valLabel.setStyle("-fx-font-size: 20px;");
        valLabel.setLayoutX(10);
        valLabel.setLayoutY(650);
        
        Button startButton = new Button("Start");
        startButton.setLayoutX(600);
        startButton.setLayoutY(10);
        startButton.setOnAction(e -> startGame());
        
        root.getChildren().addAll(canvas, stoneLabel, valLabel, startButton);
        
        Scene scene = new Scene(root, 1000, 700);
        primaryStage.setTitle("OthelloGUI");
        primaryStage.setScene(scene);
        primaryStage.setOnCloseRequest(e -> {
            if (aiProcess != null) {
                aiProcess.destroy();
            }
        });
        primaryStage.show();
        
        startGame();
    }

    private void initAI() throws IOException {
        ProcessBuilder pb = new ProcessBuilder("java", "-cp", ".", "OthelloAI_03");
        pb.redirectErrorStream(false);
        aiProcess = pb.start();
        
        // エラー出力を別スレッドで読み取る
        new Thread(() -> {
            try (BufferedReader errorReader = new BufferedReader(
                    new InputStreamReader(aiProcess.getErrorStream()))) {
                String line;
                while ((line = errorReader.readLine()) != null) {
                    System.err.println("AI stderr: " + line);
                }
            } catch (IOException e) {
                e.printStackTrace();
            }
        }).start();
        
        aiOutput = new BufferedReader(new InputStreamReader(aiProcess.getInputStream()));
        aiInput = new BufferedWriter(new OutputStreamWriter(aiProcess.getOutputStream()));
        
        // ★修正: まずREADYを待つ
        System.err.println("Waiting for READY...");
        String line;
        while ((line = aiOutput.readLine()) != null) {
            System.err.println("AI stdout: " + line);
            if (line.equals("READY")) {
                System.err.println("AI is ready");
                break;
            }
        }
        
        // ★修正: READYを受け取った後にAIプレイヤーを送信
        aiInput.write(aiPlayer + "\n");
        aiInput.flush();
        System.err.println("Sent AI player: " + aiPlayer);
    }

    private void startGame() {
        othello = new Othello();
        othello.checkLegal();
        showGrid();
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
        
        // ★修正: ゲーム開始時のAI先手の処理
        if (othello.player == aiPlayer && othello.player != -1 && 
            othello.nStones[0] + othello.nStones[1] == 4) { // 初期状態のみ
            valLabel.setText("AI thinking...");
            new Thread(() -> {
                executeAIMove();
            }).start();
        }
    }

    private void handleMove(int y, int x) {
        System.out.println(y + " " + x);
        
        othello.move(y, x);
        updateStoneLabel();
        
        // ★修正: 合法手チェックの前にshowGridを呼ばない
        // ★修正: ゲーム終了チェック
        if (!othello.checkLegal()) {
            othello.player = 1 - othello.player;
            if (!othello.checkLegal()) {
                othello.printInfo();
                othello.player = -1;
                showGrid(); // ★ゲーム終了時のみ表示更新
                System.out.println("end");
                return; // ★終了したら抜ける
            }
        }
        
        showGrid(); // ★合法手チェック後に表示更新
        
        // ★修正: AIの番なら別スレッドで実行
        if (othello.player == aiPlayer) {
            valLabel.setText("AI thinking...");
            new Thread(() -> {
                executeAIMove();
            }).start();
        }
    }

    private void executeAIMove() {
        try {
            // グリッド情報を送信（8行、各行8文字）
            StringBuilder gridStr = new StringBuilder();
            for (int i = 0; i < Othello.HW; i++) {
                for (int j = 0; j < Othello.HW; j++) {
                    if (othello.grid[i][j] == Othello.BLACK) {
                        gridStr.append('0');
                    } else if (othello.grid[i][j] == Othello.WHITE) {
                        gridStr.append('1');
                    } else {
                        gridStr.append('.');
                    }
                }
                gridStr.append('\n');
            }
            
            System.err.println("Sending board to AI:");
            System.err.print(gridStr.toString());
            
            aiInput.write(gridStr.toString());
            aiInput.flush();
            
            System.err.println("Waiting for AI response...");
            
            // AIの応答を読み取る
            String line = aiOutput.readLine();
            System.err.println("AI response: " + line);
            
            if (line == null) {
                System.err.println("AI process terminated");
                return;
            }
            
            String[] parts = line.trim().split("\\s+");
            if (parts.length < 3) {
                System.err.println("Invalid AI response format: " + line);
                return;
            }
            
            int y = Integer.parseInt(parts[0]);
            int x = Integer.parseInt(parts[1]);
            double val = Double.parseDouble(parts[2]);
            
            System.out.println(y + " " + x);
            
            // ★修正: UI更新は全てPlatform.runLaterで実行
            Platform.runLater(() -> {
                valLabel.setText("value: " + val);
                othello.move(y, x);
                updateStoneLabel();
                
                // ★修正: 合法手チェックの前にshowGridを呼ばない
                // ★修正: ゲーム終了チェック
                if (!othello.checkLegal()) {
                    othello.player = 1 - othello.player;
                    if (!othello.checkLegal()) {
                        othello.printInfo();
                        othello.player = -1;
                        showGrid(); // ★ゲーム終了時のみ表示更新
                        System.out.println("end");
                        return; // ★終了したら抜ける
                    }
                }
                
                showGrid(); // ★合法手チェック後に表示更新
                
                // ★修正: パス後にAIの番になった場合の処理
                if (othello.player == aiPlayer) {
                    valLabel.setText("AI thinking...");
                    new Thread(() -> {
                        executeAIMove();
                    }).start();
                }
            });
            
        } catch (Exception e) {
            System.err.println("Error in executeAIMove:");
            e.printStackTrace();
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
