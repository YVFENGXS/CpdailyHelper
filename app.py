# -*- coding: utf-8 -*-
"""
今日校园签到助手（独立版）

功能：
  1. 图形界面填写：学校、学号、密码、设备号、手机型号、系统版本、签到地址、经纬度
  2. 自动解析学校入口 -> 登录 -> 查询未签到任务 -> 判断定位是否在范围内 -> 给出“能否签到”结论
  3. 一键立即签到（普通签到 / 查寝）
  4. 自定义星期方案（每天 / 工作日 / 周一至周四 / 自定义）创建独立计划任务

隔离说明：
  本程序只读取自己的配置 %APPDATA%\\CpdailyHelper\\config.json，
  计划任务名称为 CpdailyHelperAutoSign，不会读写 auto-sign 目录下的配置，
  也不会修改或删除现有的 TodaySchoolAutoSign 计划任务。
"""
import os
import sys
import json
import math
import time
import uuid
import base64
import socket
import shutil
import tempfile
import subprocess
import threading
import queue
import traceback
import argparse
from datetime import datetime
from urllib.parse import urlparse

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from pyDes import des, CBC, PAD_PKCS5

APP_TITLE = '今日校园签到助手'
APP_ID = 'CpdailyHelper'
TASK_NAME = 'CpdailyHelperAutoSign'
LOGIN_PORT = 8081

# ---------- 主题：深空绿（深色）/ 米白 + 浅葱绿（浅色） ----------
FONT_UI = 'Microsoft YaHei UI'
FONT_MONO = 'Consolas'

THEMES = {
    'dark': {
        'bg': '#0B0F0E',        # 页面底色
        'sidebar': '#070A09',   # 左侧导航栏
        'nav_active': '#151B19',
        'nav_hover': '#0D1210',
        'statusbar': '#090D0C',
        'card': '#141A18',      # 卡片
        'card_alt': '#0E1412',  # 卡片内的输入区 / 文本区
        'field': '#0F1513',     # 输入框
        'field_hover': '#18211E',
        'line': '#26312D',      # 卡片描边
        'line_soft': '#1A2320',
        'text': '#F1F6F4',      # 主文字
        'text_dim': '#B6C5C0',  # 表单标签
        'muted': '#7C8E88',     # 次要文字
        'faint': '#55655F',     # 最弱的文字
        'cyan': '#3BE8C1',      # 荧光青绿（高亮 / 主按钮）
        'cyan_dim': '#1E9A85',
        'purple': '#B49BFF',
        'amber': '#F2C879',
        'red': '#FF7B86',
        'select_bg': '#1B4C40',
        'select_fg': '#FFFFFF',
        'primary_fg': '#04241C',     # 主按钮文字
        'primary_hover': '#6BF4D6',
        'primary_press': '#1E9A85',
        'ghost_press': '#0A0F0E',
        'purple_bg': '#191528',
        'purple_line': '#352C55',
        'purple_hover': '#221C37',
        'purple_press': '#151124',
        'danger_hover': '#221518',
        'danger_press': '#171012',
        'icon_tile': '#1C2A26',
        'log_text': '#9FF5DC',
    },
    'light': {
        'bg': '#F5F1E8',        # 米白
        'sidebar': '#EFEADF',
        'nav_active': '#E7F0E6',
        'nav_hover': '#F2EDE2',
        'statusbar': '#EFEADF',
        'card': '#FFFCF4',
        'card_alt': '#F8F4EA',
        'field': '#FBF8F0',
        'field_hover': '#F1F7EC',
        'line': '#DDD6C5',
        'line_soft': '#E9E3D5',
        'text': '#1F2A22',
        'text_dim': '#414D43',
        'muted': '#6C7B6E',
        'faint': '#9AA69B',
        'cyan': '#A9DCBE',      # 浅葱绿（主按钮填充）
        'cyan_dim': '#4F9B77',  # 深一档的葱绿（图标 / 聚焦描边）
        'purple': '#7C6BAE',
        'amber': '#B5872F',
        'red': '#C05A62',
        'select_bg': '#CDEBD9',
        'select_fg': '#12281C',
        'primary_fg': '#123522',
        'primary_hover': '#BEE9CF',
        'primary_press': '#8FCCA9',
        'ghost_press': '#EDE7D8',
        'purple_bg': '#F2EEF9',
        'purple_line': '#DCD3EE',
        'purple_hover': '#EAE3F6',
        'purple_press': '#E2D9F0',
        'danger_hover': '#F8EDEA',
        'danger_press': '#F1E1DD',
        'icon_tile': '#E4F0E5',
        'log_text': '#2F6B4E',
    },
}

THEME = dict(THEMES['dark'])


def apply_theme(name):
    """切换到指定主题（必须在创建任何窗口控件之前调用）。"""
    THEME.clear()
    THEME.update(THEMES.get(name) or THEMES['dark'])


# 主题切换后用于重建窗口
_RESTART = {'pending': False}


def enable_dpi_awareness():
    """让 Windows 不再对窗口做位图拉伸，字体才会真正清晰。"""
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # system DPI aware
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def ui_scale():
    """按系统 DPI 缩放像素尺寸，使 125% / 150% 下比例不变。"""
    try:
        import ctypes
        dpi = int(ctypes.windll.user32.GetDpiForSystem())
        if dpi > 0:
            return max(1.0, dpi / 96.0)
    except Exception:
        pass
    return 1.0


_SCALE = None


def S(value):
    """按 DPI 换算像素；首次调用时读取，确保已开启 DPI 感知。"""
    global _SCALE
    if _SCALE is None:
        _SCALE = ui_scale()
    return int(round(value * _SCALE))


ICON_FONT = 'Segoe MDL2 Assets'

# ---------- 协议常量（与 auto-sign/index.py 保持一致） ----------
APPS = {
    'sign': {
        'name': '签到',
        'list': '/wec-counselor-sign-apps/stu/sign/getStuSignInfosInOneDay',
        'detail': '/wec-counselor-sign-apps/stu/sign/detailSignTaskInst',
        'submit': '/wec-counselor-sign-apps/stu/sign/completeSignIn',
        'sts': '/wec-counselor-sign-apps/stu/sign/getStsAccess',
        'preview': '/wec-counselor-sign-apps/stu/sign/previewAttachment',
    },
    'attendance': {
        'name': '查寝',
        'list': '/wec-counselor-attendance-apps/student/attendance/getStuAttendacesInOneDay',
        'detail': '/wec-counselor-attendance-apps/student/attendance/detailSignInstance',
        'submit': '/wec-counselor-attendance-apps/student/attendance/submitSign',
        'sts': '/wec-counselor-attendance-apps/student/attendance/getStsAccess',
        'preview': '/wec-counselor-attendance-apps/student/attendance/previewAttachment',
    },
}

FKEY_CAT = 'hru89rwr87Nthifa'
APP_VERSION = '9.9.24'
DEFAULT_TENANT_ID = 'dbbbb15d-e6ed-423b-8631-3b899640d1f8'
DEFAULT_BUILD_ID = 'VLFCNXM'

BASE_HEADERS = {
    'Accept': 'application/json, text/plain, */*',
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/83.0.4103.97 Safari/537.36'),
    'content-type': 'application/json',
    'Accept-Encoding': 'gzip,deflate',
    'Accept-Language': 'zh-CN,en-US;q=0.8',
}

WEEK_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
WEEK_CODES = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']
PRESETS = [
    ('每天', [0, 1, 2, 3, 4, 5, 6]),
    ('工作日（周一至周五）', [0, 1, 2, 3, 4]),
    ('周一至周六', [0, 1, 2, 3, 4, 5]),
    ('周一至周四', [0, 1, 2, 3]),
    ('仅周末（周六、周日）', [5, 6]),
]

DEFAULT_CONFIG = {
    'school': '',
    'username': '',
    'password': '',
    'deviceId': '',
    'deviceModel': '',
    'systemVersion': '15',
    'buildId': DEFAULT_BUILD_ID,
    'address': '',
    'lon': '',
    'lat': '',
    'abnormalReason': '在校',
    'photo': '',
    'host': '',
    'idsUrl': '',
    'tenantId': '',
    'resolvedSchool': '',
    'javaPath': '',
    'theme': 'dark',
    'schedule': {'days': [0, 1, 2, 3, 4], 'time': '22:03'},
}


# ================= 路径与配置 =================

def exe_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def data_dir():
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    path = os.path.join(base, APP_ID)
    os.makedirs(path, exist_ok=True)
    return path


def log_dir():
    path = os.path.join(data_dir(), 'logs')
    os.makedirs(path, exist_ok=True)
    return path


def config_path():
    return os.path.join(data_dir(), 'config.json')


def resource_path(name):
    """打包后从 _MEIPASS 取，开发时从 resources 目录取。"""
    candidates = []
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        candidates.append(os.path.join(meipass, name))
        candidates.append(os.path.join(meipass, 'resources', name))
    base = exe_dir()
    candidates.append(os.path.join(base, 'resources', name))
    candidates.append(os.path.join(base, name))
    for path in candidates:
        if os.path.exists(path):
            return path
    raise FileNotFoundError('缺少内置资源：%s' % name)


def ensure_resource_copy(name):
    """把随包资源复制到数据目录，避免 onefile 临时目录被清理。"""
    dst = os.path.join(data_dir(), name)
    src = resource_path(name)
    if (not os.path.exists(dst)) or os.path.getsize(dst) != os.path.getsize(src):
        shutil.copy2(src, dst)
    return dst


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    path = config_path()
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                for key, value in saved.items():
                    if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                        cfg[key].update(value)
                    else:
                        cfg[key] = value
        except Exception:
            pass
    return cfg


def save_config(cfg):
    path = config_path()
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


class Logger:
    """同时写日志文件和推送到界面。"""

    def __init__(self, name='run', sink=None):
        self.sink = sink
        self.path = os.path.join(log_dir(), '%s-%s.log' % (name, datetime.now().strftime('%Y%m%d')))
        self.lock = threading.Lock()

    def __call__(self, message):
        line = '%s %s' % (now_str(), message)
        with self.lock:
            try:
                with open(self.path, 'a', encoding='utf-8') as f:
                    f.write(line + '\n')
            except OSError:
                pass
        if self.sink:
            try:
                self.sink(line)
            except Exception:
                pass


# ================= 校验 =================

REQUIRED_FIELDS = [
    ('school', '学校名称'),
    ('username', '学号'),
    ('password', '密码'),
    ('deviceId', '设备号'),
    ('deviceModel', '手机型号'),
    ('systemVersion', '系统版本'),
    ('address', '签到地址'),
    ('lon', '经度'),
    ('lat', '纬度'),
]


def validate_config(cfg):
    missing = [label for key, label in REQUIRED_FIELDS if not str(cfg.get(key, '')).strip()]
    if missing:
        raise ValueError('请先填写：' + '、'.join(missing))
    try:
        lon = float(cfg['lon'])
        lat = float(cfg['lat'])
    except (TypeError, ValueError):
        raise ValueError('经度/纬度必须是数字，例如 116.397428 / 39.909230')
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError('经度/纬度超出合法范围，请检查是否填反了')
    if len(str(cfg['deviceId']).strip()) < 16:
        raise ValueError('设备号格式不正确（一般是 36 位 UUID），请按提示从手机中获取')
    return True


# ================= 学校解析 =================

def resolve_school(cfg, log):
    school = str(cfg.get('school', '')).strip()
    if not school:
        raise ValueError('请填写学校全称')

    log('正在查询「%s」的今日校园入口……' % school)
    url = 'https://mobile.campushoy.com/v6/config/guest/tenant/list'
    data = requests.get(url, timeout=20, verify=False).json().get('data') or []
    matched = [x for x in data if x.get('name') == school]
    if not matched:
        matched = [x for x in data if school in (x.get('name') or '')]
    if not matched:
        raise RuntimeError('没有找到「%s」，请填写学校全称（以今日校园中的名称为准）' % school)

    tenant = matched[0]
    if tenant.get('joinType') == 'NONE':
        raise RuntimeError('「%s」未开通今日校园' % tenant.get('name'))

    tenant_id = tenant['id']
    info_url = 'https://mobile.campushoy.com/v6/config/guest/tenant/info'
    info = (requests.get(info_url, params={'ids': tenant_id}, timeout=20, verify=False)
            .json().get('data') or [])
    if not info:
        raise RuntimeError('获取学校入口信息失败，请稍后重试')
    info = info[0]

    host = ''
    for key in ('ampUrl2', 'ampUrl'):
        amp = info.get(key) or ''
        if 'campusphere' in amp or 'cpdaily' in amp:
            host = urlparse(amp).netloc
            break
    if not host:
        raise RuntimeError('该校暂不支持自动解析入口，请在“高级”中手动填写 host')

    ids_url = info.get('idsUrl') or ('https://' + host + '/iap')
    cfg['host'] = host
    cfg['idsUrl'] = ids_url
    cfg['tenantId'] = tenant_id
    cfg['resolvedSchool'] = school
    log('已匹配：%s（租户 %s）' % (tenant.get('name'), tenant_id))
    log('登录入口：%s' % ids_url)
    return host, ids_url, tenant_id


# ================= 登录组件 =================

