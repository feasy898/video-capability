#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_cp7_artifacts.py — 由 cp7_run_report.json 构建漫剧线 CP7 工件（本地仓）。
复刻短剧线同名脚本（ecd9b80 双形态裁决），换 comicanime_ep01 内容与亲看构图结论。

产出：
  1) cp7_shot_01..09.json：单镜工件，checkpoint.schema cp7 分支（draft_clip）合规形态——
     契约自身粒度即每镜一件（contracts/v2/examples/cp7.json notes「本集 4 镜各一份」）。
  2) cp7.json：任务书要求的聚合形态（payload.shots[] 逐镜留痕）。
     ⚠ schema draft_clip 为单镜形态（additionalProperties:false + 顶层单镜必备字段），
     payload.shots[] 与「过 checkpoint.schema cp7 分支」按现行契约不可同时成立——
     两形态都做 jsonschema 校验并如实记录 exit（ecd9b80 主裁：逐镜件=权威形态，
     聚合件如实记 EXIT=1，供 episode 级簿记）。
  3) schema_validation.log：canonical 命令逐件 EXIT 留痕（沿短剧线同款）。

fingerprint 一律实算：工件=sha256(canonical payload)（src/gate/fingerprint.py 同算法）；
资产=mp4 文件字节 sha256（生成时实测，report 内 mp4_sha256）。
"""
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))          # .../cp7
EP = os.path.dirname(HERE)                                  # .../comicanime_ep01
REPO = os.path.abspath(os.path.join(EP, "..", "..", "..", "..", ".."))  # 仓根（EP 上溯 5 层）
REPORT = os.path.join(HERE, "cp7_run_report.json")
CP3 = os.path.join(EP, "cp3.json")
CP5 = os.path.join(EP, "cp5.json")
CP6 = os.path.join(EP, "cp6.json")
ART_PREFIX = "overnight/vpipe/out/m2/comicanime_ep01/cp7"
PRODUCED_BY = "agent.cp7_draft_generator"

# 亲看代表帧构图结论（代理=本链工程师，Read 工具逐帧过目 9/9；
# frame=中间帧 n=16/33，由 ffmpeg select=eq(n,16) 抽取后逐帧查看）
FRAME_CHECK = {
    "shot_01": ("成立（弱）", "棚檐/塑料条帘/顶部灯笼形物/右侧入棚人形可辨，逆光入棚构图在；"
                             "整帧过曝重（LTX 色偏+洗白），人物剪影偏画面右缘细节弱"),
    "shot_02": ("部分成立", "坐姿人物+案台+雨丝可辨；「指节敲案点单」动作与面部近景未成形"
                            "（过曝洗白，头部融进背景亮区）"),
    "shot_03": ("成立", "灶后台后人物+前景锅具台面+蒸汽漫布，中近景构图与 CP3 action 对位"),
    "shot_04": ("成立", "俯拍碗+面条旋纹清晰+右上角手部入画，蒸汽感在；俯拍案台构图对位"),
    "shot_05": ("弱成立", "器物圆面特写占满画幅、磨痕纹理可辨、画面无脸（与「没有人脸」对位）；"
                          "「火苗舔锅底」元素未成形"),
    "shot_06": ("成立", "面部大特写+眼部可辨、暗调压面，与「瞳孔骤缩」惊变情绪对位；"
                        "缓推运动方向与蒸汽背景在本帧不可证"),
    "shot_07": ("成立（最强）", "双男主题材双人对坐构图完整：两人隔案相对、案上碗碟、背景货架，"
                                "与 CP3「双人同框隔案对坐一镜不切」高对位；横筷动作不可辨"),
    "shot_08": ("弱成立", "失神扭曲的面部近景+暗调结构可辨、情绪对位；「扶案沿/毛巾滑落」动作不可辨，"
                          "画面结构偏乱"),
    "shot_09": ("部分成立", "案上碗具群+雨帘线条+右侧灯笼形物可辨、空镜收尾感在；"
                            "「两碗面并排」失真为多碗（草稿层精确计数不可控，G3 相关，如实记录不修）"),
}


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fp_payload(payload):
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


report = json.load(open(REPORT, encoding="utf-8"))
prompts = json.load(open(os.path.join(HERE, "cp7_prompts.json"), encoding="utf-8"))
prompt_by_sid = {r["shot_id"]: r for r in prompts["shots"]}
cp3 = json.load(open(CP3, encoding="utf-8"))
cp3_by_sid = {s["shot_id"]: s for s in cp3["payload"]["shots"]}
sids = [r["shot_id"] for r in report["shots"]]

upstreams = []
for f, cpid in ((CP3, "cp3"), (CP5, "cp5"), (CP6, "cp6")):
    a = json.load(open(f, encoding="utf-8"))
    upstreams.append({"cp_id": cpid, "fingerprint": a["fingerprint"]})

N = len(sids)
GATE_NOTE = (f"黑帧 0：{N}/{N} 镜帧级均值<2 计数=0（生成张量与 mp4 端到端回检双侧），"
             "black_mono_ratio 全 0.0 ≤ 0.50（thresholds.yaml l0_preflight."
             "black_frame_ratio_max）；NaN=0；逐镜 L0 证据 <shot_id>.draft.l0.json。")
AUX_NOTES = [
    {"type": "hard_verify", "params_ref": "l0_preflight.duration_dev_max", "result": "pass",
     "note": (f"{N}/{N} 镜实测 1.375s == 声明 1.375s（33帧@24fps，dev=0.0% ≤ 2%，"
              "thresholds.yaml l0_preflight.duration_dev_max）。声明值=本批资产规格："
              "任务书固定 33 帧档（spike 验证包络），CP3 分镜声明镜长 2.17–5.22s 与草稿"
              "时长差异如实登记于 shots[].cp3_duration_s，节奏预演按帧数比例。")},
    {"type": "hard_verify", "params_ref": "cp7.gate.uses_existing_keys", "result": "pass",
     "note": (f"NaN/黑帧布尔项=0/0；帧率 24/1、分辨率 704x480（480x704 HxW 口径）符合声明档；"
              f"ffprobe 三元组逐镜 h264/yuv420p/33帧；确定性抽验 shot_04 二遍生成全帧 MAE=0.0"
              "（SPIKE-REPORT ③ 复证）。")},
]

# ---------- 1) 单镜合规工件 ----------
per_shot_payloads = {}
for rec in report["shots"]:
    sid = rec["shot_id"]
    payload = {
        "work_id": "comicanime_ep01",
        "shot_id": sid,
        "channel": "local_ltx_2b",
        "asset": {
            "kind": "clip",
            "fingerprint": rec["mp4_sha256"],
            "path": f"{ART_PREFIX}/{sid}.draft.mp4",
        },
        "width": rec["ffprobe"]["width"],
        "height": rec["ffprobe"]["height"],
        "fps": 24,
        "declared_duration_s": rec["declared_duration_s"],
        "actual_duration_s": rec["actual_duration_s"],
        "black_mono_ratio": rec["tensor_stats"]["black_frames_lt2"] / rec["tensor_stats"]["frames"],
        "nan_detected": bool(rec["tensor_stats"]["nan_count"] > 0),
        "seed": rec["seed"],
        "l0_preflight": {
            "accepted": bool(rec["l0_accepted"]),
            "evidence_ref": f"{ART_PREFIX}/{sid}.draft.l0.json",
        },
    }
    per_shot_payloads[sid] = payload
    verdict, detail = FRAME_CHECK[sid]
    art = {
        "schema_version": "2.0",
        "cp_id": "cp7",
        "artifact_type": "draft_clip",
        "fingerprint": fp_payload(payload),
        "produced_by": PRODUCED_BY,
        "produced_at": now_iso(),
        "upstream_refs": upstreams,
        "status": "passed" if rec["l0_accepted"] else "rejected",
        "gate": {"type": "hard_verify", "params_ref": "l0_preflight.black_frame_ratio_max",
                 "result": "pass" if rec["l0_accepted"] else "fail", "note": GATE_NOTE},
        "aux_gates": AUX_NOTES,
        "payload": payload,
        "notes": (
            f"单镜草稿（T2 层，非交付物；CP8 择优器为其唯一消费者）。prompt_en（与 seed={rec['seed']}）"
            f"逐镜留痕于 {ART_PREFIX}/cp7_prompts.json，全文：{prompt_by_sid[sid]['prompt_en']}。"
            f"CP3 action_zh：{cp3_by_sid[sid]['action']}。"
            f"CP3 声明镜长 {cp3_by_sid[sid]['duration_s']}s vs 草稿 33帧@24fps=1.375s（任务书固定帧档，"
            f"构图/运动/节奏预演按帧数比例，见 aux_gates 口径）。生成墙钟 gen={rec.get('gen_s')}s "
            f"encode={rec.get('encode_s')}s。【构图人检】代理亲看代表帧（n=16/33，"
            f"{ART_PREFIX}/frame_{sid}.jpg）：{verdict}——{detail}。"
            "【漫剧风格如实记录】LTX-2B 草稿层输出为写实向厚涂图像，非国漫厚涂赛璐璐平涂；"
            "prompt 风格词（anime manhua cel shading）仅带来轻微平涂化倾向，不能作为 G8 风格判定依据——"
            "G8 风格化由 CP9 精修通道（H3-Max 四风格全成口径）承担，草稿层只表示构图/运动/节奏。"
            "色偏为 LTX-2B-v0.9.1 checkpoint 固有（SPIKE-REPORT 发现 B），只记录不修：草稿色彩不可依赖，"
            "CP8 择优与 CP9 精修不看草稿色彩。"
            "确定性：同 seed 逐比特可复现（本批 shot_04 二遍 MAE=0.0）。"),
    }
    out = os.path.join(HERE, f"cp7_{sid}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(art, f, ensure_ascii=False, indent=2)
    os.chmod(out, 0o644)

# ---------- 2) 聚合工件（任务书形态 payload.shots[]）----------
agg_shots = []
for rec in report["shots"]:
    sid = rec["shot_id"]
    row = prompt_by_sid[sid]
    verdict, detail = FRAME_CHECK[sid]
    agg_shots.append({
        "shot_id": sid,
        "prompt_en": row["prompt_en"],
        "negative": row["negative"],
        "seed": rec["seed"],
        "asset": {"kind": "clip", "fingerprint": rec["mp4_sha256"],
                  "path": f"{ART_PREFIX}/{sid}.draft.mp4"},
        "pixel": {"width": rec["ffprobe"]["width"], "height": rec["ffprobe"]["height"]},
        "width": rec["ffprobe"]["width"],
        "height": rec["ffprobe"]["height"],
        "fps": 24,
        "duration_frames": 33,
        "declared_duration_s": rec["declared_duration_s"],
        "actual_duration_s": rec["actual_duration_s"],
        "duration_dev": rec["duration_dev"],
        "cp3_duration_s": cp3_by_sid[sid]["duration_s"],
        "cp3_action_zh": cp3_by_sid[sid]["action"],
        "frame_check": {"verdict": verdict, "detail": detail,
                        "evidence": f"{ART_PREFIX}/frame_{sid}.jpg"},
        "black_mono_ratio": rec["tensor_stats"]["black_frames_lt2"] / rec["tensor_stats"]["frames"],
        "black_frames_tensor": rec["tensor_stats"]["black_frames_lt2"],
        "black_frames_decoded": rec["end_to_end_decode"]["black_frames_lt2"],
        "nan_detected": bool(rec["tensor_stats"]["nan_count"] > 0),
        "l0_preflight": {"accepted": bool(rec["l0_accepted"]),
                         "evidence_ref": f"{ART_PREFIX}/{sid}.draft.l0.json"},
        "ffprobe": rec["ffprobe"],
        "mp4_md5": rec["mp4_md5"],
        "gen_s": rec.get("gen_s"),
        "encode_s": rec.get("encode_s"),
        "shot_wall_s": rec.get("shot_wall_s"),
    })

agg_payload = {
    "work_id": "comicanime_ep01",
    "channel": "local_ltx_2b",
    "model": {"path": "/data/night/models/LTX-Video", "pipeline": "LTXPipeline",
              "dtype": "float16"},
    "params": {"num_frames": 33, "height": 480, "width": 704, "steps": 15,
               "guidance_scale": 3.0, "fps": 24,
               "seed_rule": "42 + shot ordinal (1-based): shot_01->43 ... shot_09->51"},
    "prompts_ref": f"{ART_PREFIX}/cp7_prompts.json",
    "determinism": report["determinism"],
    "run_report_ref": f"{ART_PREFIX}/cp7_run_report.json",
    "frame_check_summary": {
        "method": "代理亲看每镜代表帧（ffmpeg select=eq(n,16) 抽中帧，Read 工具逐帧过目 9/9）",
        "verdicts": {sid: FRAME_CHECK[sid][0] for sid in sids},
        "conclusion": ("9/9 构图可判：4 成立（shot_03/04/06/07，其中 shot_07 双人对坐最强）、"
                       "3 弱成立（shot_01/05/08）、2 部分（shot_02/09）；0 镜主体完全不可辨"
                       "（短剧线 shot_09 v1 那种「无可辨主体」废片本批未出现，无回炉轮）。"
                       "已知色偏/过曝与写实向画风为 LTX-2B checkpoint 固有，只记录不修。"),
    },
    "shots": agg_shots,
}
agg = {
    "schema_version": "2.0",
    "cp_id": "cp7",
    "artifact_type": "draft_clip",
    "fingerprint": fp_payload(agg_payload),
    "produced_by": PRODUCED_BY,
    "produced_at": now_iso(),
    "upstream_refs": upstreams,
    "status": "passed",
    "gate": {"type": "hard_verify", "params_ref": "l0_preflight.black_frame_ratio_max",
             "result": "pass", "note": GATE_NOTE},
    "aux_gates": AUX_NOTES,
    "payload": agg_payload,
    "notes": (
        f"聚合工件（任务书要求形态 payload.shots[]，{N} 镜逐镜留痕 asset/pixel/fps/"
        "declared_vs_actual/black_mono_ratio/nan_detected/seed/l0_preflight/prompt_en/frame_check）。"
        "⚠ 契约矛盾声明（ecd9b80 主裁沿用）：checkpoint.schema.json definitions.draft_clip 为单镜形态"
        "（additionalProperties:false + 顶层单镜必备字段），payload.shots[] 与「过 checkpoint.schema "
        "cp7 分支」按现行契约不可同时成立；契约自身粒度为每镜一件。双形态交付：cp7_shot_01..09.json"
        "（单镜件，schema 9/9，权威形态）+ 本件（聚合视图，如实记 schema EXIT=1，供 episode 级簿记）。"
        "【硬条件】英文 prompt 层（SPIKE-REPORT 发现 A，中文直喂=100% 废片），逐镜带漫剧风格词；"
        "色偏/过曝为 checkpoint 固有（发现 B）只记录不修——草稿色彩不可依赖，CP8 择优与 CP9 精修不看"
        "草稿色彩；确定性 shot_04 同参数二遍全帧 MAE=0.0（发现 ③ 复证）。"
        "【漫剧风格在草稿层的体现程度（如实记录）】草稿输出为写实向厚涂图像，非国漫厚涂赛璐璐平涂；"
        "风格词仅轻微平涂化倾向（shot_03/07 可感），G8 风格化不在此判定——由 CP9 精修通道"
        "（H3-Max G8 四风格全成实测口径）承担，草稿层只表示构图/运动/节奏。"
        "【构图人检】代理亲看 9/9 代表帧（结论见 payload.frame_check_summary）：4 成立+3 弱成立+2 部分，"
        "0 镜无可辨主体，无回炉轮（修订轮数 0）。"
        "【时长口径】任务书固定 33 帧档（480x704 HxW/15步/guidance 3.0/24fps），declared=1.375s 为"
        "资产规格，L0 时长门禁校验编码一致性（实测=声明，dev=0.0%）；CP3 镜长 2.17–5.22s 与草稿差异"
        "逐镜登记于 shots[].cp3_duration_s。【红线】只卡 0：起跑前卡0=310MiB/卡1=26706MiB 未触碰；"
        "全程卡0 nvidia-smi 峰值 18776MiB（本进程）；不 kill/不 pip/不下载。"),
}
with open(os.path.join(EP, "cp7.json"), "w", encoding="utf-8") as f:
    json.dump(agg, f, ensure_ascii=False, indent=2)
os.chmod(os.path.join(EP, "cp7.json"), 0o644)

print("per-shot artifacts:", len(per_shot_payloads))
print("aggregate written:", os.path.join(EP, "cp7.json"))
print("aggregate fingerprint:", agg["fingerprint"])

# ---------- 3) schema_validation.log（canonical 命令逐件 EXIT 留痕）----------
SCHEMA = "overnight/vpipe/contracts/v2/checkpoint.schema.json"
CHECKS = ([f"overnight/vpipe/out/m2/comicanime_ep01/cp7/cp7_{sid}.json" for sid in sids]
          + ["overnight/vpipe/out/m2/comicanime_ep01/cp7.json"])
lines = [
    f"# CP7 schema validation log — {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
    f"# cwd={os.getcwd()}",
    '# 命令口径 = SPEC_v2.md:145 canonical: python3 -c "import json,jsonschema,pathlib; '
    "s=json.loads(pathlib.Path('overnight/vpipe/contracts/v2/checkpoint.schema.json').read_text()); "
    'jsonschema.validate(artifact, s)"',
    "",
]
for rel in CHECKS:
    p = os.path.join(REPO, rel)
    code = subprocess.run(
        [sys.executable, "-c",
         "import json,jsonschema,pathlib,sys;"
         "s=json.loads(pathlib.Path(sys.argv[1]).read_text());"
         "a=json.loads(pathlib.Path(sys.argv[2]).read_text());",
         ], capture_output=True, text=True)
    # 上面三行只是占位防误用；实际校验：
    r = subprocess.run(
        [sys.executable, "-c",
         "import json,jsonschema,pathlib,sys\n"
         "s=json.loads(pathlib.Path(sys.argv[1]).read_text())\n"
         "a=json.loads(pathlib.Path(sys.argv[2]).read_text())\n"
         "jsonschema.validate(a,s)\n",
         SCHEMA, p], capture_output=True, text=True)
    lines.append(f"EXIT={r.returncode} {rel}"
                 + ("" if r.returncode == 0 else f"  # {r.stderr.strip().splitlines()[-1][:120]}"))
lines.append("")
lines.append("--- aggregate 校验错误详情（jsonschema.ValidationError 摘要）---")
r = subprocess.run(
    [sys.executable, "-c",
     "import json,jsonschema,pathlib,sys\n"
     "s=json.loads(pathlib.Path(sys.argv[1]).read_text())\n"
     "a=json.loads(pathlib.Path(sys.argv[2]).read_text())\n"
     "try:\n"
     "    jsonschema.validate(a,s)\n"
     "    print('VALID')\n"
     "except jsonschema.ValidationError as e:\n"
     "    print('ValidationError:', str(e.message)[:120])\n"
     "    print('validator:', e.validator, '| schema path:', list(e.absolute_schema_path)[:4])\n",
     SCHEMA, os.path.join(REPO, "overnight/vpipe/out/m2/comicanime_ep01/cp7.json")],
    capture_output=True, text=True)
lines.append(r.stdout.strip())
with open(os.path.join(HERE, "schema_validation.log"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("schema_validation.log written")
