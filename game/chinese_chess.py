# -*- coding: utf-8 -*-
"""
中国象棋（带窗口 GUI）

功能：
  1. 完整的象棋基础走子规则
  2. 人人 / 人机对战，人机难度分级
  3. AI 预测下一步按钮
  4. 实时局面评分
  5. 三种 AI 引擎可切换：
       - 内置AI    ：alpha-beta 搜索 + 手写评估（无需依赖）
       - Pikafish  ：外部 UCI 超强引擎（需自行下载，棋力远超人类）
       - AlphaZero ：本地自对弈训练得到的神经网络模型（见 az/ 目录）

运行：py chinese_chess.py
"""

import tkinter as tk
from tkinter import messagebox
import threading

from xiangqi_core import (
    ROWS, COLS, RED, BLACK, PIECE_CHARS, Board, Engine, opponent,
)

# 内置 AI 难度 -> 搜索深度
DIFFICULTY = {'简单': 1, '普通': 2, '困难': 3, '大师': 4}

ENGINES = ['内置AI', 'Pikafish', 'AlphaZero']

# ---------------------------------------------------------------------------
# GUI 常量
# ---------------------------------------------------------------------------
MARGIN = 40
CELL = 60
BOARD_W = MARGIN * 2 + CELL * (COLS - 1)
BOARD_H = MARGIN * 2 + CELL * (ROWS - 1)

COLOR_BG = '#f0d9a8'
COLOR_LINE = '#5a3a1a'
COLOR_RED = '#c0392b'
COLOR_BLACK = '#1c1c1c'
COLOR_SEL = '#2ecc71'
COLOR_HINT = '#3498db'
COLOR_PREDICT = '#e67e22'


