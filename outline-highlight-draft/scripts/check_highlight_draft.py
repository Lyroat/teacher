#!/usr/bin/env python3
"""Check outline-highlight-draft Markdown structure and countable body length.

字数统计采用正向白名单：只统计 docs/output-contract.md 「字数」一节明确列为
“计入正文”的区域，其余一律不计入，并在输出中逐项列出，便于与人工统计对照。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# 数值来源：docs/output-contract.md 的「字数」一节。
# 该节是唯一权威来源；修改字数标准时必须同步改这里，不得只改一处。
COUNT_TARGET = 1200
COUNT_MIN = 1170
COUNT_MAX = 1230

# 硬性要求：超出即 FAIL。两项都可通过拆句或改写陈述句修复，属 self-check 的 [自动修正] 范围。
PARAGRAPH_MAX = 180
QUESTION_MAX = 8

# 软性建议：超出只 WARNING，需人工判断。
SUMMARY_MIN = 200
SUMMARY_MAX = 250
FUN_MAX_COUNT = 1
FUN_MAX_CHARS = 100

# 依赖互动表格的表述：删除表格后这些句子会失去指向
INTERACTION_DEP_PHRASES = [
    "刚才的探索",
    "刚才的实验",
    "刚才的模拟",
    "你刚才看到",
    "刚才你看到",
    "上面的探索",
    "上面的实验",
    "刚才的操作",
]

FORBIDDEN = [
    "<span",
    "background-color",
    '"',
]

INTERACTION_REQUIRED = [
    "互动探索位置",
    "探索问题",
    "预测问题",
    "选项 A",
    "选项 B",
    "正确答案",
    "操作探索",
    "观察分析",
    "得出结论",
]

# 「题型」是后加的要求，早于该要求的旧稿普遍没有，只 WARNING 不 FAIL
INTERACTION_RECOMMENDED = ["题型"]

SECTION_INTRO = "【引入】"
SECTION_INTERACTION = "【互动探索】"
SECTION_SUMMARY = "【大总结】"

FUN_OPEN = "**【趣味拓展】**"
FUN_CLOSE = "**【/趣味拓展】**"
MAINLINE_TAG = "（回答主线问题）"

LABEL_META = "文件元信息"
LABEL_FUN = "趣味拓展"
LABEL_TABLE = "【互动探索】表格"
LABEL_OTHER_TABLE = "其他表格"

def section_name(line: str) -> str | None:
    match = re.match(r"^##\s+(.+?)\s*$", line)
    return match.group(1) if match else None


def is_heading(line: str) -> bool:
    return bool(re.match(r"^\s*#{1,6}\s+", line))


def is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def strip_markdown(line: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", line)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^[>\-\*\d\.\s]+", "", text)
    return text.strip()


def count_readable_chars(text: str) -> int:
    """统计可朗读字符数。

    汉字和标点符号逐字计入；连续的字母/数字串按 1 个字计（“2019”算 1 字）；
    空白字符不计。计法以 docs/output-contract.md「字数」一节为准。
    """
    runs = re.findall(r"[A-Za-z0-9]+", text)
    extra = sum(len(run) - 1 for run in runs)
    compact = re.sub(r"\s", "", text)
    return len(compact) - extra


def count_questions(text: str) -> int:
    return text.count("？") + text.count("?")


def split_fun_ranges(line: str, inside: bool) -> tuple[list[str], list[str], bool]:
    """把一行按趣味拓展起止标记拆成 (计入片段, 趣味拓展片段, 行尾是否仍在标记内)。"""
    plain: list[str] = []
    fun: list[str] = []
    rest = line
    while rest:
        if inside:
            idx = rest.find(FUN_CLOSE)
            if idx == -1:
                fun.append(rest)
                break
            fun.append(rest[:idx])
            rest = rest[idx + len(FUN_CLOSE):]
            inside = False
        else:
            idx = rest.find(FUN_OPEN)
            if idx == -1:
                plain.append(rest)
                break
            plain.append(rest[:idx])
            rest = rest[idx + len(FUN_OPEN):]
            inside = True
    return plain, fun, inside


def analyse(lines: list[str]) -> dict[str, object]:
    """逐行归类，返回分项字数、问题句数、超长段落和趣味拓展闭合情况。"""
    items: list[dict[str, object]] = []
    index: dict[str, dict[str, object]] = {}

    def bucket(label: str, counted: bool) -> dict[str, object]:
        if label not in index:
            entry = {"label": label, "chars": 0, "counted": counted}
            index[label] = entry
            items.append(entry)
        return index[label]

    current_section = ""
    current_label = LABEL_META
    current_counted = False
    fun_inside = False
    fun_unclosed_line = 0

    question_count = 0
    dep_hits: list[tuple[int, str]] = []
    long_paragraphs: list[tuple[int, int]] = []
    paragraph_start = 0
    paragraph_text: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph_start, paragraph_text
        if paragraph_text:
            size = count_readable_chars("".join(paragraph_text))
            if size > PARAGRAPH_MAX:
                long_paragraphs.append((paragraph_start, size))
        paragraph_start = 0
        paragraph_text = []

    for idx, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")
        name = section_name(line)

        if name is not None:
            flush_paragraph()
            current_section = name
            if re.match(r"^关键问题\d+：", name):
                short = re.match(r"^(关键问题\d+)", name)
                current_label = short.group(1) if short else name
                current_counted = True
            elif name == SECTION_INTERACTION:
                # 表格本身不计入；表格之后的正文归属上一个关键问题，见下方处理
                current_label = LABEL_TABLE
                current_counted = False
            else:
                current_label = name
                current_counted = False
            bucket(current_label, current_counted)
            continue

        if is_heading(line):
            flush_paragraph()
            continue

        if is_table_line(line):
            flush_paragraph()
            label = LABEL_TABLE if current_section == SECTION_INTERACTION else LABEL_OTHER_TABLE
            bucket(label, False)["chars"] += count_readable_chars(strip_markdown(line))
            continue

        if current_section == SECTION_INTERACTION and current_label == LABEL_TABLE:
            # 表格结束后的正文，按契约计入正文，归到最近的关键问题
            prev = next(
                (e["label"] for e in reversed(items)
                 if isinstance(e["label"], str) and e["label"].startswith("关键问题")),
                None,
            )
            if prev and strip_markdown(line):
                current_label = prev
                current_counted = True

        plain_parts, fun_parts, fun_inside_after = split_fun_ranges(line, fun_inside)
        if fun_inside and not fun_unclosed_line:
            pass
        if fun_inside_after and not fun_inside:
            fun_unclosed_line = idx
        if not fun_inside_after:
            fun_unclosed_line = 0
        fun_inside = fun_inside_after

        fun_text = strip_markdown(" ".join(fun_parts)) if fun_parts else ""
        if fun_text:
            bucket(LABEL_FUN, False)["chars"] += count_readable_chars(fun_text)

        plain_raw = " ".join(plain_parts)
        plain_text = strip_markdown(plain_raw).replace(MAINLINE_TAG, "")
        if not plain_text:
            flush_paragraph()
            continue

        size = count_readable_chars(plain_text)
        bucket(current_label, current_counted)["chars"] += size

        # 问题句按“可朗读口播范围”统计：引入、关键问题、互动后正文、大总结
        readable = current_counted or current_section in (SECTION_INTRO, SECTION_SUMMARY)
        if readable:
            question_count += count_questions(plain_text)
            # 正文不得依赖互动模块存在，见 output-contract.md「互动探索与正文的边界」
            for phrase in INTERACTION_DEP_PHRASES:
                if phrase in plain_text:
                    dep_hits.append((idx, phrase))

        # 段落长度只查引入和关键问题正文；
        # 大总结另有 200-250 字的独立要求，不受 180 字段落上限约束
        if current_counted or current_section == SECTION_INTRO:
            if not paragraph_text:
                paragraph_start = idx
            paragraph_text.append(plain_text)
        else:
            flush_paragraph()

    flush_paragraph()

    body_count = sum(int(e["chars"]) for e in items if e["counted"])
    summary = index.get(SECTION_SUMMARY)
    return {
        "items": items,
        "body_count": body_count,
        "summary_count": int(summary["chars"]) if summary else 0,
        "question_count": question_count,
        "long_paragraphs": long_paragraphs,
        "interaction_dependencies": dep_hits,
        "fun_unclosed_line": fun_unclosed_line if fun_inside else 0,
    }


def extract_table(lines: list[str], heading: str) -> list[str]:
    in_section = False
    table: list[str] = []
    for line in lines:
        name = section_name(line)
        if name:
            if in_section:
                break
            in_section = name == heading
            continue
        if in_section and is_table_line(line):
            table.append(line)
    return table


def table_has_rows(table: list[str], required: list[str]) -> list[str]:
    joined = "\n".join(table)
    return [row for row in required if row not in joined]


def normalise_question(text: str) -> str:
    """去掉【】标签、⭐、标点和空白，只留可比较的问题主干。"""
    text = re.sub(r"【[^】]*】", "", text)
    text = re.sub(r"^关键问题\d+[：:]\s*", "", text.strip())
    # 只保留汉字、字母和数字，标点/星标/空白差异不算不一致
    return "".join(re.findall(r"[一-鿿A-Za-z0-9]", text))


def extract_labels(text: str) -> list[str]:
    return re.findall(r"【([^】]*)】", text)


def draft_key_questions(lines: list[str]) -> list[tuple[int, str, str]]:
    """返回 (行号, 编号, 标题原文)。"""
    found: list[tuple[int, str, str]] = []
    for idx, raw in enumerate(lines, start=1):
        match = re.match(r"^##\s+关键问题(\d+)[：:]\s*(.*?)\s*$", raw.rstrip("\n"))
        if match:
            found.append((idx, match.group(1), match.group(2)))
    return found


def framework_key_questions(framework: Path, episode: str) -> list[str] | None:
    """从大纲框架里取出指定单集的关键问题标题；找不到该集返回 None。"""
    lines = framework.read_text(encoding="utf-8").splitlines()
    head_pat = rf"^#+\s*E0?{episode}\b"
    row_pat = rf"^\|?\s*\*{{0,2}}E0?{episode}\*{{0,2}}\s*\|"

    # 标题行优先；目录表格里也会出现 `| E07 | 土壤圈 |` 这类行，作为兜底候选。
    starts = [i for i, line in enumerate(lines) if re.match(head_pat, line.strip())]
    starts += [i for i, line in enumerate(lines) if re.match(row_pat, line.strip())]
    if not starts:
        return None

    for start in starts:
        end = len(lines)
        for idx in range(start + 1, len(lines)):
            stripped = lines[idx].strip()
            if re.match(r"^#+\s*E\d", stripped) and not re.match(head_pat, stripped):
                end = idx
                break
            if re.match(r"^\|?\s*\*{0,2}E\d+\*{0,2}\s*\|", stripped) and not re.match(
                row_pat, stripped
            ):
                end = idx
                break

        block = "\n".join(lines[start:end])
        titles: list[tuple[int, str]] = []
        # 两种写法都要认：表格行 `| 关键问题1 | 标题 |` 和行内 `关键问题1：标题`
        for match in re.finditer(
            r"关键问题\s*(\d+)\s*(?:[：:]|\s*\|)\s*([^|\n•◦▪]+)", block
        ):
            titles.append((int(match.group(1)), match.group(2).strip()))
        if not titles:
            continue
        titles.sort(key=lambda item: item[0])
        seen: set[int] = set()
        ordered: list[str] = []
        for number, title in titles:
            if number in seen:
                continue
            seen.add(number)
            ordered.append(title)
        return ordered
    return []


def episode_from_path(path: Path) -> str | None:
    match = re.search(r"E0*(\d+)", path.name) or re.search(r"E0*(\d+)", str(path))
    return match.group(1) if match else None


def fun_blocks(text: str) -> list[str]:
    pattern = re.escape(FUN_OPEN) + r"(.*?)" + re.escape(FUN_CLOSE)
    return [strip_markdown(block) for block in re.findall(pattern, text, flags=re.S)]


def strip_interaction(lines: list[str]) -> list[str]:
    """删掉【互动探索】表格区块，保留表格之后的正文，用于正文独立性检查。"""
    kept: list[str] = []
    in_interaction = False
    table_seen = False
    for raw in lines:
        line = raw.rstrip("\n")
        name = section_name(line)
        if name is not None:
            if name == SECTION_INTERACTION:
                in_interaction = True
                table_seen = False
                continue
            in_interaction = False
        if in_interaction:
            if is_table_line(line):
                table_seen = True
                continue
            if not table_seen:
                continue
        kept.append(line)
    return kept


def check(path: Path, framework: Path | None = None,
          episode: str | None = None) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    failures: list[str] = []
    warnings: list[str] = []
    infos: list[str] = []

    for token in FORBIDDEN:
        if token in text:
            failures.append(f"包含禁用内容：{token}")

    questions = draft_key_questions(lines)
    key_headings = [f"关键问题{num}：{title}" for _, num, title in questions]
    if not key_headings:
        failures.append("没有发现 `## 关键问题N：...` 小标题")

    # 编号连续性、重复和顺序
    numbers = [int(num) for _, num, _ in questions]
    duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
    if duplicates:
        failures.append("关键问题编号重复：" + "、".join(f"关键问题{n}" for n in duplicates))
    if numbers and numbers != sorted(numbers):
        failures.append("关键问题编号顺序颠倒：实际为 " + "、".join(str(n) for n in numbers))
    if numbers:
        expected = list(range(1, len(numbers) + 1))
        if sorted(numbers) != expected:
            missing = [n for n in expected if n not in numbers]
            if missing:
                failures.append(
                    "关键问题编号不连续，缺少：" + "、".join(f"关键问题{n}" for n in missing)
                )
            else:
                failures.append(
                    f"关键问题编号应为 1—{len(numbers)}，实际为 "
                    + "、".join(str(n) for n in numbers)
                )

    if "## 【互动探索】" not in text:
        failures.append("缺少 `## 【互动探索】` 模块")
    else:
        table = extract_table(lines, SECTION_INTERACTION)
        missing = table_has_rows(table, INTERACTION_REQUIRED)
        if missing:
            failures.append("【互动探索】表格缺少项目：" + "、".join(missing))
        recommended = table_has_rows(table, INTERACTION_RECOMMENDED)
        if recommended:
            warnings.append(
                "【互动探索】表格建议补充项目：" + "、".join(recommended)
                + "（题型决定「正确答案」怎么填，见 docs/interaction-design.md）"
            )

    if "## 【大总结】" not in text:
        failures.append("缺少 `## 【大总结】` 模块")

    result = analyse(lines)
    body_count = int(result["body_count"])

    if body_count < COUNT_MIN:
        failures.append(f"正文讲述内容约 {body_count} 字，低于 {COUNT_MIN} 字")
    elif body_count > COUNT_MAX:
        failures.append(f"正文讲述内容约 {body_count} 字，高于 {COUNT_MAX} 字")

    if result["fun_unclosed_line"]:
        failures.append(
            f"第 {result['fun_unclosed_line']} 行的 {FUN_OPEN} 没有对应的 {FUN_CLOSE} 闭合标记"
        )

    # 硬性：两项都能靠拆句/改陈述句修好，不需要动知识内容
    if int(result["question_count"]) > QUESTION_MAX:
        failures.append(
            f"口播范围问题句 {result['question_count']} 个，超过上限 {QUESTION_MAX} 个"
        )

    long_paragraphs = result["long_paragraphs"]
    if long_paragraphs:
        preview = "、".join(f"第{line}行约{size}字" for line, size in long_paragraphs[:5])
        failures.append(f"存在超过 {PARAGRAPH_MAX} 字的正文段落：" + preview)

    # 软性：大总结字数需要人工权衡内容取舍
    summary_count = int(result["summary_count"])
    if summary_count and not SUMMARY_MIN <= summary_count <= SUMMARY_MAX:
        warnings.append(
            f"【大总结】约 {summary_count} 字，建议范围 {SUMMARY_MIN}—{SUMMARY_MAX} 字"
        )

    # 趣味拓展：非必需，但出现时有数量和长度约束
    blocks = fun_blocks(text)
    if len(blocks) > FUN_MAX_COUNT:
        failures.append(f"趣味拓展出现 {len(blocks)} 处，每篇最多 {FUN_MAX_COUNT} 处")
    for i, block in enumerate(blocks, start=1):
        size = count_readable_chars(block)
        if size > FUN_MAX_CHARS:
            warnings.append(
                f"第 {i} 处趣味拓展约 {size} 字，建议不超过 {FUN_MAX_CHARS} 字"
            )

    # 正文不得依赖互动模块
    dep_hits = result["interaction_dependencies"]
    if dep_hits:
        preview = "、".join(f"第{line}行“{phrase}”" for line, phrase in dep_hits[:5])
        failures.append(
            "正文出现依赖互动模块的表述（删掉互动表格后会失去指向）：" + preview
        )

    # 框架标题核对：只在显式传入框架文件时执行
    framework_diff: list[dict[str, str]] = []
    if framework is not None:
        number = episode or episode_from_path(path)
        if number is None:
            warnings.append("未能从文件名判断集号，跳过框架标题核对；可用 --episode 指定")
        else:
            fw_titles = framework_key_questions(framework, number)
            if fw_titles is None:
                warnings.append(f"框架文件中没找到 E{number} 区块，跳过框架标题核对")
            elif not fw_titles:
                warnings.append(f"框架 E{number} 区块中没解析出关键问题标题，跳过核对")
            else:
                if len(fw_titles) != len(questions):
                    warnings.append(
                        f"关键问题数量与框架不一致：框架 {len(fw_titles)} 个，"
                        f"标绿稿 {len(questions)} 个"
                    )
                for i, (_, num, title) in enumerate(questions):
                    if i >= len(fw_titles):
                        break
                    fw_title = fw_titles[i]
                    if normalise_question(title) != normalise_question(fw_title):
                        framework_diff.append(
                            {"number": num, "draft": title, "framework": fw_title}
                        )
                        continue
                    # 标签写在标题前还是标题后属排版差异，只比集合
                    draft_labels = set(extract_labels(title))
                    fw_labels = set(extract_labels(fw_title))
                    if draft_labels and fw_labels and draft_labels != fw_labels:
                        framework_diff.append(
                            {"number": num, "draft": title, "framework": fw_title}
                        )
                if framework_diff:
                    for diff in framework_diff:
                        warnings.append(
                            f"关键问题{diff['number']} 标题与框架不一致："
                            f"框架为“{diff['framework']}”，标绿稿为“{diff['draft']}”"
                            "；若为有意改动请确认框架是否同步"
                        )
                else:
                    infos.append(f"关键问题标题与框架 E{number} 逐字一致")

    infos.append(f"关键问题小标题数 {len(key_headings)} 个")
    infos.append(
        f"口播范围问题句 {result['question_count']} 个（上限 {QUESTION_MAX} 个）"
    )
    if summary_count:
        infos.append(
            f"【大总结】约 {summary_count} 字"
            f"（建议 {SUMMARY_MIN}—{SUMMARY_MAX} 字）"
        )
    infos.append(f"趣味拓展 {len(blocks)} 处")
    infos.append("以下项脚本无法判断，需人工按 docs/self-check.md 核对："
                 "大总结是否回答主线问题、是否覆盖各关键问题结论、"
                 "科学表述是否准确、知识点顺序是否通顺")

    return {
        "path": str(path),
        "framework": str(framework) if framework else None,
        "body_count": body_count,
        "count_breakdown": result["items"],
        "summary_count": summary_count,
        "question_count": result["question_count"],
        "key_question_headings": len(key_headings),
        "key_questions": key_headings,
        "fun_blocks": len(blocks),
        "framework_diff": framework_diff,
        "failures": failures,
        "warnings": warnings,
        "infos": infos,
        "ok": not failures,
    }


def print_interaction_test(path: Path) -> None:
    """输出删掉互动表格后的正文，供人工判断正文能否独立成篇。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = strip_interaction(lines)
    result = analyse(kept)
    print("=" * 60)
    print("互动独立性测试：以下是删掉【互动探索】表格后的正文")
    print("=" * 60)
    for line in kept:
        if line.strip():
            print(line)
    print("=" * 60)
    print(f"删除表格后计入正文约 {result['body_count']} 字")
    dep_hits = result["interaction_dependencies"]
    if dep_hits:
        print("以下表述依赖互动模块，删掉表格后会失去指向：")
        for line_no, phrase in dep_hits:
            print(f"  第{line_no}行：“{phrase}”")
    print("请人工确认上面的正文是否已独立说清：")
    print("  1. 观察到了什么现象")
    print("  2. 为什么会这样")
    print("  3. 这说明了什么")
    print("  4. 与主线问题的关系")
    print("本测试只输出材料，不单独判定通过或未通过。")
    print("")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("draft", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--framework",
        type=Path,
        default=None,
        help="可选：大纲框架或内容简案文件，用于逐字核对关键问题标题。"
             "反向同步（以标绿稿为准改框架）时不要传，避免误报。",
    )
    parser.add_argument(
        "--episode",
        default=None,
        help="可选：集号，如 7。默认从文件名里的 E7/E07 推断。",
    )
    parser.add_argument(
        "--interaction-test",
        action="store_true",
        help="额外输出删掉互动表格后的正文，供人工判断正文能否独立成篇。",
    )
    args = parser.parse_args()

    result = check(args.draft, framework=args.framework, episode=args.episode)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1

    if args.interaction_test:
        print_interaction_test(args.draft)

    print(f"文件：{result['path']}")
    if result["framework"]:
        print(f"对照框架：{result['framework']}")
    print("")
    print("字数分项：")
    for entry in result["count_breakdown"]:
        label = entry["label"]
        chars = entry["chars"]
        if entry["counted"]:
            print(f"  {label}：{chars} 字")
        else:
            print(f"  {label}：{chars} 字（未计入）")
    print(f"  ── 合计计入：{result['body_count']} 字"
          f"（目标 {COUNT_TARGET}，范围 {COUNT_MIN}—{COUNT_MAX}）")
    print("")
    for info in result["infos"]:
        print(f"INFO: {info}")
    for warning in result["warnings"]:
        print(f"WARNING: {warning}")
    for failure in result["failures"]:
        print(f"FAIL: {failure}")
    print("")
    print("说明：FAIL 必须修好；WARNING 需人工判断，可在说明理由后保留；INFO 只是统计。")
    print("结果：" + ("通过" if result["ok"] else "未通过"))

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
