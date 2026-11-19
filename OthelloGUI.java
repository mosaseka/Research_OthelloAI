import java.awt.BorderLayout;
import java.awt.CardLayout;
import java.awt.Color;
import java.awt.Component;
import java.awt.Dimension;
import java.awt.Font;
import java.awt.GradientPaint;
import java.awt.Graphics;
import java.awt.Graphics2D;
import java.awt.GridBagLayout;
import java.awt.GridLayout;
import java.awt.Insets;
import java.awt.Rectangle;
import java.awt.RenderingHints;
import java.awt.event.ActionEvent;
import java.awt.event.KeyEvent;
import java.awt.event.WindowAdapter;
import java.awt.event.WindowEvent;
import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.net.URISyntaxException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayDeque;
import java.util.Locale;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.function.LongConsumer;
import javax.swing.AbstractAction;
import javax.swing.BorderFactory;
import javax.swing.Box;
import javax.swing.BoxLayout;
import javax.swing.JButton;
import javax.swing.JComponent;
import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.JOptionPane;
import javax.swing.JPanel;
import javax.swing.JScrollPane;
import javax.swing.JTextArea;
import javax.swing.KeyStroke;
import javax.swing.SwingUtilities;
import javax.swing.SwingWorker;
import javax.swing.Timer;

public class OthelloGUI {
    private static final String AI_CLASS = "OthelloAI_final_48";
    private static final int DEFAULT_AI_MOVE_TIME_MS = 3_000;
    private static final int RESULT_DISPLAY_SECONDS = 6;
    private static final Color BACKGROUND = new Color(0x153b33);
    private static final Color BOARD_GREEN = new Color(0x16866d);
    private static final Color GRID_COLOR = new Color(0x103a30);
    private static final Color LEGAL_BLUE = new Color(0x3498db);
    private static final Color IVORY = new Color(0xf4f0e3);

    private final JFrame frame = new JFrame("オセロ - " + AI_CLASS);
    private final CardLayout pages = new CardLayout();
    private final JPanel content = new JPanel(pages);
    private final BoardPanel boardPanel = new BoardPanel();
    private final JLabel playerLabel = label("", 17, IVORY);
    private final JLabel stoneLabel = label("", 28, IVORY);
    private final JLabel turnLabel = label("", 17, IVORY);
    private final JLabel statusDetailLabel = label(" ", 16, IVORY);
    private final JLabel valueLabel = label("", 17, IVORY);
    private final JButton restartButton = new JButton();
    private final JButton fullScreenButton = new JButton("全画面表示");
    private final JButton aiErrorButton = new JButton("エラーの詳細");
    private String aiErrorDetails;

    private boolean fullScreen;
    private Rectangle windowedBounds;
    private int windowedState;
    private Othello othello;
    private int aiPlayer;
    private AiConnection ai;
    private Timer searchCountdown;
    private Timer resultReturnTimer;

    private void show() {
        content.add(createTitlePanel(), "title");
        content.add(createGamePanel(), "game");
        fullScreenButton.setToolTipText("F11 で切り替え、Esc で解除");
        fullScreenButton.addActionListener(e -> toggleFullScreen());
        JPanel header = new JPanel(new BorderLayout());
        header.setBackground(BACKGROUND);
        header.setBorder(BorderFactory.createEmptyBorder(12, 18, 0, 18));
        header.add(fullScreenButton, BorderLayout.LINE_END);
        frame.add(header, BorderLayout.NORTH);
        frame.add(content, BorderLayout.CENTER);
        bindKey(KeyEvent.VK_F11, "fullscreen", this::toggleFullScreen);
        bindKey(KeyEvent.VK_ESCAPE, "exitFullscreen", () -> {
            if (fullScreen) {
                toggleFullScreen();
            }
        });
        frame.setDefaultCloseOperation(JFrame.DISPOSE_ON_CLOSE);
        frame.addWindowListener(new WindowAdapter() {
            @Override
            public void windowClosing(WindowEvent event) {
                cancelResultReturn();
                stopAI();
            }
        });
        frame.setMinimumSize(new Dimension(720, 510));
        frame.setSize(900, 600);
        frame.setLocationRelativeTo(null);
        frame.setVisible(true);
    }

    private void bindKey(int key, String name, Runnable action) {
        var root = frame.getRootPane();
        root.getInputMap(JComponent.WHEN_IN_FOCUSED_WINDOW).put(KeyStroke.getKeyStroke(key, 0), name);
        root.getActionMap().put(name, new AbstractAction() {
            @Override
            public void actionPerformed(ActionEvent event) {
                action.run();
            }
        });
    }

