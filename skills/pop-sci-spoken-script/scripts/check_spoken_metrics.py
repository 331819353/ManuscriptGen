#!/usr/bin/env python3
"""Validate pure teleprompter text for spoken-script readiness, rhythm, and anti-AI-ism."""

from __future__ import annotations

import argparse
import json
import math
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
SENTENCE_SPLIT_RE = re.compile(r"[。！？!?]+")
UNSPOKEN_ARTIFACT_RE = re.compile(r"[（）()【】\[\]/\*#]")
DIRECT_YOU_RE = re.compile(r"你(?!们)")
BROADCAST_TERMS = ("大家", "人们", "大众", "消费者", "患者们", "朋友们", "你们")
BROADCAST_RE = re.compile("|".join(re.escape(term) for term in BROADCAST_TERMS))
STARTER_PRONOUN_EXCLUSIONS = {"你", "我", "他", "她", "它", "这", "那"}

RuleList = list[tuple[str, re.Pattern[str], str]]

WRITTEN_CLICHE_RULES: RuleList = [
    ("因此", re.compile(r"因此"), "改用“所以”或“这样一来”"),
    ("综上所述", re.compile(r"综上所述"), "改用“说白了”或“总结成一句话”"),
    ("总而言之", re.compile(r"总而言之"), "改用“一句话说完”或“说到底”"),
    ("换言之", re.compile(r"换言之"), "改用“翻译成大白话就是”或“说白了就是”"),
    ("众所周知", re.compile(r"众所周知"), "直接删掉进主题，或改用“你肯定听过”"),
    ("由此可见", re.compile(r"由此可见"), "改用“你看，这就说明”或“难怪会这样”"),
    ("旨在", re.compile(r"旨在"), "改用“就是为了”或“专门用来”"),
    ("不仅如此", re.compile(r"不仅如此"), "改用“更绝的是”“还没完”或“甚至”"),
    ("与此同时", re.compile(r"与此同时"), "改用“同一时间”“另一边”或“顺带着”"),
    ("前者", re.compile(r"前者"), "直接重复具体事物名称，避免听众听觉回指卡壳"),
    ("后者", re.compile(r"后者"), "直接重复具体事物名称，避免听众听觉回指卡壳"),
    ("就…而言", re.compile(r"就[^，。！？\n]{1,12}而言"), "改用“拿……来说”或“单看……这一块”"),
    ("通过…的方式", re.compile(r"通过[^，。！？\n]{1,15}的方式"), "直接用动词短语，如“靠……”“用……”"),
    ("显著提升", re.compile(r"显著提升"), "换成画面感表达，如“直接拉满”“涨了一大截”"),
    ("显著下降", re.compile(r"显著下降"), "换成画面感表达，如“砍掉将近一半”“断崖式往下掉”"),
    ("研究表明", re.compile(r"研究表明"), "改用“科学家做过一个实验发现”或“实测结果更扎心”"),
    ("数据显示", re.compile(r"数据显示"), "改用“你看这组数有多吓人”或直接口语报核心比例"),
    ("不可或缺", re.compile(r"不可或缺"), "改用“少不了”或“离了它真不行”"),
    ("至关重要", re.compile(r"至关重要"), "改用“最关键”“最要命”或“直接决定了……”"),
]

ANTITHESIS_TIC_RULES: RuleList = [
    ("不是…而是…", re.compile(r"不是[^，。！？\n]{1,18}[，,]?\s*而是"), "删掉虚设稻草人 X，直接说出核心结论或真实误区"),
    ("并非…而是…", re.compile(r"并非[^，。！？\n]{1,18}[，,]?\s*而是"), "改用直接口语陈述，避免伪深刻反转腔"),
    ("与其说…不如说…", re.compile(r"与其说[^，。！？\n]{1,18}[，,]?\s*不如说"), "去掉书面对比壳，直给核心动作或画面"),
    ("不只是…更是…", re.compile(r"不只是[^，。！？\n]{1,18}[，,]?\s*更是"), "拆成两句具体递进，别套排比句壳"),
]

