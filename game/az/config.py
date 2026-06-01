# -*- coding: utf-8 -*-
"""AlphaZero-lite 超参数配置。

默认值刻意调小，便于在单机 CPU/单 GPU 上**快速跑通整条训练管线**（自对弈→训练→对弈）。
要真正提升棋力，需要把规模（网络大小、模拟次数、对局数、迭代轮数）放大若干数量级，
并使用更快的走法生成（C/位棋盘）和多进程并行自对弈 —— 详见 az/README.md 的算力说明。
"""

import os

# 网络结构
NUM_RES_BLOCKS = 5          # 残差块数量（AlphaZero 用 19~39）
CHANNELS = 64               # 卷积通道数（AlphaZero 用 256）

# MCTS
C_PUCT = 1.5                # PUCT 探索系数
DIRICHLET_ALPHA = 0.3       # 根节点狄利克雷噪声
DIRICHLET_EPS = 0.25
SELFPLAY_SIMULATIONS = 80   # 自对弈每步模拟次数（AlphaZero 用 800）
TEMP_MOVES = 20             # 前若干步用温度=1 采样以增加多样性，之后趋于贪心

# 自对弈
GAMES_PER_ITER = 10         # 每轮迭代自对弈对局数
MAX_GAME_MOVES = 150        # 单局最大步数（超出判和）
REPLAY_BUFFER_SIZE = 20000  # 经验回放上限（样本数）

# 训练
BATCH_SIZE = 128
LR = 1e-3
WEIGHT_DECAY = 1e-4
TRAIN_STEPS_PER_ITER = 200  # 每轮迭代的梯度步数
VALUE_LOSS_WEIGHT = 1.0

# 总体
NUM_ITERATIONS = 1000       # 训练迭代轮数（可随时中断，断点续训）

# 路径
_BASE = os.path.dirname(os.path.abspath(__file__))
CHECKPOINT_DIR = os.path.join(_BASE, 'checkpoints')
DATA_DIR = os.path.join(_BASE, 'data')
BEST_MODEL = os.path.join(CHECKPOINT_DIR, 'best.pt')
LATEST_MODEL = os.path.join(CHECKPOINT_DIR, 'latest.pt')


def device():
    import torch
    return 'cuda' if torch.cuda.is_available() else 'cpu'
