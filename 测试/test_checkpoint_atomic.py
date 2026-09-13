# -*- coding: utf-8 -*-
"""检查点原子写回归测试 (M2 修复: 爬虫.py:_save_checkpoint 直写 -> tmp+os.replace)。

## 为什么需要 (M2)

`_save_checkpoint` 每章调用一次, 旧实现 `Path(ck_path).write_text(...)` **直写最终路径**。
写入过程中若进程被杀/断电/磁盘满, 会留下**半截 JSON**。而检查点是断点续传的命脉:
`_load_checkpoint` 遇到损坏 JSON 会返回 None -> 整本进度丢失, 只能从头重抓。

修复采用项目既有范式 (见 `爬取历史.py:_落盘` U17): **tmp + os.replace**。
`os.replace` 在同一文件系统内是原子操作 -> 检查点要么是旧版完整内容, 要么是新版完整内容,
不存在中间态。

## 锁定的契约 (改动 _save_checkpoint 前必读)

1. **tmp 文件名带 pid** — GUI 与远控是**两个进程**, 可能对同一输出文件写检查点;
   共用一个 `.tmp` 会互相截断, 可能 replace 出"半 A 半 B"的损坏文件 (U16 教训)。
   注: 4 个调用点都在**主线程串行**执行 (章节 worker 只抓取, 不写检查点), 故 pid 足够,
   无需线程 id。
2. **tmp 必须与目标同目录** — `os.replace` 跨文件系统/跨盘会抛 OSError, 原子性失效。
3. **file_handle 传入时先 flush** — P0-1 契约: 章节正文必须先于检查点落盘,
   否则崩溃时"检查点说已完成、正文却丢了", 续传永久跳过该章。
4. **保存后不留 tmp 残留** — replace 成功后 tmp 应消失。

所有写文件在 tempfile 临时目录, tearDown 清理, 不联网, 不触碰项目产物。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / '源码'))


def _造蜘蛛():
    from 爬虫 import NovelSpider
    return NovelSpider('https://example.com')


class TestCheckpoint原子写(unittest.TestCase):
    """M2: _save_checkpoint 必须走 tmp + os.replace, 不得直写最终路径"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix='ckpt_test_')
        self.out_file = os.path.join(self.tmp_dir, '测试书.txt')
        self.ck_path = self.out_file + '.checkpoint.json'
        self.spider = _造蜘蛛()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_保存后检查点内容正确(self):
        self.spider._save_checkpoint(self.out_file, 'https://a.com/book/1/', 42, 100)
        data = json.loads(Path(self.ck_path).read_text(encoding='utf-8'))
        self.assertEqual('https://a.com/book/1/', data['catalog_url'])
        self.assertEqual(42, data['completed'])
        self.assertEqual(100, data['total'])
        self.assertIn('updated', data)

    def test_经由os_replace落盘而非直写(self):
        """核心断言: 必须调用 os.replace (原子替换), 证明不是 write_text 直写目标"""
        with mock.patch('爬虫.os.replace', wraps=os.replace) as m:
            self.spider._save_checkpoint(self.out_file, 'https://a.com/b/', 1, 10)
        self.assertTrue(m.called, '_save_checkpoint 必须通过 os.replace 原子落盘')
        args, _ = m.call_args
        src, dst = Path(args[0]), Path(args[1])
        self.assertEqual(Path(self.ck_path).resolve(), dst.resolve(),
                         'os.replace 目标必须是检查点最终路径')
        self.assertIn('.tmp', src.name, '源必须是临时文件')

    def test_临时文件名带pid(self):
        """U16 契约: tmp 名带 pid, 防 GUI/远控双进程互相截断"""
        with mock.patch('爬虫.os.replace', wraps=os.replace) as m:
            self.spider._save_checkpoint(self.out_file, 'https://a.com/b/', 1, 10)
        src = Path(m.call_args[0][0])
        self.assertIn(str(os.getpid()), src.name,
                      f'临时文件名应含 pid 防双进程冲突, 实际: {src.name}')

    def test_临时文件与目标同目录(self):
        """os.replace 跨盘会抛 OSError, tmp 必须与检查点同目录"""
        with mock.patch('爬虫.os.replace', wraps=os.replace) as m:
            self.spider._save_checkpoint(self.out_file, 'https://a.com/b/', 1, 10)
        src, dst = Path(m.call_args[0][0]), Path(m.call_args[0][1])
        self.assertEqual(src.parent.resolve(), dst.parent.resolve(),
                         '临时文件必须与目标同目录, 否则 os.replace 不保证原子')

    def test_保存后无tmp残留(self):
        self.spider._save_checkpoint(self.out_file, 'https://a.com/b/', 5, 10)
        残留 = [p.name for p in Path(self.tmp_dir).iterdir() if '.tmp' in p.name]
        self.assertEqual([], 残留, 'os.replace 后临时文件应已消失, 不应残留')

    def test_连续多章保存均可读回(self):
        """模拟逐章保存: 每次都是完整合法 JSON, 无中间损坏态"""
        for i in range(1, 12):
            self.spider._save_checkpoint(self.out_file, 'https://a.com/b/', i, 11)
            data = json.loads(Path(self.ck_path).read_text(encoding='utf-8'))
            self.assertEqual(i, data['completed'])

    def test_往返_load能读回save(self):
        self.spider._save_checkpoint(self.out_file, 'https://a.com/b/', 7, 20)
        ck = self.spider._load_checkpoint(self.out_file, 'https://a.com/b/')
        self.assertIsNotNone(ck, '刚保存的检查点应能被读回')
        self.assertEqual(7, ck['completed'])

    def test_保存时flush输出文件句柄(self):
        """P0-1 契约: 传入 file_handle 时必须先 flush, 保证正文先于检查点落盘"""
        假句柄 = mock.Mock()
        self.spider._save_checkpoint(self.out_file, 'https://a.com/b/', 3, 10,
                                     file_handle=假句柄)
        假句柄.flush.assert_called_once()

    def test_句柄flush失败不阻塞保存(self):
        """flush 抛错 (句柄已关等) 时检查点仍应保存成功, 不中断抓取"""
        坏句柄 = mock.Mock()
        坏句柄.flush.side_effect = ValueError('I/O operation on closed file')
        self.spider._save_checkpoint(self.out_file, 'https://a.com/b/', 3, 10,
                                     file_handle=坏句柄)
        self.assertTrue(Path(self.ck_path).is_file(), 'flush 失败不应阻止检查点落盘')


class TestCheckpoint读取健壮性(unittest.TestCase):
    """_load_checkpoint 对损坏/不匹配检查点的容错 (断点续传不被改坏)"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix='ckpt_load_')
        self.out_file = os.path.join(self.tmp_dir, '测试书.txt')
        self.ck_path = self.out_file + '.checkpoint.json'
        self.spider = _造蜘蛛()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_检查点不存在返回None(self):
        self.assertIsNone(self.spider._load_checkpoint(self.out_file, 'https://a.com/b/'))

    def test_损坏JSON返回None(self):
        """M2 要防的场景: 半截 JSON 必须被识别为损坏并返回 None, 不得抛出"""
        Path(self.ck_path).write_text('{"catalog_url": "https://a.com/b/", "compl',
                                      encoding='utf-8')
        self.assertIsNone(self.spider._load_checkpoint(self.out_file, 'https://a.com/b/'))

    def test_目录URL不匹配返回None(self):
        """不同小说共用输出名时, 不得误用旧进度"""
        self.spider._save_checkpoint(self.out_file, 'https://a.com/b/', 5, 10)
        self.assertIsNone(self.spider._load_checkpoint(self.out_file, 'https://other.com/x/'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
