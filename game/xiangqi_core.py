# -*- coding: utf-8 -*-
"""
中国象棋规则核心（无 GUI 依赖）。

供以下模块共用：
  - chinese_chess.py  (tkinter 窗口)
  - pikafish_engine.py (UCI 外部引擎)
  - az/*              (AlphaZero 自对弈训练)

坐标约定：grid[row][col]，row 0 在上方=黑方，row 9 在下=红方。
"""

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
ROWS, COLS = 10, 9
RED, BLACK = 'r', 'b'

PIECE_CHARS = {
    RED:   {'K': '帅', 'A': '仕', 'E': '相', 'H': '马', 'R': '车', 'C': '炮', 'P': '兵'},
    BLACK: {'K': '将', 'A': '士', 'E': '象', 'H': '马', 'R': '车', 'C': '炮', 'P': '卒'},
}

PIECE_VALUE = {'K': 10000, 'R': 900, 'C': 450, 'H': 400, 'E': 200, 'A': 200, 'P': 100}

# 标准 FEN 字母（红=大写，黑=小写）：象=B(bishop) 马=N(knight)
CORE_TO_FEN = {'K': 'K', 'A': 'A', 'E': 'B', 'H': 'N', 'R': 'R', 'C': 'C', 'P': 'P'}
FEN_TO_CORE = {v: k for k, v in CORE_TO_FEN.items()}

# 位置价值表（红方视角）
PAWN_TABLE = [
    [0, 0, 0, 0, 0, 0, 0, 0, 0], [70, 90, 110, 110, 110, 110, 110, 90, 70],
    [70, 90, 110, 110, 110, 110, 110, 90, 70], [70, 90, 110, 110, 110, 110, 110, 90, 70],
    [60, 70, 90, 90, 100, 90, 90, 70, 60], [40, 50, 70, 70, 70, 70, 70, 50, 40],
    [20, 20, 20, 25, 30, 25, 20, 20, 20], [0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0], [0, 0, 0, 0, 0, 0, 0, 0, 0],
]
HORSE_TABLE = [
    [4, 8, 16, 12, 4, 12, 16, 8, 4], [4, 10, 28, 16, 8, 16, 28, 10, 4],
    [12, 14, 16, 20, 18, 20, 16, 14, 12], [8, 24, 18, 24, 20, 24, 18, 24, 8],
    [6, 16, 14, 18, 16, 18, 14, 16, 6], [6, 16, 14, 18, 16, 18, 14, 16, 6],
    [8, 24, 18, 24, 20, 24, 18, 24, 8], [12, 14, 16, 20, 18, 20, 16, 14, 12],
    [4, 10, 28, 16, 8, 16, 28, 10, 4], [4, 8, 16, 12, 4, 12, 16, 8, 4],
]
ROOK_TABLE = [
    [14, 14, 12, 18, 16, 18, 12, 14, 14], [16, 20, 18, 24, 26, 24, 18, 20, 16],
    [12, 12, 12, 18, 18, 18, 12, 12, 12], [12, 18, 16, 22, 22, 22, 16, 18, 12],
    [12, 14, 12, 18, 18, 18, 12, 14, 12], [12, 16, 14, 20, 20, 20, 14, 16, 12],
    [6, 10, 8, 14, 14, 14, 8, 10, 6], [4, 8, 6, 14, 12, 14, 6, 8, 4],
    [8, 4, 8, 16, 8, 16, 8, 4, 8], [-2, 10, 6, 14, 12, 14, 6, 10, -2],
]
CANNON_TABLE = [
    [6, 4, 0, -10, -12, -10, 0, 4, 6], [2, 2, 0, -4, -14, -4, 0, 2, 2],
    [2, 2, 0, -10, -8, -10, 0, 2, 2], [0, 0, -2, 4, 10, 4, -2, 0, 0],
    [0, 0, 0, 2, 8, 2, 0, 0, 0], [-2, 0, 4, 2, 6, 2, 4, 0, -2],
    [0, 0, 0, 2, 4, 2, 0, 0, 0], [4, 0, 8, 6, 10, 6, 8, 0, 4],
    [0, 2, 4, 6, 6, 6, 4, 2, 0], [0, 0, 2, 6, 6, 6, 2, 0, 0],
]
POSITION_TABLES = {'P': PAWN_TABLE, 'H': HORSE_TABLE, 'R': ROOK_TABLE, 'C': CANNON_TABLE}

