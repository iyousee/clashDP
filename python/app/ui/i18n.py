"""
i18n.py —— 中英界面切换（极简方案）
用法：在界面代码里直接写  _("中文", "English")，程序按当前语言返回对应文本。
大白话：不用 Qt 那套繁琐的 .ts/.qm 翻译文件，就用一个函数搞定双语。
"""
# 当前语言：'zh' 中文 / 'en' 英文
current = "zh"


def set_lang(lang):
    """切换语言。lang 取 'zh' 或 'en'。"""
    global current
    current = lang


def _(zh, en):
    """根据当前语言返回中文或英文。"""
    return zh if current == "zh" else en