    private void toggleFullScreen() {
        // Recreate the native window's decorations without replacing its content or the game.
        Rectangle screenBounds = frame.getGraphicsConfiguration().getBounds();
        if (!fullScreen) {
            windowedBounds = frame.getBounds();
            windowedState = frame.getExtendedState();
        }
        frame.dispose();
        fullScreen = !fullScreen;
        frame.setExtendedState(JFrame.NORMAL);
        frame.setUndecorated(fullScreen);
        frame.setBounds(fullScreen ? screenBounds : windowedBounds);
        if (!fullScreen) {
            frame.setExtendedState(windowedState);
        }
        fullScreenButton.setText(fullScreen ? "全画面を解除" : "全画面表示");
        frame.setVisible(true);
    }

    private JPanel createTitlePanel() {
        JPanel page = new JPanel(new GridBagLayout()) {
            @Override
            protected void paintComponent(Graphics graphics) {
                super.paintComponent(graphics);
                Graphics2D g = (Graphics2D) graphics.create();
                g.setPaint(new GradientPaint(0, 0, BACKGROUND, getWidth(), getHeight(), new Color(0x25483a)));
                g.fillRect(0, 0, getWidth(), getHeight());
                g.dispose();
            }
        };

        JLabel title = label("オセロ", 58, IVORY);
        title.setFont(new Font(Font.SERIF, Font.BOLD, 58));
        JLabel opponent = label("対戦相手　" + AI_CLASS, 15, new Color(0xc9d7c6));
        JPanel choices = new JPanel(new GridLayout(1, 2, 10, 0));
        choices.setOpaque(false);
        choices.add(titleButton("先手（黒）で対戦", Othello.BLACK));
        choices.add(titleButton("後手（白）で対戦", Othello.WHITE));
        JPanel heading = column(title, opponent, Box.createVerticalStrut(18), choices);
        JPanel hero = new JPanel(new BorderLayout(42, 0));
        hero.setOpaque(false);
        hero.add(heading, BorderLayout.CENTER);
        hero.add(openingDiagram(), BorderLayout.EAST);

        JPanel guide = new JPanel(new GridLayout(1, 3, 18, 0));
        guide.setOpaque(false);
        guide.add(guideColumn("石を置く", "青いマスをクリックすると石を置けます。縦・横・斜めにはさんだ相手の石が裏返ります。"));
        guide.add(guideColumn("パスと勝敗", "置ける場所がないと自動でパスします。両者とも置けなくなったら終局し、石の多い方が勝ちです。"));
        guide.add(guideColumn("もう一局遊ぶ", "終局後は結果を表示し、自動でタイトルに戻ります。「再戦」ですぐに同じ色で対戦できます。"));
        JLabel guideTitle = label("操作ガイド", 21, BACKGROUND);
        guideTitle.setFont(guideTitle.getFont().deriveFont(Font.BOLD));
        JPanel instructions = new JPanel(new BorderLayout(0, 8));
        instructions.setBackground(IVORY);
        instructions.setBorder(BorderFactory.createEmptyBorder(14, 18, 14, 18));
        instructions.add(guideTitle, BorderLayout.NORTH);
        instructions.add(guide, BorderLayout.CENTER);

        JPanel layout = column(hero, Box.createVerticalStrut(24), instructions);
        layout.setPreferredSize(new Dimension(650, layout.getPreferredSize().height));
        page.add(layout);
        return page;
    }

    private JButton titleButton(String text, int color) {
        JButton button = new JButton(text);
        button.setMargin(new Insets(10, 14, 10, 14));
        button.setBackground(color == Othello.BLACK ? IVORY : new Color(0x31574b));
        button.setForeground(color == Othello.BLACK ? BACKGROUND : IVORY);
        button.addActionListener(e -> startGame(color));
        return button;
    }

    private JPanel guideColumn(String heading, String description) {
        JLabel name = label(heading, 15, BACKGROUND);
        name.setFont(name.getFont().deriveFont(Font.BOLD));
        JTextArea body = new JTextArea(description, 5, 15);
        body.setOpaque(false);
        body.setEditable(false);
        body.setFocusable(false);
        body.setLineWrap(true);
        body.setWrapStyleWord(true);
        body.setFont(new Font(Font.SANS_SERIF, Font.PLAIN, 13));
        body.setForeground(new Color(0x374a40));
        JPanel column = new JPanel(new BorderLayout(0, 5));
        column.setOpaque(false);
        column.add(name, BorderLayout.NORTH);
        column.add(body, BorderLayout.CENTER);
        return column;
    }

