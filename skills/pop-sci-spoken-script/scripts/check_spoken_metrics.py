#!/usr/bin/env python3
"""Lightweight hygiene validator for pure teleprompter spoken scripts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PACE_RATES_PER_MIN: dict[str, float] = {
    "slow": 210.0,
    "standard": 250.0,
    "fast": 280.0,
}

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
ASCII_WORD_RE = re.compile(r"[A-Za-z0-9]+")
CLAUSE_SPLIT_RE = re.compile(r"[，。！？；：…—,\.!?;:]+")
UNSPOKEN_ARTIFACT_RE = re.compile(r"[（）()【】\[\]/\*#]")
DIRECT_YOU_RE = re.compile(r"你(?!们)")
BROADCAST_TERMS = ("大家", "人们", "大众", "消费者", "患者们", "朋友们", "你们")
BROADCAST_RE = re.compile("|".join(re.escape(term) for term in BROADCAST_TERMS))

RuleList = list[tuple[str, re.Pattern[str], str]]

WRITTEN_CLICHE_RULES: RuleList = [
    ("因此", re.compile(r"因此"), "改用“所以”或“这样一来”"),
    ("综上所述", re.compile(r"综上所述"), "改用“说到底”或直接收住"),
    ("总而言之", re.compile(r"总而言之"), "改用“一句话说完”或删掉"),
    ("换言之", re.compile(r"换言之"), "改用“大白话就是”"),
    ("众所周知", re.compile(r"众所周知"), "直接删掉进主题"),
    ("由此可见", re.compile(r"由此可见"), "改用“你看，这就说明”"),
    ("旨在", re.compile(r"旨在"), "改用“就是为了”或“专门用来”"),
    ("不仅如此", re.compile(r"不仅如此"), "改用“更绝的是”或“还没完”"),
    ("与此同时", re.compile(r"与此同时"), "改用“同一时间”或“另一边”"),
    ("前者", re.compile(r"前者"), "直接重复具体事物名称，避免回指听晕"),
    ("后者", re.compile(r"后者"), "直接重复具体事物名称，避免回指听晕"),
    ("就…而言", re.compile(r"就[^，。！？\n]{1,12}而言"), "改用“拿……来说”"),
    ("通过…的方式", re.compile(r"通过[^，。！？\n]{1,15}的方式"), "改用直接动词，如“靠……”“用……”"),
    ("显著提升", re.compile(r"显著提升"), "换成画面感表达"),
    ("显著下降", re.compile(r"显著下降"), "换成具体幅度的口语描述"),
    ("研究表明", re.compile(r"研究表明"), "改用“有项实验专门测过”等自然口语"),
    ("数据显示", re.compile(r"数据显示"), "直接报核心对比数字或占比"),
    ("不可或缺", re.compile(r"不可或缺"), "改用“少不了”"),
    ("至关重要", re.compile(r"至关重要"), "改用“最关键”或“最要命”"),
]

AI_SLOP_RULES: RuleList = [
    ("底层逻辑", re.compile(r"底层逻辑"), "改用“真正的原因”或“最根本那条规则”"),
    ("赋能", re.compile(r"赋能"), "换成具体动作，如“帮到你”"),
    ("本质上", re.compile(r"本质上"), "改用“说白了”或直接删掉"),
    ("悄然", re.compile(r"悄然"), "改用“偷偷”或“不知不觉”"),
    ("重塑", re.compile(r"重塑"), "换成具体改变动作"),
    ("双刃剑", re.compile(r"双刃剑"), "直说哪边赚了、哪边亏了"),
    ("归根结底", re.compile(r"归根结底"), "改用“说到底”"),
    ("值得注意的是", re.compile(r"值得注意的是"), "改用“有意思的是”"),
    ("换句话说", re.compile(r"换句话说"), "改用“说穿了”或重说一遍"),
    ("不可忽视", re.compile(r"不可忽视"), "改用“最容易漏掉”"),
    ("不言而喻", re.compile(r"不言而喻"), "删掉或用具体后果说话"),
    ("显而易见", re.compile(r"显而易见"), "删掉或直接展示对比"),
    ("首先", re.compile(r"首先"), "避免 PPT 路标词，直接顺着思绪讲第一件"),
    ("其次", re.compile(r"其次"), "改用自然承接词或直接进下一段"),
    ("此外", re.compile(r"此外"), "改用“还有一点”或“顺带一提”"),
    ("按下了暂停键", re.compile(r"按下了暂停键"), "换掉陈旧比喻，用具体动作画面"),
    ("无形的枷锁", re.compile(r"无形的枷锁"), "具体说出到底是什么卡住了人"),
    ("交响乐团", re.compile(r"交响乐团"), "换掉泛滥比喻"),
    ("拥抱更美好的", re.compile(r"拥抱更美好的"), "删掉强行鸡汤升华，自然收尾"),
    ("这充分说明", re.compile(r"这充分说明"), "例子讲完直接往下走，别替听众划重点"),
    ("这完全可以理解", re.compile(r"这完全可以理解"), "删掉客服腔伪共情"),
    ("这真不是你的错", re.compile(r"这真不是你的错"), "换掉模板安抚，直接点破真实原因"),
]

INANIMATE_NOMINALIZATION_RULES: RuleList = [
    ("这一机制", re.compile(r"这一机制"), "把主语换回“你 / 具体人或物” + 动作动词"),
    ("这种现象", re.compile(r"这种现象"), "指明具体发生的动作或画面"),
    ("该过程", re.compile(r"该过程"), "直接说“这一步”或“走下来”"),
    ("的累积效应", re.compile(r"的累积效应"), "改为“一天天攒下来的账”"),
    ("的根本原因在于", re.compile(r"的根本原因在于"), "改用“说白了就是因为”"),
    ("带来了显著的", re.compile(r"带来了显著的"), "直接说出具体让人发生了什么变化"),
    ("发挥着重要作用", re.compile(r"发挥着重要作用"), "具体说出它到底干了什么活"),
    ("起到了关键作用", re.compile(r"起到了关键作用"), "直接说“全靠它顶着”或“最关键看它”"),
    ("对…产生了", re.compile(r"对[^，。！？\n]{1,10}产生了"), "去掉“产生”，改用直接及物动词"),
]

MCN_CLICHE_RULES: RuleList = [
    ("说句扎心的", re.compile(r"说句扎心的"), "删掉套话，直接讲真实细节"),
    ("听我一句劝", re.compile(r"听我一句劝"), "去掉说教口吻，换成平视分享"),
    ("干货满满", re.compile(r"干货满满"), "删掉自夸套话，用内容本身说话"),
    ("点赞收藏防走丢", re.compile(r"点赞收藏防走丢"), "去掉营销号催三连"),
    ("一定要看到最后", re.compile(r"一定要看到最后"), "靠真实内容吸引，不用口头强留"),
    ("千万别划走", re.compile(r"千万别划走"), "删掉强迫留存话术"),
    ("一次性给你扒干净", re.compile(r"一次性给你扒干净"), "换用平实直白的说法"),
    ("今天不灌鸡汤", re.compile(r"今天不灌鸡汤"), "删掉廉价表态，直接切入主题"),
    ("保姆级教程", re.compile(r"保姆级教程"), "换成具体能帮到观众的平实表述"),
    ("家人们谁懂啊", re.compile(r"家人们谁懂啊"), "改为单数“你”的自然共鸣"),
]

BROCHURE_RULES: RuleList = [
    ("双向奔赴", re.compile(r"双向奔赴"), "换成大白话说明双方各图什么"),
    ("核心竞争力", re.compile(r"核心竞争力"), "具体说出拿得出手的本事或手艺"),
    ("综合素质", re.compile(r"综合素质"), "具体说出到底看什么硬条件"),
    ("换来的是", re.compile(r"换来的是"), "去掉总结腔，直接说出实打实的甜头与代价"),
    ("依然是块", re.compile(r"依然是块"), "去掉官样套话，直白讲清真实门槛"),
]

RULE_CATEGORIES: list[tuple[str, str, str, RuleList]] = [
    ("written_cliches", "written_cliche_count", "书面语残留", WRITTEN_CLICHE_RULES),
    ("ai_slop_phrases", "ai_slop_count", "AI高频套词", AI_SLOP_RULES),
    ("inanimate_nominalizations", "inanimate_nominalization_count", "无灵主语/抽象名词化", INANIMATE_NOMINALIZATION_RULES),
    ("mcn_cliches", "mcn_cliche_count", "短视频营销套话", MCN_CLICHE_RULES),
    ("brochure_cliches", "brochure_cliche_count", "宣讲通稿套词", BROCHURE_RULES),
]

TEMPORAL_CRUTCH_RULES: RuleList = [
    ("前一阵", re.compile(r"(前一阵子?|前阵子|前段时间)"), "改用意象承接、轻追问或直接进具体场景，少用时间起手式硬切"),
    (
        "以前",
        re.compile(
            r"(以前[啊呀呢嘛])|(?:^|[，。！？；：])\s*((?:其实|说实话)?(?:我)?以前)(?=[，、\s]|的时候|总|老|一直|觉得|以为|也|就|都|特别|挺|很|爱|喜欢)"
        ),
        "改用具体心境或画面前后反差过渡，避免用“以前啊”起头打补丁",
    ),
    ("年轻的时候", re.compile(r"(年轻的时候|年轻那会儿)"), "改用具体的当年境遇或细节切入，别反复贴时间标签"),
    ("早些年", re.compile(r"(早些年|早年间)"), "减少空泛时间起手式，直接抛出当年具体画面或念头"),
    ("小时候", re.compile(r"(?:^|[，。！？；：])\s*((?:我)?小时候)"), "控制“小时候”起头次数，直接从当时一件具体的事或物件说起"),
    ("那时候", re.compile(r"(?:^|[，。！？；：])\s*(那时候)"), "直接承接上文画面或情绪余温，少用“那时候”转场"),
    ("有一次", re.compile(r"(?:^|[，。！？；：])\s*((?:我)?(?:记得)?有(?:一次|一回|回))"), "直接把那件事的现场动作或原话抛出来，不必先报“有一次”"),
]


def count_spoken_units(text: str) -> tuple[float, int, int]:
    """Return (spoken_units, cjk_char_count, ascii_token_count)."""
    cjk_count = len(CJK_RE.findall(text))
    ascii_tokens = len(ASCII_WORD_RE.findall(text))
    return float(cjk_count) + ascii_tokens * 1.5, cjk_count, ascii_tokens


def extract_clauses(text: str) -> list[dict[str, Any]]:
    """Split text into pause-delimited clauses preserving 1-based line numbers."""
    clauses: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for raw_clause in CLAUSE_SPLIT_RE.split(line):
            clause = raw_clause.strip()
            if not clause:
                continue
            units, _, _ = count_spoken_units(clause)
            cjk_only = "".join(CJK_RE.findall(clause))
            clauses.append({"line": line_no, "text": clause, "units": round(units, 1), "cjk_only": cjk_only})
    return clauses


def scan_triadic_symmetry(clauses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect 3+ consecutive clauses (>=4 CJK chars) sharing the same 2-CJK prefix."""
    findings: list[dict[str, Any]] = []
    idx, n = 0, len(clauses)
    while idx < n:
        cjk = clauses[idx]["cjk_only"]
        if len(cjk) < 4:
            idx += 1
            continue
        prefix = cjk[:2]
        end = idx + 1
        while end < n and len(clauses[end]["cjk_only"]) >= 4 and clauses[end]["cjk_only"][:2] == prefix:
            end += 1
        if end - idx >= 3:
            group = clauses[idx:end]
            findings.append({
                "start_line": group[0]["line"],
                "end_line": group[-1]["line"],
                "prefix": prefix,
                "count": end - idx,
                "clauses": [item["text"] for item in group],
            })
        idx = end
    return findings


