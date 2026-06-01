# -*- coding: utf-8 -*-
"""AlphaZero-lite 训练主循环：自对弈 -> 训练 -> 保存，循环迭代，支持断点续训。

用法：
    py az/train.py                # 用默认配置开始/继续训练
    py az/train.py --iters 5      # 只跑 5 轮迭代
    py az/train.py --games 4 --sims 40   # 更快地跑通流程（棋力低，仅验证管线）

中断（Ctrl+C）后再次运行会从 checkpoints/latest.pt 继续。
"""

import argparse
import os
import pickle
import random
import sys
import time
from collections import deque

import numpy as np
import torch
import torch.nn.functional as F

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.dirname(_HERE)):
    if _p not in sys.path:
        sys.path.append(_p)
from xiangqi_core import ACTION_SIZE  # noqa: E402
import config  # noqa: E402
from network import PolicyValueNet, save as save_model, load as load_model  # noqa: E402
from selfplay import play_game, pi_to_dense  # noqa: E402


REPLAY_PATH = os.path.join(config.DATA_DIR, 'replay.pkl')


def build_model(device):
    model = PolicyValueNet().to(device)
    meta = {'iteration': 0}
    if os.path.exists(config.LATEST_MODEL):
        meta = load_model(model, config.LATEST_MODEL, map_location=device)
        print(f'已加载断点 latest.pt（迭代轮 {meta.get("iteration", 0)}）')
    return model, meta


def load_replay():
    buf = deque(maxlen=config.REPLAY_BUFFER_SIZE)
    if os.path.exists(REPLAY_PATH):
        try:
            with open(REPLAY_PATH, 'rb') as f:
                for s in pickle.load(f):
                    buf.append(s)
            print(f'已加载经验回放 {len(buf)} 条')
        except Exception as e:
            print('经验回放加载失败:', e)
    return buf


def save_replay(buf):
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(REPLAY_PATH, 'wb') as f:
        pickle.dump(list(buf), f)


def selfplay_phase(model, device, buf, games, sims, max_moves):
    t0 = time.time()
    results = {'r': 0, 'b': 0, None: 0}
    for g in range(games):
        data, winner = play_game(model, device, simulations=sims,
                                 max_moves=max_moves, verbose=True)
        for planes, pi, z in data:
            buf.append((planes, pi_to_dense(pi), z))
        results[winner] = results.get(winner, 0) + 1
        print(f'  [{g + 1}/{games}] 已累计样本 {len(buf)}')
    print(f'自对弈完成: 红胜{results["r"]} 黑胜{results["b"]} 和{results[None]} '
          f'耗时{time.time() - t0:.1f}s')


def train_phase(model, device, buf, steps):
    if len(buf) < config.BATCH_SIZE:
        print('样本不足，跳过训练'); return
    opt = torch.optim.Adam(model.parameters(), lr=config.LR,
                           weight_decay=config.WEIGHT_DECAY)
    model.train()
    samples = list(buf)
    tot_p = tot_v = 0.0
    for step in range(steps):
        batch = random.sample(samples, config.BATCH_SIZE)
        planes = torch.from_numpy(np.stack([b[0] for b in batch])).to(device)
        target_pi = torch.from_numpy(np.stack([b[1] for b in batch])).to(device)
        target_v = torch.tensor([b[2] for b in batch], dtype=torch.float32, device=device)

        logits, value = model(planes)
        logp = F.log_softmax(logits, dim=1)
        policy_loss = -(target_pi * logp).sum(dim=1).mean()
        value_loss = F.mse_loss(value, target_v)
        loss = policy_loss + config.VALUE_LOSS_WEIGHT * value_loss

        opt.zero_grad()
        loss.backward()
        opt.step()
        tot_p += policy_loss.item()
        tot_v += value_loss.item()
    print(f'训练完成: 策略损失{tot_p / steps:.4f} 价值损失{tot_v / steps:.4f}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--iters', type=int, default=config.NUM_ITERATIONS)
    ap.add_argument('--games', type=int, default=config.GAMES_PER_ITER)
    ap.add_argument('--sims', type=int, default=config.SELFPLAY_SIMULATIONS)
    ap.add_argument('--steps', type=int, default=config.TRAIN_STEPS_PER_ITER)
    ap.add_argument('--max-moves', type=int, default=config.MAX_GAME_MOVES)
    args = ap.parse_args()

    device = config.device()
    print(f'设备: {device}')
    model, meta = build_model(device)
    buf = load_replay()
    start_iter = meta.get('iteration', 0)

    try:
        for it in range(start_iter, start_iter + args.iters):
            print(f'\n===== 迭代 {it + 1} =====')
            model.eval()
            selfplay_phase(model, device, buf, args.games, args.sims, args.max_moves)
            train_phase(model, device, buf, args.steps)
            save_model(model, config.LATEST_MODEL, meta={'iteration': it + 1})
            save_model(model, config.BEST_MODEL, meta={'iteration': it + 1})
            save_replay(buf)
            print(f'已保存断点（迭代 {it + 1}）')
    except KeyboardInterrupt:
        print('\n收到中断，正在保存断点...')
        save_model(model, config.LATEST_MODEL, meta={'iteration': it})
        save_replay(buf)
        print('已保存，可下次继续。')


if __name__ == '__main__':
    main()
