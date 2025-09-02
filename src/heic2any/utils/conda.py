# -*- coding: utf-8 -*-
"""
Conda 环境发现与依赖检测。
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import List, Tuple
import sys


@dataclass
class CondaEnv:
    """Conda 环境信息。"""
    name: str
    prefix: str

    @property
    def python(self) -> str:
        # Windows与Unix分别处理
        if os.name == 'nt':
            return os.path.join(self.prefix, 'python.exe')
        return os.path.join(self.prefix, 'bin', 'python')


def _run(cmd: List[str]) -> Tuple[int, str, str]:
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate(timeout=10)
    return p.returncode, out, err


def find_conda_envs() -> List[CondaEnv]:
    """发现所有Conda环境。"""
    # 优先用JSON
    code, out, err = _run(['conda', 'env', 'list', '--json'])
    envs: List[CondaEnv] = []
    if code == 0:
        try:
            data = json.loads(out)
            for p in data.get('envs', []):
                name = os.path.basename(p)
                envs.append(CondaEnv(name=name, prefix=p))
            return envs
        except Exception:
            pass
    # 退化解析文本
    code, out, err = _run(['conda', 'info', '--envs'])
    if code == 0:
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            p = parts[-1]
            if os.path.isdir(p):
                envs.append(CondaEnv(name=os.path.basename(p), prefix=p))
    return envs


def test_env_dependencies(env: CondaEnv) -> Tuple[bool, str]:
    """检测指定环境是否具备必要依赖。"""
    if not os.path.isfile(env.python):
        return False, f"未找到Python: {env.python}"
    code, out, err = _run([env.python, '-c', 'import PIL, pillow_heif; print("OK")'])
    if code == 0 and 'OK' in out:
        return True, "依赖就绪"
    return False, err or out or "依赖不满足"


def find_system_pythons() -> List[str]:
    """发现系统中的 Python 解释器路径列表。

    - 永远包含当前进程的 `sys.executable`
    - Windows 上尝试通过 `py -0p` 枚举已注册的解释器
    - 其他平台可扩展 PATH 搜索，这里保守返回当前解释器
    """
    paths: List[str] = []
    try:
        paths.append(sys.executable)
    except Exception:
        pass
    # Windows 的 py 启动器
    if os.name == 'nt':
        try:
            code, out, err = _run(['py', '-0p'])
            if code == 0:
                for line in out.splitlines():
                    p = line.strip()
                    if p and os.path.isfile(p) and p.lower().endswith('python.exe'):
                        if p not in paths:
                            paths.append(p)
        except Exception:
            pass
    # 去重
    uniq = []
    for p in paths:
        if p and p not in uniq:
            uniq.append(p)
    return uniq
