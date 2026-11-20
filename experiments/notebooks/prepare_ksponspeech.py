"""Build small, reproducible Colab input archives from the official AI Hub ZIPs."""

import argparse
from io import TextIOWrapper
import json
from pathlib import Path, PurePosixPath
from random import Random
import re
import unicodedata
from zipfile import ZIP_DEFLATED, ZipFile


SAMPLE_RATE = 16_000
MAX_SHARD_BYTES = 64 * 1024 * 1024
PREFIX = "mumu-kspon-v1"
ORTHOGRAPHY = re.compile(r"\(([^()]*)\)\s*/\s*\(([^()]*)\)")
EVENT = re.compile(r"(?<!\w)[bln]/")
UNKNOWN_OR_OVERLAP = re.compile(r"(?<!\w)[ou]/")


def clean_label(text):
    text = unicodedata.normalize("NFC", text.strip())
    if UNKNOWN_OR_OVERLAP.search(text) or any(mark in text for mark in "*+"):
        return None
    text = ORTHOGRAPHY.sub(r"\1", text)
    text = " ".join(EVENT.sub("", text).split())
    if "/" in text or not any(char.isalnum() for char in text):
        return None
    return text


def collect(scripts, audio, split):
    is_train = split == "train"
    members = {
        PurePosixPath(info.filename).name: info
        for info in audio.infolist()
        if info.filename.endswith(".pcm") and (is_train or info.filename.startswith("eval_clean/"))
    }
    rows = []
    with TextIOWrapper(scripts.open(f"{split}.trn"), encoding="utf-8-sig") as labels:
        for line in labels:
            source, separator, text = line.partition(" :: ")
            if not separator:
                continue
            name = PurePosixPath(source.replace("\\", "/")).name
            entry = members.get(name)
            if entry is None:
                continue
            samples = entry.file_size // 2
            if not SAMPLE_RATE <= samples <= SAMPLE_RATE * 15:
                continue
            target = clean_label(text)
            if target:
                rows.append((entry, samples, target))
    rows.sort(key=lambda row: row[0].filename)
    return rows


def select_training(rows, hours, rng):
    budget = round(hours * 3600 * SAMPLE_RATE)
    rng.shuffle(rows)
    selected = []
    for row in rows:
        if row[1] <= budget:
            selected.append(row)
            budget -= row[1]
    return selected


def select_evaluation(rows, rng):
    questions = [row for row in rows if row[2].endswith(("?", "？"))]
    statements = [row for row in rows if row[2].endswith(".") and "?" not in row[2]]
    selected = rng.sample(questions, 60) + rng.sample(statements, 60)
    rng.shuffle(selected)
    return selected


def write_shards(rows, output):
    shard, used = [], 0
    groups = []
    for item in rows:
        size = item[2][1] * 2
        if shard and used + size > MAX_SHARD_BYTES:
            groups.append(shard)
            shard, used = [], 0
        shard.append(item)
        used += size
    if shard:
        groups.append(shard)

    paths = []
    for number, group in enumerate(groups, 1):
        output_path = output / f"{PREFIX}-{number:02}.zip"
        temporary_path = output_path.with_suffix(".zip.tmp")
        records = []
        with ZipFile(temporary_path, "w", compression=ZIP_DEFLATED, compresslevel=4) as archive:
            for split, source, (entry, samples, text) in group:
                name = PurePosixPath(entry.filename).stem
                member = f"audio/{name}.pcm"
                archive.writestr(member, source.read(entry)[: samples * 2])
                records.append(dict(id=name, split=split, audio=member, samples=samples, text=text))
            archive.writestr("manifest.jsonl", "\n".join(json.dumps(row, ensure_ascii=False) for row in records))
        with ZipFile(temporary_path) as archive:
            invalid_member = archive.testzip()
            if invalid_member is not None:
                raise RuntimeError(f"압축 검증 실패 ({invalid_member})")
        temporary_path.replace(output_path)
        paths.append(output_path)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    names = ("KsponSpeech_scripts.zip", "KsponSpeech_01.zip", "KsponSpeech_eval.zip")
    scripts_path, train_path, eval_path = (next(args.source.rglob(name)) for name in names)
    with ZipFile(scripts_path) as scripts, ZipFile(train_path) as train_audio, ZipFile(eval_path) as eval_audio:
        train = select_training(collect(scripts, train_audio, "train"), hours=2, rng=Random(42))
        evaluation = select_evaluation(collect(scripts, eval_audio, "eval_clean"), rng=Random(42))
        train_samples = sum(row[1] for row in train)
        if train_samples < int(1.99 * 3600 * SAMPLE_RATE):
            raise ValueError("2시간 학습 표본을 만들 음성이 부족합니다.")
        for name, rows in (("train", train), ("eval_clean", evaluation)):
            duration = sum(row[1] for row in rows) / SAMPLE_RATE
            questions = sum(row[2].endswith(("?", "？")) for row in rows)
            print(f"{name}: {len(rows)} clips, {duration:.2f}s, {questions} questions", flush=True)
        shards = write_shards(
            [("train", train_audio, row) for row in train]
            + [("eval_clean", eval_audio, row) for row in evaluation], args.output,
        )
        for shard in shards:
            print(f"{shard.name}: {shard.stat().st_size} bytes", flush=True)


if __name__ == "__main__":
    main()
