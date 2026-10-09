#!/usr/bin/env python3
"""J1 glm8 batch judge (rerun 2026-10-06; v2 2026-10-09) — GLM-5.3-Flash API, 8帧 rubric, 六字段协议.

v2 变更（2026-10-09，召回补缺轮）：RUBRIC 新增「三、时序帧对专项」——f04-f05 / f03-f06
  两组有序帧对 + 相邻帧对扫描的跨帧运动比对（段落互换→temporal_swap、明暗/饱和交替→
  flicker、画面凝固→frame_freeze），输出仍走 judge_common.py 冻结词表既有键，无新增通道；
  六字段协议零改动。改动动机与验收：exp59 基线 045/046/052 双漏（J1/J3 同判净），E10
  recall 0.8929<0.90；判定纪律与盲测口径不变。旧版判官输出存档 数据/judges/judges_v1_round3/。

重建口径（对齐原夜 2026-09-30 J1 配方，材料出处见 JUDGES-RERUN.md）：
  * 模型: glm-5.3-flash（zhipu coding-plan OpenAI 兼容端点，BIGMODEL_API_KEY 环境变量注入）
  * 输入: /data/night/golden/frames/<cid>/f01..f08.jpg（金标统一抽帧，jpg q=2）
  * 协议: 边界测试方案.md §2.3 盲测协议 {"clip_id","defect_detected","defect_types",
          "confidence","spans","notes"}（judge_common.py 冻结协议）
  * 8 类缺陷定义逐字取自 judges_src/judge_common.py DEFECT_ZH；B 类意图词表
    （hand_anomaly/count_error/physics_error/identity_drift/other）按原夜 glm8 输出实证词表
    （reference/orig_judges_extracted/glm8/ 40 条全部 def_types 枚举）
  * 盲测: 不输入金标分布/其他判官结论；只给帧序与时间戳元数据

Usage:
  BIGMODEL_API_KEY=... python glm8_batch.py --frames-root /data/night/golden/frames \
      --manifest /data/night/golden/manifest.json --out-dir DIR --raw-dir DIR --meta FILE \
      [--workers 8] [--limit N] [--only cid,cid]
"""
import argparse
import base64
import concurrent.futures as cf
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

DEFECT_ZH = {
    "frame_freeze": "画面定格（数秒不动）",
    "flicker": "帧间明暗/内容快速交替闪烁",
    "color_shift": "整体色偏（颜色异常偏移）",
    "face_blur": "人脸模糊（人脸区域异常模糊）",
    "garble_text": "乱码文字（画面出现乱码/无意义文字）",
    "temporal_swap": "段落错乱（时序跳变/场景切换不连贯）",
    "pixelate": "像素化（画面局部马赛克/像素块）",
    "ghosting": "拖影（运动残影/重影）",
}
B_TYPES = ["hand_anomaly", "count_error", "physics_error", "identity_drift", "other"]
KNOWN = set(DEFECT_ZH) | set(B_TYPES)