def scan_pattern_rules(text: str, rules: RuleList) -> list[dict[str, Any]]:
    """Match regex rules line-by-line and return structured findings."""
    findings: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for label, pattern, suggestion in rules:
            for match in pattern.finditer(line):
                findings.append({
                    "line": line_no,
                    "label": label,
                    "matched": match.group(0),
                    "suggestion": suggestion,
                })
    return findings


def scan_temporal_crutches(text: str) -> list[dict[str, Any]]:
    """Match temporal transition crutches line-by-line without leading punctuation."""
    findings: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for label, pattern, suggestion in TEMPORAL_CRUTCH_RULES:
            for match in pattern.finditer(line):
                matched = next((g for g in match.groups() if g is not None), match.group(0))
                findings.append({
                    "line": line_no,
                    "label": label,
                    "matched": matched,
                    "suggestion": suggestion,
                })
    return findings


def resolve_banned_phrases(phrases_arg: str | None = None, banned_file: str | None = None) -> list[str]:
    """Merge comma-separated CLI phrases and line-delimited UTF-8 file phrases."""
    raw: list[str] = []
    if phrases_arg:
        raw.extend(re.split(r"[,，]+", phrases_arg))
    if banned_file:
        for line in Path(banned_file).read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                raw.append(stripped)
    return list(dict.fromkeys(item.strip() for item in raw if item.strip()))