AI_SLOP_RULES: RuleList = [
    ("底层逻辑", re.compile(r"底层逻辑"), "改用“真正的原因”“最根本那条规则”或直接讲机制"),
    ("赋能", re.compile(r"赋能"), "换成具体动作，如“帮到你”“给你省事”"),
    ("本质上", re.compile(r"本质上"), "改用“说白了”“说到底”或直接删掉"),
    ("悄然", re.compile(r"悄然"), "改用“偷偷”“不知不觉”"),
    ("重塑", re.compile(r"重塑"), "换成具体动作，如“彻底改掉”“重新搭一遍”"),
    ("双刃剑", re.compile(r"双刃剑"), "说清具体哪边赚了、哪边亏了，别甩万能套话"),
    ("归根结底", re.compile(r"归根结底"), "改用“说到底”“算总账”"),
    ("值得注意的是", re.compile(r"值得注意的是"), "改用“有意思的是”“你得留意这点”"),
    ("换句话说", re.compile(r"换句话说"), "改用“翻译成大白话”或直接重说一遍"),
    ("不可忽视", re.compile(r"不可忽视"), "改用“最容易漏掉”“别不当回事”"),
    ("不言而喻", re.compile(r"不言而喻"), "删掉或用具体后果说话"),
    ("显而易见", re.compile(r"显而易见"), "删掉或直接展示对比结果"),
    ("首先", re.compile(r"首先"), "口播避免“首先/其次”念稿腔，改用“第一件事”“先说最要紧的”"),
    ("其次", re.compile(r"其次"), "改用“第二”“紧接着”“更要命的是”"),
    ("此外", re.compile(r"此外"), "改用“还有一点”“顺带说一句”"),
    ("按下了暂停键", re.compile(r"按下了暂停键"), "换掉塑料比喻，改用具体物理画面动作"),
    ("无形的枷锁", re.compile(r"无形的枷锁"), "换掉陈词滥调隐喻，写具体卡住受众的东西"),
    ("交响乐团", re.compile(r"交响乐团"), "换掉泛滥比喻，贴合目标人群自己的兴趣意象"),
    ("拥抱更美好的", re.compile(r"拥抱更美好的"), "删掉强行鸡汤升华，收在具体行动或互动问题"),
    ("这充分说明", re.compile(r"这充分说明"), "包袱/例子讲完直接进下句，别替观众划重点"),
    ("这完全可以理解", re.compile(r"这完全可以理解"), "删掉客服式伪共情，换成具体狼狈场景共鸣"),
    ("这真不是你的错", re.compile(r"这真不是你的错"), "删掉模板安抚，直接点破身体/系统怎么坑了你"),
]

INANIMATE_NOMINALIZATION_RULES: RuleList = [
    ("这一机制", re.compile(r"这一机制"), "把主语换回“你/大脑/具体器官”+ 动作动词"),
    ("这种现象", re.compile(r"这种现象"), "指明具体发生的动作或画面，别用抽象代词"),
    ("该过程", re.compile(r"该过程"), "直接说“这一步”“跑完这趟下来”"),
    ("的累积效应", re.compile(r"的累积效应"), "改成动态表述，如“一天天攒下来的账”"),
    ("的根本原因在于", re.compile(r"的根本原因在于"), "改用“说白了就是因为”“问题卡在这儿”"),
    ("带来了显著的", re.compile(r"带来了显著的"), "直接说“让你……”“直接把……拉满/砍半”"),
    ("发挥着重要作用", re.compile(r"发挥着重要作用"), "具体说出它到底干了什么活"),
    ("起到了关键作用", re.compile(r"起到了关键作用"), "直接说“全靠它顶着”“最关键就看它”"),
    ("对…产生了", re.compile(r"对[^，。！？\n]{1,10}产生了"), "去掉“产生”，改成直接及物动词（如“搞乱了”“拖垮了”）"),
]