class ChessGUI:
    def __init__(self, root):
        self.root = root
        self.root.title('中国象棋')
        self.board = Board()
        self.engine = Engine()
        self.turn = RED
        self.selected = None
        self.legal_for_sel = []
        self.history = []
        self.predict_move = None
        self.ai_thinking = False
        self.game_over = False

        # 外部引擎缓存
        self._pikafish = None
        self._az_player = None

        self.mode_var = tk.StringVar(value='人机对战')
        self.diff_var = tk.StringVar(value='普通')
        self.human_color_var = tk.StringVar(value='红方')
        self.engine_var = tk.StringVar(value='内置AI')

        self._build_ui()
        self.draw()
        self.update_status()

    # ---- UI ----
    def _build_ui(self):
        main = tk.Frame(self.root)
        main.pack(fill='both', expand=True)

        self.canvas = tk.Canvas(main, width=BOARD_W, height=BOARD_H,
                                bg=COLOR_BG, highlightthickness=0)
        self.canvas.grid(row=0, column=0, padx=8, pady=8)
        self.canvas.bind('<Button-1>', self.on_click)

        panel = tk.Frame(main, width=220)
        panel.grid(row=0, column=1, sticky='ns', padx=(0, 10), pady=8)

        tk.Label(panel, text='游戏模式', font=('微软雅黑', 11, 'bold')).pack(anchor='w', pady=(2, 0))
        for m in ('人机对战', '双人对战'):
            tk.Radiobutton(panel, text=m, variable=self.mode_var, value=m,
                           command=self.on_mode_change).pack(anchor='w')

        tk.Label(panel, text='AI 引擎', font=('微软雅黑', 11, 'bold')).pack(anchor='w', pady=(6, 0))
        for e in ENGINES:
            tk.Radiobutton(panel, text=e, variable=self.engine_var, value=e,
                           command=self.on_engine_change).pack(anchor='w')

        tk.Label(panel, text='难度/强度', font=('微软雅黑', 11, 'bold')).pack(anchor='w', pady=(6, 0))
        for d in DIFFICULTY:
            tk.Radiobutton(panel, text=d, variable=self.diff_var, value=d).pack(anchor='w')

        tk.Label(panel, text='玩家执子', font=('微软雅黑', 11, 'bold')).pack(anchor='w', pady=(6, 0))
        for col in ('红方', '黑方'):
            tk.Radiobutton(panel, text=col + '(先手)' if col == '红方' else col,
                           variable=self.human_color_var, value=col).pack(anchor='w')

        tk.Button(panel, text='新游戏', width=20, command=self.new_game).pack(pady=(10, 2))
        tk.Button(panel, text='悔棋', width=20, command=self.undo).pack(pady=2)
        tk.Button(panel, text='AI 预测下一步', width=20, command=self.predict).pack(pady=2)

        tk.Frame(panel, height=2, bg='#aaa').pack(fill='x', pady=8)

        self.status_label = tk.Label(panel, text='', font=('微软雅黑', 11, 'bold'),
                                     fg=COLOR_RED, justify='left')
        self.status_label.pack(anchor='w')

        tk.Label(panel, text='局面评分(红方视角)', font=('微软雅黑', 10)).pack(anchor='w', pady=(8, 0))
        self.score_label = tk.Label(panel, text='0', font=('Consolas', 16, 'bold'))
        self.score_label.pack(anchor='w')
        self.score_bar = tk.Canvas(panel, width=200, height=18, bg='#ddd', highlightthickness=1,
                                   highlightbackground='#999')
        self.score_bar.pack(anchor='w', pady=(2, 6))

        self.info_label = tk.Label(panel, text='', font=('微软雅黑', 9), fg='#555',
                                   wraplength=200, justify='left')
        self.info_label.pack(anchor='w')

    # ---- 坐标 ----
    def cell_xy(self, r, c):
        return MARGIN + c * CELL, MARGIN + r * CELL

    def xy_cell(self, x, y):
        c = round((x - MARGIN) / CELL)
        r = round((y - MARGIN) / CELL)
        if Board.in_board(r, c):
            cx, cy = self.cell_xy(r, c)
            if abs(cx - x) <= CELL / 2 and abs(cy - y) <= CELL / 2:
                return r, c
        return None

    # ---- 绘制 ----
    def draw(self):
        cv = self.canvas
        cv.delete('all')
        for r in range(ROWS):
            x1, y = self.cell_xy(r, 0)
            x2, _ = self.cell_xy(r, COLS - 1)
            cv.create_line(x1, y, x2, y, fill=COLOR_LINE)
        for c in range(COLS):
            x, y1 = self.cell_xy(0, c)
            if c == 0 or c == COLS - 1:
                _, y2 = self.cell_xy(ROWS - 1, c)
                cv.create_line(x, y1, x, y2, fill=COLOR_LINE)
            else:
                _, ya = self.cell_xy(4, c)
                _, yb = self.cell_xy(5, c)
                cv.create_line(x, y1, x, ya, fill=COLOR_LINE)
                _, yend = self.cell_xy(ROWS - 1, c)
                cv.create_line(x, yb, x, yend, fill=COLOR_LINE)
        for (r1, c1, r2, c2) in [(0, 3, 2, 5), (0, 5, 2, 3), (7, 3, 9, 5), (7, 5, 9, 3)]:
            x1, y1 = self.cell_xy(r1, c1)
            x2, y2 = self.cell_xy(r2, c2)
            cv.create_line(x1, y1, x2, y2, fill=COLOR_LINE)
        _, cy = self.cell_xy(4, 0)
        cv.create_text(BOARD_W / 2 - CELL * 1.5, cy + CELL / 2, text='楚 河',
                       font=('楷体', 22), fill=COLOR_LINE)
        cv.create_text(BOARD_W / 2 + CELL * 1.5, cy + CELL / 2, text='漢 界',
                       font=('楷体', 22), fill=COLOR_LINE)

        if self.selected:
            self._mark(self.selected[0], self.selected[1], COLOR_SEL, width=3)
        for (r, c) in self.legal_for_sel:
            x, y = self.cell_xy(r, c)
            if self.board.at(r, c):
                self._mark(r, c, COLOR_HINT, width=2)
            else:
                cv.create_oval(x - 7, y - 7, x + 7, y + 7, fill=COLOR_HINT, outline='')
        if self.predict_move:
            fr, fc, tr, tc = self.predict_move
            self._mark(fr, fc, COLOR_PREDICT, width=3)
            self._mark(tr, tc, COLOR_PREDICT, width=3)
            x1, y1 = self.cell_xy(fr, fc)
            x2, y2 = self.cell_xy(tr, tc)
            cv.create_line(x1, y1, x2, y2, fill=COLOR_PREDICT, width=2, arrow='last')

        for r in range(ROWS):
            for c in range(COLS):
                p = self.board.at(r, c)
                if p:
                    self._draw_piece(r, c, p)

    def _mark(self, r, c, color, width=2):
        x, y = self.cell_xy(r, c)
        rad = CELL // 2 - 3
        self.canvas.create_rectangle(x - rad, y - rad, x + rad, y + rad,
                                     outline=color, width=width)

    def _draw_piece(self, r, c, p):
        color, t = p
        x, y = self.cell_xy(r, c)
        rad = CELL // 2 - 5
        fg = COLOR_RED if color == RED else COLOR_BLACK
        self.canvas.create_oval(x - rad, y - rad, x + rad, y + rad,
                                fill='#fff7e6', outline=fg, width=2)
        self.canvas.create_text(x, y, text=PIECE_CHARS[color][t],
                                font=('楷体', 24, 'bold'), fill=fg)

    # ---- 交互 ----
    def on_click(self, event):
        if self.game_over or self.ai_thinking or self._is_ai_turn():
            return
        cell = self.xy_cell(event.x, event.y)
        if not cell:
            return
        r, c = cell
        p = self.board.at(r, c)
        if self.selected:
            if (r, c) in self.legal_for_sel:
                self.do_move(self.selected[0], self.selected[1], r, c)
                return
            if p and p[0] == self.turn:
                self.select(r, c)
            else:
                self.selected = None
                self.legal_for_sel = []
                self.draw()
        else:
            if p and p[0] == self.turn:
                self.select(r, c)

    def select(self, r, c):
        self.selected = (r, c)
        self.predict_move = None
        all_moves = self.board.legal_moves(self.turn)
        self.legal_for_sel = [(tr, tc) for (fr, fc, tr, tc) in all_moves
                              if fr == r and fc == c]
        self.draw()

    def do_move(self, fr, fc, tr, tc):
        self.history.append((self.board.clone(), self.turn))
        self.board.move(fr, fc, tr, tc)
        self.selected = None
        self.legal_for_sel = []
        self.predict_move = None
        self.turn = opponent(self.turn)
        self.draw()
        self.update_status()
        if self._check_end():
            return
        if self._is_ai_turn():
            self.root.after(150, self.ai_move)

    # ---- 胜负 ----
    def _check_end(self):
        if not self.board.legal_moves(self.turn):
            self.game_over = True
            winner = '黑方' if self.turn == RED else '红方'
            loser = '红方' if self.turn == RED else '黑方'
            kind = '被将死' if self.board.in_check(self.turn) else '无子可动（困毙）'
            self.update_status()
            messagebox.showinfo('游戏结束', f'{loser}{kind}！{winner}胜！')
            return True
        return False

    # ---- 引擎调度 ----
    def _is_ai_turn(self):
        if self.mode_var.get() != '人机对战':
            return False
        human = RED if self.human_color_var.get() == '红方' else BLACK
        return self.turn != human

    def _compute_move(self, board, color):
        """在工作线程中计算走法。返回 (move, info_text)。"""
        eng = self.engine_var.get()
        if eng == 'Pikafish':
            pf = self._get_pikafish()
            move = pf.best_move(board, color,
                                movetime=self._pikafish_movetime())
            return move, f'Pikafish 已给出走法（{self.diff_var.get()}）'
        if eng == 'AlphaZero':
            az = self._get_az_player()
            move = az.best_move(board, color, simulations=self._az_sims())
            return move, f'AlphaZero 模型走法（模拟 {self._az_sims()} 次）'
        # 内置 AI
        depth = DIFFICULTY[self.diff_var.get()]
        move, score = self.engine.best_move(board, color, depth)
        return move, f'内置AI 深度{depth} 节点{self.engine.nodes} 评估{score:+d}'

    def _pikafish_movetime(self):
        return {'简单': 100, '普通': 400, '困难': 1500, '大师': 4000}[self.diff_var.get()]

    def _az_sims(self):
        return {'简单': 50, '普通': 200, '困难': 600, '大师': 1200}[self.diff_var.get()]

    def _get_pikafish(self):
        if self._pikafish is None:
            import pikafish_engine
            self._pikafish = pikafish_engine.get_engine()
        return self._pikafish

    def _get_az_player(self):
        if self._az_player is None:
            from az.az_player import AZPlayer
            self._az_player = AZPlayer()
        return self._az_player

    # ---- AI 行棋 ----
    def ai_move(self):
        if self.game_over or self.ai_thinking:
            return
        self.ai_thinking = True
        self.update_status()
        color = self.turn
        board_copy = self.board.clone()

        def work():
            try:
                move, info = self._compute_move(board_copy, color)
                self.root.after(0, lambda: self._apply_ai(move, info))
            except Exception as ex:
                self.root.after(0, lambda e=ex: self._engine_error(e))

        threading.Thread(target=work, daemon=True).start()

    def _apply_ai(self, move, info):
        self.ai_thinking = False
        if move is None:
            self._check_end()
            self.update_status()
            return
        self.info_label.config(text=info)
        self.do_move(*move)

    def _engine_error(self, ex):
        self.ai_thinking = False
        self.update_status()
        messagebox.showerror('引擎错误', str(ex))
        # 出错时回退到内置 AI
        self.engine_var.set('内置AI')

    # ---- 预测 ----
    def predict(self):
        if self.game_over or self.ai_thinking:
            return
        self.ai_thinking = True
        self.update_status()
        color = self.turn
        board_copy = self.board.clone()

        def work():
            try:
                move, info = self._compute_move(board_copy, color)
                self.root.after(0, lambda: self._show_predict(move, color, info))
            except Exception as ex:
                self.root.after(0, lambda e=ex: self._engine_error(e))

        threading.Thread(target=work, daemon=True).start()

    def _show_predict(self, move, color, info):
        self.ai_thinking = False
        if move is None:
            self.update_status()
            return
        self.predict_move = move
        self.selected = None
        self.legal_for_sel = []
        fr, fc, tr, tc = move
        p = self.board.at(fr, fc)
        name = PIECE_CHARS[p[0]][p[1]] if p else '?'
        self.info_label.config(
            text=f'预测：{"红" if color == RED else "黑"}方 {name} '
                 f'({fr},{fc})→({tr},{tc})\n{info}')
        self.draw()
        self.update_status()

    # ---- 状态/评分 ----
    def update_status(self):
        if self.game_over:
            self.status_label.config(text='游戏结束', fg='#555')
        elif self.ai_thinking:
            self.status_label.config(text=f'{self.engine_var.get()} 思考中...', fg=COLOR_PREDICT)
        else:
            txt = '红方走棋' if self.turn == RED else '黑方走棋'
            if self.board.in_check(self.turn):
                txt += '（将军！）'
            self.status_label.config(
                text=txt, fg=COLOR_RED if self.turn == RED else COLOR_BLACK)
        score = Engine.evaluate(self.board)
        self.score_label.config(text=f'{score:+d}',
                                fg=COLOR_RED if score >= 0 else COLOR_BLACK)
        self._draw_score_bar(score)

    def _draw_score_bar(self, score):
        import math
        bar = self.score_bar
        bar.delete('all')
        w = 200
        mid = w / 2
        ratio = math.tanh(score / 1000.0)
        length = mid * ratio
        if length >= 0:
            bar.create_rectangle(mid, 1, mid + length, 17, fill=COLOR_RED, outline='')
        else:
            bar.create_rectangle(mid + length, 1, mid, 17, fill=COLOR_BLACK, outline='')
        bar.create_line(mid, 0, mid, 18, fill='#666')

    # ---- 控制 ----
    def on_mode_change(self):
        if self._is_ai_turn() and not self.game_over:
            self.root.after(150, self.ai_move)

    def on_engine_change(self):
        # 切换引擎清空缓存的旧引擎（按需重新加载）
        self.info_label.config(text=f'当前引擎：{self.engine_var.get()}')

    def new_game(self):
        self.board = Board()
        self.turn = RED
        self.selected = None
        self.legal_for_sel = []
        self.history = []
        self.predict_move = None
        self.game_over = False
        self.ai_thinking = False
        self.info_label.config(text='')
        self.draw()
        self.update_status()
        if self._is_ai_turn():
            self.root.after(250, self.ai_move)

    def undo(self):
        if self.ai_thinking or not self.history:
            return
        steps = 2 if (self.mode_var.get() == '人机对战' and len(self.history) >= 2) else 1
        for _ in range(steps):
            if self.history:
                self.board, self.turn = self.history.pop()
        self.selected = None
        self.legal_for_sel = []
        self.predict_move = None
        self.game_over = False
        self.draw()
        self.update_status()


def main():
    root = tk.Tk()
    root.resizable(False, False)
    ChessGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
