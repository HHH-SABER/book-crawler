# -*- coding: utf-8 -*-
"""EPUB 导出器: 把爬虫生成的 txt (## 章节标题 + 正文) 转为 EPUB (ebooklib)

章节格式与爬虫输出一致: 每章以 "## " 开头, 其后为正文 (每行一段)。
转换失败返回 None 并打印原因, 绝不抛出影响主流程。

用法:
    from epub_exporter import txt_to_epub
    epub_path = txt_to_epub('小说.txt', title='小说名', author='')
"""
import os
import re
import html
import uuid

try:
    from ebooklib import epub
    _ebooklib_ok = True
except Exception:
    epub = None
    _ebooklib_ok = False

try:
    import 日志 as _app_log
    _log = _app_log.get('epub')
except Exception:
    import logging
    _log = logging.getLogger('epub')


def is_available() -> bool:
    """ebooklib 是否可用 (未安装时跳过导出)"""
    return _ebooklib_ok


def parse_txt_chapters(txt_path: str, encoding: str = 'utf-8'):
    """把 txt 解析为 [(章节标题, 正文), ...]; 解析失败返回空列表"""
    chapters = []
    try:
        with open(txt_path, 'r', encoding=encoding, errors='replace') as f:
            lines = f.read().splitlines()
    except OSError as e:
        _log.info(f"[epub] 读取失败: {e}")
        return []
    cur_title, cur_lines = None, []
    for ln in lines:
        if ln.startswith('## '):
            if cur_title is not None:
                chapters.append((cur_title, '\n'.join(cur_lines)))
            cur_title = ln[3:].strip()
            cur_lines = []
        else:
            cur_lines.append(ln)
    if cur_title is not None:
        chapters.append((cur_title, '\n'.join(cur_lines)))
    return chapters


def _paragraphs(content: str):
    """正文 -> 段落列表 (每非空行一段, 与爬虫 txt 输出一致)"""
    return [ln.strip() for ln in content.splitlines() if ln.strip()]


def txt_to_epub(txt_path: str, epub_path: str = None, title: str = '',
                author: str = '', encoding: str = 'utf-8'):
    """把 txt 转成 EPUB, 返回生成的 .epub 路径; 失败返回 None

    Args:
        txt_path: 源 txt (爬虫抓取结果)
        epub_path: 输出 epub 路径 (None = 与 txt 同目录同名)
        title: 书名 (None/空 = 取文件名)
        author: 作者 (可选)
    """
    if not _ebooklib_ok:
        _log.info("[epub] ebooklib 未安装, 跳过 EPUB 导出")
        return None
    if not os.path.isfile(txt_path):
        _log.info(f"[epub] 源文件不存在: {txt_path}")
        return None
    chapters = parse_txt_chapters(txt_path, encoding=encoding)
    if not chapters:
        _log.info(f"[epub] 未解析到章节, 跳过: {txt_path}")
        return None
    if epub_path is None:
        epub_path = os.path.splitext(txt_path)[0] + '.epub'
    if not title:
        title = os.path.splitext(os.path.basename(txt_path))[0]
    try:
        book = epub.EpubBook()
        book.set_identifier(str(uuid.uuid4()))
        book.set_title(title)
        book.set_language('zh-CN')
        if author:
            book.add_author(author)
        book.add_metadata('DC', 'description', f'{title} — 由小说爬虫导出')

        # 样式: 中文阅读排版 (段落缩进 / 行距 / 衬线字体)
        css = ('body { font-family: serif, "Songti SC", "SimSun"; line-height: 1.7; }\n'
               'h1 { font-size: 1.35em; text-align: center; margin: 1em 0; }\n'
               'p { text-indent: 2em; margin: 0.35em 0; text-align: justify; }\n')
        style = epub.EpubItem(uid='style', file_name='style/style.css',
                              media_type='text/css', content=css.encode('utf-8'))
        book.add_item(style)

        items = []
        for i, (ctitle, ccontent) in enumerate(chapters, 1):
            item = epub.EpubHtml(title=ctitle, file_name=f'chap_{i}.xhtml', lang='zh-CN')
            paras = ''.join(f'<p>{html.escape(p)}</p>' for p in _paragraphs(ccontent))
            item.content = f'<h1>{html.escape(ctitle)}</h1>\n' + paras
            item.add_item(style)
            book.add_item(item)
            items.append(item)

        book.toc = items
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = ['nav'] + items
        epub.write_epub(epub_path, book)
        size_kb = os.path.getsize(epub_path) / 1024
        _log.info(f"[epub] ✅ 已导出: {epub_path} "
                  f"({len(chapters)} 章, {size_kb:.1f} KB, 书名={title})")
        return epub_path
    except Exception as e:
        _log.info(f"[epub] 导出失败: {e}")
        return None