MCN_CLICHE_RULES: RuleList = [
    ("说句扎心的", re.compile(r"说句扎心的"), "删掉套话，直接抛事实或具体画面"),
    ("听我一句劝", re.compile(r"听我一句劝"), "去掉说教口吻，换成平视分享或具体经历"),
    ("干货满满", re.compile(r"干货满满"), "删掉自夸套话，用真实信息说话"),
    ("点赞收藏防走丢", re.compile(r"点赞收藏防走丢"), "改为自然话题互动，不要营销号催三连"),
    ("一定要看到最后", re.compile(r"一定要看到最后"), "靠内容钩子留人，不靠口头强留"),
    ("千万别划走", re.compile(r"千万别划走"), "删掉强迫留存话术，直接进核心悬念"),
    ("一次性给你扒干净", re.compile(r"一次性给你扒干净"), "改用具体讲清什么事的平实表达"),
    ("今天不灌鸡汤", re.compile(r"今天不灌鸡汤"), "删掉廉价表态，直接切入故事或现象"),
    ("保姆级教程", re.compile(r"保姆级教程"), "换成具体能帮到观众的平实说法"),
    ("家人们谁懂啊", re.compile(r"家人们谁懂啊"), "改为单数“你”的精准场景共鸣"),
]

BROCHURE_RULES: RuleList = [
    ("双向奔赴", re.compile(r"双向奔赴"), "换大白话说明双方各自图什么、怎么看对眼"),
    ("核心竞争力", re.compile(r"核心竞争力"), "具体说出真正拿得出手的本事或手艺"),
    ("综合素质", re.compile(r"综合素质"), "具体说出到底考什么、看什么硬条件"),
    ("换来的是", re.compile(r"换来的是"), "去掉通稿总结腔，直接说出实打实的甜头与代价"),
    ("依然是块", re.compile(r"依然是块"), "去掉“依然是块敲门砖”这类官方套话，直接讲真实门槛"),
]


def count_spoken_units(text: str) -> tuple[float, int, int]:
    """Return (spoken_units, cjk_char_count, ascii_token_count)."""
    cjk_count = len(CJK_RE.findall(text))
    ascii_tokens = len(ASCII_WORD_RE.findall(text))
    spoken_units = float(cjk_count) + ascii_tokens * 1.5
    return spoken_units, cjk_count, ascii_tokens


def scan_unspoken_artifacts(text: str) -> list[dict[str, Any]]:
    """Find brackets, slashes, or markdown markers unsuitable for teleprompters."""
    findings: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        matches = list(UNSPOKEN_ARTIFACT_RE.finditer(line))
        if matches:
            symbols = "".join(dict.fromkeys(m.group(0) for m in matches))
            findings.append(
                {
                    "line": line_no,
                    "symbols": symbols,
                    "text": line.strip(),
                }
            )
    return findings


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
            clauses.append(
                {
                    "line": line_no,
                    "text": clause,
                    "units": round(units, 1),
                    "cjk_only": cjk_only,
                }
            )
    return clauses


