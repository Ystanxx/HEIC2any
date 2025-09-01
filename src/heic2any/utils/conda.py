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

