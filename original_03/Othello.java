public class Othello {
    public static final int HW = 8;
    public static final int HW2 = 64;
    public static final int[] DY = {0, 1, 0, -1, 1, 1, -1, -1};
    public static final int[] DX = {1, 0, -1, 0, 1, -1, 1, -1};
    public static final int BLACK = 0;
    public static final int WHITE = 1;
    public static final int LEGAL = 2;
    public static final int VACANT = 3;

    public int[][] grid;
    public int player;
    public int[] nStones;

    public Othello() {
        grid = new int[HW][HW];
        for (int i = 0; i < HW; i++) {
            for (int j = 0; j < HW; j++) {
                grid[i][j] = VACANT;
            }
        }
        grid[3][3] = WHITE;
        grid[3][4] = BLACK;
        grid[4][3] = BLACK;
        grid[4][4] = WHITE;
        player = BLACK;
        nStones = new int[]{2, 2};
    }

    public static boolean inside(int y, int x) {
        return 0 <= y && y < HW && 0 <= x && x < HW;
    }

    public boolean checkLegal() {
        for (int ny = 0; ny < HW; ny++) {
            for (int nx = 0; nx < HW; nx++) {
                if (grid[ny][nx] == LEGAL) {
                    grid[ny][nx] = VACANT;
                }
            }
        }
        boolean haveLegal = false;
        for (int y = 0; y < HW; y++) {
            for (int x = 0; x < HW; x++) {
                if (grid[y][x] != VACANT) {
                    continue;
                }
                boolean legalFlag = false;
                for (int dr = 0; dr < 8; dr++) {
                    boolean drLegalFlag1 = false;
                    boolean drLegalFlag2 = false;
                    int ny = y;
                    int nx = x;
                    for (int d = 0; d < HW - 1; d++) {
                        ny += DY[dr];
                        nx += DX[dr];
                        if (!inside(ny, nx)) {
                            drLegalFlag1 = false;
                            break;
                        } else if (grid[ny][nx] == VACANT || grid[ny][nx] == LEGAL) {
                            drLegalFlag1 = false;
                            break;
                        } else if (grid[ny][nx] != player) {
                            drLegalFlag1 = true;
                        } else if (grid[ny][nx] == player) {
                            drLegalFlag2 = true;
                            break;
                        }
                    }
                    if (drLegalFlag1 && drLegalFlag2) {
                        legalFlag = true;
                        break;
                    }
                }
                if (legalFlag) {
                    grid[y][x] = LEGAL;
                    haveLegal = true;
                }
            }
        }
        return haveLegal;
    }

    public void move(int y, int x) {
        if (!inside(y, x)) {
            System.out.println("out of range");
            return;
        }
        if (grid[y][x] != LEGAL) {
            System.out.println("illegal move");
            return;
        }
        int nFlipped = 0;
        for (int dr = 0; dr < 8; dr++) {
            boolean drLegalFlag = false;
            int drNFlipped = 0;
            int ny = y;
            int nx = x;
            for (int d = 0; d < HW - 1; d++) {
                ny += DY[dr];
                nx += DX[dr];
                if (!inside(ny, nx)) {
                    drLegalFlag = false;
                    break;
                } else if (grid[ny][nx] == VACANT || grid[ny][nx] == LEGAL) {
                    drLegalFlag = false;
                    break;
                } else if (grid[ny][nx] != player) {
                    drLegalFlag = true;
                } else if (grid[ny][nx] == player) {
                    drNFlipped = d;
                    break;
                }
            }
            if (drLegalFlag) {
                nFlipped += drNFlipped;
                for (int d = 0; d < drNFlipped; d++) {
                    ny = y + DY[dr] * (d + 1);
                    nx = x + DX[dr] * (d + 1);
                    grid[ny][nx] = player;
                }
            }
        }
        grid[y][x] = player;
        nStones[player] += nFlipped + 1;
        nStones[1 - player] -= nFlipped;
        player = 1 - player;
    }

    public void printInfo() {
        System.out.println("  A B C D E F G H");
        for (int y = 0; y < HW; y++) {
            System.out.print((y + 1) + " ");
            for (int x = 0; x < HW; x++) {
                if (grid[y][x] == BLACK) {
                    System.out.print("X ");
                } else if (grid[y][x] == WHITE) {
                    System.out.print("O ");
                } else if (grid[y][x] == LEGAL) {
                    System.out.print("* ");
                } else {
                    System.out.print(". ");
                }
            }
            System.out.println();
        }
        System.out.println("Black X " + nStones[0] + " - " + nStones[1] + " O White");
    }
}