def scan_triadic_symmetry(clauses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect 3+ consecutive clauses (>=4 CJK chars) sharing the same 2-CJK prefix."""
    findings: list[dict[str, Any]] = []
    idx = 0
    n = len(clauses)
    while idx < n:
        cjk = clauses[idx]["cjk_only"]
        if len(cjk) < 4:
            idx += 1
            continue
        prefix = cjk[:2]
        end = idx + 1
        while end < n:
            next_cjk = clauses[end]["cjk_only"]
            if len(next_cjk) >= 4 and next_cjk[:2] == prefix:
                end += 1
            else:
                break
        run_len = end - idx
        if run_len >= 3:
            group = clauses[idx:end]
            findings.append(
                {
                    "start_line": group[0]["line"],
                    "end_line": group[-1]["line"],
                    "prefix": prefix,
                    "count": run_len,
                    "clauses": [item["text"] for item in group],
                }
            )
        idx = end
    return findings


def scan_pattern_rules(
    text: str,
    rules: RuleList,
    multiline: bool = False,
) -> list[dict[str, Any]]:
    """Match pattern rules against text and return structured findings with line numbers."""
    findings: list[dict[str, Any]] = []
    if multiline:
        for label, pattern, suggestion in rules:
            for match in pattern.finditer(text):
                line_no = text.count("\n", 0, match.start()) + 1
                matched_clean = re.sub(r"\s+", "", match.group(0))
                findings.append(
                    {
                        "line": line_no,
                        "label": label,
                        "matched": matched_clean,
                        "suggestion": suggestion,
                    }
                )
        return findings

    for line_no, line in enumerate(text.splitlines(), start=1):
        for label, pattern, suggestion in rules:
            for match in pattern.finditer(line):
                findings.append(
                    {
                        "line": line_no,
                        "label": label,
                        "matched": match.group(0),
                        "suggestion": suggestion,
                    }
                )
    return findings


def scan_rhythm_monotony(clauses: list[dict[str, Any]]) -> tuple[int, int]:
    """Return (short_punch_count <= 5.0 units, max_monotonous_run of 8.0..16.0 units)."""
    short_punch_count = 0
    max_monotonous_run = 0
    current_run = 0
    for item in clauses:
        units = item["units"]
        if units <= 5.0:
            short_punch_count += 1
        if 8.0 <= units <= 16.0:
            current_run += 1
            if current_run > max_monotonous_run:
                max_monotonous_run = current_run
        else:
            current_run = 0
    return short_punch_count, max_monotonous_run


def scan_starter_repetitions(text: str) -> list[dict[str, Any]]:
    """Detect recurring 2-CJK sentence starters (>= 4 times) across long enough scripts (>= 12 sentences)."""
    total_sentences = 0
    starter_hits: dict[str, list[tuple[int, str]]] = {}

    for line_no, line in enumerate(text.splitlines(), start=1):
        for raw_sentence in SENTENCE_SPLIT_RE.split(line):
            sentence = raw_sentence.strip()
            if not sentence:
                continue
            total_sentences += 1
            cjk_only = "".join(CJK_RE.findall(sentence))
            if len(cjk_only) < 6:
                continue
            if cjk_only[0] in STARTER_PRONOUN_EXCLUSIONS:
                continue
            starter = cjk_only[:2]
            starter_hits.setdefault(starter, []).append((line_no, sentence))

    if total_sentences < 12:
        return []

    findings: list[dict[str, Any]] = []
    for starter, hits in starter_hits.items():
        if len(hits) >= 4:
            findings.append(
                {
                    "starter": starter,
                    "count": len(hits),
                    "lines": [item[0] for item in hits],
                    "samples": [item[1] for item in hits[:3]],
                }
            )
    findings.sort(key=lambda item: (-item["count"], item["lines"][0]))
    return findings


def resolve_banned_phrases(
    phrases_arg: str | None = None,
    banned_file: str | None = None,
) -> list[str]:
    """Merge comma-separated CLI phrases and line-delimited UTF-8 file phrases."""
    raw_phrases: list[str] = []
    if phrases_arg:
        raw_phrases.extend(re.split(r"[,，]+", phrases_arg))
    if banned_file:
        file_text = Path(banned_file).read_text(encoding="utf-8")
        for line in file_text.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                raw_phrases.append(stripped)
    return list(dict.fromkeys(phrase.strip() for phrase in raw_phrases if phrase.strip()))


def analyze_script(
    text: str,
    target_seconds: int | None = None,
    pace: str = "standard",
    max_clause_len: int = 25,
    banned_phrases: list[str] | None = None,
    mode: str = "hook",
) -> dict[str, Any]:
    """Analyze pure teleprompter text and return structured QA metrics and warnings."""
    if mode not in ("hook", "companion"):
        raise ValueError(f"Unsupported mode: {mode}")

    spoken_units, cjk_chars, ascii_tokens = count_spoken_units(text)
    if mode == "companion":
        burstiness_min = 0.24
        monotonous_run_limit = 14
        antithesis_limit = max(1, math.ceil(spoken_units / 1000.0))
        direct_you_min_units = 300
        direct_you_min_count = 2
    else:
        burstiness_min = 0.28
        monotonous_run_limit = 10
        antithesis_limit = 1
        direct_you_min_units = 150
        direct_you_min_count = 3
    durations_sec = {
        key: round(spoken_units / (rate / 60.0), 1)
        for key, rate in PACE_RATES_PER_MIN.items()
    }
    selected_est_sec = durations_sec[pace]

    artifacts = scan_unspoken_artifacts(text)
    clauses = extract_clauses(text)
    clause_count = len(clauses)
    clause_lengths = [item["units"] for item in clauses]
    max_clause_units = max(clause_lengths, default=0.0)
    long_clauses = [
        {"line": item["line"], "units": item["units"], "text": item["text"]}
        for item in clauses
        if item["units"] > max_clause_len
    ]

    burstiness_cv: float | None = None
    if clause_count >= 8:
        mean_len = sum(clause_lengths) / clause_count
        if mean_len > 0:
            stdev = math.sqrt(
                sum((length - mean_len) ** 2 for length in clause_lengths) / clause_count
            )
            burstiness_cv = round(stdev / mean_len, 2)

    short_punch_count, max_monotonous_run = scan_rhythm_monotony(clauses)
    starter_repetitions = scan_starter_repetitions(text)
    triadic_symmetry = scan_triadic_symmetry(clauses)
    cliches = scan_pattern_rules(text, WRITTEN_CLICHE_RULES)
    antithesis_tics = scan_pattern_rules(text, ANTITHESIS_TIC_RULES, multiline=True)
    ai_slop_phrases = scan_pattern_rules(text, AI_SLOP_RULES)
    inanimate_nominalizations = scan_pattern_rules(text, INANIMATE_NOMINALIZATION_RULES)
    mcn_cliches = scan_pattern_rules(text, MCN_CLICHE_RULES)
    brochure_cliches = scan_pattern_rules(text, BROCHURE_RULES)
    clean_banned = list(dict.fromkeys(p.strip() for p in (banned_phrases or []) if p.strip()))
    custom_banned_rules: RuleList = [
        (phrase, re.compile(re.escape(phrase)), "为防止跨期同质化套壳，请替换为当期专属表达")
        for phrase in clean_banned
    ]
    custom_banned_hits = scan_pattern_rules(text, custom_banned_rules) if custom_banned_rules else []

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
            min_sec = round(target_seconds * 0.85, 1)
            max_sec = round(target_seconds * 1.15, 1)
            rate_per_sec = PACE_RATES_PER_MIN[pace] / 60.0
            delta_units = round((selected_est_sec - target_seconds) * rate_per_sec)
            in_range = min_sec <= selected_est_sec <= max_sec
            duration_check = {
                "target_seconds": target_seconds,
                "pace": pace,
                "estimated_seconds": selected_est_sec,
                "allowed_range_seconds": [min_sec, max_sec],
                "in_range": in_range,
                "delta_units": delta_units,
            }
            if not in_range:
                if delta_units > 0:
                    warnings.append(
                        f"时长偏长：按 {pace} 语速约 {selected_est_sec}s，超出目标 {target_seconds}s 的 ±15% 区间（{min_sec}s–{max_sec}s），建议精简约 {delta_units} 个口播字。"
                    )
                else:
                    warnings.append(
                        f"时长偏短：按 {pace} 语速约 {selected_est_sec}s，低于目标 {target_seconds}s 的 ±15% 区间（{min_sec}s–{max_sec}s），建议补充约 {abs(delta_units)} 个口播字。"
                    )

    if artifacts:
        warnings.append(
            f"检测到 {len(artifacts)} 处提词器禁用符号/舞台标记（如括号、斜杠、Markdown 符号），请改为纯口语或移回导演分镜表。"
        )

    if long_clauses:
        warnings.append(
            f"检测到 {len(long_clauses)} 个超长憋气长句（单气口 > {max_clause_len} 单位，最长 {max_clause_units} 单位），请拆短句并补气口。"
        )

    if burstiness_cv is not None and burstiness_cv < burstiness_min:
        warnings.append(
            f"句长过于均匀（Burstiness 变异系数 {burstiness_cv} < {burstiness_min}），容易显得像 AI 念稿；建议刻意穿插 1–5 字短锤句与长铺垫句制造呼吸反差。"
        )

    if clause_count >= 20 and short_punch_count == 0:
        warnings.append(
            "节奏缺乏短锤顿挫：全篇 ≥20 个气口却没有 1 句 ≤5 单位短句，建议穿插“错了。”“就卡在这。”等短句制造听觉停顿反差。"
        )

    if clause_count >= 20 and max_monotonous_run >= monotonous_run_limit:
        warnings.append(
            f"检测到连续 {max_monotonous_run} 个平缓中等气口（8–16 单位未间断，当前 {mode} 模式上限 < {monotonous_run_limit}），容易滑向均匀朗诵催眠腔，请插短句或切换现场画面。"
        )

    if starter_repetitions:
        rep_desc = "、".join(
            f"“{item['starter']}”（{item['count']}次）" for item in starter_repetitions
        )
        warnings.append(
            f"检测到 {len(starter_repetitions)} 组句首结构高频复读（{rep_desc}），建议改用动词、场景动作或追问错位接话。"
        )

    if triadic_symmetry:
        warnings.append(
            f"检测到 {len(triadic_symmetry)} 处机械三连排比（连续 3 句以上同前缀句式），请打破对称节奏避免 AI 八股感。"
        )

    if cliches:
        unique_labels = "、".join(dict.fromkeys(item["matched"] for item in cliches))
        warnings.append(
            f"检测到 {len(cliches)} 处书面语残留（{unique_labels}），建议替换为口语化连接词或动作表述。"
        )

    if len(antithesis_tics) > antithesis_limit:
        warnings.append(
            f"检测到 {len(antithesis_tics)} 处“不是X而是Y/与其说不如说”反转口癖（当前 {mode} 模式上限 {antithesis_limit} 处），请删掉虚设稻草人或未充分蓄能的伪深刻句式。"
        )

    if ai_slop_phrases:
        unique_slop = "、".join(dict.fromkeys(item["matched"] for item in ai_slop_phrases))
        warnings.append(
            f"检测到 {len(ai_slop_phrases)} 处 AI 高频套词/俗套隐喻/伪共情（{unique_slop}），请换为具体动作或活人直白表达。"
        )

    if inanimate_nominalizations:
        unique_nom = "、".join(dict.fromkeys(item["matched"] for item in inanimate_nominalizations))
        warnings.append(
            f"检测到 {len(inanimate_nominalizations)} 处无灵主语/抽象名词化表述（{unique_nom}），请把主语换回“你/具体行动者”+ 动作动词。"
        )

    if mcn_cliches:
        unique_mcn = "、".join(dict.fromkeys(item["matched"] for item in mcn_cliches))
        warnings.append(
            f"检测到 {len(mcn_cliches)} 处流水线短视频营销套话（{unique_mcn}），请改为符合人设的自然松弛表达。"
        )

    if brochure_cliches:
        unique_bc = "、".join(dict.fromkeys(item["matched"] for item in brochure_cliches))
        warnings.append(
            f"检测到 {len(brochure_cliches)} 处通用宣讲通稿套词（{unique_bc}），请降维成具体数字、收益或真实代价。"
        )

    if custom_banned_hits:
        unique_banned = "、".join(dict.fromkeys(item["matched"] for item in custom_banned_hits))
        warnings.append(
            f"命中 {len(custom_banned_hits)} 处自定义跨稿禁用词（{unique_banned}），请替换为当期专属物理锚物或自然语境。"
        )

    if spoken_units >= direct_you_min_units and direct_you_count < direct_you_min_count:
        warnings.append(
            f"1对1对话感不足：全文单数“你”仅出现 {direct_you_count} 次（当前 {mode} 模式 ≥{direct_you_min_units} 字建议至少 {direct_you_min_count} 次），容易像在念稿而不是跟观众聊天。"
        )

    if broadcast_count > direct_you_count:
        found_terms = "、".join(dict.fromkeys(broadcast_matches))
        warnings.append(
            f"播音腔距离感偏重：群指词（{found_terms}，共 {broadcast_count} 次）多于单数“你”（{direct_you_count} 次），建议改为单数“你”拉近距离。"
        )

    status = "PASS" if not warnings else "WARN"
    return {
        "status": status,
        "metrics": {
            "mode": mode,
            "spoken_units": round(spoken_units, 1),
            "cjk_chars": cjk_chars,
            "ascii_tokens": ascii_tokens,
            "estimated_duration_seconds": durations_sec,
            "selected_pace": pace,
            "clause_count": clause_count,
            "max_clause_units": max_clause_units,
            "max_clause_limit": max_clause_len,
            "burstiness_cv": burstiness_cv,
            "burstiness_min": burstiness_min,
            "short_punch_count": short_punch_count,
            "max_monotonous_run": max_monotonous_run,
            "monotonous_run_limit": monotonous_run_limit,
            "starter_repetition_count": len(starter_repetitions),
            "antithesis_tic_count": len(antithesis_tics),
            "antithesis_limit": antithesis_limit,
            "ai_slop_count": len(ai_slop_phrases),
            "inanimate_nominalization_count": len(inanimate_nominalizations),
            "mcn_cliche_count": len(mcn_cliches),
            "brochure_cliche_count": len(brochure_cliches),
            "custom_banned_count": len(custom_banned_hits),
            "triadic_symmetry_count": len(triadic_symmetry),
            "direct_you_count": direct_you_count,
            "broadcast_term_count": broadcast_count,
            "broadcast_terms_found": broadcast_matches,
        },
        "duration_check": duration_check,
        "findings": {
            "unspoken_artifacts": artifacts,
            "long_clauses": long_clauses,
            "starter_repetitions": starter_repetitions,
            "triadic_symmetry": triadic_symmetry,
            "written_cliches": cliches,
            "antithesis_tics": antithesis_tics,
            "ai_slop_phrases": ai_slop_phrases,
            "inanimate_nominalizations": inanimate_nominalizations,
            "mcn_cliches": mcn_cliches,
            "brochure_cliches": brochure_cliches,
            "custom_banned_hits": custom_banned_hits,
        },
        "warnings": warnings,
    }


def _append_rule_section(
    lines: list[str],
    title: str,
    items: list[dict[str, Any]],
) -> None:
    if not items:
        return
    lines.extend(["", f"### {title}"])
    for item in items:
        lines.append(
            f"- 第 {item['line']} 行命中 `{item['matched']}`（{item['label']}）→ {item['suggestion']}"
        )


def format_markdown(report: dict[str, Any]) -> str:
    """Format analysis report as concise readable Markdown."""
    m = report["metrics"]
    dur = m["estimated_duration_seconds"]
    cv_display = (
        f"{m['burstiness_cv']}（目标 ≥ {m['burstiness_min']}）"
        if m["burstiness_cv"] is not None
        else f"样本不足（仅 {m['clause_count']} 个气口，< 8 不计）"
    )
    lines = [
        f"## 口播指标质检结果：{report['status']}",
        "",
        "### 核心数据",
        f"- **校验模式**：`{m['mode']}`（`hook`=强吸引科普 / `companion`=陪伴独白）",
        f"- **口播总单位**：{m['spoken_units']}（中文 {m['cjk_chars']} 字，英文/数字词 {m['ascii_tokens']} 个）",
        f"- **预估口播时长**：慢速 {dur['slow']}s ｜ 标准 {dur['standard']}s ｜ 快速 {dur['fast']}s（当前校验语速：`{m['selected_pace']}`）",
    ]

    if report["duration_check"] is not None:
        dc = report["duration_check"]
        lo, hi = dc["allowed_range_seconds"]
        flag = "达标" if dc["in_range"] else "偏离目标"
        lines.append(
            f"- **目标时长比对**：目标 {dc['target_seconds']}s，允许区间 {lo}s–{hi}s，当前 {dc['estimated_seconds']}s（{flag}）"
        )

    lines.extend(
        [
            f"- **最长单气口**：{m['max_clause_units']} 单位（上限 {m['max_clause_limit']}）｜ **短落锤句数（≤5单位）**：{m['short_punch_count']} 句 ｜ **最长连续平缓气口（8–16单位）**：{m['max_monotonous_run']} 个（连续上限 < {m['monotonous_run_limit']}）",
            f"- **句长突发性（Burstiness CV）**：{cv_display}",
            f"- **“不是X而是Y”口癖次数**：{m['antithesis_tic_count']} 次（当前模式上限 {m['antithesis_limit']} 次）｜ **句首结构复读**：{m['starter_repetition_count']} 组",
            f"- **AI高频套词 / 营销套话 / 通稿套词 / 无灵主语 / 跨稿禁用词**：AI套词 {m['ai_slop_count']} 处 ｜ 营销套话 {m['mcn_cliche_count']} 处 ｜ 通稿套词 {m['brochure_cliche_count']} 处 ｜ 无灵主语 {m['inanimate_nominalization_count']} 处 ｜ 三连排比 {m['triadic_symmetry_count']} 处 ｜ 自定义跨稿禁用词 {m['custom_banned_count']} 处",
            f"- **1对1对话感**：单数“你” {m['direct_you_count']} 次 vs 群指词 {m['broadcast_term_count']} 次",
        ]
    )

    if report["warnings"]:
        lines.extend(["", "### 预警与修改建议"])
        for idx, warning in enumerate(report["warnings"], start=1):
            lines.append(f"{idx}. {warning}")

    findings = report["findings"]
    if findings["unspoken_artifacts"]:
        lines.extend(["", "### 提词器禁用符号明细"])
        for item in findings["unspoken_artifacts"]:
            lines.append(f"- 第 {item['line']} 行含 `{item['symbols']}`：`{item['text']}`")

    if findings["long_clauses"]:
        lines.extend(["", "### 憋气长句明细"])
        for item in findings["long_clauses"]:
            lines.append(f"- 第 {item['line']} 行（{item['units']} 单位）：`{item['text']}`")

    if findings["starter_repetitions"]:
        lines.extend(["", "### 句首结构复读明细"])
        for item in findings["starter_repetitions"]:
            joined_lines = ", ".join(map(str, item["lines"]))
            lines.append(
                f"- 第 {joined_lines} 行共 {item['count']} 句以 `{item['starter']}…` 起头（示例：`{item['samples'][0]}`）"
            )

    if findings["triadic_symmetry"]:
        lines.extend(["", "### 机械三连排比明细"])
        for item in findings["triadic_symmetry"]:
            joined = " / ".join(item["clauses"])
            lines.append(
                f"- 第 {item['start_line']}–{item['end_line']} 行连续 {item['count']} 句以 `{item['prefix']}` 开头：`{joined}`"
            )

    _append_rule_section(lines, "书面语残留明细", findings["written_cliches"])
    _append_rule_section(lines, "“不是X而是Y”反转口癖明细", findings["antithesis_tics"])
    _append_rule_section(lines, "AI高频套词与伪共情明细", findings["ai_slop_phrases"])
    _append_rule_section(lines, "流水线短视频套话明细", findings["mcn_cliches"])
    _append_rule_section(lines, "通稿套词明细", findings["brochure_cliches"])
    _append_rule_section(lines, "无灵主语与抽象名词化明细", findings["inanimate_nominalizations"])
    _append_rule_section(lines, "自定义跨稿禁用词明细", findings["custom_banned_hits"])

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate pure teleprompter text for spoken rhythm, clichés, anti-AI-isms, and duration."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="Path to pure teleprompter text file, or '-' to read from stdin (default).",
    )
    parser.add_argument(
        "--mode",
        choices=("hook", "companion"),
        default="hook",
        help="Script rhythm mode: 'hook' (short/mid punchy pop-sci) or 'companion' (reflective long monologue).",
    )
    parser.add_argument(
        "--target-seconds",
        type=int,
        default=None,
        help="Target spoken duration in seconds (checks within ±15%% at selected pace).",
    )
    parser.add_argument(
        "--pace",
        choices=tuple(PACE_RATES_PER_MIN.keys()),
        default="standard",
        help="Speaking pace for duration check: slow=210, standard=250, fast=280 units/min.",
    )
    parser.add_argument(
        "--max-clause-len",
        type=int,
        default=25,
        help="Maximum spoken units allowed between pause delimiters (default: 25).",
    )
    parser.add_argument(
        "--banned-phrases",
        type=str,
        default=None,
        help="Comma-separated custom phrases to flag for cross-episode deduplication.",
    )
    parser.add_argument(
        "--banned-file",
        type=str,
        default=None,
        help="Path to UTF-8 text file listing custom banned phrases (one per line, # for comments).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON instead of Markdown summary.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 if status is WARN.",
    )
    args = parser.parse_args()

    try:
        if args.input == "-":
            text = sys.stdin.read()
        else:
            text = Path(args.input).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Error reading input '{args.input}': {exc}", file=sys.stderr)
        return 2

    try:
        banned_phrases = resolve_banned_phrases(args.banned_phrases, args.banned_file)
    except OSError as exc:
        print(f"Error reading banned phrases file '{args.banned_file}': {exc}", file=sys.stderr)
        return 2

    report = analyze_script(
        text=text,
        target_seconds=args.target_seconds,
        pace=args.pace,
        max_clause_len=args.max_clause_len,
        banned_phrases=banned_phrases,
        mode=args.mode,
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_markdown(report))

    if args.strict and report["status"] != "PASS":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