    private JPanel openingDiagram() {
        Othello opening = new Othello();
        opening.checkLegal();
        JPanel diagram = new JPanel() {
            @Override
            protected void paintComponent(Graphics graphics) {
                super.paintComponent(graphics);
                drawPosition(graphics, boardBounds(getWidth(), getHeight()), opening, true);
            }
        };
        diagram.setOpaque(false);
        diagram.setPreferredSize(new Dimension(188, 188));
        diagram.getAccessibleContext().setAccessibleName("初期盤面。青い4マスに黒を置けます。");
        return diagram;
    }

    private JPanel createGamePanel() {
        restartButton.addActionListener(e -> startGame(1 - aiPlayer));
        JButton titleButton = new JButton("タイトルへ");
        titleButton.addActionListener(e -> showTitle());
        JPanel actions = new JPanel(new GridLayout(1, 2, 8, 0));
        actions.setOpaque(false);
        actions.add(restartButton);
        actions.add(titleButton);
        aiErrorButton.setVisible(false);
        aiErrorButton.addActionListener(e -> {
            JTextArea details = new JTextArea(aiErrorDetails, 12, 55);
            details.setEditable(false);
            details.setCaretPosition(0);
            JOptionPane.showMessageDialog(frame, new JScrollPane(details),
                    "AIのエラー", JOptionPane.ERROR_MESSAGE);
        });

        JPanel details = column(playerLabel, Box.createVerticalStrut(12), stoneLabel,
                Box.createVerticalStrut(12), turnLabel, statusDetailLabel, Box.createVerticalStrut(12),
                valueLabel, label("＋はAI有利、−はあなた有利", 13, IVORY),
                Box.createVerticalStrut(14), actions, aiErrorButton);
        JPanel sidebar = new JPanel(new GridBagLayout());
        sidebar.setOpaque(false);
        sidebar.setPreferredSize(new Dimension(310, 1));
        sidebar.add(details);

        JPanel panel = new JPanel(new BorderLayout(24, 0));
        panel.setBackground(BACKGROUND);
        panel.setBorder(BorderFactory.createEmptyBorder(16, 22, 22, 22));
        panel.add(boardPanel, BorderLayout.CENTER);
        panel.add(sidebar, BorderLayout.EAST);
        return panel;
    }

    private static JLabel label(String text, int fontSize, Color color) {
        JLabel label = new JLabel(text);
        label.setForeground(color);
        label.setFont(new Font(Font.SANS_SERIF, Font.PLAIN, fontSize));
        return label;
    }

    private static JPanel column(Component... children) {
        JPanel result = new JPanel();
        result.setLayout(new BoxLayout(result, BoxLayout.Y_AXIS));
        result.setOpaque(false);
        for (Component child : children) {
            if (child instanceof JComponent component) {
                component.setAlignmentX(JComponent.LEFT_ALIGNMENT);
            }
            result.add(child);
        }
        return result;
    }

    private void showTitle() {
        cancelResultReturn();
        stopAI();
        pages.show(content, "title");
    }

    private void startGame(int humanPlayer) {
        cancelResultReturn();
        stopAI();
        aiErrorButton.setVisible(false);
        aiPlayer = 1 - humanPlayer;
        othello = new Othello();
        othello.checkLegal();
        playerLabel.setText(humanPlayer == Othello.BLACK ? "あなたは黒（先手）" : "あなたは白（後手）");
        restartButton.setText("最初から");
        valueLabel.setText("終局の予想石差（AI視点）  —");
        pages.show(content, "game");

        try {
            ai = new AiConnection(aiPlayer);
            playTurn("");
        } catch (IOException e) {
            showAIError(e);
        }
    }

    private void stopAI() {
        clearSearchCountdown();
        if (ai != null) {
            ai.process.destroy();
            ai = null;
        }
    }

    private static Rectangle boardBounds(int width, int height) {
        int size = Math.min(width, height) / Othello.HW * Othello.HW;
        return new Rectangle((width - size) / 2, (height - size) / 2, size, size);
    }