RUBRIC = """你是视频质检盲测评委 J1。同一条生成视频按时间均匀抽取的 8 帧（f01..f08，帧下已标时间戳）如下。请按 rubric 逐项检查后输出判定。

【clip 元数据】clip_id=%s；时长=%.2fs；帧=f01..f08（8 帧均匀采样）

【检查 rubric】
一、8 类标准缺陷（逐项核对，定义如下）：
%s
二、意图/语义维度（生成能力缺陷，命中即报）：
hand_anomaly=手部解剖异常（多指/融指/指节粘连、手型不成立）；count_error=对象计数异常（数量明显违背常识或无意义重复堆叠）；physics_error=物理/时序违例（悬浮、穿模、支撑或运动不合理）；identity_drift=身份漂移（人物/主体跨帧外观突变）；文字渲染失败归 garble_text；上述都不符但有其他明显异常归 other。
三、时序帧对专项（跨帧运动比对，必查）：
把 8 帧视为同一段连续视频按时间顺序抽取的关键帧，重点比对两组有序帧对：f04 与 f05（相邻中点对）、f03 与 f06（跨段对），并顺带核对其余相邻帧对（f01-f02、f02-f03、f05-f06、f06-f07、f07-f08）。只做定性比对，不口算像素差或亮度数值。逐对检查三类时序异常：
1) 段落互换（命中报 temporal_swap）：后一帧相对前一帧出现「内容回跳」——景别/构图突然倒退（如前一帧已推近到特写、后一帧反而退回更远的全景）、已移出画面的物体或文字重新回到画面、人物姿态或物体位置跳回之前出现过的状态且与前后帧的运动趋势断裂。连续平滑的推拉摇移是正常运镜，不算。
2) 明暗/饱和交替闪烁（命中报 flicker）：相邻帧对之间肉眼可见的亮度或饱和度正负交替——一帧明显偏亮或浓艳、相邻帧又明显变暗或发灰，且在连续两组帧对上重复出现。只朝一个方向的整体渐变（逐渐变亮/变暗/调色过渡）不算。
3) 画面凝固（命中报 frame_freeze）：两帧及以上画面完全一致（构图、内容、光影均无任何可辨变化）而时间戳在推进，且与前后段的画面变化状态形成「动-停-动」断裂。
任一类命中：defect_types 加入对应英文键，notes 写明具体帧对（如 f04→f05）与看到的画面证据；三类都未命中则如实在 notes 写明「帧对比对未见时序异常」，不要为凑数而报。
四、判定纪律：
1. 盲测：只依据这 8 帧画面证据判定，不臆测视频来源与其他评委结论。
2. 相邻帧对比只做定性判断（内容有无突变/静止嫌疑/残影），不要口算像素差或亮度数值。
3. 每个结论给画面证据并引用帧号（如 f03-f05）；无缺陷就如实判干净，不要为凑数而报。
4. defect_types 只能从上述英文键中选；confidence 为 0-1 总体确信度；spans 写受影响帧/时间段；notes 写判定依据（中文，引用帧号）。

【输出】只输出一个 JSON 对象，不要输出任何其他文字或 markdown 代码块：
{"clip_id":"%s","defect_detected":true或false,"defect_types":["英文键"],"confidence":0.85,"spans":"受影响帧或时间段","notes":"判定依据"}"""


def build_req(cid, dur_s, frames, base_url, key, model):
    defs = "\n".join("%s=%s" % (k, v) for k, v in DEFECT_ZH.items())
    prompt = RUBRIC % (cid, dur_s, defs, cid)
    content = []
    for i, p in enumerate(frames, 1):
        b64 = base64.b64encode(open(p, "rb").read()).decode()
        ts = round(dur_s * (i - 0.5) / 8.0, 1)
        content.append({"type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64," + b64}})
        content.append({"type": "text", "text": "f%02d @ %.1fs" % (i, ts)})
    content.append({"type": "text", "text": prompt})
    body = {"model": model, "messages": [{"role": "user", "content": content}],
            "max_tokens": MAX_TOKENS[0], "temperature": 0.7}
    return json.dumps(body).encode(), base_url.rstrip("/") + "/chat/completions", key


MAX_TOKENS = [4096]