def _check_duration(selected_est_sec: float, target_seconds: int, pace: str) -> tuple[dict[str, Any], str | None]:
    """Check estimated spoken duration against ±15% target bounds."""
    min_sec = round(target_seconds * 0.85, 1)
    max_sec = round(target_seconds * 1.15, 1)
    rate_per_sec = PACE_RATES_PER_MIN[pace] / 60.0
    delta_units = round((selected_est_sec - target_seconds) * rate_per_sec)
    in_range = min_sec <= selected_est_sec <= max_sec
    info = {
        "target_seconds": target_seconds,
        "pace": pace,
        "estimated_seconds": selected_est_sec,
        "allowed_range_seconds": [min_sec, max_sec],
        "in_range": in_range,
        "delta_units": delta_units,
    }
    if in_range:
        return info, None
    if delta_units > 0:
        msg = f"时长偏长：按 {pace} 语速约 {selected_est_sec}s，超出目标 {target_seconds}s 的 ±15% 区间（{min_sec}s–{max_sec}s），建议精简约 {delta_units} 字。"
    else:
        msg = f"时长偏短：按 {pace} 语速约 {selected_est_sec}s，低于目标 {target_seconds}s 的 ±15% 区间（{min_sec}s–{max_sec}s），建议补充约 {abs(delta_units)} 字。"
    return info, msg


