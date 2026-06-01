# -*- coding: utf-8 -*-
"""PUCT 蒙特卡洛树搜索（MCTS），由策略-价值网络引导。

价值约定：网络对局面 s 输出的 value 是「s 的走子方」的预期胜负 ∈ (-1,1)。
回溯时逐层翻转符号，使每条边的 Q 始终是「该边所属父节点走子方」视角。
"""

import math
import os
import sys

import numpy as np
import torch

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.dirname(_HERE)):
    if _p not in sys.path:
        sys.path.append(_p)
from xiangqi_core import (  # noqa: E402
    encode_board, move_to_index, opponent,
)
import config  # noqa: E402


class Node:
    __slots__ = ('board', 'side', 'P', 'N', 'W', 'children', 'expanded',
                 'is_terminal', 'terminal_value')

    def __init__(self, board, side, prior=0.0):
        self.board = board
        self.side = side
        self.P = prior
        self.N = 0
        self.W = 0.0
        self.children = {}        # move -> Node
        self.expanded = False
        self.is_terminal = False
        self.terminal_value = 0.0

    def q(self):
        return self.W / self.N if self.N > 0 else 0.0


@torch.no_grad()
def _evaluate(model, board, side, device):
    """网络前向：返回 (legal_moves, priors_over_legal(list), value)。"""
    planes = encode_board(board, side)
    x = torch.from_numpy(planes).unsqueeze(0).to(device)
    logits, value = model(x)
    logits = logits[0].cpu().numpy()
    value = float(value.item())

    moves = board.legal_moves(side)
    if not moves:
        return [], [], value
    idxs = np.array([move_to_index(m) for m in moves])
    mlog = logits[idxs]
    mlog -= mlog.max()
    probs = np.exp(mlog)
    probs /= probs.sum()
    return moves, probs, value


def _expand(node, model, device):
    """展开叶节点：计算合法走法、先验、价值。返回 value（node.side 视角）。"""
    if node.board is None:
        raise RuntimeError('node board not materialized')
    moves, priors, value = _evaluate(model, node.board, node.side, device)
    if not moves:
        node.is_terminal = True
        node.terminal_value = -1.0   # 走子方无棋可走 => 判负
        node.expanded = True
        return -1.0
    for m, p in zip(moves, priors):
        node.children[m] = Node(None, opponent(node.side), prior=float(p))
    node.expanded = True
    return value


def _select(node):
    """按 PUCT 选择子节点。返回 (move, child)。"""
    total_n = sum(ch.N for ch in node.children.values())
    sqrt_total = math.sqrt(total_n + 1e-8)
    best_score, best_move, best_child = -1e18, None, None
    for move, ch in node.children.items():
        u = config.C_PUCT * ch.P * sqrt_total / (1 + ch.N)
        score = ch.q() + u
        if score > best_score:
            best_score, best_move, best_child = score, move, ch
    return best_move, best_child


def run_mcts(model, board, side, n_sims, device, add_noise=True):
    """对局面运行 MCTS，返回 (root, visit_counts: dict[move->N])。"""
    root = Node(board.clone(), side)
    _expand(root, model, device)
    if add_noise and root.children:
        _add_dirichlet_noise(root)

    for _ in range(n_sims):
        node = root
        path = [node]
        # 选择
        while node.expanded and not node.is_terminal:
            move, child = _select(node)
            if child.board is None:
                nb = node.board.clone()
                nb.move(*move)
                child.board = nb
            node = child
            path.append(node)
        # 评估叶
        if node.is_terminal:
            value = node.terminal_value
        else:
            value = _expand(node, model, device)
        # 回溯（逐层翻转符号）
        v = value
        for anc in reversed(path):
            anc.N += 1
            anc.W += v
            v = -v

    visits = {m: ch.N for m, ch in root.children.items()}
    return root, visits


def _add_dirichlet_noise(root):
    moves = list(root.children.keys())
    noise = np.random.dirichlet([config.DIRICHLET_ALPHA] * len(moves))
    eps = config.DIRICHLET_EPS
    for m, n in zip(moves, noise):
        ch = root.children[m]
        ch.P = (1 - eps) * ch.P + eps * float(n)


def pick_move(visits, temperature=1.0):
    """根据访问次数选择走法。temperature=0 时取最大访问。"""
    moves = list(visits.keys())
    counts = np.array([visits[m] for m in moves], dtype=np.float64)
    if temperature <= 1e-6:
        return moves[int(counts.argmax())]
    probs = counts ** (1.0 / temperature)
    probs /= probs.sum()
    return moves[int(np.random.choice(len(moves), p=probs))]
