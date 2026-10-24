# -*- coding: utf-8 -*-
"""多机同步：私有仓推送不得依赖 upstream（2026-10-24 K 机实测缺陷）。

缺陷现场：第二台机用 `多机初始化.py` 的 `clone --bare` 落地私有仓，裸克隆
**不会建立 upstream**；`多机同步.py --上传` 里原来的 `git push`（无参）直接报
"no upstream branch" —— 私有资产已 commit 却推不出去。

本用例用临时裸仓复现同一形态，并自带反证：
  ① 先证明「无参 push」在这个形态下**确实会失败**（否则用例没有意义）；
  ② 再要求 `推私有()` 返回 0；
  ③ 最后核对远端 main **真的前进**到本地 HEAD，而不是"看着像推了"。
"""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

根 = Path(__file__).resolve().parents[1]


def _载入脚本():
    路径 = 根 / '脚本' / '多机同步.py'
    spec = importlib.util.spec_from_file_location('多机同步_被测', 路径)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _跑(*参数, cwd=None, git_dir=None, work_tree=None):
    命令 = ['git']
    if git_dir:
        命令.append(f'--git-dir={git_dir}')
    if work_tree:
        命令.append(f'--work-tree={work_tree}')
    命令 += list(参数)
    return subprocess.run(命令, cwd=cwd, capture_output=True, text=True,
                          encoding='utf-8', errors='replace')


def _提交(git_dir, work_tree, 内容):
    (Path(work_tree) / 'a.txt').write_text(内容, encoding='utf-8')
    身份 = ['-c', 'user.name=测试', '-c', 'user.email=test@local']
    _跑(*身份, 'add', 'a.txt', git_dir=git_dir, work_tree=work_tree)
    return _跑(*身份, 'commit', '-m', 内容, git_dir=git_dir, work_tree=work_tree)


class Test私有仓推送(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Path(self._tmp.name)
        self.remote = self.t / 'remote.git'
        self.local = self.t / 'local.git'
        self.work = self.t / 'work'
        self.work.mkdir()
        (self.work / 'a.txt').write_text('v1', encoding='utf-8')

        # 一个已有 main 的远端
        self.assertEqual(_跑('init', '--bare', str(self.remote)).returncode, 0)
        seed = self.t / 'seed'
        seed.mkdir()
        (seed / 'a.txt').write_text('v1', encoding='utf-8')
        _跑('init', cwd=seed)
        身份 = ['-c', 'user.name=测试', '-c', 'user.email=test@local']
        _跑(*身份, 'add', 'a.txt', cwd=seed)
        _跑(*身份, 'commit', '-m', 'init', cwd=seed)
        _跑('branch', '-M', 'main', cwd=seed)
        _跑('remote', 'add', 'origin', str(self.remote), cwd=seed)
        self.assertEqual(_跑('push', '-u', 'origin', 'main', cwd=seed).returncode, 0)

        # 第二台机的形态：裸克隆 + 非 bare + work-tree，且不配 upstream
        self.assertEqual(
            _跑('clone', '--bare', str(self.remote), str(self.local)).returncode, 0)
        _跑('config', 'core.bare', 'false', git_dir=self.local)
        _跑('symbolic-ref', 'HEAD', 'refs/heads/main', git_dir=self.local)
        self.assertEqual(
            _跑('checkout', '-f', 'main', git_dir=self.local,
               work_tree=self.work).returncode, 0)
        self.assertEqual(_提交(self.local, self.work, 'v2').returncode, 0)

    def tearDown(self):
        self._tmp.cleanup()

    def test_无upstream时显式推送成功(self):
        # ① 反证：这个形态下无参 push 必失败
        裸推 = _跑('push', git_dir=self.local, work_tree=self.work)
        self.assertNotEqual(
            裸推.returncode, 0,
            '该形态本应没有 upstream；若这里成功了，说明用例没复现出缺陷')

        # ② 被测函数
        mod = _载入脚本()
        推 = mod.推私有(str(self.local), str(self.work))
        self.assertEqual(
            推.returncode, 0,
            f'推私有 应成功，实际: {(推.stderr or 推.stdout)[:300]}')

        # ③ 远端必须真的前进
        本地 = _跑('rev-parse', 'HEAD', git_dir=self.local, work_tree=self.work)
        远端 = _跑('rev-parse', 'main', git_dir=self.remote)
        self.assertEqual(本地.stdout.strip(), 远端.stdout.strip(),
                         '远端 main 未前进到本地 HEAD，推送只是"看起来成功"')


if __name__ == '__main__':
    unittest.main(verbosity=2)