def analyze_script(
    text: str,
    target_seconds: int | None = None,
    pace: str = "standard",
    max_clause_len: int = 25,
    banned_phrases: list[str] | None = None,
) -> dict[str, Any]:
    """Validate pure teleprompter text for objective readability and cleanliness without forcing rhythm."""
    spoken_units, cjk_chars, ascii_tokens = count_spoken_units(text)
    durations_sec = {key: round(spoken_units / (rate / 60.0), 1) for key, rate in PACE_RATES_PER_MIN.items()}

    artifacts = [
        {"line": line_no, "symbols": "".join(dict.fromkeys(m.group(0) for m in UNSPOKEN_ARTIFACT_RE.finditer(line))), "text": line.strip()}
        for line_no, line in enumerate(text.splitlines(), start=1)
        if UNSPOKEN_ARTIFACT_RE.search(line)
    ]
    clauses = extract_clauses(text)
    max_clause_units = max((item["units"] for item in clauses), default=0.0)
    long_clauses = [{"line": item["line"], "units": item["units"], "text": item["text"]} for item in clauses if item["units"] > max_clause_len]
    triadic_symmetry = scan_triadic_symmetry(clauses)

    direct_you_count = len(DIRECT_YOU_RE.findall(text))
    broadcast_matches = BROADCAST_RE.findall(text)
    broadcast_count = len(broadcast_matches)

    warnings: list[str] = []
    if spoken_units == 0:
        warnings.append("输入文本为空或不包含有效口播字词。")

    duration_check: dict[str, Any] | None = None
    if target_seconds is not None:
        if target_seconds <= 0:
            warnings.append(f"目标时长必须大于 0 秒（当前传入：{target_seconds}）。")
        else:
            duration_check, dur_warn = _check_duration(durations_sec[pace], target_seconds, pace)
            if dur_warn:
                warnings.append(dur_warn)

    if artifacts:
        warnings.append(f"检测到 {len(artifacts)} 处提词器禁用符号（如括号、斜杠、Markdown 标记），请清理后再进提词器。")
    if long_clauses:
        warnings.append(f"检测到 {len(long_clauses)} 个超长憋气气口（单气口 > {max_clause_len} 单位，最长 {max_clause_units} 单位），建议断句补气口。")
    if triadic_symmetry:
        warnings.append(f"检测到 {len(triadic_symmetry)} 处机械三连排比（连续 3 句以上同前缀），建议打散避免八股朗诵感。")

    metrics: dict[str, Any] = {
        "spoken_units": round(spoken_units, 1),
        "cjk_chars": cjk_chars,
        "ascii_tokens": ascii_tokens,
        "estimated_duration_seconds": durations_sec,
        "selected_pace": pace,
        "clause_count": len(clauses),
        "max_clause_units": max_clause_units,
        "max_clause_limit": max_clause_len,
        "triadic_symmetry_count": len(triadic_symmetry),
        "direct_you_count": direct_you_count,
        "broadcast_term_count": broadcast_count,
        "broadcast_terms_found": broadcast_matches,
    }
    findings: dict[str, Any] = {
        "unspoken_artifacts": artifacts,
        "long_clauses": long_clauses,
        "triadic_symmetry": triadic_symmetry,
    }

    for finding_key, count_key, label, rules in RULE_CATEGORIES:
        hits = scan_pattern_rules(text, rules)
        findings[finding_key] = hits
        metrics[count_key] = len(hits)
        if hits:
            unique = "、".join(dict.fromkeys(item["matched"] for item in hits))
            warnings.append(f"检测到 {len(hits)} 处{label}（{unique}），建议改为更自然贴耳的表达。")

    clean_banned = list(dict.fromkeys(p.strip() for p in (banned_phrases or []) if p.strip()))
    banned_rules: RuleList = [(p, re.compile(re.escape(p)), "按自定义禁词表替换，避免跨稿重复") for p in clean_banned]
    custom_hits = scan_pattern_rules(text, banned_rules) if banned_rules else []
    findings["custom_banned_hits"] = custom_hits
    metrics["custom_banned_count"] = len(custom_hits)
    if custom_hits:
        unique_banned = "、".join(dict.fromkeys(item["matched"] for item in custom_hits))
        warnings.append(f"命中 {len(custom_hits)} 处自定义禁用词（{unique_banned}），请替换为当期自然表述。")

    temporal_crutches = scan_temporal_crutches(text)
    findings["temporal_crutches"] = temporal_crutches
    metrics["temporal_crutch_count"] = len(temporal_crutches)
    if temporal_crutches:
        label_counts: dict[str, int] = {}
        for item in temporal_crutches:
            label_counts[item["label"]] = label_counts.get(item["label"], 0) + 1
        if len(temporal_crutches) >= 3 or any(count >= 2 for count in label_counts.values()):
            breakdown = "、".join(
                f"{lbl}×{cnt}" if cnt > 1 else lbl for lbl, cnt in label_counts.items()
            )
            warnings.append(
                f"时间起手式偏多或重复（共 {len(temporal_crutches)} 处：{breakdown}），"
                "易显得前后衔接像流水账；建议改用意象接力、轻追问或直接入画过渡。"
            )

    if broadcast_count > 0 and broadcast_count > direct_you_count:
        found_terms = "、".join(dict.fromkeys(broadcast_matches))
        warnings.append(f"群指播音感偏重：群指词（{found_terms}，共 {broadcast_count} 次）多于单数“你”（{direct_you_count} 次），建议改回单数“你”。")

    return {
        "status": "PASS" if not warnings else "WARN",
        "metrics": metrics,
        "duration_check": duration_check,
        "findings": findings,
        "warnings": warnings,
    }