def call_api(payload, url, key, timeout=300):
    req = urllib.request.Request(url, data=payload, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def parse_answer(text, cid):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in answer")
    d = json.loads(m.group(0))
    types = [t for t in (d.get("defect_types") or []) if t in KNOWN]
    unknown = [t for t in (d.get("defect_types") or []) if t not in KNOWN]
    conf = d.get("confidence")
    conf = float(conf) if isinstance(conf, (int, float)) else 0.5
    proto = {"clip_id": cid,
             "defect_detected": bool(d.get("defect_detected")),
             "defect_types": types,
             "confidence": round(min(1.0, max(0.0, conf)), 4),
             "spans": str(d.get("spans", ""))[:300],
             "notes": str(d.get("notes", ""))[:800]}
    if unknown:
        proto["notes"] = (proto["notes"] + "；未收录词:" + ",".join(unknown))[:800]
    return proto


def run_one(cid, item, frames_root, a):
    frames = [os.path.join(frames_root, cid, "f%02d.jpg" % i) for i in range(1, 9)]
    missing = [f for f in frames if not os.path.isfile(f)]
    if missing:
        raise RuntimeError("missing frames: %s" % missing)
    dur = float((item.get("verify") or {}).get("dur_s") or 0.0) or 7.0
    payload, url, key = build_req(cid, dur, frames, a.base_url, a.key, a.model)
    t0 = time.time()
    last = None
    for attempt in range(1, 4):
        try:
            resp = call_api(payload, url, key)
            break
        except Exception as e:
            last = e
            time.sleep(5 * attempt * 2)
    else:
        raise RuntimeError("API failed after 3 tries: %s" % last)
    lat = round(time.time() - t0, 1)
    msg = resp["choices"][0]["message"]
    text = (msg.get("content") or "")
    if not text.strip() and msg.get("reasoning_content"):
        text = "[content 空，仅 reasoning] " + msg["reasoning_content"][:200]
        raise ValueError("empty content: " + text)
    proto = parse_answer(text, cid)
    raw = {"model": a.model, "clip_id": cid, "answer_text": text,
           "finish_reason": resp["choices"][0].get("finish_reason"),
           "usage": resp.get("usage"), "latency_s": lat}
    return proto, raw, lat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-root", default="/data/night/golden/frames")
    ap.add_argument("--manifest", default="/data/night/golden/manifest.json")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--model", default="glm-5.3-flash")
    ap.add_argument("--base-url", default=os.environ.get("BIGMODEL_BASE_URL",
                      "https://open.bigmodel.cn/api/coding/paas/v4"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    a.key = os.environ.get("BIGMODEL_API_KEY") or ""
    if not a.key:
        sys.exit("BIGMODEL_API_KEY 未设置")
    MAX_TOKENS[0] = a.max_tokens
    os.makedirs(a.out_dir, exist_ok=True)
    os.makedirs(a.raw_dir, exist_ok=True)

    items = json.load(open(a.manifest))["items"]
    todo = [(it["clip_id"], it) for it in items]
    if a.only:
        keep = set(a.only.split(","))
        todo = [(c, i) for c, i in todo if c in keep]
    if a.limit:
        todo = todo[:a.limit]

    meta = {"judge": "glm8", "model": a.model, "base_url": a.base_url,
            "frames_root": a.frames_root, "workers": a.workers,
            "protocol": "边界测试方案.md §2.3 六字段（judge_common.py 冻结）",
            "rubric_source": "DEFECT_ZH=judge_common.py 原文; B类词表=原夜glm8输出实证; 盲测无金标信息",
            "started_at": time.strftime("%F %T"), "clips": []}
    n_ok = n_fail = 0
    usage_total = {"prompt_tokens": 0, "completion_tokens": 0}
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(run_one, cid, item, a.frames_root, a): cid for cid, item in todo}
        for fut in cf.as_completed(futs):
            cid = futs[fut]
            entry = {"clip_id": cid, "ok": False}
            try:
                proto, raw, lat = fut.result()
                json.dump(proto, open(os.path.join(a.out_dir, cid + ".json"), "w",
                                      encoding="utf-8"), ensure_ascii=False, indent=2)
                json.dump(raw, open(os.path.join(a.raw_dir, cid + ".json"), "w",
                                    encoding="utf-8"), ensure_ascii=False, indent=2)
                u = raw["usage"] or {}
                for k in usage_total:
                    usage_total[k] += int(u.get(k) or 0)
                entry.update(ok=True, detected=proto["defect_detected"],
                             types=proto["defect_types"], confidence=proto["confidence"],
                             latency_s=lat)
                n_ok += 1
            except Exception as e:
                entry["error"] = "%s: %s" % (type(e).__name__, e)
                n_fail += 1
                json.dump({"clip_id": cid, "defect_detected": False, "defect_types": [],
                           "confidence": 0.0, "spans": "",
                           "notes": "judge FAILED: %s" % entry["error"]},
                          open(os.path.join(a.out_dir, cid + ".json"), "w",
                               encoding="utf-8"), ensure_ascii=False, indent=2)
            meta["clips"].append(entry)
            print("[%s] %s ok=%s %s" % (time.strftime("%T"), cid, entry["ok"],
                                        entry.get("error", entry.get("types", ""))),
                  flush=True)
    meta.update(n_clips=len(todo), n_ok=n_ok, n_fail=n_fail,
                usage_total=usage_total, wall_seconds=round(time.time() - t0, 1),
                finished_at=time.strftime("%F %T"))
    json.dump(meta, open(a.meta, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("[glm8] DONE ok=%d fail=%d tokens=%s" % (n_ok, n_fail, usage_total), flush=True)


if __name__ == "__main__":
    main()
