# -*- coding: utf-8 -*-
"""
Pikafish（UCI 协议）外部引擎封装。

Pikafish 是目前最强的开源中国象棋引擎（基于 Stockfish + NNUE 神经网络评估），
棋力远超人类职业棋手，CPU 即可运行。

使用前需自行下载（免费）：
  1. 引擎本体：https://github.com/official-pikafish/Pikafish/releases
       Windows 下载形如 pikafish-windows-x86-64.exe（按 CPU 选择版本）。
  2. NNUE 权重：同一 release 中的 pikafish.nnue（约 40MB），与可执行文件放同一目录。

放置方式（任选其一即可被自动检测）：
  - 放到本目录下的  game/engines/  文件夹，命名为 pikafish.exe（+ pikafish.nnue）
  - 或将 pikafish.exe 所在目录加入系统 PATH
  - 或设置环境变量  PIKAFISH_PATH 指向可执行文件完整路径

本模块通过标准 UCI 协议与引擎通信，把内部棋盘转成 FEN 发送，并解析 bestmove。
"""

import os
import shutil
import subprocess
import threading

from xiangqi_core import RED, move_to_uci, uci_to_move


def find_pikafish():
    """按多种途径查找 Pikafish 可执行文件，找不到返回 None。"""
    # 1. 环境变量
    env = os.environ.get('PIKAFISH_PATH')
    if env and os.path.isfile(env):
        return env
    # 2. 本地 engines 目录
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ('pikafish.exe', 'pikafish-windows-x86-64.exe',
                 'pikafish-avx2.exe', 'pikafish'):
        cand = os.path.join(here, 'engines', name)
        if os.path.isfile(cand):
            return cand
    # 3. PATH
    for name in ('pikafish', 'pikafish.exe'):
        found = shutil.which(name)
        if found:
            return found
    return None


INSTALL_HELP = (
    '未找到 Pikafish 引擎。\n\n'
    '请到 https://github.com/official-pikafish/Pikafish/releases 下载：\n'
    '  1) 可执行文件（如 pikafish-windows-x86-64.exe）\n'
    '  2) 权重文件 pikafish.nnue（与可执行文件同目录）\n\n'
    '然后将可执行文件重命名为 pikafish.exe，放入：\n'
    '  game/engines/ 目录\n'
    '或设置环境变量 PIKAFISH_PATH 指向它。'
)


class PikafishEngine:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.proc = subprocess.Popen(
            [path],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
            cwd=os.path.dirname(os.path.abspath(path)),
        )
        self._send('uci')
        self._wait_for('uciok')
        self._send('isready')
        self._wait_for('readyok')

    def _send(self, cmd):
        if self.proc.stdin:
            self.proc.stdin.write(cmd + '\n')
            self.proc.stdin.flush()

    def _wait_for(self, token, timeout_lines=2000):
        for _ in range(timeout_lines):
            line = self.proc.stdout.readline()
            if not line:
                break
            if token in line:
                return line
        return ''

    def best_move(self, board, color, movetime=1000):
        """让 Pikafish 给出最佳走法，返回内部坐标 (fr,fc,tr,tc) 或 None。"""
        fen = board.to_fen(color)
        with self.lock:
            self._send('ucinewgame')
            self._send('isready')
            self._wait_for('readyok')
            self._send(f'position fen {fen}')
            self._send(f'go movetime {int(movetime)}')
            best = None
            for _ in range(100000):
                line = self.proc.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if line.startswith('bestmove'):
                    parts = line.split()
                    if len(parts) >= 2 and parts[1] not in ('(none)', '0000'):
                        best = parts[1]
                    break
        if not best:
            return None
        return uci_to_move(best)

    def quit(self):
        try:
            self._send('quit')
            self.proc.wait(timeout=2)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


_ENGINE = None


def get_engine():
    """返回全局单例 Pikafish 引擎；未安装时抛出带安装说明的异常。"""
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    path = find_pikafish()
    if not path:
        raise RuntimeError(INSTALL_HELP)
    _ENGINE = PikafishEngine(path)
    return _ENGINE


if __name__ == '__main__':
    # 简单自测：若已安装，让引擎对开局给出一手
    from xiangqi_core import Board
    try:
        eng = get_engine()
        b = Board()
        mv = eng.best_move(b, RED, movetime=800)
        print('Pikafish 推荐开局红方走法:', mv, move_to_uci(mv) if mv else None)
    except RuntimeError as e:
        print(e)
