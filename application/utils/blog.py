# coding: utf-8
import requests
from requests.exceptions import SSLError
import feedparser
from HTMLParser import HTMLParser
from time import mktime
from datetime import datetime
from datetime import timedelta
from ..models import db, Post


def grab_by_feed(blog):
    new_posts_count = 0

    # 检测博客是否在线
    try:
        res = requests.get(blog.url, verify=False)
        if res.status_code >= 500 or res.status_code == 404:
            blog.offline = True
        else:
            blog.offline = False
    except Exception, e:
        blog.offline = True

    result = feedparser.parse(blog.feed)

    # 检测feed是否失效
    if not result.entries:
        blog.bad_feed = True
    else:
        blog.bad_feed = False

    if not blog.feed_version:
        blog.feed_version = result.version
    if not blog.subtitle and 'subtitle' in result.feed:
        blog.subtitle = remove_html_tag(result.feed.subtitle)

    db.session.add(blog)
    print(blog.title)

    timezone_offset = blog.feed_timezone_offset or 0

    for entry in result.entries:
        url = entry.link

        # 判断该entry是否存在于数据库
        # 若存在url一致的条目，则存在
        # 否则判断标题和published_at
        # 若存在标题一致的post，但entry中不包含published_at，则判断为存在
        # 若存在标题一致的post，而published_at相差不超过一天，则判断为存在
        # 其他情况均判断为不存在
        post = blog.posts.filter(Post.url == url).first()
        if post:
            exist = True
        else:
            post = blog.posts.filter(Post.title == _process_title(entry.title)).first()
            if post:
                published_at = _get_entry_published_at(entry, timezone_offset)
                if not published_at:
                    exist = True
                else:
                    if published_at >= post.published_at:
                        timediff = published_at - post.published_at
                    else:
                        timediff = post.published_at - published_at

                    if timediff <= timedelta(days=1):
                        exist = True
                    else:
                        exist = False
            else:
                exist = False

        # 新博文
        if not exist:
            new_posts_count += 1
            post = Post(url=url)
            _get_info_to_post(post, entry, timezone_offset)
            blog.posts.append(post)
            print(" new - %s" % post.title)
        else:
            # 更新
            updated_at = None
            published_at = None

            if 'updated_parsed' in entry:
                updated_at = _get_time(entry.updated_parsed, timezone_offset)
            if 'published_parsed' in entry:
                published_at = _get_time(entry.published_parsed, timezone_offset)

            if (updated_at and updated_at != post.updated_at) or (
                        published_at and published_at != post.published_at):
                _get_info_to_post(post, entry, timezone_offset)
                print(" update - %s" % post.title)
                db.session.add(post)
    db.session.commit()
    return new_posts_count


def _get_info_to_post(post, entry, timezone_offset):
    """将entry中的信息转存到post中"""
    post.title = _process_title(entry.title)
    post.url = entry.link

    if 'published_parsed' in entry:
        post.published_at = _get_time(entry.published_parsed, timezone_offset)
    if 'updated_parsed' in entry:
        post.updated_at = _get_time(entry.updated_parsed, timezone_offset)

    # 若published_at不存在，则使用updated_at
    if not post.published_at and post.updated_at:
        post.published_at = post.updated_at

    # 若published_at与updated_at均不存在，则使用当前时间作为publishe_at
    if not post.published_at and not post.updated_at:
        post.publishe_at = datetime.now()

    if 'content' in entry:
        if isinstance(entry.content, list):
            post.content = entry.content[0].value
        else:
            post.content = entry.content
    elif 'summary' in entry:
        post.content = entry.summary


def _process_title(title):
    """处理feed.entries中的title"""
    html_parser = HTMLParser()
    title = html_parser.unescape(title)  # 进行2次HTML反转义
    title = html_parser.unescape(title)
    return title.replace('\r', '').replace('\n', '')  # 去除换行符


def _get_entry_published_at(entry, timezone_offset):
    """获取entry中的published_at"""
    if 'published_parsed' in entry:
        return _get_time(entry.published_parsed, timezone_offset)
    elif 'updated_parsed' in entry:
        return _get_time(entry.updated_parsed, timezone_offset)
    else:
        return None


def _get_time(time_struct, timezone_offset=None):
    """获取UTC时间"""
    result_time = datetime.fromtimestamp(mktime(time_struct))
    if timezone_offset:
        result_time -= timedelta(hours=timezone_offset)
    return result_time


# See: http://stackoverflow.com/questions/753052/strip-html-from-strings-in-python
class MLStripper(HTMLParser):
    def __init__(self):
        self.reset()
        self.fed = []

    def handle_data(self, d):
        self.fed.append(d)

    def get_data(self):
        return ''.join(self.fed)


def remove_html_tag(html_string):
    """从字符串中去除HTML元素（但是好像会过度去除？比如HTML转义字符？）"""
    s = MLStripper()
    s.feed(html_string)
    return s.get_data()
