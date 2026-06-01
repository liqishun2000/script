# -*- coding: utf-8 -*-
"""策略-价值网络（AlphaZero 式 ResNet）。

输入：棋盘编码 (15, 10, 9)
输出：
  - policy logits，长度 ACTION_SIZE=8100（from*90+to）
  - value，标量 ∈ (-1,1)，表示**当前走子方**的预期胜负
"""

import os
import sys

import torch
import torch.nn as nn
import torch.nn.functional as F

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.dirname(_HERE)):
    if _p not in sys.path:
        sys.path.append(_p)
from xiangqi_core import ACTION_SIZE, ROWS, COLS  # noqa: E402

import config  # noqa: E402

INPUT_PLANES = 15


class ResBlock(nn.Module):
    def __init__(self, ch):
        super().__init__()
        self.c1 = nn.Conv2d(ch, ch, 3, padding=1, bias=False)
        self.b1 = nn.BatchNorm2d(ch)
        self.c2 = nn.Conv2d(ch, ch, 3, padding=1, bias=False)
        self.b2 = nn.BatchNorm2d(ch)

    def forward(self, x):
        y = F.relu(self.b1(self.c1(x)))
        y = self.b2(self.c2(y))
        return F.relu(x + y)


class PolicyValueNet(nn.Module):
    def __init__(self, channels=config.CHANNELS, blocks=config.NUM_RES_BLOCKS):
        super().__init__()
        self.stem = nn.Sequential(
            nn.Conv2d(INPUT_PLANES, channels, 3, padding=1, bias=False),
            nn.BatchNorm2d(channels), nn.ReLU(inplace=True),
        )
        self.res = nn.ModuleList([ResBlock(channels) for _ in range(blocks)])

        # 策略头
        self.p_conv = nn.Conv2d(channels, 4, 1, bias=False)
        self.p_bn = nn.BatchNorm2d(4)
        self.p_fc = nn.Linear(4 * ROWS * COLS, ACTION_SIZE)

        # 价值头
        self.v_conv = nn.Conv2d(channels, 2, 1, bias=False)
        self.v_bn = nn.BatchNorm2d(2)
        self.v_fc1 = nn.Linear(2 * ROWS * COLS, 128)
        self.v_fc2 = nn.Linear(128, 1)

    def forward(self, x):
        x = self.stem(x)
        for blk in self.res:
            x = blk(x)
        p = F.relu(self.p_bn(self.p_conv(x)))
        p = self.p_fc(p.flatten(1))                 # logits
        v = F.relu(self.v_bn(self.v_conv(x)))
        v = F.relu(self.v_fc1(v.flatten(1)))
        v = torch.tanh(self.v_fc2(v)).squeeze(-1)
        return p, v


def save(model, path, meta=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    torch.save({'state_dict': model.state_dict(), 'meta': meta or {}}, path)


def load(model, path, map_location=None):
    ckpt = torch.load(path, map_location=map_location)
    model.load_state_dict(ckpt['state_dict'])
    return ckpt.get('meta', {})