def format_markdown(report: dict[str, Any]) -> str:
    """Format validation results as concise Markdown."""
    m = report["metrics"]
    dur = m["estimated_duration_seconds"]
    lines = [
        f"## 提词器客观体检结果：{report['status']}",
        "",
        f"- **口播总单位**：{m['spoken_units']}（中文 {m['cjk_chars']} 字，英文/数字词 {m['ascii_tokens']} 个）",
        f"- **预估时长**：慢速 {dur['slow']}s ｜ 标准 {dur['standard']}s ｜ 快速 {dur['fast']}s（校验语速：`{m['selected_pace']}`）",
    ]
    if report["duration_check"] is not None:
        dc = report["duration_check"]
        lo, hi = dc["allowed_range_seconds"]
        flag = "达标" if dc["in_range"] else "偏离目标"
        lines.append(f"- **目标时长**：目标 {dc['target_seconds']}s（区间 {lo}s–{hi}s），当前 {dc['estimated_seconds']}s（{flag}）")
    lines.extend([
        f"- **气口检查**：共 {m['clause_count']} 个气口，最长单气口 {m['max_clause_units']} 单位（上限 {m['max_clause_limit']}）",
        f"- **客观禁用项**：书面语 {m['written_cliche_count']} ｜ AI套词 {m['ai_slop_count']} ｜ 营销套话 {m['mcn_cliche_count']} ｜ 通稿词 {m['brochure_cliche_count']} ｜ 无灵主语 {m['inanimate_nominalization_count']} ｜ 三连排比 {m['triadic_symmetry_count']} ｜ 时间起手式 {m['temporal_crutch_count']} ｜ 自定义禁词 {m['custom_banned_count']}",
        f"- **对话感参照**：单数“你” {m['direct_you_count']} 次 vs 群指词 {m['broadcast_term_count']} 次",
    ])
    if report["warnings"]:
        lines.extend(["", "### 修改提示", *[f"{i}. {w}" for i, w in enumerate(report["warnings"], start=1)]])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Lightweight objective hygiene validator for pure teleprompter scripts.")
    parser.add_argument("input", nargs="?", default="-", help="Teleprompter text file path, or '-' for stdin (default).")
    parser.add_argument("--target-seconds", type=int, default=None, help="Optional target spoken duration in seconds (±15%% check).")
    parser.add_argument("--pace", choices=tuple(PACE_RATES_PER_MIN.keys()), default="standard", help="Speaking pace: slow=210, standard=250, fast=280 units/min.")
    parser.add_argument("--max-clause-len", type=int, default=25, help="Maximum spoken units allowed between pauses (default: 25).")
    parser.add_argument("--banned-phrases", type=str, default=None, help="Comma-separated custom phrases to check for deduplication.")
    parser.add_argument("--banned-file", type=str, default=None, help="UTF-8 file with one custom banned phrase per line (# comments ignored).")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of Markdown summary.")
    parser.add_argument("--strict", action="store_true", help="Exit with code 1 if status is WARN.")
    args = parser.parse_args()

    try:
        text = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Error reading input '{args.input}': {exc}", file=sys.stderr)
        return 2
    try:
        banned_phrases = resolve_banned_phrases(args.banned_phrases, args.banned_file)
    except OSError as exc:
        print(f"Error reading banned phrases file '{args.banned_file}': {exc}", file=sys.stderr)
        return 2

    report = analyze_script(text, args.target_seconds, args.pace, args.max_clause_len, banned_phrases)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else format_markdown(report))
    return 1 if args.strict and report["status"] != "PASS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
