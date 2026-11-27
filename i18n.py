"""网站中 / 英切换。

做法：在网站一开始调用 install()，把 Streamlit 显示文字的函数（标题、按钮、说明、表格栏名、图表标题…）包一层：
切到 EN 时，把文字里的中文词组按 i18n_en.EN 翻成英文；找不到的词组维持中文（例如自动报告、新闻分析内容）。
程序里用的值（例如页面名称、选项）不变，只换「显示出来的样子」，所以切换语言不会弄坏任何功能。

AI 现场分析：managers.LANG = "EN" 时，AI 会用英文写（见 managers.chat）。
"""
from __future__ import annotations

import functools
import re

import streamlit as st

from i18n_en import EN

CJK = re.compile(r"[一-鿿]+")
PUNCT = [("，", ", "), ("。", ". "), ("：", ": "), ("；", "; "), ("（", " ("), ("）", ") "), ("、", ", "),
         ("！", "! "), ("？", "? "), ("「", "“"), ("」", "”"), ("《", "“"), ("》", "”"), ("【", "["), ("】", "] "),
         ("～", "~"), ("　", " ")]
_installed = False


def lang() -> str:
    try:
        return st.session_state.get("lang", "中文")
    except Exception:
        return "中文"


def is_en() -> bool:
    return lang() == "EN"


MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WK = dict(zip("一二三四五六日天", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun", "Sun"]))
DATE_RULES = [
    (re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"), lambda m: f"{int(m[3])} {MON[int(m[2]) - 1]} {m[1]}"),
    (re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日"), lambda m: f"{int(m[2])} {MON[int(m[1]) - 1]}"),
    (re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月"), lambda m: f"{MON[int(m[2]) - 1]} {m[1]}"),
    (re.compile(r"(?:星期|周)([一二三四五六日天])"), lambda m: f" ({WK[m[1]]})"),
    (re.compile(r"(\d+)\s*天前"), lambda m: f"{m[1]} days ago"),
    (re.compile(r"还有\s*(\d+)\s*天"), lambda m: f"in {m[1]} days"),
    (re.compile(r"昨天"), lambda m: "yesterday"),
]
FIXES = [(re.compile(r"(\d) -(?=[a-z])"), r"\1-"),                      # 52 -week → 52-week
         (re.compile(r"\b1 (month|year|day|week|stock|company|item|hour)s\b"), r"1 \1"),
         (re.compile(r"\b(\S{2,}) \1\b"), r"\1")]                         # P/E P/E → P/E


@functools.lru_cache(maxsize=20000)
def _tr(text: str) -> str:
    for rx, fn in DATE_RULES:
        text = rx.sub(fn, text)
    missing = False
    out, last = [], 0
    for m in CJK.finditer(text):
        out.append(text[last:m.start()])
        word = m.group()
        t = EN.get(word)
        if t is None:
            missing = True
            out.append(word)
        else:
            before = text[m.start() - 1] if m.start() > 0 else " "
            after = text[m.end()] if m.end() < len(text) else " "
            if t and (before.isalnum() or before in ")%]") and not out[-1].endswith(" "):
                t = " " + t
            if t and (after.isalnum() or after in "(["):
                t = t + " "
            out.append(t)
        last = m.end()
    out.append(text[last:])
    s = "".join(out)
    if not missing:                                   # 整句都翻好了才换标点（避免把中文内容的标点换掉）
        for a, b in PUNCT:
            s = s.replace(a, b)
        s = re.sub(r"(?<=\S) {2,}(?=\S)", " ", s)
        s = re.sub(r" +([,.:;)!?%])", r"\1", s)
        s = re.sub(r"\( +", "(", s)
    for rx, rep in FIXES:
        s = rx.sub(rep, s)
    return s


def tr(x):
    """把显示文字翻成英文（中文模式或不是文字就原样返回）。"""
    if not isinstance(x, str) or not is_en() or not CJK.search(x):
        return x
    return _tr(x)


# ---------------------------------------------------------------------------
# 包装 Streamlit
# ---------------------------------------------------------------------------

TEXT_KW = ("label", "placeholder", "help", "body", "text", "caption", "value_label")
FIRST_ARG = ["title", "header", "subheader", "markdown", "caption", "text", "info", "warning", "error", "success",
             "button", "download_button", "form_submit_button", "link_button", "expander", "popover", "checkbox",
             "toggle", "text_input", "number_input", "text_area", "file_uploader", "slider", "date_input",
             "color_picker", "html", "latex", "data_editor", "camera_input", "page_link"]
CHOICE = ["radio", "selectbox", "multiselect", "pills", "segmented_control", "select_slider", "feedback"]


def _fix_kwargs(kw: dict):
    for k in TEXT_KW:
        if k in kw:
            kw[k] = tr(kw[k])


def _wrap_first(fn):
    @functools.wraps(fn)
    def w(self, *a, **kw):
        if is_en():
            if a and isinstance(a[0], str):
                a = (tr(a[0]),) + a[1:]
            _fix_kwargs(kw)
        return fn(self, *a, **kw)
    return w


def _wrap_choice(fn):
    @functools.wraps(fn)
    def w(self, *a, **kw):
        if is_en():
            if a and isinstance(a[0], str):
                a = (tr(a[0]),) + a[1:]
            _fix_kwargs(kw)
            orig = kw.get("format_func") or str
            kw["format_func"] = lambda v, _o=orig: tr(_o(v))
        return fn(self, *a, **kw)
    return w


def _wrap_write(fn):
    @functools.wraps(fn)
    def w(self, *a, **kw):
        if is_en():
            a = tuple(tr(x) if isinstance(x, str) else x for x in a)
        return fn(self, *a, **kw)
    return w


def _wrap_tabs(fn):
    @functools.wraps(fn)
    def w(self, tabs, *a, **kw):
        if is_en():
            tabs = [tr(t) for t in tabs]
            if isinstance(kw.get("default"), str):
                kw["default"] = tr(kw["default"])
        return fn(self, tabs, *a, **kw)
    return w


def _wrap_metric(fn):
    @functools.wraps(fn)
    def w(self, label, value=None, delta=None, *a, **kw):
        if is_en():
            label, value = tr(label), tr(value)
            delta = tr(delta)
            _fix_kwargs(kw)
        return fn(self, label, value, delta, *a, **kw)
    return w


def _tr_df(data, kw):
    import pandas as pd
    if isinstance(data, pd.DataFrame):
        cols = {c: tr(c) for c in data.columns if isinstance(c, str)}
        if any(k != v for k, v in cols.items()):
            data = data.rename(columns=cols)
            cc = kw.get("column_config")
            if isinstance(cc, dict):
                kw["column_config"] = {cols.get(k, k): v for k, v in cc.items()}
            for key in ("column_order",):
                if kw.get(key):
                    kw[key] = [cols.get(c, c) for c in kw[key]]
        if data.index.dtype == object:
            data = data.rename(index=lambda i: tr(i) if isinstance(i, str) else i)
        obj = data.select_dtypes(include="object").columns
        if len(obj):
            data = data.copy()
            for c in obj:
                data[c] = data[c].map(lambda v: tr(v) if isinstance(v, str) else v)
    return data


def _wrap_df(fn):
    @functools.wraps(fn)
    def w(self, data=None, *a, **kw):
        if is_en():
            data = _tr_df(data, kw)
        return fn(self, data, *a, **kw)
    return w


def _wrap_chart(fn):
    @functools.wraps(fn)
    def w(self, data=None, *a, **kw):
        if is_en():
            import pandas as pd
            if isinstance(data, pd.DataFrame):
                data = data.rename(columns=lambda c: tr(c) if isinstance(c, str) else c)
            _fix_kwargs(kw)
        return fn(self, data, *a, **kw)
    return w


def _tr_fig(fig):
    try:
        lay = fig.layout
        if lay.title and lay.title.text:
            lay.title.text = tr(lay.title.text)
        for ax in ("xaxis", "yaxis", "yaxis2"):
            a = getattr(lay, ax, None)
            if a is not None and a.title and a.title.text:
                a.title.text = tr(a.title.text)
        for ann in lay.annotations or []:
            if ann.text:
                ann.text = tr(ann.text)
        for t in fig.data:
            if getattr(t, "name", None):
                t.name = tr(t.name)
            if getattr(t, "labels", None) is not None:
                t.labels = [tr(v) for v in t.labels]
            for k in ("x", "y"):
                v = getattr(t, k, None)
                if v is not None and len(v) and isinstance(v[0], str):
                    setattr(t, k, [tr(i) for i in v])
            if getattr(t, "hovertemplate", None):
                t.hovertemplate = tr(t.hovertemplate)
    except Exception:
        pass
    return fig


def _wrap_plotly(fn):
    @functools.wraps(fn)
    def w(self, fig, *a, **kw):
        if is_en():
            fig = _tr_fig(fig)
        return fn(self, fig, *a, **kw)
    return w


def install():
    """在 app.py 一开始调用一次。"""
    global _installed
    if _installed:
        return
    _installed = True
    from streamlit.delta_generator import DeltaGenerator as DG
    for name in FIRST_ARG:
        if hasattr(DG, name):
            setattr(DG, name, _wrap_first(getattr(DG, name)))
    for name in CHOICE:
        if hasattr(DG, name):
            setattr(DG, name, _wrap_choice(getattr(DG, name)))
    DG.write = _wrap_write(DG.write)
    DG.tabs = _wrap_tabs(DG.tabs)
    DG.metric = _wrap_metric(DG.metric)
    DG.dataframe = _wrap_df(DG.dataframe)
    DG.table = _wrap_df(DG.table)
    for name in ("line_chart", "bar_chart", "area_chart", "scatter_chart"):
        setattr(DG, name, _wrap_chart(getattr(DG, name)))
    DG.plotly_chart = _wrap_plotly(DG.plotly_chart)
    # st.xxx 是在 import 时绑定好的，要重新绑定到包好的版本
    main, side = st._main, st.sidebar
    for name in FIRST_ARG + CHOICE + ["write", "tabs", "metric", "dataframe", "table", "line_chart", "bar_chart",
                                      "area_chart", "scatter_chart", "plotly_chart"]:
        if hasattr(DG, name) and hasattr(st, name):
            setattr(st, name, getattr(main, name))
    # spinner / toast / progress 不是 DeltaGenerator 的方法
    _spinner = st.spinner

    def spinner(text="In progress...", *a, **kw):
        return _spinner(tr(text), *a, **kw)
    st.spinner = spinner
    _toast = st.toast
    st.toast = lambda body, *a, **kw: _toast(tr(body), *a, **kw)
    _progress = DG.progress

    def progress(self, value, text=None, *a, **kw):
        return _progress(self, value, tr(text), *a, **kw)
    DG.progress = progress
    st.progress = main.progress
    # 进度条的 .progress(text=…) 更新：在 Streamlit 里也是同一个方法