    private static void drawPosition(Graphics graphics, Rectangle area, Othello position, boolean markLegal) {
        Graphics2D g = (Graphics2D) graphics.create();
        g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
        g.setColor(BOARD_GREEN);
        g.fillRect(area.x, area.y, area.width, area.height);
        int cellSize = area.width / Othello.HW;
        int inset = Math.max(2, cellSize / 16);
        for (int row = 0; row < Othello.HW; row++) {
            for (int column = 0; column < Othello.HW; column++) {
                int x = area.x + column * cellSize;
                int y = area.y + row * cellSize;
                g.setColor(GRID_COLOR);
                g.drawRect(x, y, cellSize - 1, cellSize - 1);
                int cell = position.grid[row][column];
                if (cell == Othello.BLACK || cell == Othello.WHITE) {
                    g.setColor(cell == Othello.BLACK ? new Color(0x12221d) : IVORY);
                    g.fillOval(x + inset, y + inset, cellSize - 2 * inset, cellSize - 2 * inset);
                } else if (markLegal && cell == Othello.LEGAL) {
                    g.setColor(LEGAL_BLUE);
                    g.fillRect(x + inset, y + inset, cellSize - 2 * inset, cellSize - 2 * inset);
                }
            }
        }
        g.dispose();
    }

    private final class BoardPanel extends JPanel {
        private final JButton[][] moves = new JButton[Othello.HW][Othello.HW];

        BoardPanel() {
            super(null);
            setOpaque(false);
            for (int y = 0; y < Othello.HW; y++) {
                for (int x = 0; x < Othello.HW; x++) {
                    int row = y;
                    int column = x;
                    JButton move = new JButton();
                    move.setBackground(LEGAL_BLUE);
                    move.setBorderPainted(false);
                    move.getAccessibleContext().setAccessibleName("" + (char) ('A' + x) + (y + 1));
                    move.addActionListener(e -> {
                        if (ai != null && othello.player != aiPlayer && othello.grid[row][column] == Othello.LEGAL) {
                            handleMove(row, column);
                        }
                    });
                    move.setVisible(false);
                    moves[y][x] = move;
                    add(move);
                }
            }
        }

        @Override
        public void doLayout() {
            Rectangle area = boardBounds(getWidth(), getHeight());
            int cell = area.width / Othello.HW;
            int inset = Math.max(2, cell / 16);
            for (int y = 0; y < Othello.HW; y++) {
                for (int x = 0; x < Othello.HW; x++) {
                    moves[y][x].setBounds(area.x + x * cell + inset, area.y + y * cell + inset,
                            cell - 2 * inset, cell - 2 * inset);
                }
            }
        }

        @Override
        protected void paintComponent(Graphics graphics) {
            super.paintComponent(graphics);
            if (othello != null) {
                drawPosition(graphics, boardBounds(getWidth(), getHeight()), othello, false);
            }
        }

        void refresh() {
            boolean humanTurn = ai != null && othello.player >= 0 && othello.player != aiPlayer;
            for (int y = 0; y < Othello.HW; y++) {
                for (int x = 0; x < Othello.HW; x++) {
                    moves[y][x].setVisible(humanTurn && othello.grid[y][x] == Othello.LEGAL);
                }
            }
            repaint();
        }
    }

