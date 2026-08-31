"""Build a tiny fake xml-p5 tree for catalog_index / corpus_sync tests."""

from __future__ import annotations

from pathlib import Path

_TMPL = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0" xmlns:cb="http://www.cbeta.org/ns/1.0">
  <teiHeader><fileDesc>
    <titleStmt>
      <title>Taisho Tripitaka, Electronic version, No. {no} {title}</title>
      <author>{author}</author>
    </titleStmt>
    <extent>{juan_n}卷</extent>
    <sourceDesc><bibl>Taisho Tripitaka Vol. {volnum}, No. {no}</bibl></sourceDesc>
  </fileDesc></teiHeader>
  <text><body>
{juan}
  </body></text>
</TEI>
"""


def write_work(root: Path, stem: str, *, title: str, author: str, juan: int = 1) -> Path:
    canon = stem[: 1 if stem[1].isdigit() else 2]
    volnum = stem[len(canon) : stem.index("n")]
    vol = f"{canon}{volnum}"
    no = stem[stem.index("n") + 1 :]
    juan_xml = "\n".join(
        f'    <milestone n="{i + 1}" unit="juan"/>'
        f'<cb:juan n="{i + 1:03d}" fun="open"><cb:jhead>{title}卷{i + 1}</cb:jhead></cb:juan>'
        f"<p>正文{i + 1}。</p>"
        for i in range(juan)
    )
    path = root / canon / vol / f"{stem}.xml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _TMPL.format(
            no=no, title=title, author=author, juan=juan_xml, juan_n=juan, volnum=int(volnum)
        ),
        "utf-8",
    )
    return path


def build_fake_corpus(root: Path) -> Path:
    write_work(root, "T01n0001", title="長阿含經", author="後秦 佛陀耶舍共竺佛念譯", juan=2)
    write_work(root, "T02n0128a", title="須摩提女經", author="吳 支謙譯", juan=1)
    write_work(root, "T02n0128b", title="須摩提女經", author="劉宋 求那跋陀羅譯", juan=1)
    write_work(root, "T02n0150A", title="七處三觀經", author="後漢 安世高譯", juan=1)
    write_work(root, "T02n0150B", title="九橫經", author="後漢 安世高譯", juan=1)
    write_work(root, "L130n1557", title="阿毘達磨大毘婆沙論", author="唐 玄奘譯", juan=3)
    write_work(root, "L131n1557", title="阿毘達磨大毘婆沙論", author="唐 玄奘譯", juan=4)
    write_work(root, "T05n0220a", title="大般若波羅蜜多經", author="唐 玄奘譯", juan=2)
    write_work(root, "T06n0220b", title="大般若波羅蜜多經", author="唐 玄奘譯", juan=2)
    return root
