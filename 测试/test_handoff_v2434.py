# -*- coding: utf-8 -*-
"""本轮接手回归：离线复现数据保护、停止竞态、日志窗口与远控边界。"""
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'源码'))
sys.path.insert(0, str(ROOT/'脚本'))
from gui_components import task_manager as tm
from 远控 import 服务


class 接手回归(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.history = self.root/'任务历史.json'
        self.path_patch = mock.patch.object(tm.TaskManager, '_历史路径', return_value=str(self.history))
        self.path_patch.start(); self.addCleanup(self.path_patch.stop)
        self.mgr = tm.TaskManager(None)
        p=mock.patch.object(服务, '_任务管理器', return_value=self.mgr)
        p.start(); self.addCleanup(p.stop)
        p=mock.patch.object(服务, '取配置', return_value={'token':'testtoken'})
        p.start(); self.addCleanup(p.stop)
        from fastapi.testclient import TestClient
        self.client=TestClient(服务.app, raise_server_exceptions=False)

    def test_停止信号在空闲闸门前已置位(self):
        stop=threading.Event();stop.set();gate=threading.Semaphore(1)
        self.assertFalse(tm._获取域闸门(gate,stop))
        self.assertTrue(gate.acquire(blocking=False))

    def test_停止后旧线程未退出不得重启(self):
        finish=threading.Event()
        worker=threading.Thread(target=lambda:finish.wait(3),daemon=True);worker.start()
        self.addCleanup(finish.set)
        t=tm.TaskInfo('task_1','https://example.com/book',status='stopped',thread=worker)
        t.stop_flag.set(); self.mgr.tasks[t.task_id]=t
        with mock.patch.object(self.mgr,'_run_task'):
            self.assertFalse(self.mgr.restart_task(t.task_id))
        self.assertIs(t.thread,worker);self.assertTrue(t.stop_flag.is_set())
        finish.set();worker.join(2)

    def test_停止后晚到完成事件不覆盖终态(self):
        t=tm.TaskInfo('task_1','https://example.com/book',status='stopped');t.stop_flag.set()
        tm.TaskLogRedirector(t,io.StringIO())._应用完成终态()
        self.assertEqual(t.status,'stopped')

    def test_创建任务启动前持久化(self):
        with mock.patch.object(threading.Thread,'start'):
            tid=self.mgr.create_task('https://example.com/book')
        self.assertTrue(self.history.exists())
        self.assertEqual(json.loads(self.history.read_text(encoding='utf-8'))[0]['task_id'],tid)

    def test_500条日志后继续接收(self):
        t=tm.TaskInfo('task_1','https://example.com/book');self.mgr.tasks[t.task_id]=t
        w=tm.TaskLogRedirector(t,io.StringIO())
        with mock.patch.object(w,'_log_to_file'):
            for i in range(500):w.write(f'日志 {i}\n')
            w.write('最新日志\n')
        res=self.client.get('/api/v1/tasks/task_1/logs?after=500&k=testtoken')
        self.assertEqual(res.status_code,200)
        self.assertEqual(res.json()['total'],501)
        self.assertEqual(res.json()['entries'][-1]['msg'],'最新日志')
        self.assertLessEqual(len(t.logs),500)

    def test_非ASCII鉴权返回401(self):
        self.assertEqual(self.client.get('/api/v1/tasks?k=中文').status_code,401)

    def test_错误参数拒绝且不启动任务(self):
        bad=[{'url':123},{'url':'https://example.com','mode':'typo'},
             {'url':'https://example.com','mode':'range'},
             {'url':'https://example.com','mode':'range','chapter_range':[5,2]},
             {'url':'https://example.com','mode':'range','chapter_range':['1',3]},
             {'url':'https://example.com','resume':'false'}]
        with mock.patch.object(self.mgr,'create_task',return_value='mock') as create:
            for body in bad:
                with self.subTest(body=body):
                    self.assertEqual(self.client.post('/api/v1/tasks?k=testtoken',json=body).status_code,400)
            create.assert_not_called()

    def test_删除远控项持久化(self):
        self.mgr.tasks['task_1']=tm.TaskInfo('task_1','https://example.com',status='completed')
        self.mgr._保存任务历史()
        self.assertTrue(服务._删除展示任务('task_1'))
        self.assertEqual(json.loads(self.history.read_text(encoding='utf-8')),[])

    def test_恢复历史终态不重新推送(self):
        t=tm.TaskInfo('task_1','https://example.com',status='completed');t.metrics.end_time=123
        self.mgr.tasks[t.task_id]=t;self.mgr._保存任务历史();self.mgr=tm.TaskManager(None)
        with mock.patch.object(服务,'_任务管理器',return_value=self.mgr), mock.patch.object(服务,'_发送推送') as send, mock.patch.object(服务,'_已推终态',set()):
            服务._扫描终态();send.assert_not_called()

    def test_坏检查点不影响其他记录(self):
        (self.root/'坏.txt.checkpoint.json').write_text(json.dumps({'catalog_url':'https://example.com/1','completed':'oops'}),encoding='utf-8')
        (self.root/'好.txt.checkpoint.json').write_text(json.dumps({'catalog_url':'https://example.com/2','completed':2,'total':4}),encoding='utf-8')
        with mock.patch.object(服务,'get_default_output_dir',return_value=str(self.root)),mock.patch.object(服务,'_已扫中断',False):
            服务._恢复中断任务()
        self.assertEqual(len(self.mgr.tasks),1)
        self.assertEqual(next(iter(self.mgr.tasks.values())).title,'好')

    def test_章节保留开篇(self):
        p=self.root/'book.txt';p.write_text('导语\n## 第一章\n正文\n',encoding='utf-8')
        chapters=服务._解析章节({'路径':str(p)})
        self.assertEqual([x['标题'] for x in chapters],['(开篇)','第一章'])

    def test_坏阅读进度兼容(self):
        (self.root/'数据').mkdir();(self.root/'数据'/'阅读进度.json').write_text('[]',encoding='utf-8')
        with mock.patch.object(服务,'get_state_root',return_value=str(self.root)):
            self.assertEqual(服务._读进度('book'),0)
            服务._写进度('book',2)
            self.assertEqual(服务._读进度('book'),2)

    def test_DNS本机绑定保留系统语义(self):
        import dns_doh as dns
        with mock.patch.object(dns,'_orig_getaddrinfo',return_value=['native']) as original:
            self.assertEqual(dns._patched_getaddrinfo(None,80),['native'])
            self.assertEqual(dns._patched_getaddrinfo(b'localhost',80),['native'])
            self.assertEqual(original.call_count,2)

    def test_EPUB失败保留旧文件(self):
        import epub_exporter as exp
        p=self.root/'book.txt';p.write_text('## 第一章\n正文',encoding='utf-8')
        target=p.with_suffix('.epub');target.write_bytes(b'old-valid-epub')
        def bad_write(path,book):
            Path(path).write_bytes(b'broken');raise OSError('模拟中断')
        with mock.patch.object(exp.epub,'write_epub',side_effect=bad_write):
            self.assertIsNone(exp.txt_to_epub(str(p)))
        self.assertEqual(target.read_bytes(),b'old-valid-epub')

    def test_EPUB重建失败不下载旧版本(self):
        import epub_exporter as exp
        import os
        p=self.root/'book.txt';p.write_text('## 第一章\n正文',encoding='utf-8')
        target=p.with_suffix('.epub');target.write_bytes(b'old');os.utime(target,(1,1))
        with mock.patch.object(exp,'txt_to_epub',return_value=None):
            with self.assertRaises(服务.HTTPException):服务._确保epub({'路径':str(p),'标题':'书'})

    def test_保护失败中止且不丢原文件(self):
        import build_exe as build
        dist=self.root/'dist';dist.mkdir();(dist/'站点配置.json').write_text('original',encoding='utf-8')
        with mock.patch.object(build.shutil,'move',side_effect=OSError('权限失败')),mock.patch.object(build,'log'):
            with self.assertRaises(RuntimeError):build.保护dist用户数据(str(dist))
        self.assertEqual((dist/'站点配置.json').read_text(encoding='utf-8'),'original')

    def test_恢复冲突保留stash原件(self):
        import build_exe as build
        dist=self.root/'dist';stash=self.root/'stash';dist.mkdir();stash.mkdir()
        (dist/'站点配置.json').write_text('new',encoding='utf-8')
        src=stash/'站点配置.json';src.write_text('original',encoding='utf-8')
        with mock.patch.object(build,'log'):build.恢复dist用户数据(str(dist),str(stash))
        self.assertTrue(src.exists());self.assertEqual(src.read_text(encoding='utf-8'),'original')

    def test_历史倒序快照不会覆盖新记录(self):
        import 爬取历史, 站点历史
        for cls in (爬取历史.爬取历史,站点历史.站点历史):
            with self.subTest(cls=cls.__name__):
                h=object.__new__(cls);h._file=str(self.root/(cls.__name__+'.json'))
                h._io_lock=threading.Lock();h._数据={'a':{'n':1}};h._上次落盘=0;h._脏=False
                with h._io_lock:old=h._快照(force=True)
                with h._io_lock:h._数据['a']['n']=2;new=h._快照(force=True)
                h._落盘(new);h._落盘(old)
                self.assertEqual(json.loads(Path(h._file).read_text(encoding='utf-8'))['a']['n'],2)

    def test_写盘期间新修改仍标脏(self):
        import 爬取历史,站点历史
        for cls in (爬取历史.爬取历史,站点历史.站点历史):
            h=object.__new__(cls);h._file=str(self.root/(cls.__name__+'.json'))
            h._io_lock=threading.Lock();h._数据={'a':{'n':1}};h._上次落盘=0;h._脏=False
            with h._io_lock:old=h._快照(force=True)
            original=Path.write_text
            def write_and_mutate(path,*a,**k):
                result=original(path,*a,**k)
                with h._io_lock:h._数据['a']['n']=2;h._快照(force=True)
                return result
            with mock.patch.object(Path,'write_text',write_and_mutate):h._落盘(old)
            self.assertTrue(h._脏)
            h.flush();self.assertEqual(json.loads(Path(h._file).read_text(encoding='utf-8'))['a']['n'],2)

    def test_站点历史退出刷新未落盘记录(self):
        import 站点历史
        h=object.__new__(站点历史.站点历史)
        h._file=str(self.root/'站点.json');h._io_lock=threading.Lock()
        h._数据={'a':{'任务数':1}};h._上次落盘=0;h._脏=True
        h._atexit_flush();self.assertTrue(Path(h._file).exists())

    def test_JSON控制字符仅在字符串内转义(self):
        import content_decoder as d
        text='{\n "content": "第一行\n第二行",\n "n": 1\n}'
        self.assertEqual(json.loads(d._json_safe(text)),{'content':'第一行\n第二行','n':1})

    def _造蜘蛛(self):
        import 爬虫 as c
        spider=c.NovelSpider('https://example.com')
        self.addCleanup(spider.close)
        spider.get_novel_title=lambda *a:'测试书'
        spider.get_chapter_list=lambda *a:[{'title':f'第{i}章','url':f'https://example.com/{i}'} for i in range(1,4)]
        spider._记录站点历史=lambda *a,**k:None
        spider._记录爬取历史=lambda *a,**k:None
        spider._生成质检汇总报告=lambda *a,**k:{}
        return spider

    def test_停止后未提交章节不推进检查点(self):
        spider=self._造蜘蛛();stop=threading.Event()
        def decide(url):stop.set();return False
        spider._是否应跳过章节=decide
        spider._fetch_chapter_worker=mock.Mock(return_value='正文')
        output=self.root/'book.txt'
        with mock.patch('风控事件.add'),mock.patch('风控事件.flush'),mock.patch('网站清单.记录'),mock.patch.object(spider,'_save_checkpoint') as save:
            spider.run('https://example.com/book',output_file=str(output),output_dir=str(self.root),resume=False,show_progress=False,threads=2,delay=0,stop_event=stop)
        save.assert_not_called();spider._fetch_chapter_worker.assert_not_called()
        self.assertTrue(spider.last_aborted)

    def test_增量追加必须抓取未保存正文(self):
        for threads in (1,2):
            with self.subTest(threads=threads):
                spider=self._造蜘蛛();spider._是否应跳过章节=lambda *a:True
                spider._fetch_with_retry=mock.Mock(return_value='新正文')
                spider._fetch_chapter_worker=mock.Mock(return_value='新正文')
                output=self.root/f'book{threads}.txt';output.write_text('## 第1章\n旧正文\n',encoding='utf-8')
                with mock.patch('风控事件.add'),mock.patch('风控事件.flush'),mock.patch('网站清单.记录'):
                    spider.run('https://example.com/book',output_file=str(output),output_dir=str(self.root),resume=True,show_progress=False,threads=threads,delay=0,incremental=True)
                text=output.read_text(encoding='utf-8')
                self.assertEqual(text.count('## '),3);self.assertEqual(text.count('新正文'),2)

    def test_缺少TXT不按旧检查点跳章(self):
        spider=self._造蜘蛛();spider._fetch_with_retry=mock.Mock(return_value='正文')
        output=self.root/'missing.txt'
        Path(str(output)+'.checkpoint.json').write_text(json.dumps({'catalog_url':'https://example.com/book','completed':2,'total':3}),encoding='utf-8')
        with mock.patch('风控事件.add'),mock.patch('风控事件.flush'),mock.patch('网站清单.记录'):
            spider.run('https://example.com/book',output_file=str(output),output_dir=str(self.root),resume=True,show_progress=False,threads=1,delay=0)
        self.assertEqual(output.read_text(encoding='utf-8').count('## '),3)

    def test_坏检查点结构返回无有效记录(self):
        spider=self._造蜘蛛();out=self.root/'x.txt';ck=Path(str(out)+'.checkpoint.json')
        for value in [[],{'catalog_url':'https://example.com/book','completed':'bad','total':3}]:
            ck.write_text(json.dumps(value),encoding='utf-8')
            self.assertIsNone(spider._load_checkpoint(str(out),'https://example.com/book'))

    def test_去重标题仍尝试配置的备用源(self):
        import 爬虫 as c
        primary='https://example.com/book';alternate='https://backup.example/book'
        pre=mock.Mock();pre.get_novel_title.return_value='书';pre._captcha_manager.config.data={'fallback_sources':{primary:[alternate]}}
        bad=mock.Mock();bad.run.side_effect=RuntimeError('主源失败')
        good=mock.Mock();good.run.return_value='book.txt';good.last_failed=[];good.last_total=3;good.last_aborted=False
        good.last_novel_title='书';good.last_output_file='book.txt';good._captcha_manager=None
        with mock.patch.object(c,'NovelSpider',side_effect=[pre,bad,good]),mock.patch.object(c,'_resolve_unique_title',return_value='书'),mock.patch('书架.记录'):
            self.assertEqual(c.run_crawl(primary,unique_title=True,output_dir=str(self.root)),'book.txt')
        self.assertEqual(good.run.call_args.args[0],alternate)
        good.get_novel_title.assert_not_called();pre.close.assert_called_once()

    def test_空目录任务失败且关闭会话(self):
        import 爬虫 as c
        for mode in ['full','test']:
            pre=mock.Mock();pre._captcha_manager=None;pre.get_chapter_list.return_value=[]
            bad=mock.Mock();bad._captcha_manager=None;bad.run.return_value=None;bad.last_failed=None;bad.last_total=0;bad.last_aborted=False
            with mock.patch.object(c,'NovelSpider',side_effect=[pre,bad]):
                with self.assertRaises(RuntimeError):c.run_crawl('https://example.com',mode=mode,output_dir=str(self.root))
            pre.close.assert_called()

    def test_全部章节失败不报完成(self):
        import 爬虫 as c
        pre=mock.Mock();pre._captcha_manager=None
        bad=mock.Mock();bad._captcha_manager=None;bad.run.return_value='bad.txt';bad.last_failed=[1,2];bad.last_total=2;bad.last_aborted=False
        with mock.patch.object(c,'NovelSpider',side_effect=[pre,bad]):
            with self.assertRaises(RuntimeError):c.run_crawl('https://example.com',output_dir=str(self.root))

    def test_打包新版本保留旧CHANGELOG正文(self):
        import build_exe as build
        p=self.root/'CHANGELOG.md';old='前言\n\n## [2.4.33] - 2026-09-29\n\n历史修复说明\n'
        p.write_text(old,encoding='utf-8')
        with mock.patch.object(build,'ROOT',str(self.root)):
            build._同步CHANGELOG('2.4.34','2026-09-30')
        text=p.read_text(encoding='utf-8');self.assertIn(old[old.index('## '):],text)
        self.assertIn('## [2.4.34] - 2026-09-30',text)

    def test_日志换轮即使新游标更大也重发(self):
        old=tm.TaskInfo('task_1','https://example.com');old.logs.append({'time':'00','msg':'旧'})
        epoch=old.logs.epoch
        new=tm.TaskInfo('task_1','https://example.com');new.logs.extend([{'time':'00','msg':'新1'},{'time':'00','msg':'新2'}])
        self.mgr.tasks['task_1']=new
        res=self.client.get('/api/v1/tasks/task_1/logs',params={'after':1,'epoch':epoch,'k':'testtoken'})
        self.assertEqual(len(res.json()['entries']),2);self.assertTrue(res.json()['截断'])

    def test_SSE流跨轮次重发且500行后增量继续(self):
        import asyncio
        t=tm.TaskInfo('task_1','https://example.com')
        t.logs.extend([{'time':'00','msg':str(i)} for i in range(500)])
        self.mgr.tasks['task_1']=t
        async def verify():
            response=await 服务.任务日志流('task_1',after=499,k='testtoken',authorization=None)
            stream=response.body_iterator
            first=json.loads((await anext(stream)).split('data: ',1)[1])
            self.assertEqual(len(first['entries']),1)
            t.logs.append({'time':'00','msg':'第501行'})
            second=json.loads((await anext(stream)).split('data: ',1)[1])
            self.assertEqual(second['total'],501);self.assertEqual(second['entries'][0]['msg'],'第501行')
            t.logs=tm.TaskLogBuffer();t.logs.extend([{'time':'00','msg':'新'} for _ in range(503)])
            third=json.loads((await anext(stream)).split('data: ',1)[1])
            self.assertTrue(third['截断']);self.assertEqual(len(third['entries']),500)
            await stream.aclose()
        asyncio.run(verify())

    def test_恢复的中断项不虚增耗时(self):
        from gui_components.row_detail import _fmt_elapsed
        t=tm.TaskInfo('task_1','https://example.com',status='interrupted');t.metrics.start_time=1
        self.assertEqual(服务._任务快照(t)['耗时秒'],0)
        self.assertEqual(_fmt_elapsed(t),'—')


if __name__=='__main__': unittest.main()