    private void showGrid() {
        boardPanel.refresh();
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
            showResult();
        } else if (othello.player == aiPlayer) {
            turnLabel.setText(passMessage + "AI思考中…");
            requestAIMove();
        } else {
            turnLabel.setText(passMessage + "あなたの番");
        }
    }

    private void showResult() {
        stopAI();
        int difference = othello.nStones[1 - aiPlayer] - othello.nStones[aiPlayer];
        String result = "引き分け";
        if (difference != 0) {
            String winner = difference > 0 ? "あなたの勝ち" : "AIの勝ち";
            result = winner + "（" + Math.abs(difference) + "石差）";
        }
        turnLabel.setText("最終結果　" + result);
        restartButton.setText("再戦");
        statusDetailLabel.setText(RESULT_DISPLAY_SECONDS + "秒後にタイトルへ戻ります");

        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(RESULT_DISPLAY_SECONDS);
        resultReturnTimer = new Timer(200, e -> {
            long remaining = deadline - System.nanoTime();
            if (remaining <= 0) {
                showTitle();
            } else {
                int seconds = (int) Math.ceil(remaining / 1_000_000_000.0);
                statusDetailLabel.setText(seconds + "秒後にタイトルへ戻ります");
            }
        });
        resultReturnTimer.start();
    }

    private void cancelResultReturn() {
        if (resultReturnTimer != null) {
            resultReturnTimer.stop();
            resultReturnTimer = null;
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
        statusDetailLabel.setText("探索開始を待っています…");
        new SwingWorker<AiMove, Void>() {
            @Override
            protected AiMove doInBackground() throws IOException {
                return connection.play(position, deadline -> SwingUtilities.invokeLater(() -> {
                    if (ai == connection) {
                        startSearchCountdown(deadline);
                    }
                }));
            }

            @Override
            protected void done() {
                if (ai != connection) {
                    return;
                }
                clearSearchCountdown();
                try {
                    AiMove move = get();
                    if (!Othello.inside(move.y(), move.x()) || othello.grid[move.y()][move.x()] != Othello.LEGAL) {
                        throw new IOException("Illegal move from AI: " + move);
                    }
                    valueLabel.setText(String.format(Locale.ROOT, "終局の予想石差（AI視点）  %+.2f 石", move.value()));
                    handleMove(move.y(), move.x());
                } catch (ExecutionException e) {
                    showAIError(e.getCause());
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    showAIError(e);
                } catch (IOException e) {
                    showAIError(e);
                }
            }
        }.execute();
    }

    private void startSearchCountdown(long deadline) {
        clearSearchCountdown();
        updateSearchCountdown(deadline);
        searchCountdown = new Timer(100, e -> updateSearchCountdown(deadline));
        searchCountdown.start();
    }

    private void updateSearchCountdown(long deadline) {
        double remainingSeconds = Math.max(0L, deadline - System.nanoTime()) / 1_000_000_000.0;
        statusDetailLabel.setText(String.format(Locale.ROOT, "探索上限まで 約 %.1f 秒", remainingSeconds));
    }

    private void clearSearchCountdown() {
        if (searchCountdown != null) {
            searchCountdown.stop();
            searchCountdown = null;
        }
        statusDetailLabel.setText(" ");
    }

    private void showAIError(Throwable error) {
        System.err.println("AI error: " + error.getMessage());
        aiErrorDetails = error.toString();
        String diagnostics = ai == null ? "" : ai.diagnostics();
        if (!diagnostics.isEmpty()) {
            aiErrorDetails += "\n\n" + diagnostics;
        }
        stopAI();
        showGrid();
        turnLabel.setText("<html>AIとの通信に失敗しました。<br>「最初から」で対戦をやり直せます。</html>");
        aiErrorButton.setVisible(true);
    }

    private record AiMove(int y, int x, double value) {}

    private static class AiConnection {
        private final Process process;
        private final BufferedReader output;
        private final BufferedWriter input;
        private final ArrayDeque<String> recentErrors = new ArrayDeque<>();
        private final Thread errorReader;
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
            ProcessBuilder builder = new ProcessBuilder(javaCommand, "-Dothello.reportSearchBudget=true",
                    "-cp", engineClassPath.toString(), AI_CLASS)
                    .directory(engineDirectory.toFile());
            builder.environment().compute("OTHELLO_MOVE_TIME_MS", (name, configured) ->
                    configured == null || configured.isBlank() ? Integer.toString(DEFAULT_AI_MOVE_TIME_MS) : configured);
            process = builder.start();
            output = new BufferedReader(new InputStreamReader(process.getInputStream()));
            input = new BufferedWriter(new OutputStreamWriter(process.getOutputStream()));
            errorReader = new Thread(this::readErrors, "othello-ai-stderr");
            errorReader.setDaemon(true);
            errorReader.start();
        }

        private void readErrors() {
            try (BufferedReader errors = process.errorReader()) {
                String line;
                while ((line = errors.readLine()) != null) {
                    synchronized (recentErrors) {
                        if (recentErrors.size() == 30) {
                            recentErrors.removeFirst();
                        }
                        recentErrors.addLast(line);
                    }
                    System.err.println(line);
                }
            } catch (IOException ignored) {
                // Destroying the AI on restart or exit can close its error stream.
            }
        }

        String diagnostics() {
            synchronized (recentErrors) {
                return String.join("\n", recentErrors);
            }
        }

        private IOException processExited(String message) {
            try {
                errorReader.join(250);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
            return new IOException(message);
        }

        AiMove play(String position, LongConsumer onSearchStarted) throws IOException {
            if (!ready) {
                String response = output.readLine();
                if (response == null) {
                    throw processExited("The AI exited before initialization completed.");
                }
                if (!"READY".equals(response)) {
                    throw new IOException("Unexpected AI initialization response: " + response);
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
                throw processExited("The AI process exited.");
            }
            String[] parts = line.trim().split("\\s+");
            if (parts.length != 3) {
                throw new IOException("Invalid AI response: " + line);
            }
            return new AiMove(Integer.parseInt(parts[0]), Integer.parseInt(parts[1]), Double.parseDouble(parts[2]));
        }
    }

    public static void main(String[] args) {
        SwingUtilities.invokeLater(() -> new OthelloGUI().show());
    }
}
