# -*- coding: utf-8 -*-
"""自对弈：用当前网络 + MCTS 自我对弈生成训练样本。"""

import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.dirname(_HERE)):
    if _p not in sys.path:
        sys.path.append(_p)
from xiangqi_core import (  # noqa: E402
    Board, RED, opponent, encode_board, move_to_index,
)
import config  # noqa: E402
from mcts import run_mcts, pick_move  # noqa: E402


def play_game(model, device, simulations=None, max_moves=None, verbose=False):
    """进行一局自对弈，返回样本列表 [(planes, pi_dict, side), ...] 与结果字符串。

    结果：'r' 红胜 / 'b' 黑胜 / None 和棋。
    """
    sims = simulations or config.SELFPLAY_SIMULATIONS
    max_moves = max_moves or config.MAX_GAME_MOVES
    board = Board()
    side = RED
    samples = []          # (planes, pi_dict, side)
    winner = None

    for ply in range(max_moves):
        if not board.legal_moves(side):
            winner = opponent(side)     # 当前方无棋可走 => 对方胜
            break

        _, visits = run_mcts(model, board, side, sims, device, add_noise=True)
        total = sum(visits.values())
        pi = {move_to_index(m): n / total for m, n in visits.items()}
        samples.append((encode_board(board, side), pi, side))

        temp = 1.0 if ply < config.TEMP_MOVES else 0.0
        move = pick_move(visits, temperature=temp)
        board.move(*move)
        side = opponent(side)
    else:
        winner = None   # 达到步数上限判和

    # 回填胜负标签 z（每个样本以其走子方视角）
    data = []
    for planes, pi, s in samples:
        if winner is None:
            z = 0.0
        else:
            z = 1.0 if winner == s else -1.0
        data.append((planes, pi, z))
    if verbose:
        print(f'  对局结束: 步数={len(samples)} 结果={winner or "和"}')
    return data, winner


def pi_to_dense(pi_dict):
    from xiangqi_core import ACTION_SIZE
    arr = np.zeros(ACTION_SIZE, dtype=np.float32)
    for idx, p in pi_dict.items():
        arr[idx] = p
    return arr