PIECE_TYPES = ['K', 'A', 'E', 'H', 'R', 'C', 'P']  # 用于 NN 平面编码顺序


def opponent(color):
    return BLACK if color == RED else RED


# ---------------------------------------------------------------------------
# 棋盘 / 规则
# ---------------------------------------------------------------------------
class Board:
    def __init__(self, setup=True):
        self.grid = [[None] * COLS for _ in range(ROWS)]
        if setup:
            self.setup()

    def setup(self):
        back = ['R', 'H', 'E', 'A', 'K', 'A', 'E', 'H', 'R']
        for c, t in enumerate(back):
            self.grid[0][c] = (BLACK, t)
        self.grid[2][1] = (BLACK, 'C')
        self.grid[2][7] = (BLACK, 'C')
        for c in (0, 2, 4, 6, 8):
            self.grid[3][c] = (BLACK, 'P')
        for c, t in enumerate(back):
            self.grid[9][c] = (RED, t)
        self.grid[7][1] = (RED, 'C')
        self.grid[7][7] = (RED, 'C')
        for c in (0, 2, 4, 6, 8):
            self.grid[6][c] = (RED, 'P')

    def clone(self):
        b = Board.__new__(Board)
        b.grid = [row[:] for row in self.grid]
        return b

    def at(self, r, c):
        return self.grid[r][c]

    @staticmethod
    def in_board(r, c):
        return 0 <= r < ROWS and 0 <= c < COLS

    @staticmethod
    def in_palace(color, r, c):
        if c < 3 or c > 5:
            return False
        return (7 <= r <= 9) if color == RED else (0 <= r <= 2)

    def find_king(self, color):
        for r in range(ROWS):
            for c in range(COLS):
                p = self.grid[r][c]
                if p and p[0] == color and p[1] == 'K':
                    return (r, c)
        return None

    def piece_moves(self, r, c):
        p = self.grid[r][c]
        if not p:
            return []
        color, t = p
        moves = []
        enemy = opponent(color)

        def add(tr, tc):
            if not self.in_board(tr, tc):
                return False
            tp = self.grid[tr][tc]
            if tp and tp[0] == color:
                return False
            moves.append((tr, tc))
            return tp is None

        if t == 'K':
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nr, nc = r + dr, c + dc
                if self.in_palace(color, nr, nc):
                    add(nr, nc)
        elif t == 'A':
            for dr, dc in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                nr, nc = r + dr, c + dc
                if self.in_palace(color, nr, nc):
                    add(nr, nc)
        elif t == 'E':
            for dr, dc in ((2, 2), (2, -2), (-2, 2), (-2, -2)):
                nr, nc = r + dr, c + dc
                mr, mc = r + dr // 2, c + dc // 2
                if not self.in_board(nr, nc):
                    continue
                if self.grid[mr][mc] is not None:
                    continue
                if color == RED and nr < 5:
                    continue
                if color == BLACK and nr > 4:
                    continue
                add(nr, nc)
        elif t == 'H':
            for dr, dc in ((2, 1), (2, -1), (-2, 1), (-2, -1),
                           (1, 2), (1, -2), (-1, 2), (-1, -2)):
                nr, nc = r + dr, c + dc
                if not self.in_board(nr, nc):
                    continue
                if abs(dr) == 2:
                    lr, lc = r + dr // 2, c
                else:
                    lr, lc = r, c + dc // 2
                if self.grid[lr][lc] is not None:
                    continue
                add(nr, nc)
        elif t == 'R':
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nr, nc = r + dr, c + dc
                while self.in_board(nr, nc):
                    if not add(nr, nc):
                        break
                    nr, nc = nr + dr, nc + dc
        elif t == 'C':
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nr, nc = r + dr, c + dc
                while self.in_board(nr, nc) and self.grid[nr][nc] is None:
                    moves.append((nr, nc))
                    nr, nc = nr + dr, nc + dc
                nr, nc = nr + dr, nc + dc
                while self.in_board(nr, nc):
                    tp = self.grid[nr][nc]
                    if tp is not None:
                        if tp[0] == enemy:
                            moves.append((nr, nc))
                        break
                    nr, nc = nr + dr, nc + dc
        elif t == 'P':
            forward = -1 if color == RED else 1
            add(r + forward, c)
            crossed = (color == RED and r <= 4) or (color == BLACK and r >= 5)
            if crossed:
                add(r, c - 1)
                add(r, c + 1)
        return moves

    def kings_facing(self):
        rk = self.find_king(RED)
        bk = self.find_king(BLACK)
        if not rk or not bk or rk[1] != bk[1]:
            return False
        col = rk[1]
        lo, hi = min(rk[0], bk[0]), max(rk[0], bk[0])
        for r in range(lo + 1, hi):
            if self.grid[r][col] is not None:
                return False
        return True

    def is_attacked(self, r, c, by_color):
        for rr in range(ROWS):
            for cc in range(COLS):
                p = self.grid[rr][cc]
                if p and p[0] == by_color:
                    if (r, c) in self.piece_moves(rr, cc):
                        return True
        return False

    def in_check(self, color):
        k = self.find_king(color)
        if not k:
            return True
        return self.is_attacked(k[0], k[1], opponent(color))

    def legal_moves(self, color):
        result = []
        for r in range(ROWS):
            for c in range(COLS):
                p = self.grid[r][c]
                if p and p[0] == color:
                    for tr, tc in self.piece_moves(r, c):
                        nb = self.clone()
                        nb.grid[tr][tc] = nb.grid[r][c]
                        nb.grid[r][c] = None
                        if nb.kings_facing() or nb.in_check(color):
                            continue
                        result.append((r, c, tr, tc))
        return result

    def move(self, fr, fc, tr, tc):
        captured = self.grid[tr][tc]
        self.grid[tr][tc] = self.grid[fr][fc]
        self.grid[fr][fc] = None
        return captured

    def king_alive(self, color):
        return self.find_king(color) is not None

    # ---- FEN ----
    def to_fen(self, side):
        """导出标准象棋 FEN（含走子方）。side 为 RED/BLACK。"""
        rows = []
        for r in range(ROWS):
            empty = 0
            s = ''
            for c in range(COLS):
                p = self.grid[r][c]
                if p is None:
                    empty += 1
                else:
                    if empty:
                        s += str(empty)
                        empty = 0
                    letter = CORE_TO_FEN[p[1]]
                    s += letter if p[0] == RED else letter.lower()
            if empty:
                s += str(empty)
            rows.append(s)
        placement = '/'.join(rows)
        stm = 'w' if side == RED else 'b'
        return f'{placement} {stm} - - 0 1'

    @staticmethod
    def from_fen(fen):
        """从 FEN 解析，返回 (Board, side)。"""
        parts = fen.split()
        placement = parts[0]
        side = RED if (len(parts) < 2 or parts[1] == 'w') else BLACK
        b = Board(setup=False)
        for r, row in enumerate(placement.split('/')):
            c = 0
            for ch in row:
                if ch.isdigit():
                    c += int(ch)
                else:
                    color = RED if ch.isupper() else BLACK
                    b.grid[r][c] = (color, FEN_TO_CORE[ch.upper()])
                    c += 1
        return b, side


