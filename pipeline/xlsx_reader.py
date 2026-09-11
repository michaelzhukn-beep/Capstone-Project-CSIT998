"""最小可用的 .xlsx 读取器,只用标准库。V6。

## 为什么不用 openpyxl

实测在本机的 Python 3.14 上,openpyxl 3.1.5 读同一份文件**时好时坏**:
只读模式报 `'code' object has no attribute 'get'`,非只读模式报
`'Cell' object is not callable` —— 都是库内部的错,和文件本身无关。

抓数据的脚本是**一次性、要能被别人重跑**的东西。依赖一个随时会挂的库,
等于把"能不能复现"交给运气。xlsx 本质上就是一个装着 XML 的 zip,
自己读六十行就够,而且从此不再有这个依赖。

只实现读取所需的部分:共享字符串、单元格值、按行返回。不支持公式求值
(用 data_only 的场景本来也只要值)、不支持样式、不写入。
"""

import re
import zipfile
from xml.etree import ElementTree

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_DOC_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_COL = re.compile(r"([A-Z]+)")


def _col_index(ref: str) -> int:
    """单元格坐标 -> 列号(0 起)。"A1"->0,"AB7"->27。"""
    match = _COL.match(ref or "")
    if not match:
        return 0
    index = 0
    for char in match.group(1):
        index = index * 26 + (ord(char) - 64)
    return index - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    """共享字符串表。文本单元格存的是这张表的下标,不是文本本身。"""
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    out = []
    for si in root.findall(f"{_NS}si"):
        # 一个 si 可能被拆成多段富文本(<r><t>),要拼起来
        out.append("".join(node.text or "" for node in si.iter(f"{_NS}t")))
    return out


def sheet_names(path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        return [s.get("name") for s in root.iter(f"{_NS}sheet")]


def _sheet_path(archive: zipfile.ZipFile, name: str) -> str:
    root = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    rid = next((s.get(f"{_DOC_REL}id") for s in root.iter(f"{_NS}sheet")
                if s.get("name") == name), None)
    if rid is None:
        raise KeyError(f"工作表 {name!r} 不存在。可用的:{sheet_names_from(root)}")
    rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    target = next(r.get("Target") for r in rels.iter(f"{_REL_NS}Relationship")
                  if r.get("Id") == rid)
    target = target.lstrip("/")
    return target if target.startswith("xl/") else f"xl/{target}"


def sheet_names_from(root) -> list[str]:
    return [s.get("name") for s in root.iter(f"{_NS}sheet")]


def read_rows(path, sheet: str):
    """逐行产出一个工作表。每行是一个 list,空单元格补 None。

    用 iterparse 流式解析:CSA 那份表有 34 万行,一次性读进内存没必要。
    """
    with zipfile.ZipFile(path) as archive:
        strings = _shared_strings(archive)
        with archive.open(_sheet_path(archive, sheet)) as handle:
            row: list = []
            for event, element in ElementTree.iterparse(handle, events=("end",)):
                if element.tag == f"{_NS}c":
                    index = _col_index(element.get("r", ""))
                    while len(row) <= index:
                        row.append(None)
                    kind = element.get("t")
                    if kind == "s":                       # 共享字符串下标
                        node = element.find(f"{_NS}v")
                        text = node.text if node is not None else None
                        row[index] = (strings[int(text)]
                                      if text is not None and text.isdigit() else None)
                    elif kind == "inlineStr":             # 内联字符串
                        row[index] = "".join(t.text or "" for t in element.iter(f"{_NS}t"))
                    else:                                 # 数字 / 布尔 / 日期序列号
                        node = element.find(f"{_NS}v")
                        text = node.text if node is not None else None
                        if text is None:
                            row[index] = None
                        else:
                            try:
                                value = float(text)
                                row[index] = int(value) if value.is_integer() else value
                            except ValueError:
                                row[index] = text
                    element.clear()
                elif element.tag == f"{_NS}row":
                    yield row
                    row = []
                    element.clear()


def read_table(path, sheet: str) -> tuple[list[str], list[list]]:
    """读成 (表头, 数据行)。第一行当表头。"""
    rows = read_rows(path, sheet)
    header = [str(h) if h is not None else "" for h in next(rows)]
    return header, [r for r in rows if any(v is not None for v in r)]