def port_open(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            return True
    except OSError:
        return False


def find_java(cfg):
    explicit = str(cfg.get('javaPath') or '').strip().strip('"')
    if explicit and os.path.exists(explicit):
        return explicit
    # 优先使用随环境附带的 JDK 11（PATH 里可能是 Java 8，无法运行登录组件）
    base = exe_dir()
    for _ in range(3):
        candidate = os.path.join(base, '.runtime', 'jdk-11.0.2', 'bin', 'java.exe')
        if os.path.exists(candidate):
            return candidate
        base = os.path.dirname(base)
    java_home = os.environ.get('JAVA_HOME')
    if java_home:
        candidate = os.path.join(java_home, 'bin', 'java.exe')
        if os.path.exists(candidate):
            return candidate
    found = shutil.which('java')
    if found:
        return found
    return None


def ensure_login_server(cfg, log):
    if port_open(LOGIN_PORT):
        log('登录组件已在 %d 端口运行，直接复用' % LOGIN_PORT)
        return True
    jar = ensure_resource_copy('login-api.jar')
    java = find_java(cfg)
    if not java:
        raise RuntimeError('未找到 Java 运行环境。请安装 JDK/JRE 11 后重试，'
                           '或在“高级”中填写 java.exe 的完整路径。')
    log('正在启动登录组件（%s）……' % java)
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    subprocess.Popen(
        [java, '-jar', jar, '--server.port=%d' % LOGIN_PORT],
        cwd=data_dir(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=flags)
    for i in range(60):
        time.sleep(1)
        if port_open(LOGIN_PORT):
            log('登录组件已就绪（用时 %d 秒）' % (i + 1))
            return True
    raise RuntimeError('登录组件启动超时，请确认 Java 可用后重试')


def login(cfg, host, ids_url, log):
    login_url = ids_url.rstrip('/') + '/login?service=https%3A%2F%2F' + host + '%2Fportal%2Flogin'
    params = {
        'login_url': login_url,
        'needcaptcha_url': '',
        'captcha_url': '',
        'username': str(cfg['username']).strip(),
        'password': str(cfg['password']),
    }
    api = 'http://127.0.0.1:%d/wisedu-unified-login-api-v1.0/api/login' % LOGIN_PORT
    log('正在登录（学号 %s）……' % params['username'])
    try:
        res = requests.post(api, data=params, timeout=90, verify=False)
        payload = res.json()
    except Exception as e:
        raise RuntimeError('登录服务无响应：%s' % e)

    cookie_str = str(payload.get('cookies'))
    if cookie_str in ('None', '', 'null'):
        raise RuntimeError('登录失败：%s' % json.dumps(payload, ensure_ascii=False)[:400])

    cookies = {}
    for line in cookie_str.split(';'):
        if '=' not in line:
            continue
        name, value = line.strip().split('=', 1)
        cookies[name] = value
    session = requests.session()
    session.cookies = requests.utils.cookiejar_from_dict(cookies, cookiejar=None, overwrite=True)
    log('登录成功，已获取会话')
    return session


# ================= 任务查询 / 表单 / 提交 =================

def list_unsigned_tasks(session, host, log):
    found = []
    for key, app in APPS.items():
        try:
            res = session.post(
                url='https://%s%s' % (host, app['list']),
                headers=BASE_HEADERS, data=json.dumps({}), timeout=30, verify=False)
            datas = res.json().get('datas')
        except Exception as e:
            log('查询%s任务失败：%s' % (app['name'], e))
            continue
        if not isinstance(datas, dict):
            continue
        for task in datas.get('unSignedTasks') or []:
            found.append((key, task))
    return found


def get_task_detail(session, host, app, task):
    params = {'signInstanceWid': task['signInstanceWid'], 'signWid': task.get('signWid')}
    res = session.post(
        url='https://%s%s' % (host, app['detail']),
        headers=BASE_HEADERS, data=json.dumps(params), timeout=30, verify=False)
    return res.json()['datas']


def geo_distance(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(math.radians, [float(lon1), float(lat1), float(lon2), float(lat2)])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * math.asin(math.sqrt(a)) * 6371393


def pick_extra_item(field):
    """附加题自动选择：优先常见正向选项，否则取第一项。"""
    items = field.get('extraFieldItems') or []
    if not items:
        return None
    keywords = ('在校', '是', '正常', '已返校', '住校', '符合', '已归寝')
    for keyword in keywords:
        for item in items:
            if keyword in str(item.get('content') or ''):
                return item
    return items[0]


def analyze_task(session, host, app, task, cfg, log):
    detail = get_task_detail(session, host, app, task)
    lon = float(cfg['lon'])
    lat = float(cfg['lat'])

    places = detail.get('signPlaceSelected') or []
    in_range = None
    place_info = []
    if places:
        in_range = False
        for place in places:
            try:
                distance = geo_distance(lon, lat, place['longitude'], place['latitude'])
                radius = float(place.get('radius') or 0)
                place_info.append((place.get('address') or place.get('placeName') or '签到点', distance, radius))
                if distance < radius:
                    in_range = True
            except Exception:
                continue
    else:
        in_range = detail.get('isMalposition', 0) == 0

    extras = []
    if detail.get('isNeedExtra') == 1:
        for field in detail.get('extraField') or []:
            item = pick_extra_item(field)
            if item:
                extras.append((field.get('title') or '附加项', item.get('content')))

    return {
        'app': app,
        'task': task,
        'detail': detail,
        'in_range': in_range,
        'places': place_info,
        'extras': extras,
        'need_photo': detail.get('isPhoto') == 1,
    }


def upload_picture(session, host, app, image_path, log):
    try:
        import oss2
    except ImportError:
        raise RuntimeError('缺少 oss2 组件，无法上传照片')
    url = 'https://%s%s' % (host, app['sts'])
    res = session.post(url=url, headers={'content-type': 'application/json'},
                       data=json.dumps({}), timeout=30, verify=False)
    datas = res.json().get('datas') or {}
    bucket = oss2.Bucket(
        oss2.Auth(access_key_id=datas['accessKeyId'], access_key_secret=datas['accessKeySecret']),
        datas['endPoint'], datas['bucket'])
    with open(image_path, 'rb') as f:
        data = f.read()
    bucket.put_object(key=datas['fileName'], headers={'x-oss-security-token': datas['securityToken']},
                      data=data)
    log('照片已上传：%s' % os.path.basename(image_path))
    return datas['fileName']


def get_picture_url(session, host, app, file_name):
    url = 'https://%s%s' % (host, app['preview'])
    res = session.post(url=url, headers={'content-type': 'application/json'},
                       data=json.dumps({'ossKey': file_name}), timeout=30, verify=False)
    return res.json().get('datas')


def des_encrypt(text, key='ST83=@XV'):
    cipher = des(key, CBC, b'\x01\x02\x03\x04\x05\x06\x07\x08', pad=None, padmode=PAD_PKCS5)
    return base64.b64encode(cipher.encrypt(text)).decode()


def aes_encrypt(text, key=FKEY_CAT):
    iv = b'\x01\x02\x03\x04\x05\x06\x07\x08\t\x01\x02\x03\x04\x05\x06\x07'
    cipher = AES.new(key.encode('utf-8'), AES.MODE_CBC, iv)
    return base64.b64encode(cipher.encrypt(pad(text.encode('utf-8'), AES.block_size))).decode()


def crypto_selftest(log):
    text = '{"test":"今日校园"}'
    encrypted = aes_encrypt(text)
    iv = b'\x01\x02\x03\x04\x05\x06\x07\x08\t\x01\x02\x03\x04\x05\x06\x07'
    cipher = AES.new(FKEY_CAT.encode('utf-8'), AES.MODE_CBC, iv)
    decrypted = unpad(cipher.decrypt(base64.b64decode(encrypted)), AES.block_size).decode('utf-8')
    if decrypted != text:
        raise RuntimeError('加密自检失败')
    des_encrypt('{"deviceId":"selftest"}')
    log('加密自检通过（AES-128-CBC / DES）')


def build_form(session, host, app, analyzed, cfg, log, do_upload):
    detail = analyzed['detail']
    form = {}

    if analyzed['need_photo']:
        if do_upload:
            photo = str(cfg.get('photo') or '').strip()
            if not photo or not os.path.exists(photo):
                photo = ensure_resource_copy('default.png')
            file_name = upload_picture(session, host, app, photo, log)
            form['signPhotoUrl'] = get_picture_url(session, host, app, file_name) or ''
        else:
            form['signPhotoUrl'] = '<上传照片后填写>'
    else:
        form['signPhotoUrl'] = ''

    if analyzed['extras']:
        items = []
        for field in detail.get('extraField') or []:
            chosen = pick_extra_item(field)
            if not chosen:
                continue
            value = chosen.get('content')
            if chosen.get('isOtherItems') == 1:
                value = chosen.get('content') or '无'
            items.append({'extraFieldItemValue': value, 'extraFieldItemWid': chosen['wid']})
            log('附加题「%s」自动选择：%s' % (field.get('title') or '附加项', value))
        form['extraFieldItems'] = items

    form['signInstanceWid'] = detail.get('signInstanceWid') or analyzed['task'].get('signInstanceWid')
    form['longitude'] = float(cfg['lon'])
    form['latitude'] = float(cfg['lat'])
    form['isMalposition'] = 0 if analyzed['in_range'] else 1
    form['abnormalReason'] = str(cfg.get('abnormalReason') or '在校')
    form['position'] = str(cfg.get('address') or '')
    if app['name'] == '查寝':
        form['qrUuid'] = ''
        form['uaIsCpadaily'] = True
    return form


def user_agent(cfg):
    model = str(cfg.get('deviceModel') or '').strip()
    version = str(cfg.get('systemVersion') or '').strip()
    build = str(cfg.get('buildId') or DEFAULT_BUILD_ID).strip()
    return ('Mozilla/5.0 (Linux; Android %s; %s Build/%s; wv) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.230 Mobile Safari/537.36 '
            'okhttp/4.12.0 cpdaily/%s wisedu/%s' % (version, model, build, APP_VERSION, APP_VERSION))


def submit_form(session, host, app, form, cfg, log):
    device_id = str(cfg['deviceId']).strip()
    tenant_id = str(cfg.get('tenantId') or DEFAULT_TENANT_ID).strip()
    device_info = {
        'systemName': 'android',
        'systemVersion': str(cfg.get('systemVersion') or '15').strip(),
        'model': str(cfg.get('deviceModel') or '').strip(),
        'deviceId': device_id,
        'appVersion': APP_VERSION,
        'lon': float(cfg['lon']),
        'lat': float(cfg['lat']),
        'userId': str(cfg['username']).strip(),
    }
    device_json = json.dumps(device_info, ensure_ascii=False)
    headers = {
        'tenantId': tenant_id,
        'User-Agent': user_agent(cfg),
        'CpdailyStandAlone': '0',
        'extension': '1',
        'sign': '1',
        'CpdailyClientType': 'CPDAILY',
        'clientType': 'cpdaily_student',
        'deviceType': '1',
        'Content-Type': 'application/json; charset=utf-8',
        'Host': host,
        'Connection': 'Keep-Alive',
        'Cpdaily-Extension': des_encrypt(device_json, key='b3L26XNL'),
        'CpdailyInfo': des_encrypt(device_json, key='ST83=@XV'),
    }
    token = session.cookies.get('sessionToken') or ''
    if token:
        encrypted_token = des_encrypt(token, key='XCE927==')
        headers['sessionTokenKey'] = encrypted_token
        headers['SessionToken'] = encrypted_token

    payload = dict(device_info)
    payload['bodyString'] = aes_encrypt(json.dumps(form, ensure_ascii=False))
    payload['version'] = 'first_v4'
    payload['calVersion'] = 'firstv'

    res = session.post(url='https://%s%s' % (host, app['submit']), headers=headers,
                       data=json.dumps(payload, ensure_ascii=False), timeout=45, verify=False)
    return res.json()


def explain_failure(result):
    code = str(result.get('code') or '')
    message = str(result.get('message') or '')
    if code == '3' or '更换手机' in message or '授权' in message:
        return ('设备未授权：请先用这台手机打开今日校园正常签到一次，'
                '或联系辅导员在「辅导猫 → 手机授权管理」中授权该设备；'
                '同时确认设备号、型号填写的是这台手机。')
    if '版本过低' in message:
        return '服务端拒绝了本次加密请求（提示版本过低），请确认程序为最新版本。'
    if code == '4':
        return '服务端无法解析提交内容，请检查账号与设备信息是否匹配。'
    return message or ('提交失败（code=%s）' % code)


# ================= 检测 / 签到主流程 =================

def prepare(cfg, log):
    validate_config(cfg)
    school = str(cfg.get('school') or '').strip()
    host = str(cfg.get('host') or '').strip()
    ids_url = str(cfg.get('idsUrl') or '').strip()
    tenant_id = str(cfg.get('tenantId') or '').strip()
    if (not host) or (not ids_url) or (not tenant_id) or str(cfg.get('resolvedSchool') or '') != school:
        host, ids_url, tenant_id = resolve_school(cfg, log)

    ensure_login_server(cfg, log)
    session = login(cfg, host, ids_url, log)
    crypto_selftest(log)
    tasks = list_unsigned_tasks(session, host, log)
    return {'session': session, 'host': host, 'ids_url': ids_url, 'tasks': tasks}


def describe_analysis(analyzed, index):
    lines = []
    task = analyzed['task']
    app = analyzed['app']
    lines.append('[%d] 【%s】%s' % (index, app['name'], task.get('taskName') or '未命名任务'))
    begin = task.get('singleTaskBeginTime') or ''
    end = task.get('singleTaskEndTime') or ''
    if begin or end:
        lines.append('    时间：%s ~ %s' % (begin, end))
    if analyzed['places']:
        for name, distance, radius in analyzed['places']:
            lines.append('    定位：距「%s」约 %.0f 米（允许 %d 米）' % (name, distance, radius))
        lines.append('    判定：%s' % ('在签到范围内，可正常提交' if analyzed['in_range']
                                    else '超出签到范围，提交时会被标记为异常定位'))
    else:
        lines.append('    定位：该任务未限制签到地点')
    if analyzed['need_photo']:
        lines.append('    拍照：任务要求拍照，将自动上传照片')
    if analyzed['extras']:
        lines.append('    附加题：%s' % '，'.join('%s=%s' % (k, v) for k, v in analyzed['extras']))
    return '\n'.join(lines)


def run_check(cfg, log):
    ctx = prepare(cfg, log)
    host = ctx['host']
    tasks = ctx['tasks']
    if not tasks:
        return ('登录与加密均正常。\n当前没有未签到的任务（可能今天已签到，或任务还没发布）。\n'
                '等任务发布后再点“立即签到”，或直接依赖自动签到。')

    lines = ['登录成功，共发现 %d 个未签到任务。' % len(tasks), '']
    analyses = []
    for i, (key, task) in enumerate(tasks, 1):
        analyzed = analyze_task(ctx['session'], host, APPS[key], task, cfg, log)
        analyses.append(analyzed)
        lines.append(describe_analysis(analyzed, i))
        lines.append('')
    can = all(a['in_range'] for a in analyses)
    if can:
        lines.append('结论：可以签到。点击“立即签到”即可提交。')
    else:
        lines.append('结论：定位超出范围，仍可提交，但会被标记为异常定位，存在被学校核查的风险。')
    return '\n'.join(lines)


def run_sign(cfg, log):
    ctx = prepare(cfg, log)
    host = ctx['host']
    tasks = ctx['tasks']
    if not tasks:
        log('当前没有未签到任务')
        return '当前没有未签到任务，无需提交。'

    results = []
    for key, task in tasks:
        app = APPS[key]
        log('处理【%s】%s' % (app['name'], task.get('taskName')))
        analyzed = analyze_task(ctx['session'], host, app, task, cfg, log)
        log('定位判定：%s' % ('在范围内' if analyzed['in_range'] else '超出范围'))
        form = build_form(ctx['session'], host, app, analyzed, cfg, log, do_upload=True)
        try:
            result = submit_form(ctx['session'], host, app, form, cfg, log)
        except Exception as e:
            log('提交异常：%s' % e)
            results.append((app['name'], False, '提交异常：%s' % e))
            continue
        message = str(result.get('message') or '')
        log('提交%s返回：%s' % (app['name'], json.dumps(result, ensure_ascii=False)))
        if message == 'SUCCESS':
            results.append((app['name'], True, '签到成功'))
        else:
            results.append((app['name'], False, explain_failure(result)))

    lines = []
    for name, ok, message in results:
        lines.append('%s：%s（%s）' % (name, '成功' if ok else '失败', message))
    success = sum(1 for _, ok, _ in results if ok)
    lines.append('')
    lines.append('共 %d 个任务，成功 %d 个。' % (len(results), success))
    return '\n'.join(lines)


# ================= 计划任务 =================

def schedule_command():
    if getattr(sys, 'frozen', False):
        return '"%s" --auto' % os.path.abspath(sys.executable)
    python = sys.executable
    script = os.path.abspath(__file__)
    return '"%s" "%s" --auto' % (python, script)


def _run_schtasks(args):
    proc = subprocess.run(['schtasks'] + args, capture_output=True)
    out = (proc.stdout or b'').decode('gbk', errors='replace')
    err = (proc.stderr or b'').decode('gbk', errors='replace')
    return proc.returncode, (out + err).strip()


def create_schedule(days, hhmm):
    if not days:
        raise ValueError('请至少选择一天')
    try:
        hour, minute = [int(x) for x in hhmm.split(':')]
        assert 0 <= hour <= 23 and 0 <= minute <= 59
    except Exception:
        raise ValueError('时间格式应为 HH:MM，例如 22:03')

    days = sorted(set(days))
    args = ['/Create', '/F', '/TN', TASK_NAME, '/TR', schedule_command()]
    if len(days) == 7:
        args += ['/SC', 'DAILY', '/ST', hhmm]
    else:
        args += ['/SC', 'WEEKLY', '/D', ','.join(WEEK_CODES[d] for d in days), '/ST', hhmm]
    code, output = _run_schtasks(args)
    if code != 0:
        raise RuntimeError('创建计划任务失败：%s' % (output or '未知错误'))
    return query_schedule()


def delete_schedule():
    code, output = _run_schtasks(['/Delete', '/F', '/TN', TASK_NAME])
    if code != 0 and '找不到' not in output and 'cannot find' not in output.lower():
        raise RuntimeError('删除计划任务失败：%s' % (output or '未知错误'))
    return '计划任务已删除'


def query_schedule():
    code, output = _run_schtasks(['/Query', '/TN', TASK_NAME, '/FO', 'LIST'])
    if code != 0:
        return '未创建自动签到计划任务'
    wanted = ('TaskName', 'Status', 'Next Run Time', 'Task To Run', 'Start In', 'Scheduled Task State')
    lines = [line.strip() for line in output.splitlines()
             if any(line.strip().startswith(key) for key in wanted)]
    return '\n'.join(lines) if lines else '计划任务已存在'


# ================= 内置地图选点（高德底图） =================

PICKER_HTML = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>地图选点</title>
<link rel="stylesheet" href="__CSS__">
<style>
  html, body, #map { height: 100%; margin: 0; background: #04120D;
                     font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif; }
  .panel { position: absolute; top: 14px; left: 14px; z-index: 1000; width: 320px;
           background: #081C15; border: 1px solid #174A38; border-radius: 12px; padding: 14px 16px;
           box-shadow: 0 10px 32px rgba(0,0,0,.55), 0 0 0 1px rgba(43,245,200,.08); }
  .title { font-size: 15px; font-weight: 600; color: #2BF5C8; letter-spacing: .4px; }
  .hint { font-size: 12px; color: #6E9C8B; line-height: 1.6; margin-top: 4px; }
  .coord { margin: 10px 0 6px; padding: 8px 10px; background: #0C2A20;
           border: 1px solid #174A38; border-radius: 8px;
           font-family: Consolas, monospace; font-size: 15px; color: #2BF5C8; }
  .row { display: flex; gap: 6px; margin-top: 6px; }
  .row input { flex: 1; min-width: 0; padding: 6px 8px; background: #0C2A20;
               border: 1px solid #174A38; border-radius: 6px; font-size: 12px;
               color: #D6F5EA; outline: none; }
  .row input::placeholder { color: #4E7568; }
  .row input:focus { border-color: #2BF5C8; }
  .btns { display: flex; gap: 8px; margin-top: 12px; }
  button { border: 1px solid #174A38; background: #0C2A20; color: #D6F5EA; font-size: 13px;
           padding: 8px 14px; border-radius: 8px; cursor: pointer; }
  button:hover { background: #123A2C; border-color: #2BF5C8; color: #2BF5C8; }
  button.primary { background: #2BF5C8; border-color: #2BF5C8; color: #04120D;
                   font-weight: 600; flex: 1; }
  button.primary:hover { background: #5BFBDA; border-color: #5BFBDA; color: #04120D; }
  #msg { min-height: 16px; }
  .pin-dot { width: 18px; height: 18px; border-radius: 50%; background: #2BF5C8;
             border: 3px solid #04120D; box-shadow: 0 0 0 2px #A97CFF, 0 0 14px rgba(43,245,200,.9); }
  .footer { position: absolute; right: 14px; bottom: 12px; z-index: 1000; color: #8FD8C4;
            font-size: 11px; background: rgba(8,28,21,.88); border: 1px solid #174A38;
            padding: 3px 8px; border-radius: 6px; }
  .leaflet-control-zoom a { background: #081C15 !important; color: #2BF5C8 !important;
                            border-color: #174A38 !important; }
  .leaflet-control-zoom a:hover { background: #123A2C !important; }
  .leaflet-control-scale-line { background: rgba(8,28,21,.85) !important; color: #8FD8C4 !important;
                                border-color: #174A38 !important; }
</style>
</head>
<body>
<div id="map"></div>
<div class="panel">
  <div class="title">地图选点（高德 GCJ-02）</div>
  <div class="hint">在地图上单击你的签到位置，可拖动红点微调。坐标精度 6 位小数，可直接用于签到。</div>
  <div class="coord"><span id="lng">--</span>, <span id="lat">--</span></div>
  <div class="row">
    <input id="jump" placeholder="粘贴坐标跳转：经度,纬度">
    <button onclick="jump()">跳转</button>
  </div>
  <div class="btns">
    <button class="primary" onclick="useHere()">使用此坐标</button>
    <button onclick="cancel()">取消</button>
  </div>
  <div class="hint" id="msg">正在加载地图……</div>
</div>
<div class="footer">底图 © 高德地图 · 坐标为 GCJ-02</div>
<script src="__JS__"></script>
<script>
  var map = L.map('map', { zoomControl: true, attributionControl: false });
  map.setView([__LAT__, __LON__], __ZOOM__);
  L.tileLayer('https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}', {
    subdomains: '1234', minZoom: 3, maxZoom: 19
  }).addTo(map);
  L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(map);

  var marker = null;
  var ready = false;

  function show(lng, lat) {
    document.getElementById('lng').innerText = lng.toFixed(6);
    document.getElementById('lat').innerText = lat.toFixed(6);
  }

  function setPoint(lng, lat, pan) {
    if (marker) {
      marker.setLatLng([lat, lng]);
    } else {
      marker = L.marker([lat, lng], {
        draggable: true,
        icon: L.divIcon({ className: 'pin', html: '<div class="pin-dot"></div>',
                          iconSize: [18, 18], iconAnchor: [9, 9] })
      }).addTo(map);
      marker.on('dragend', function () {
        var p = marker.getLatLng();
        show(p.lng, p.lat);
      });
    }
    show(lng, lat);
    if (pan) { map.setView([lat, lng], Math.max(map.getZoom(), 17)); }
  }

  function current() {
    if (!marker) { return null; }
    var p = marker.getLatLng();
    return [p.lng, p.lat];
  }

  map.on('click', function (e) { setPoint(e.latlng.lng, e.latlng.lat, false); });

  function jump() {
    var parts = document.getElementById('jump').value.trim().split(/[,，\s]+/);
    if (parts.length < 2) {
      document.getElementById('msg').innerText = '请输入「经度,纬度」，例如 116.397428,39.909230';
      return;
    }
    var lng = parseFloat(parts[0]), lat = parseFloat(parts[1]);
    if (isNaN(lng) || isNaN(lat)) {
      document.getElementById('msg').innerText = '坐标格式不正确';
      return;
    }
    setPoint(lng, lat, true);
    document.getElementById('msg').innerText = '已跳转到输入坐标';
  }

  function bridge() {
    return (window.pywebview && window.pywebview.api) ? window.pywebview.api : null;
  }

  function useHere() {
    var c = current();
    if (!c) {
      document.getElementById('msg').innerText = '请先在地图上单击选择位置';
      return;
    }
    var api = bridge();
    if (!api) {
      document.getElementById('msg').innerText = '内置浏览器尚未就绪，请稍等一秒再试';
      return;
    }
    var info = JSON.stringify({
      leaflet: (typeof L !== 'undefined') ? L.version : '',
      tiles: document.querySelectorAll('.leaflet-tile-loaded').length
    });
    api.confirm(c[0], c[1], info);
  }

  function cancel() {
    var api = bridge();
    if (api) { api.cancel(); }
  }

  window.__picker = { setPoint: setPoint, useHere: useHere, current: current, map: map };

  window.addEventListener('pywebviewready', function () {
    ready = true;
    document.getElementById('msg').innerText = '已就绪：单击地图选点，然后点「使用此坐标」';
  });
  setTimeout(function () {
    if (!ready) {
      document.getElementById('msg').innerText = bridge()
        ? '已就绪：单击地图选点，然后点「使用此坐标」'
        : '地图已加载，等待内置浏览器桥接……';
    }
  }, 1500);

  if (__HAS_START__) { setPoint(__LON__, __LAT__, false); }
  __SELFTEST__
</script>
</body>
</html>
'''

PICKER_DEFAULT_LON = 116.397428
PICKER_DEFAULT_LAT = 39.909230


def _picker_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not (-180.0 <= number <= 180.0):
        return None
    return number


def build_picker_page(lon, lat, selftest=False):
    css = resource_path('leaflet/leaflet.css')
    js = resource_path('leaflet/leaflet.js')
    if not (css and js):
        raise RuntimeError('缺少地图组件资源（resources/leaflet）')
    start_lon = _picker_number(lon)
    start_lat = _picker_number(lat)
    has_start = start_lon is not None and start_lat is not None
    zoom = 17 if has_start else 12
    page = PICKER_HTML
    replacements = {
        '__CSS__': pathlib_uri(css),
        '__JS__': pathlib_uri(js),
        '__LON__': repr(start_lon if has_start else PICKER_DEFAULT_LON),
        '__LAT__': repr(start_lat if has_start else PICKER_DEFAULT_LAT),
        '__ZOOM__': str(zoom),
        '__HAS_START__': 'true' if has_start else 'false',
        '__SELFTEST__': (
            "setTimeout(function(){ setPoint(%r, %r, true); setTimeout(useHere, 1200); }, 1800);"
            % (PICKER_DEFAULT_LON, PICKER_DEFAULT_LAT)
        ) if selftest else '',
    }
    for token, value in replacements.items():
        page = page.replace(token, value)
    path = os.path.join(data_dir(), 'picker.html')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(page)
    return path


def pathlib_uri(path):
    return 'file:///' + os.path.abspath(path).replace('\\', '/')


def run_picker(out_path, lon='', lat='', selftest=False):
    """独立进程运行地图选点窗口，结果写入 out_path（JSON）。"""
    try:
        import webview
    except Exception as e:
        raise RuntimeError('内置地图组件不可用：%s' % e)

    page = build_picker_page(lon, lat, selftest=selftest)

    class PickerApi:
        def confirm(self, lng, latv, info=''):
            payload = {'lon': float(lng), 'lat': float(latv), 'info': info}
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False)
            for window in list(webview.windows):
                window.destroy()
            return True

        def cancel(self):
            for window in list(webview.windows):
                window.destroy()
            return True

    webview.create_window('地图选点 - %s' % APP_TITLE, url=pathlib_uri(page),
                          js_api=PickerApi(), width=980, height=730, min_size=(760, 560))
    webview.start(private_mode=True)
    return os.path.exists(out_path)


def picker_command(out_path, lon='', lat=''):
    if getattr(sys, 'frozen', False):
        base = [os.path.abspath(sys.executable)]
    else:
        base = [sys.executable, os.path.abspath(__file__)]
    return base + ['--picker', '--out', out_path, '--lon', lon, '--lat', lat]


# ================= 命令行入口 =================

def cli_run(check_only):
    cfg = load_config()
    logger = Logger('check' if check_only else 'auto')
    logger('===== %s 开始 =====' % ('检测' if check_only else '自动签到'))
    try:
        if check_only:
            text = run_check(cfg, logger)
        else:
            text = run_sign(cfg, logger)
        for line in text.splitlines():
            logger(line)
        logger('===== 结束：成功 =====')
        return 0
    except Exception as e:
        logger('失败：%s' % e)
        logger(traceback.format_exc())
        return 1


# ================= 图形界面 =================

def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    cfg = load_config()
    active_theme = cfg.get('theme') if cfg.get('theme') in THEMES else 'dark'
    apply_theme(active_theme)
    root = tk.Tk()
    root.title('%s v1.0' % APP_TITLE)
    try:
        root.iconbitmap(resource_path('app.ico'))
    except Exception:
        pass
    root.geometry('%dx%d' % (S(1180), S(820)))
    root.minsize(S(1060), S(740))
    root.configure(bg=THEME['bg'])
    root.option_add('*Font', (FONT_UI, 10))
    root.option_add('*TCombobox*Listbox.background', THEME['field'])
    root.option_add('*TCombobox*Listbox.foreground', THEME['text'])
    root.option_add('*TCombobox*Listbox.selectBackground', THEME['select_bg'])
    root.option_add('*TCombobox*Listbox.selectForeground', THEME['select_fg'])
    root.option_add('*TCombobox*Listbox.font', (FONT_UI, 10))

    style = ttk.Style()
    try:
        style.theme_use('clam')
    except Exception:
        pass

    def safe_configure(name, **options):
        try:
            style.configure(name, **options)
        except tk.TclError:
            pass

    bg = THEME['bg']
    surface = THEME['card']
    field = THEME['field']
    line = THEME['line']
    text = THEME['text']
    cyan = THEME['cyan']
    purple = THEME['purple']

    safe_configure('.', font=(FONT_UI, 10))
    safe_configure('TFrame', background=bg)
    safe_configure('TLabel', background=bg, foreground=text)

    safe_configure('TEntry', fieldbackground=field, foreground=text, insertcolor=cyan,
                   bordercolor=line, lightcolor=line, darkcolor=line,
                   selectbackground=THEME['select_bg'], selectforeground=THEME['select_fg'],
                   padding=(11, 9), relief='flat', font=(FONT_UI, 9))
    style.map('TEntry',
              fieldbackground=[('focus', THEME['field_hover']), ('readonly', field)],
              bordercolor=[('focus', cyan)],
              lightcolor=[('focus', cyan)],
              darkcolor=[('focus', cyan)])

    safe_configure('Time.TEntry', fieldbackground=field, foreground=cyan, insertcolor=cyan,
                   bordercolor=line, lightcolor=field, darkcolor=field,
                   selectbackground=THEME['select_bg'], selectforeground=THEME['select_fg'],
                   padding=(16, 12), relief='flat', font=(FONT_MONO, 16, 'bold'))
    style.map('Time.TEntry',
              fieldbackground=[('focus', THEME['field_hover'])],
              bordercolor=[('focus', THEME['cyan_dim'])],
              lightcolor=[('focus', field)],
              darkcolor=[('focus', field)])

    safe_configure('Flat.TEntry', fieldbackground=field, foreground=text, insertcolor=cyan,
                   bordercolor=field, lightcolor=field, darkcolor=field,
                   selectbackground=THEME['select_bg'], selectforeground=THEME['select_fg'],
                   padding=(14, 6), relief='flat', font=(FONT_UI, 9))
    style.map('Flat.TEntry',
              fieldbackground=[('focus', field), ('readonly', field)],
              bordercolor=[('focus', field)],
              lightcolor=[('focus', field)],
              darkcolor=[('focus', field)])

    safe_configure('TimeFlat.TEntry', fieldbackground=field, foreground=cyan, insertcolor=cyan,
                   bordercolor=field, lightcolor=field, darkcolor=field,
                   selectbackground=THEME['select_bg'], selectforeground=THEME['select_fg'],
                   padding=(14, 4), relief='flat', font=(FONT_MONO, 16, 'bold'))
    style.map('TimeFlat.TEntry',
              fieldbackground=[('focus', field)],
              bordercolor=[('focus', field)],
              lightcolor=[('focus', field)],
              darkcolor=[('focus', field)])

    safe_configure('TButton', background=field, foreground=THEME['text_dim'], bordercolor=line,
                   lightcolor=field, darkcolor=field, focuscolor=bg,
                   padding=(14, 8), relief='flat', font=(FONT_UI, 9))
    style.map('TButton',
              background=[('disabled', surface), ('pressed', THEME['ghost_press']),
                          ('active', THEME['field_hover'])],
              foreground=[('disabled', THEME['faint']), ('pressed', cyan), ('active', cyan)],
              bordercolor=[('active', THEME['cyan_dim'])])
    safe_configure('Accent.TButton', background=cyan, foreground=THEME['primary_fg'],
                   bordercolor=cyan, lightcolor=cyan, darkcolor=cyan,
                   padding=(18, 9), relief='flat', font=(FONT_UI, 9, 'bold'))
    style.map('Accent.TButton',
              background=[('disabled', field), ('pressed', THEME['primary_press']),
                          ('active', THEME['primary_hover'])],
              foreground=[('disabled', THEME['faint']), ('pressed', THEME['primary_fg']),
                          ('active', THEME['primary_fg'])],
              bordercolor=[('disabled', field), ('active', THEME['primary_hover'])])
    safe_configure('Purple.TButton', background=field, foreground=purple,
                   bordercolor=THEME['purple_line'], lightcolor=field, darkcolor=field,
                   padding=(14, 8), relief='flat', font=(FONT_UI, 9))
    style.map('Purple.TButton',
              background=[('disabled', surface), ('pressed', THEME['purple_press']),
                          ('active', THEME['purple_hover'])],
              foreground=[('disabled', THEME['faint']), ('active', purple)],
              bordercolor=[('active', purple)])

    safe_configure('TCheckbutton', background=bg, foreground=THEME['text'], focuscolor=bg,
                   indicatorbackground=field, indicatorforeground=cyan, padding=2)
    style.map('TCheckbutton',
              background=[('active', bg)],
              foreground=[('active', cyan)],
              indicatorbackground=[('selected', THEME['select_bg']),
                                   ('active', THEME['field_hover'])],
              indicatorforeground=[('selected', cyan)])

    safe_configure('TCombobox', fieldbackground=field, background=field, foreground=text,
                   arrowcolor=cyan, bordercolor=line, lightcolor=line, darkcolor=line,
                   padding=(10, 7), relief='flat')
    style.map('TCombobox',
              fieldbackground=[('readonly', field)],
              foreground=[('readonly', text)],
              selectbackground=[('readonly', field)],
              selectforeground=[('readonly', cyan)],
              background=[('active', THEME['field_hover'])],
              arrowcolor=[('active', cyan)],
              bordercolor=[('focus', cyan), ('active', THEME['cyan_dim'])])

    safe_configure('TScrollbar', background=THEME['line'], troughcolor=bg, bordercolor=bg,
                   arrowcolor=THEME['faint'], lightcolor=THEME['line'],
                   darkcolor=THEME['line'], arrowsize=10, width=8)
    style.map('TScrollbar', background=[('active', THEME['cyan_dim'])],
              arrowcolor=[('active', cyan)])

    def style_text(widget, mono=True, color=None):
        widget.configure(background=THEME['card_alt'], foreground=color or text,
                         insertbackground=cyan, selectbackground=THEME['select_bg'],
                         selectforeground=THEME['select_fg'], relief='flat',
                         borderwidth=0, highlightthickness=1,
                         highlightbackground=THEME['line_soft'],
                         highlightcolor=THEME['cyan_dim'],
                         padx=12, pady=10,
                         font=(FONT_MONO, 9) if mono else (FONT_UI, 9))
        return widget

    # ---------- 自绘控件：圆角卡片 / 药丸开关 ----------
    import tkinter.font as tkfont

    def rounded_points(x1, y1, x2, y2, r, steps=None):
        """按四角小圆弧逐点生成闭合多边形，避免样条过冲越界。"""
        r = max(0.0, min(float(r), (x2 - x1) / 2.0, (y2 - y1) / 2.0))
        if r <= 0:
            return [x1, y1, x2, y1, x2, y2, x1, y2]
        if steps is None:
            # 弧线段越密，边缘越接近平滑曲线；大圆角给更多分段
            steps = max(8, min(20, int(r * 1.2)))
        pts = []
        for cx, cy, a0 in ((x2 - r, y1 + r, -90), (x2 - r, y2 - r, 0),
                           (x1 + r, y2 - r, 90), (x1 + r, y1 + r, 180)):
            for i in range(steps + 1):
                a = math.radians(a0 + 90.0 * i / steps)
                pts.extend([cx + r * math.cos(a), cy + r * math.sin(a)])
        return pts

    def rounded_rect(canvas, x1, y1, x2, y2, r, **kwargs):
        return canvas.create_polygon(rounded_points(x1, y1, x2, y2, r), **kwargs)

    # ---------- 抗锯齿圆角：用 PIL 超采样生成图片，消除多边形锯齿 ----------
    try:
        from PIL import Image as _PILImage, ImageDraw as _PILDraw, ImageTk as _PILTk
    except Exception:
        _PILImage = _PILDraw = _PILTk = None

    _round_cache = {}
    theme_shapes = []

    def rounded_photo(w, h, r, fill, outline=None, width=1):
        """返回宽 w 高 h 的抗锯齿圆角矩形图片。"""
        if _PILImage is None or w < 2 or h < 2:
            return None
        key = (w, h, int(r), fill, outline, int(width))
        photo = _round_cache.get(key)
        if photo is not None:
            return photo
        # 大图降低超采样倍数，避免切换主题时一次性生成过多像素而卡顿
        area = w * h
        ss = 4 if area <= 60000 else (3 if area <= 220000 else 2)
        img = _PILImage.new('RGBA', (w * ss, h * ss), (0, 0, 0, 0))
        draw = _PILDraw.Draw(img)
        inset = width * ss / 2.0
        draw.rounded_rectangle(
            (inset, inset, w * ss - inset, h * ss - inset),
            radius=max(0.0, r * ss - inset),
            fill=fill or None, outline=outline, width=max(1, int(round(width * ss))))
        img = img.resize((w, h), _PILImage.LANCZOS)
        photo = _PILTk.PhotoImage(img)
        if len(_round_cache) < 600:
            _round_cache[key] = photo
        return photo

    def paint_round(canvas, item, x, y, w, h, r, fill, outline=None, width=1):
        """在 canvas 上绘制/更新圆角矩形；优先用抗锯齿图片，失败时退回多边形。"""
        photo = rounded_photo(w, h, r, fill, outline, width)
        if photo is None:
            pts = rounded_points(x, y, x + w, y + h, r)
            if item is None:
                return canvas.create_polygon(pts, fill=fill, outline=outline or '',
                                             width=width)
            try:
                canvas.coords(item, *pts)
                canvas.itemconfigure(item, fill=fill, outline=outline or '', width=width)
            except tk.TclError:
                item = canvas.create_polygon(pts, fill=fill, outline=outline or '',
                                             width=width)
            return item
        if item is None:
            item = canvas.create_image(x, y, anchor='nw', image=photo)
        else:
            try:
                canvas.itemconfigure(item, image=photo)
            except tk.TclError:
                item = canvas.create_image(x, y, anchor='nw', image=photo)
        photos = getattr(canvas, '_round_photos', None)
        if photos is None:
            photos = canvas._round_photos = {}
        photos[item] = photo
        return item

    def static_round(canvas, x, y, w, h, r, fill_key, outline_key=None):
        """颜色取自 THEME 的静态圆角，主题切换时自动重绘。"""
        holder = {'item': None}

        def draw():
            holder['item'] = paint_round(
                canvas, holder['item'], x, y, w, h, r, THEME[fill_key],
                THEME[outline_key] if outline_key else None, 1)

        draw()
        theme_shapes.append(draw)
        return holder

    class Card(tk.Frame):
        """带圆角描边的卡片，内容放进 card.body"""

        def __init__(self, master, radius=12, padx=24, pady=20, auto_height=True, height=None):
            super().__init__(master, bg=bg, bd=0, highlightthickness=0)
            self._radius = S(radius)
            self._padx, self._pady = S(padx), S(pady)
            self._auto = auto_height and not height
            self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0,
                                    width=1, height=S(height) if height else S(40))
            self.canvas.pack(fill='both', expand=True)
            self.body = tk.Frame(self.canvas, bg=THEME['card'])
            self._win = self.canvas.create_window(padx, pady, window=self.body, anchor='nw')
            self._shape = None
            self.actions = None
            self.canvas.bind('<Configure>', self._draw)
            self.body.bind('<Configure>', self._sync)
            self._sync()

        def _sync(self, _event=None):
            if not self._auto:
                return
            want = self.body.winfo_reqheight() + self._pady * 2
            if abs(int(float(self.canvas['height'])) - want) > 1:
                self.canvas.configure(height=want)

        def _draw(self, _event=None):
            w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
            if w < 4 or h < 4:
                return
            self._shape = paint_round(self.canvas, self._shape, 1, 1, w - 2, h - 2,
                                      self._radius, THEME['card'], THEME['line'], 1)
            self.canvas.tag_lower(self._shape)
            self.canvas.itemconfigure(self._win, width=max(24, w - self._padx * 2))
            if not self._auto:
                self.canvas.itemconfigure(self._win, height=max(24, h - self._pady * 2))

        def refresh_theme(self):
            self.body.configure(bg=THEME['card'])
            self._draw()

    class Btn(tk.Canvas):
        """自绘的圆角按钮，主按钮为实心荧光青"""

        @staticmethod
        def styles():
            return {
                'primary': (THEME['cyan'], THEME['primary_fg'], THEME['cyan'],
                            THEME['primary_hover'], THEME['primary_press']),
                'ghost': (THEME['field'], THEME['text_dim'], THEME['line'],
                          THEME['field_hover'], THEME['ghost_press']),
                'purple': (THEME['purple_bg'], THEME['purple'], THEME['purple_line'],
                           THEME['purple_hover'], THEME['purple_press']),
                'danger': (THEME['field'], THEME['red'], THEME['line'],
                           THEME['danger_hover'], THEME['danger_press']),
            }

        def __init__(self, master, text, command=None, kind='ghost', font=None,
                     padx=18, pady=8, bg=None, height=None):
            bold = kind == 'primary'
            use_font = font or (FONT_UI, 9, 'bold' if bold else 'normal')
            padx, pady = S(padx), S(pady)
            fnt = tkfont.Font(font=use_font)
            w = fnt.measure(text) + padx * 2
            h = S(height) if height else max(S(38), fnt.metrics('linespace') + pady * 2)
            super().__init__(master, width=w, height=h, bg=bg or THEME['card'],
                             highlightthickness=0, bd=0, cursor='hand2')
            self._kind, self._command, self._enabled = kind, command, True
            self._cw, self._ch = w, h
            self._shape = None
            self._label = self.create_text(w / 2, h / 2 + 1, text=text, font=use_font)
            self.bind('<Button-1>', self._press)
            self.bind('<ButtonRelease-1>', self._release)
            self.bind('<Enter>', lambda e: self._paint(True))
            self.bind('<Leave>', lambda e: self._paint(False))
            self._paint()

        def _render(self, fill, outline):
            self._shape = paint_round(self, self._shape, 2, 2, self._cw - 4, self._ch - 4,
                                      (self._ch - 4) // 2, fill, outline, 1)
            self.tag_lower(self._shape)

        def _paint(self, hover=False, press=False):
            fill, fg, outline, hover_fill, press_fill = self.styles()[self._kind]
            if not self._enabled:
                self._render(THEME['field'], THEME['line_soft'])
                self.itemconfigure(self._label, fill=THEME['faint'])
                return
            self._render(press_fill if press else (hover_fill if hover else fill), outline)
            self.itemconfigure(self._label, fill=fg)

        def refresh_theme(self):
            self._paint()

        def _press(self, _event=None):
            if self._enabled:
                self._paint(True, True)

        def _release(self, _event=None):
            if not self._enabled:
                return
            self._paint(True)
            if self._command:
                self._command()

        def configure(self, cnf=None, **kw):
            if 'state' in kw:
                self._enabled = kw.pop('state') != 'disabled'
                self._paint()
            if 'kind' in kw:
                self._kind = kw.pop('kind')
                self._paint()
            if 'text' in kw:
                self.itemconfigure(self._label, text=kw.pop('text'))
            if cnf is None and not kw:
                return super().configure()
            return super().configure(cnf, **kw)

    class EntryBox(tk.Canvas):
        """圆角输入框：内部放一个无边框 ttk.Entry，聚焦时描边变亮"""

        def __init__(self, master, textvariable=None, show=None, height=42, radius=10,
                     style='Flat.TEntry', font=None, justify='left', width=None, bg=None):
            kw = {'height': S(height), 'bg': bg or THEME['card'],
                  'highlightthickness': 0, 'bd': 0}
            if width:
                kw['width'] = S(width)
            super().__init__(master, **kw)
            self._radius = S(radius)
            self.entry = ttk.Entry(self, textvariable=textvariable, show=show, style=style)
            if font:
                self.entry.configure(font=font)
            if justify:
                self.entry.configure(justify=justify)
            self._win = self.create_window(4, 3, window=self.entry, anchor='nw')
            self._shape = None
            self.bind('<Configure>', self._draw)
            self.entry.bind('<FocusIn>', lambda e: self._ring(True))
            self.entry.bind('<FocusOut>', lambda e: self._ring(False))

        def _draw(self, _event=None):
            w, h = self.winfo_width(), self.winfo_height()
            if w < 6 or h < 6:
                return
            fill = THEME['field_hover'] if self.entry.focus_get() is self.entry else THEME['field']
            outline = THEME['cyan_dim'] if self.entry.focus_get() is self.entry else THEME['line']
            self._shape = paint_round(self, self._shape, 1, 1, w - 2, h - 2,
                                      self._radius, fill, outline, 1)
            self.tag_lower(self._shape)
            self.itemconfigure(self._win, width=max(20, w - 8), height=max(20, h - 6))

        def _ring(self, focus):
            self._draw()

        def refresh_theme(self):
            self._draw()

    class PillToggle(tk.Canvas):
        """可选中的圆角标签，用于选择重复星期"""

        def __init__(self, master, label, variable):
            fnt = tkfont.Font(font=(FONT_UI, 9))
            w, h = fnt.measure(label) + S(34), S(32)
            super().__init__(master, width=w, height=h, bg=THEME['card'],
                             highlightthickness=0, bd=0, cursor='hand2')
            self._var = variable
            self._cw, self._ch = w, h
            self._shape = None
            self._text = self.create_text(w / 2, h / 2 + 1, text=label,
                                          fill=THEME['muted'], font=(FONT_UI, 9))
            self.bind('<Button-1>', self._toggle)
            variable.trace_add('write', lambda *_: self._paint())
            self._paint()

        def _toggle(self, _event=None):
            self._var.set(not bool(self._var.get()))

        def _paint(self):
            on = bool(self._var.get())
            self._shape = paint_round(
                self, self._shape, 2, 2, self._cw - 4, self._ch - 4, (self._ch - 4) // 2,
                THEME['cyan'] if on else THEME['card_alt'],
                THEME['cyan'] if on else THEME['line'], 1)
            self.tag_lower(self._shape)
            self.itemconfigure(self._text, fill=THEME['primary_fg'] if on else THEME['muted'],
                               font=(FONT_UI, 9, 'bold') if on else (FONT_UI, 9))

        def refresh_theme(self):
            self._paint()

    # ---------- 自绘窗口顶栏（去掉系统标题栏） ----------
    frameless_done = [False]

    def strip_native_titlebar(force=False):
        """去掉 WS_CAPTION 与 WS_THICKFRAME，避免顶边出现系统白边。"""
        try:
            import ctypes
            root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -16)
            new_style = style & ~0x00C00000 & ~0x00040000
            if new_style != style:
                ctypes.windll.user32.SetWindowLongW(hwnd, -16, new_style)
                ctypes.windll.user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0004 | 0x0010 | 0x0020)
            frameless_done[0] = True
        except Exception:
            pass

    def drag_window(event=None):
        """记录按下位置，供鼠标拖动移动窗口。"""
        try:
            root._drag_offset = (event.x_root - root.winfo_x(),
                                 event.y_root - root.winfo_y())
        except Exception:
            root._drag_offset = None

    def move_window(event=None):
        offset = getattr(root, '_drag_offset', None)
        if not offset:
            return
        try:
            root.geometry('+%d+%d' % (event.x_root - offset[0], event.y_root - offset[1]))
        except Exception:
            pass

    topbar = tk.Frame(root, bg=THEME['sidebar'], height=S(40))
    topbar.pack(side='top', fill='x')
    topbar.pack_propagate(False)
    try:
        bar_icon = tk.PhotoImage(file=resource_path('app.png')).subsample(8, 8)
        icon_label = tk.Label(topbar, image=bar_icon, bg=THEME['sidebar'], bd=0)
        icon_label.image = bar_icon
        icon_label.pack(side='left', padx=(S(14), 0))
        icon_label.bind('<Button-1>', drag_window)
        icon_label.bind('<B1-Motion>', move_window)
    except Exception:
        pass
    title_label = tk.Label(topbar, text=APP_TITLE, bg=THEME['sidebar'], fg=THEME['text_dim'],
                           font=(FONT_UI, 9))
    title_label.pack(side='left', padx=(S(10), S(8)))
    version_label = tk.Label(topbar, text='v1.0', bg=THEME['sidebar'], fg=THEME['faint'],
                             font=(FONT_UI, 8))
    version_label.pack(side='left')
    for widget in (topbar, title_label, version_label):
        widget.bind('<Button-1>', drag_window)
        widget.bind('<B1-Motion>', move_window)

    def window_button(glyph, command, hover_color):
        label = tk.Label(topbar, text=glyph, bg=THEME['sidebar'], fg=THEME['muted'],
                         font=(ICON_FONT, 9), cursor='hand2')
        label.pack(side='right', padx=(S(2), S(12)), pady=(S(9), 0))
        label.bind('<Button-1>', lambda e: command())
        label.bind('<Enter>', lambda e: label.configure(fg=hover_color))
        label.bind('<Leave>', lambda e: label.configure(fg=THEME['muted']))
        return label

    close_button = window_button('\uE8BB', root.destroy, THEME['red'])
    minimize_button = window_button('\uE921', root.iconify, THEME['cyan'])

    # ---------- 左侧导航 ----------
    sidebar = tk.Frame(root, bg=THEME['sidebar'], width=S(236))
    sidebar.pack(side='left', fill='y')
    sidebar.pack_propagate(False)
    tk.Frame(sidebar, width=1, bg=THEME['line_soft']).pack(side='right', fill='y')
    main = tk.Frame(root, bg=bg)
    main.pack(side='left', fill='both', expand=True)

    brand = tk.Frame(sidebar, bg=THEME['sidebar'])
    brand.pack(fill='x', padx=S(23), pady=(S(26), S(30)))
    mark = tk.Canvas(brand, width=S(32), height=S(32), bg=THEME['sidebar'],
                     highlightthickness=0, bd=0)
    mark.pack(side='left')
    static_round(mark, 0, 0, S(32), S(32), S(10), 'cyan')
    mark.create_text(S(16), S(17), text='C', fill=THEME['primary_fg'],
                     font=(FONT_UI, 13, 'bold'))
    btext = tk.Frame(brand, bg=THEME['sidebar'])
    btext.pack(side='left', padx=(S(11), 0))
    tk.Label(btext, text='CPDAILY', bg=THEME['sidebar'], fg=text,
             font=(FONT_UI, 11, 'bold')).pack(anchor='w')
    tk.Label(btext, text='签到控制台', bg=THEME['sidebar'], fg=THEME['muted'],
             font=(FONT_UI, 8)).pack(anchor='w', pady=(1, 0))

    tk.Label(sidebar, text='工作台', bg=THEME['sidebar'], fg=THEME['faint'],
             font=(FONT_UI, 8)).pack(anchor='w', padx=S(26), pady=(0, S(10)))

    pages = {}
    nav_widgets = {}
    active_tab = ['basic']

    def add_nav(key, icon, title):
        item = tk.Frame(sidebar, bg=THEME['sidebar'], cursor='hand2')
        item.pack(fill='x', padx=14, pady=(0, 4))
        bar = tk.Frame(item, width=3, bg=THEME['sidebar'])
        bar.pack(side='left', fill='y')
        rowf = tk.Frame(item, bg=THEME['sidebar'])
        rowf.pack(side='left', fill='x', expand=True, padx=(13, 12), pady=11)
        ic = tk.Label(rowf, text=icon, bg=THEME['sidebar'], fg=THEME['faint'],
                      font=(ICON_FONT, 11))
        ic.pack(side='left')
        lb = tk.Label(rowf, text=title, bg=THEME['sidebar'], fg=THEME['muted'],
                      font=(FONT_UI, 10))
        lb.pack(side='left', padx=(11, 0))
        nav_widgets[key] = {'item': item, 'bar': bar, 'icon': ic, 'label': lb, 'row': rowf}
        for widget in (item, rowf, ic, lb):
            widget.bind('<Button-1>', lambda e, k=key: show_tab(k))
            widget.bind('<Enter>', lambda e, k=key: hover_nav(k, True))
            widget.bind('<Leave>', lambda e, k=key: hover_nav(k, False))

    def paint_nav():
        for key, parts in nav_widgets.items():
            on = key == active_tab[0]
            base = THEME['nav_active'] if on else THEME['sidebar']
            parts['item'].configure(bg=base)
            parts['row'].configure(bg=base)
            parts['bar'].configure(bg=THEME['cyan'] if on else base)
            parts['icon'].configure(bg=base, fg=THEME['cyan'] if on else THEME['faint'])
            parts['label'].configure(bg=base, fg=THEME['text'] if on else THEME['muted'],
                                     font=(FONT_UI, 10, 'bold') if on else (FONT_UI, 10))

    def hover_nav(key, entering):
        if key == active_tab[0]:
            return
        base = THEME['nav_hover'] if entering else THEME['sidebar']
        parts = nav_widgets[key]
        parts['item'].configure(bg=base)
        parts['row'].configure(bg=base)
        parts['bar'].configure(bg=base)
        parts['icon'].configure(bg=base)
        parts['label'].configure(bg=base)

    def show_tab(name):
        active_tab[0] = name
        for key, page in pages.items():
            if key == name:
                page.pack(fill='both', expand=True)
            else:
                page.pack_forget()
        paint_nav()

    # ---------- 热切换配色：就地改颜色，不重建窗口 ----------
    COLOR_OPTIONS = ('background', 'foreground', 'highlightbackground', 'highlightcolor',
                     'insertbackground', 'selectbackground', 'selectforeground',
                     'activebackground', 'activeforeground', 'troughcolor',
                     'disabledforeground', 'readonlybackground', 'bordercolor',
                     'lightcolor', 'darkcolor', 'fieldbackground', 'indicatorbackground',
                     'indicatorforeground', 'arrowcolor', 'focuscolor')
    STYLE_NAMES = ('.', 'TFrame', 'TLabel', 'TEntry', 'Time.TEntry', 'Flat.TEntry',
                   'TimeFlat.TEntry', 'TButton', 'Accent.TButton', 'Purple.TButton',
                   'TCheckbutton', 'TCombobox', 'TScrollbar')
    # 两套配色里有同色值的情况，按这里的先后决定该用哪个键的新色
    KEY_PRIORITY = ('bg', 'sidebar', 'statusbar', 'card', 'card_alt', 'field', 'field_hover',
                    'nav_active', 'nav_hover', 'line', 'line_soft', 'text', 'text_dim',
                    'muted', 'faint', 'cyan', 'cyan_dim', 'purple', 'amber', 'red',
                    'select_bg', 'select_fg', 'primary_fg', 'primary_hover', 'primary_press',
                    'ghost_press', 'purple_bg', 'purple_line', 'purple_hover', 'purple_press',
                    'danger_hover', 'danger_press', 'icon_tile', 'log_text')

    def theme_pairs(old, new):
        ranked = [k for k in KEY_PRIORITY if k in old] + [k for k in old if k not in KEY_PRIORITY]
        pairs = {}
        for key in ranked:
            value, target = old.get(key), new.get(key)
            if not isinstance(value, str) or not isinstance(target, str):
                continue
            if value.lower() != target.lower():
                pairs.setdefault(value.lower(), target)
        return pairs

    def restyle_ttk(pairs):
        for name in STYLE_NAMES:
            try:
                opts = style.configure(name) or {}
            except tk.TclError:
                continue
            changes = {k: pairs[str(v).lower()] for k, v in opts.items()
                       if k in COLOR_OPTIONS and str(v).lower() in pairs}
            if changes:
                safe_configure(name, **changes)
            try:
                maps = style.map(name) or {}
            except tk.TclError:
                continue
            newmap = {}
            for key, states in maps.items():
                if key not in COLOR_OPTIONS:
                    continue
                entries = []
                for item in states:
                    if len(item) == 2 and str(item[1]).lower() in pairs:
                        entries.append((item[0], pairs[str(item[1]).lower()]))
                    else:
                        entries.append(tuple(item))
                newmap[key] = entries
            if newmap:
                try:
                    style.map(name, **newmap)
                except tk.TclError:
                    pass

    def recolor_tree(widget, pairs):
        try:
            keys = widget.keys()
        except Exception:
            keys = ()
        changes = {}
        for opt in COLOR_OPTIONS:
            if opt not in keys:
                continue
            try:
                value = str(widget.cget(opt)).lower()
            except Exception:
                continue
            if value in pairs:
                changes[opt] = pairs[value]
        if changes:
            try:
                widget.configure(**changes)
            except tk.TclError:
                pass
        if widget.winfo_class() == 'Canvas':
            for item in widget.find_all():
                item_changes = {}
                for opt in ('fill', 'outline'):
                    try:
                        value = str(widget.itemcget(item, opt)).lower()
                    except tk.TclError:
                        continue
                    if value in pairs:
                        item_changes[opt] = pairs[value]
                if item_changes:
                    try:
                        widget.itemconfigure(item, **item_changes)
                    except tk.TclError:
                        pass
        for child in widget.winfo_children():
            recolor_tree(child, pairs)

    def collect_refreshers(widget, tasks):
        refresh = getattr(widget, 'refresh_theme', None)
        if callable(refresh):
            try:
                area = widget.winfo_width() * widget.winfo_height()
            except Exception:
                area = 0
            tasks.append((area, refresh))
        for child in widget.winfo_children():
            collect_refreshers(child, tasks)

    theme_generation = [0]

    def apply_theme_live(key):
        """不关闭窗口，直接把所有控件的配色换成另一套。"""
        nonlocal active_theme
        old = dict(THEME)
        apply_theme(key)
        pairs = theme_pairs(old, THEME)
        recolor_tree(root, pairs)
        restyle_ttk(pairs)
        try:
            root.configure(bg=THEME['bg'])
        except tk.TclError:
            pass
        for pattern, color in (('*TCombobox*Listbox.background', THEME['field']),
                               ('*TCombobox*Listbox.foreground', THEME['text']),
                               ('*TCombobox*Listbox.selectBackground', THEME['select_bg']),
                               ('*TCombobox*Listbox.selectForeground', THEME['select_fg'])):
            root.option_add(pattern, color)
        active_theme = key
        paint_nav()
        for theme_key, button in theme_buttons.items():
            button.configure(kind='primary' if theme_key == key else 'ghost')
        set_status('已切换到%s配色' % ('深色' if key == 'dark' else '浅色'), 'ok')
        strip_native_titlebar()
        # 圆角图片分帧重绘，避免一次性生成大量图片造成卡顿
        theme_generation[0] += 1
        token = theme_generation[0]
        collected = []
        collect_refreshers(root, collected)
        collected.sort(key=lambda pair: -pair[0])  # 面积大的先画，减少视觉不一致
        tasks = [refresh for _area, refresh in collected] + list(theme_shapes)

        def step(start=0):
            if token != theme_generation[0]:
                return
            for task in tasks[start:start + 8]:
                try:
                    task()
                except Exception:
                    pass
            if start + 8 < len(tasks):
                root.after(8, step, start + 8)
            else:
                try:
                    root.update_idletasks()
                except tk.TclError:
                    pass

        root.after(1, step)

    def switch_theme(key):
        """保存当前输入并就地换配色，不重启窗口。"""
        if key == active_theme:
            return
        try:
            data = collect_config()
        except Exception:
            data = load_config()
        data['theme'] = key
        try:
            save_config(data)
        except Exception:
            set_status('主题偏好保存失败', 'bad')
            return
        apply_theme_live(key)

    sfoot = tk.Frame(sidebar, bg=THEME['sidebar'])
    sfoot.pack(side='bottom', fill='x', padx=S(23), pady=(0, S(20)))
    tk.Frame(sfoot, height=1, bg=THEME['line_soft']).pack(fill='x', pady=(0, S(14)))
    tk.Label(sfoot, text='外观', bg=THEME['sidebar'], fg=THEME['faint'],
             font=(FONT_UI, 8)).pack(anchor='w')
    theme_row = tk.Frame(sfoot, bg=THEME['sidebar'])
    theme_row.pack(fill='x', pady=(S(8), 0))
    theme_buttons = {}
    for theme_key, theme_label in (('dark', '深色'), ('light', '浅色')):
        theme_button = Btn(theme_row, theme_label, command=lambda k=theme_key: switch_theme(k),
                           kind='primary' if theme_key == active_theme else 'ghost',
                           font=(FONT_UI, 9), padx=16, pady=5, height=32,
                           bg=THEME['sidebar'])
        theme_button.pack(side='left', padx=(0, S(8)))
        theme_buttons[theme_key] = theme_button
    tk.Label(sfoot, text='v1.0 · 配置仅保存在本机', bg=THEME['sidebar'],
             fg=THEME['faint'], font=(FONT_UI, 8)).pack(anchor='w', pady=(S(12), 0))

    # ---------- 底部状态栏 ----------
    statusbar = tk.Frame(main, bg=THEME['statusbar'])
    statusbar.pack(side='bottom', fill='x')
    tk.Frame(statusbar, height=1, bg=THEME['line_soft']).pack(fill='x')
    srow = tk.Frame(statusbar, bg=THEME['statusbar'])
    srow.pack(fill='x', padx=S(34), pady=S(10))
    status_dot = tk.Canvas(srow, width=S(7), height=S(7), bg=THEME['statusbar'],
                           highlightthickness=0, bd=0)
    status_dot.pack(side='left', pady=(1, 0))
    dot_item = status_dot.create_oval(0, 0, S(7), S(7), fill=THEME['muted'], outline='')
    status_label = tk.Label(srow, text='就绪', bg=THEME['statusbar'], fg=THEME['muted'],
                            font=(FONT_UI, 9))
    status_label.pack(side='left', padx=(S(10), 0))
    tk.Label(srow, text=config_path(), bg=THEME['statusbar'], fg=THEME['faint'],
             font=(FONT_UI, 8)).pack(side='right')

    def set_status(message, kind='hint'):
        color = {'ok': THEME['cyan'], 'bad': THEME['red'],
                 'warn': THEME['amber']}.get(kind, THEME['muted'])
        status_label.configure(text=message, fg=color)
        status_dot.itemconfigure(dot_item, fill=color)

    page_host = tk.Frame(main, bg=bg)
    page_host.pack(fill='both', expand=True)

    def build_page(key, title, subtitle):
        page = tk.Frame(page_host, bg=bg)
        pages[key] = page
        head = tk.Frame(page, bg=bg)
        head.pack(fill='x', padx=S(34), pady=(S(30), 0))
        titles = tk.Frame(head, bg=bg)
        titles.pack(side='left', anchor='w')
        tk.Label(titles, text='CPDAILY  /  %s' % subtitle[0], bg=bg, fg=THEME['faint'],
                 font=(FONT_UI, 8)).pack(anchor='w')
        tk.Label(titles, text=title, bg=bg, fg=text,
                 font=(FONT_UI, 24, 'bold')).pack(anchor='w', pady=(S(9), 0))
        tk.Label(titles, text=subtitle[1], bg=bg, fg=THEME['muted'],
                 font=(FONT_UI, 9)).pack(anchor='w', pady=(S(7), 0))
        actions = tk.Frame(head, bg=bg)
        actions.pack(side='right', anchor='e', pady=(S(14), 0))
        tk.Frame(page, height=1, bg=THEME['line_soft']).pack(
            fill='x', padx=S(34), pady=(S(20), 0))

        wrap = tk.Frame(page, bg=bg)
        wrap.pack(fill='both', expand=True, padx=(S(34), S(18)), pady=(S(16), S(8)))
        canvas = tk.Canvas(wrap, bg=bg, highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(wrap, orient='vertical', command=canvas.yview)
        # 固定滚动步长，避免像素级平滑滚动造成残影
        canvas.configure(yscrollcommand=sb.set, yscrollincrement=S(18))
        sb.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True, padx=(0, S(10)))
        inner = tk.Frame(canvas, bg=bg)
        win = canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(win, width=e.width))
        inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))

        def on_wheel(event):
            canvas.yview_scroll(-2 if event.delta > 0 else 2, 'units')
            canvas.update_idletasks()

        canvas.bind('<Enter>', lambda e: canvas.bind_all('<MouseWheel>', on_wheel))
        canvas.bind('<Leave>', lambda e: canvas.unbind_all('<MouseWheel>'))
        return page, inner, actions, canvas

    page_basic, inner_basic, actions_basic, basic_canvas = build_page(
        'basic', '基本配置', ('基本配置', '填写账号、设备与签到位置，程序会自动判断现在能否签到'))
    page_auto, inner_auto, actions_auto, auto_canvas = build_page(
        'auto', '自动签到', ('自动签到', '选择签到方案与执行时间，创建独立的 Windows 计划任务'))
    page_log, inner_log, actions_log, log_canvas = build_page(
        'log', '运行日志', ('运行日志', '签到流程的每一步都会实时记录在这里'))

    add_nav('basic', '\uE713', '基本配置')
    add_nav('auto', '\uE787', '自动签到')
    add_nav('log', '\uE7C3', '运行日志')
    show_tab('basic')

    # ---------- 基本配置 ----------
    vars_ = {}

    def card(parent, title, desc='', icon=''):
        c = Card(parent)
        c.pack(fill='x', pady=(0, S(12)))
        head = tk.Frame(c.body, bg=THEME['card'])
        head.pack(fill='x')
        if icon:
            tile = tk.Canvas(head, width=S(26), height=S(26), bg=THEME['card'],
                             highlightthickness=0, bd=0)
            tile.pack(side='left', padx=(0, S(11)), pady=(1, 0))
            static_round(tile, 0, 0, S(26), S(26), S(8), 'icon_tile')
            tile.create_text(S(13), S(14), text=icon, fill=cyan, font=(ICON_FONT, 10))
        tk.Label(head, text=title, bg=THEME['card'], fg=text,
                 font=(FONT_UI, 11, 'bold')).pack(side='left')
        c.actions = tk.Frame(head, bg=THEME['card'])
        c.actions.pack(side='right')
        if desc:
            tk.Label(c.body, text=desc, bg=THEME['card'], fg=THEME['muted'],
                     font=(FONT_UI, 8), justify='left', anchor='w',
                     wraplength=S(720)).pack(fill='x', pady=(S(7), S(18)))
        else:
            tk.Frame(c.body, bg=THEME['card'], height=S(18)).pack(fill='x')
        return c

    def metric_tile(parent, label, right=12, icon=''):
        c = Card(parent, pady=16, auto_height=False, height=110)
        c.pack(side='left', fill='x', expand=True, padx=(0, S(right)))
        if icon:
            tk.Label(c.body, text=icon, bg=THEME['card'], fg=THEME['cyan_dim'],
                     font=(ICON_FONT, 11)).place(relx=1.0, rely=0, x=-1, y=1, anchor='ne')
        tk.Label(c.body, text=label, bg=THEME['card'], fg=THEME['faint'],
                 font=(FONT_UI, 8)).pack(anchor='w')
        value = tk.Label(c.body, text='—', bg=THEME['card'], fg=text,
                         font=(FONT_UI, 14, 'bold'))
        value.pack(anchor='w', pady=(9, 3))
        sub = tk.Label(c.body, text='', bg=THEME['card'], fg=THEME['muted'],
                       font=(FONT_UI, 8))
        sub.pack(anchor='w')
        return value, sub

    def row(parent, bottom=14):
        r = tk.Frame(parent, bg=THEME['card'])
        r.pack(fill='x', pady=(0, S(bottom)))
        return r

    def cell(parent, right=15):
        c = tk.Frame(parent, bg=THEME['card'])
        c.pack(side='left', fill='x', expand=True, padx=(0, S(right)))
        return c

    def caption(parent, message, fg=None, wrap=660):
        return tk.Label(parent, text=message, bg=THEME['card'], fg=fg or THEME['faint'],
                        font=(FONT_UI, 8), justify='left', anchor='w',
                        wraplength=S(wrap))

    def field(parent, key, label, hint='', show=None, button=None, wrap=320):
        var = tk.StringVar(value=str(cfg.get(key) or ''))
        vars_[key] = var
        tk.Label(parent, text=label, bg=THEME['card'], fg=THEME['text_dim'],
                 font=(FONT_UI, 9)).pack(anchor='w', pady=(0, S(6)))
        holder = tk.Frame(parent, bg=THEME['card'])
        holder.pack(fill='x')
        box = EntryBox(holder, textvariable=var, show=show)
        box.pack(side='left', fill='x', expand=True)
        entry = box.entry
        if button:
            button_text, button_command = button
            Btn(holder, button_text, command=button_command, pady=6, height=42).pack(
                side='left', padx=(S(8), 0))
        if hint:
            caption(parent, hint, wrap=wrap).pack(fill='x', pady=(S(6), 0))
        return entry

    def import_did():
        path = filedialog.askopenfilename(title='选择 deviceId 文件',
                                          filetypes=[('所有文件', '*.*'), ('文本', '*.txt')])
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
            for token in text.replace('\n', ' ').split():
                if len(token) >= 16:
                    vars_['deviceId'].set(token.strip())
                    return
            messagebox.showwarning('未识别', '文件里没有找到有效的设备号')
        except Exception as e:
            messagebox.showerror('读取失败', str(e))

    metrics = tk.Frame(inner_basic, bg=bg)
    metrics.pack(fill='x', pady=(2, 14))
    m_acc, m_acc_sub = metric_tile(metrics, '账号', icon='\uE77B')
    m_loc, m_loc_sub = metric_tile(metrics, '签到坐标', icon='\uE707')
    m_plan, m_plan_sub = metric_tile(metrics, '自动签到', 0, icon='\uE823')

    acc = card(inner_basic, '账号信息', '今日校园登录身份与设备指纹，设备号必须与平时签到的那台手机一致',
               icon='\uE77B')
    r = row(acc.body)
    field(cell(r), 'school', '学校名称', '填写学校全称，程序会自动匹配登录入口')
    field(cell(r, 0), 'username', '学号', '今日校园登录账号，一般为学号')

    r = row(acc.body)
    field(cell(r), 'password', '密码', '仅保存在本机配置文件中，不会上传到任何第三方', show='*')
    field(cell(r, 0), 'systemVersion', '系统版本', '设置 → 关于手机 → Android 版本，例如「15」')

    r = row(acc.body, 12)
    field(r, 'deviceId', '设备号',
          '手机文件管理器打开「内部存储/Pictures/wismcp/did」，复制里面的文本；'
          '也可用抓包工具查看 deviceId。必须与你平时签到的那台手机一致，否则会触发设备风控。',
          button=('从文件读取', import_did), wrap=700)

    r = row(acc.body, 0)
    field(r, 'deviceModel', '手机型号')

    loc = card(inner_basic, '签到位置', '签到时会提交这组坐标，用地图选点取到的就是高德坐标系（GCJ-02）',
               icon='\uE707')
    map_button = Btn(loc.actions, '地图选点', command=lambda: on_pick_map(), kind='purple',
                     pady=5)
    map_button.pack(side='right')

    vars_['lon'] = tk.StringVar(value=str(cfg.get('lon') or ''))
    vars_['lat'] = tk.StringVar(value=str(cfg.get('lat') or ''))
    r = row(loc.body, 12)
    lon_cell = cell(r)
    tk.Label(lon_cell, text='经度', bg=THEME['card'], fg=THEME['text_dim'],
             font=(FONT_UI, 9)).pack(anchor='w', pady=(0, 6))
    EntryBox(lon_cell, textvariable=vars_['lon']).pack(fill='x')
    lat_cell = cell(r, 0)
    tk.Label(lat_cell, text='纬度', bg=THEME['card'], fg=THEME['text_dim'],
             font=(FONT_UI, 9)).pack(anchor='w', pady=(0, 6))
    EntryBox(lat_cell, textvariable=vars_['lat']).pack(fill='x')
    caption(loc.body,
            '点「地图选点」在内置高德地图上单击位置，坐标保留 6 位小数；'
            '也可在浏览器打开 lbs.amap.com/tools/picker 复制坐标。', wrap=700).pack(fill='x')

    si = card(inner_basic, '签到信息', '提交时展示给学校的文字与照片', icon='\uE8A5')
    r = row(si.body)
    field(cell(r), 'address', '签到地址', '显示的位置文字，与校内实际地点一致即可')
    field(cell(r, 0), 'abnormalReason', '在校状态', '一般填「在校」，学校有要求时按实际填写')

    photo_var = tk.StringVar(value=str(cfg.get('photo') or ''))

    def choose_photo():
        path = filedialog.askopenfilename(title='选择签到照片',
                                          filetypes=[('图片', '*.png *.jpg *.jpeg'), ('所有文件', '*.*')])
        if path:
            photo_var.set(path)

    r = row(si.body, 12)
    tk.Label(r, text='照片（可选）', bg=THEME['card'], fg=THEME['text_dim'],
             font=(FONT_UI, 9)).pack(anchor='w', pady=(0, 6))
    photo_row = tk.Frame(r, bg=THEME['card'])
    photo_row.pack(fill='x')
    EntryBox(photo_row, textvariable=photo_var).pack(side='left', fill='x', expand=True)
    Btn(photo_row, '选择图片', command=choose_photo, pady=6).pack(
        side='left', padx=(8, 0), pady=(3, 0))
    caption(si.body, '任务要求拍照时上传这张图片；留空则使用内置占位二维码。', wrap=700).pack(fill='x')

    adv = card(inner_basic, '高级设置', '通常留空即可，程序会自动解析学校域名与登录地址',
               icon='\uE713')
    r = row(adv.body)
    field(cell(r), 'host', '服务器 host', '例如 xxx.campusphere.net，仅当无法自动解析时填写')
    field(cell(r, 0), 'idsUrl', '认证地址', '例如 https://xxx.campusphere.net/iap')
    r = row(adv.body, 0)
    field(r, 'javaPath', 'java.exe 路径',
          '仅当程序找不到 Java 时填写，例如 C:\\Program Files\\Java\\jdk-11\\bin\\java.exe', wrap=700)

    res = card(inner_basic, '检测结果', '点击右上角「检测配置」，这里会列出当前能否签到的判断依据',
               icon='\uE73E')
    result_box = style_text(tk.Text(res.body, height=9, wrap='word'), mono=False)
    result_box.pack(fill='x')
    result_box.configure(state='disabled')

    # ---------- 自动签到 ----------
    time_var = tk.StringVar(value=str((cfg.get('schedule') or {}).get('time') or '22:03'))
    day_vars = []
    saved_days = list((cfg.get('schedule') or {}).get('days') or [0, 1, 2, 3, 4])

    when = card(inner_auto, '执行时间', '每天在设定时间自动签到，电脑需保持开机并已登录当前账户',
                icon='\uE823')
    r = row(when.body, 0)
    tcell = cell(r, 0)
    tk.Label(tcell, text='签到时间', bg=THEME['card'], fg=THEME['text_dim'],
             font=(FONT_UI, 9)).pack(anchor='w', pady=(0, 6))
    th = tk.Frame(tcell, bg=THEME['card'])
    th.pack(fill='x')
    EntryBox(th, textvariable=time_var, width=150, height=54, radius=12,
             style='TimeFlat.TEntry', font=(FONT_MONO, 16, 'bold')).pack(side='left')
    tk.Label(th, text='24 小时制，例如 22:03', bg=THEME['card'], fg=THEME['faint'],
             font=(FONT_UI, 8)).pack(side='left', padx=(14, 0), pady=(20, 0))

    qrow = tk.Frame(when.body, bg=THEME['card'])
    qrow.pack(fill='x', pady=(16, 0))
    tk.Label(qrow, text='快捷时间', bg=THEME['card'], fg=THEME['faint'],
             font=(FONT_UI, 8)).pack(side='left', padx=(0, 12))
    for label in ('08:00', '12:30', '18:00', '22:03'):
        Btn(qrow, label, command=lambda v=label: time_var.set(v), pady=5).pack(
            side='left', padx=(0, 8))

    wd = card(inner_auto, '重复星期', '只选需要自动签到的日子，周末没课可以不选',
              icon='\uE787')
    prow = tk.Frame(wd.body, bg=THEME['card'])
    prow.pack(anchor='w')
    for index, name in enumerate(WEEK_NAMES):
        var = tk.BooleanVar(value=index in saved_days)
        day_vars.append(var)
        PillToggle(prow, name, var).pack(side='left', padx=(0, 8))

    quick = tk.Frame(wd.body, bg=THEME['card'])
    quick.pack(fill='x', pady=(16, 0))
    tk.Label(quick, text='快捷选择', bg=THEME['card'], fg=THEME['faint'],
             font=(FONT_UI, 8)).pack(side='left', padx=(0, 10))
    for name, days in PRESETS:
        Btn(quick, name.split('（')[0], pady=5,
            command=lambda d=days: [v.set(i in d) for i, v in enumerate(day_vars)]
            ).pack(side='left', padx=(0, 8))

    task = card(inner_auto, '计划任务',
                '任务名称 %s，与现有的 TodaySchoolAutoSign 完全独立，不会互相影响' % TASK_NAME,
                icon='\uE7C3')
    schedule_status = style_text(tk.Text(task.body, height=8, wrap='word'), color=THEME['purple'])
    schedule_status.pack(fill='both', expand=True)
    schedule_status.configure(state='disabled')
    caption(task.body, '创建后 Windows 会按设定的时间自动运行本程序，可在「任务计划程序」中查看或删除。',
            wrap=700).pack(fill='x', pady=(10, 0))

    # ---------- 日志 ----------
    log_wrap = log_canvas.master
    log_wrap.pack_forget()
    log_hold = tk.Frame(page_log, bg=bg)
    log_hold.pack(fill='both', expand=True, padx=S(34), pady=(S(16), S(16)))
    log_card = Card(log_hold, pady=20, auto_height=False)
    log_card.pack(fill='both', expand=True)
    lhead = tk.Frame(log_card.body, bg=THEME['card'])
    lhead.pack(fill='x', pady=(0, S(14)))
    live = tk.Canvas(lhead, width=S(8), height=S(8), bg=THEME['card'],
                     highlightthickness=0, bd=0)
    live.pack(side='left', pady=(5, 0), padx=(0, S(9)))
    live.create_oval(0, 0, S(8), S(8), fill=THEME['cyan'], outline='')
    tk.Label(lhead, text='实时输出', bg=THEME['card'], fg=text,
             font=(FONT_UI, 11, 'bold')).pack(side='left')
    tk.Label(lhead, text=log_dir(), bg=THEME['card'], fg=THEME['faint'],
             font=(FONT_UI, 8)).pack(side='left', padx=(S(12), 0), pady=(3, 0))
    log_box = style_text(tk.Text(log_card.body, wrap='word'), color=THEME['log_text'])
    log_box.pack(fill='both', expand=True)
    log_box.configure(state='disabled')

    def open_log_dir():
        os.startfile(log_dir())

    def clear_log():
        log_box.configure(state='normal')
        log_box.delete('1.0', 'end')
        log_box.configure(state='disabled')

    Btn(actions_log, '打开日志目录', command=open_log_dir, bg=bg, height=40).pack(
        side='right', padx=(S(10), 0))
    Btn(actions_log, '清空显示', command=clear_log, bg=bg, height=40).pack(side='right')

    # ---------- 交互逻辑 ----------
    ui_queue = queue.Queue()
    session_logger = Logger('gui', sink=lambda line: ui_queue.put(('log', line)))
    busy = [False]

    def append_text(widget, text):
        widget.configure(state='normal')
        widget.insert('end', text)
        widget.see('end')
        widget.configure(state='disabled')

    def set_result(text):
        result_box.configure(state='normal')
        result_box.delete('1.0', 'end')
        result_box.insert('1.0', text)
        result_box.configure(state='disabled')
        result_box.see('1.0')
        root.update_idletasks()
        total = max(1, inner_basic.winfo_reqheight())
        target = res.winfo_y() - 12
        basic_canvas.yview_moveto(min(1.0, max(0.0, target / float(total))))

    def collect_config():
        data = dict(cfg)
        for key, var in vars_.items():
            data[key] = var.get().strip()
        data['photo'] = photo_var.get().strip()
        data['schedule'] = {
            'days': [i for i, var in enumerate(day_vars) if var.get()],
            'time': time_var.get().strip(),
        }
        return data

    def persist(quiet=False):
        try:
            data = collect_config()
            validate_config(data)
            save_config(data)
            cfg.update(data)
            if not quiet:
                set_status('配置已保存到 %s' % config_path(), 'ok')
            refresh_metrics()
            return True
        except Exception as e:
            set_status(str(e), 'bad')
            if not quiet:
                messagebox.showwarning('配置不完整', str(e))
            return False

    def refresh_metrics():
        school = vars_.get('school').get().strip()
        user = vars_.get('username').get().strip()
        m_acc.configure(text=school or '未填写学校')
        m_acc_sub.configure(text=('学号 ' + user) if user else '在下方补充账号信息')
        lon = vars_.get('lon').get().strip()
        lat = vars_.get('lat').get().strip()
        try:
            pair = '%.4f, %.4f' % (float(lon), float(lat))
        except (TypeError, ValueError):
            pair = ''
        m_loc.configure(text=pair or '未设置坐标')
        m_loc_sub.configure(text='高德 GCJ-02 坐标系' if pair else '用地图选点快速填写')
        days = [i for i, var in enumerate(day_vars) if var.get()]
        m_plan.configure(text=time_var.get().strip() or '未设置时间')
        m_plan_sub.configure(text=('每周 %d 天自动执行' % len(days)) if days else '尚未选择重复日')

    for key in ('school', 'username', 'lon', 'lat'):
        vars_[key].trace_add('write', lambda *_: refresh_metrics())
    time_var.trace_add('write', lambda *_: refresh_metrics())
    for var in day_vars:
        var.trace_add('write', lambda *_: refresh_metrics())
    refresh_metrics()

    def set_busy(value, message=''):
        busy[0] = value
        for button in action_buttons:
            button.configure(state='disabled' if value else 'normal')
        if message:
            set_status(message, 'warn' if value else 'hint')

    def start_job(func, done_text):
        if busy[0]:
            return
        if not persist(quiet=True):
            return
        data = collect_config()
        set_busy(True, '正在执行，请稍候……')
        show_tab('log')

        def worker():
            try:
                text = func(data, session_logger)
                ui_queue.put(('result', text))
                ui_queue.put(('status', done_text, 'ok'))
            except Exception as e:
                session_logger('失败：%s' % e)
                session_logger(traceback.format_exc())
                ui_queue.put(('result', '执行失败：%s' % e))
                ui_queue.put(('status', '执行失败：%s' % e, 'bad'))
            finally:
                ui_queue.put(('done', None))

        threading.Thread(target=worker, daemon=True).start()

    def poll_queue():
        try:
            while True:
                item = ui_queue.get_nowait()
                kind = item[0]
                if kind == 'log':
                    append_text(log_box, item[1] + '\n')
                elif kind == 'result':
                    show_tab('basic')
                    set_result(item[1])
                elif kind == 'status':
                    set_status(item[1], 'ok' if item[2] == 'ok' else 'bad')
                elif kind == 'sched':
                    schedule_status.configure(state='normal')
                    schedule_status.delete('1.0', 'end')
                    schedule_status.insert('1.0', item[1])
                    schedule_status.configure(state='disabled')
                elif kind == 'picked':
                    map_button.configure(state='normal')
                    data = item[1]
                    if data and data.get('lon') is not None and data.get('lat') is not None:
                        vars_['lon'].set('%.6f' % float(data['lon']))
                        vars_['lat'].set('%.6f' % float(data['lat']))
                        set_status('已从地图选取坐标（%.6f, %.6f），记得点「保存配置」生效。'
                                   % (float(data['lon']), float(data['lat'])), 'ok')
                        session_logger('地图选点：%s' % data.get('info', ''))
                    elif data and data.get('error'):
                        set_status('地图选点失败：%s' % data['error'], 'bad')
                        session_logger('地图选点失败：%s' % data['error'])
                    else:
                        set_status('已取消地图选点。')
                elif kind == 'done':
                    set_busy(False)
        except queue.Empty:
            pass
        root.after(120, poll_queue)

    def on_save():
        persist()

    def on_check():
        start_job(run_check, '检测完成')

    def on_sign():
        if not persist(quiet=True):
            return
        if not messagebox.askyesno('确认签到', '将立即向学校提交签到，确认继续？'):
            return
        start_job(run_sign, '签到流程结束')

    def on_create_schedule():
        if not persist(quiet=True):
            return
        days = [i for i, var in enumerate(day_vars) if var.get()]
        hhmm = time_var.get().strip()

        def worker():
            try:
                text = create_schedule(days, hhmm)
                session_logger('已创建计划任务 %s：%s %s' % (TASK_NAME, hhmm, ','.join(
                    WEEK_NAMES[d] for d in sorted(days))))
                ui_queue.put(('sched', text))
                ui_queue.put(('status', '计划任务已创建/更新', 'ok'))
            except Exception as e:
                session_logger('创建计划任务失败：%s' % e)
                ui_queue.put(('sched', str(e)))
                ui_queue.put(('status', str(e), 'bad'))

        threading.Thread(target=worker, daemon=True).start()

    def on_delete_schedule():
        if not messagebox.askyesno('确认删除', '确定删除计划任务 %s？' % TASK_NAME):
            return

        def worker():
            try:
                session_logger(delete_schedule())
                ui_queue.put(('sched', query_schedule()))
                ui_queue.put(('status', '计划任务已删除', 'ok'))
            except Exception as e:
                ui_queue.put(('status', str(e), 'bad'))

        threading.Thread(target=worker, daemon=True).start()

    def on_query_schedule():
        def worker():
            ui_queue.put(('sched', query_schedule()))
        threading.Thread(target=worker, daemon=True).start()

    def on_pick_map():
        out_path = os.path.join(tempfile.gettempdir(), 'cpdaily_picker_%d.json' % os.getpid())
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except OSError:
            pass
        lon_val = vars_['lon'].get().strip()
        lat_val = vars_['lat'].get().strip()
        for value in (lon_val, lat_val):
            if value:
                try:
                    float(value)
                except ValueError:
                    messagebox.showwarning('坐标格式', '经度/纬度需为数字，例如 116.397428')
                    return
        map_button.configure(state='disabled')
        set_status('正在打开内置地图，请在地图上单击选择位置……')
        try:
            proc = subprocess.Popen(picker_command(out_path, lon_val, lat_val))
        except Exception as e:
            map_button.configure(state='normal')
            messagebox.showerror('无法打开地图', str(e))
            return

        def worker():
            try:
                proc.wait(timeout=900)
            except Exception:
                pass
            data = None
            if os.path.exists(out_path):
                try:
                    with open(out_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception:
                    data = None
                try:
                    os.remove(out_path)
                except OSError:
                    pass
            ui_queue.put(('picked', data))

        threading.Thread(target=worker, daemon=True).start()

    action_buttons = []
    save_button = Btn(actions_basic, '保存配置', command=on_save, bg=bg, height=40)
    check_button = Btn(actions_basic, '检测配置', command=on_check, kind='purple',
                       bg=bg, height=40)
    sign_button = Btn(actions_basic, '立即签到', command=on_sign, kind='primary',
                      bg=bg, height=40)
    sign_button.pack(side='right', padx=(S(10), 0))
    check_button.pack(side='right', padx=(S(10), 0))
    save_button.pack(side='right')
    action_buttons += [save_button, check_button, sign_button, map_button]

    create_button = Btn(actions_auto, '创建 / 更新计划任务', command=on_create_schedule,
                        kind='primary', bg=bg, height=40)
    delete_button = Btn(actions_auto, '删除计划任务', command=on_delete_schedule,
                        kind='danger', bg=bg, height=40)
    query_button = Btn(actions_auto, '查看状态', command=on_query_schedule,
                       bg=bg, height=40)
    create_button.pack(side='right')
    delete_button.pack(side='right', padx=(S(10), 0))
    query_button.pack(side='right', padx=(S(10), 0))

    # 窗口映射完成后去掉系统标题栏（只做一次，避免切换主题时反复改窗口样式）
    def ensure_frameless(_event=None):
        if not frameless_done[0]:
            root.after(60, strip_native_titlebar)

    root.bind('<Map>', ensure_frameless)
    root.after(300, strip_native_titlebar)
    poll_queue()
    root.after(300, on_query_schedule)
    root.mainloop()


def main(argv=None):
    parser = argparse.ArgumentParser(description='今日校园签到助手')
    parser.add_argument('--auto', action='store_true', help='按配置静默签到（供计划任务调用）')
    parser.add_argument('--check', action='store_true', help='命令行检测配置与任务')
    parser.add_argument('--picker', action='store_true', help='打开内置地图选点窗口')
    parser.add_argument('--out', default='', help='地图选点结果的保存路径')
    parser.add_argument('--lon', default='', help='地图初始经度')
    parser.add_argument('--lat', default='', help='地图初始纬度')
    parser.add_argument('--picker-selftest', action='store_true', help='地图选点自检')
    args = parser.parse_args(argv)

    requests.packages.urllib3.disable_warnings()
    if args.picker or args.picker_selftest:
        out = args.out or os.path.join(tempfile.gettempdir(), 'cpdaily_picker.json')
        try:
            ok = run_picker(out, args.lon, args.lat, selftest=args.picker_selftest)
            return 0 if ok else 1
        except Exception as e:
            try:
                with open(out, 'w', encoding='utf-8') as f:
                    json.dump({'error': str(e)}, f, ensure_ascii=False)
            except Exception:
                pass
            return 1
    if args.auto:
        return cli_run(check_only=False)
    if args.check:
        return cli_run(check_only=True)
    enable_dpi_awareness()
    while True:
        run_gui()
        if not _RESTART['pending']:
            break
        _RESTART['pending'] = False
    return 0


if __name__ == '__main__':
    sys.exit(main())