# ---------------------------------------------------------------------------
# UCI 坐标 <-> 内部坐标
# ---------------------------------------------------------------------------
def move_to_uci(move):
    """(fr,fc,tr,tc) -> 'a0a1' 形式。file a-i 自左到右，rank 0-9 自红方底线起。"""
    fr, fc, tr, tc = move
    return (f'{chr(ord("a") + fc)}{9 - fr}'
            f'{chr(ord("a") + tc)}{9 - tr}')


def uci_to_move(s):
    """'a0a1' -> (fr,fc,tr,tc)。"""
    fc = ord(s[0]) - ord('a')
    fr = 9 - int(s[1])
    tc = ord(s[2]) - ord('a')
    tr = 9 - int(s[3])
    return (fr, fc, tr, tc)


# ---------------------------------------------------------------------------
# 神经网络走法/棋盘编码
# ---------------------------------------------------------------------------
ACTION_SIZE = ROWS * COLS * ROWS * COLS  # 90*90 = 8100


def move_to_index(move):
    fr, fc, tr, tc = move
    return (fr * COLS + fc) * (ROWS * COLS) + (tr * COLS + tc)


def index_to_move(idx):
    src, dst = divmod(idx, ROWS * COLS)
    fr, fc = divmod(src, COLS)
    tr, tc = divmod(dst, COLS)
    return (fr, fc, tr, tc)


