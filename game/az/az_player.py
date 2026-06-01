# -*- coding: utf-8 -*-
"""把训练好的 AlphaZero 模型包装成棋手，供 GUI 调用。

若尚未训练出模型（缺少 checkpoints/best.pt），将使用随机初始化的网络
（棋力很弱），仅用于验证「训练→对弈」链路打通。训练后棋力随迭代提升。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.dirname(_HERE)):
    if _p not in sys.path:
        sys.path.append(_p)

import config  # noqa: E402
from network import PolicyValueNet, load as load_model  # noqa: E402
from mcts import run_mcts, pick_move  # noqa: E402


class AZPlayer:
    def __init__(self, model_path=None):
        import torch  # 延迟导入，未装 torch 时给出清晰错误
        self.device = config.device()
        self.model = PolicyValueNet().to(self.device)
        self.trained = False
        path = model_path or config.BEST_MODEL
        if os.path.exists(path):
            meta = load_model(self.model, path, map_location=self.device)
            self.trained = True
            self.iteration = meta.get('iteration', 0)
        self.model.eval()

    def best_move(self, board, color, simulations=400):
        """用 MCTS（不加噪声、贪心选择）给出走法。"""
        if not board.legal_moves(color):
            return None
        _, visits = run_mcts(self.model, board, color, simulations,
                             self.device, add_noise=False)
        if not visits:
            return None
        return pick_move(visits, temperature=0.0)

    @property
    def status(self):
        if self.trained:
            return f'AlphaZero 模型（已训练 {self.iteration} 轮）'
        return 'AlphaZero 模型（未训练，棋力很弱，请先运行 az/train.py）'