def encode_board(board, side):
    """棋盘 -> numpy 平面 (15,10,9)。前 7 平面=走子方棋子，中 7=对方，末 1=走子方(红1黑0)。"""
    import numpy as np
    planes = np.zeros((15, ROWS, COLS), dtype=np.float32)
    me = side
    for r in range(ROWS):
        for c in range(COLS):
            p = board.grid[r][c]
            if not p:
                continue
            color, t = p
            ti = PIECE_TYPES.index(t)
            base = 0 if color == me else 7
            planes[base + ti, r, c] = 1.0
    planes[14, :, :] = 1.0 if side == RED else 0.0
    return planes


# ---------------------------------------------------------------------------
# 内置 AI：alpha-beta 搜索 + 评估
# ---------------------------------------------------------------------------
class Engine:
    def __init__(self):
        self.nodes = 0

    @staticmethod
    def evaluate(board):
        score = 0
        for r in range(ROWS):
            for c in range(COLS):
                p = board.grid[r][c]
                if not p:
                    continue
                color, t = p
                val = PIECE_VALUE[t]
                table = POSITION_TABLES.get(t)
                if table:
                    val += table[r][c] if color == RED else table[ROWS - 1 - r][c]
                score += val if color == RED else -val
        return score

    def search(self, board, color, depth, alpha, beta):
        self.nodes += 1
        moves = board.legal_moves(color)
        if not moves:
            if board.in_check(color):
                return (-1_000_000 - depth if color == RED else 1_000_000 + depth), None
            return 0, None
        if depth == 0:
            return self.evaluate(board), None

        def move_key(m):
            target = board.grid[m[2]][m[3]]
            return PIECE_VALUE[target[1]] if target else 0
        moves.sort(key=move_key, reverse=True)

        best_move = None
        if color == RED:
            best = -float('inf')
            for m in moves:
                nb = board.clone()
                nb.move(*m)
                val, _ = self.search(nb, BLACK, depth - 1, alpha, beta)
                if val > best:
                    best, best_move = val, m
                alpha = max(alpha, best)
                if beta <= alpha:
                    break
            return best, best_move
        else:
            best = float('inf')
            for m in moves:
                nb = board.clone()
                nb.move(*m)
                val, _ = self.search(nb, RED, depth - 1, alpha, beta)
                if val < best:
                    best, best_move = val, m
                beta = min(beta, best)
                if beta <= alpha:
                    break
            return best, best_move

    def best_move(self, board, color, depth):
        self.nodes = 0
        score, move = self.search(board, color, depth, -float('inf'), float('inf'))
        return move, score
