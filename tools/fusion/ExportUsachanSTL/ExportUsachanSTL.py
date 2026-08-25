# -*- coding: utf-8 -*-
"""usachan_asm の部品を STL として body/ に書き出す（Fusion 360 スクリプト）。

Fusion 側で実行します。

    ユーティリティ > アドイン > スクリプトとアドイン
      > スクリプト タブの「+」> 既存のスクリプトを追加
      > このファイルが入っているフォルダを選ぶ
      > ExportUsachanSTL を選んで「実行」

**M5Stack と基板のモデルは書き出しません。** 買ってきた基板も
Eagle から来た基板も印刷対象ではないうえ、部品数が多くてファイルも
大きいためです。除外は名前の部分一致で行うので、機体側の部品に
"cores3" や "board" のような名前を付けると巻き込まれます。
実行後のレポートで何を飛ばしたか確認できます。

書き出しは**コンポーネントのローカル座標**で行います。組立位置ではなく
部品それぞれの原点で出るので、そのままスライサに載せられます。
"""

import os
import re
import traceback

import adsk.core
import adsk.fusion


# ---- 設定 -----------------------------------------------------------------

# 書き出し先。既定ではこのスクリプトから見たリポジトリの body/。
# スクリプトを別の場所へ置いた場合はここを直接書く（例 r"C:\\path\\to\\body"）
OUTPUT_DIR = None

# 開いているドキュメントがこれでなければ確認を出す
EXPECTED_DOC = "usachan_asm"

# 書き出さない部品。**小文字の部分一致**で判定する。
# "m5" だけにすると M5 ネジ（M5x12 など）まで巻き込むので入れないこと。
# "board" は Eagle から来た基板（usachan_board_hip など）を落とすため
SKIP_PATTERNS = (
    "m5stack", "m5 stack", "m5-stack", "cores3", "core s3", "core_s3",
    "board",
)

# メッシュの細かさ。high / medium / low
REFINEMENT = "high"

# バイナリ STL。ASCII より桁違いに小さい
BINARY_STL = True


# ---- 中身 -----------------------------------------------------------------

def _default_output_dir():
    """tools/fusion/ExportUsachanSTL/ から見たリポジトリ直下の body/。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", "..", "body"))


def _sanitize(name):
    """コンポーネント名をファイル名にする。"""
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    name = re.sub(r"\s+", "_", name.strip())
    name = name.rstrip(". ")
    return name or "part"


def _skip_reason(name):
    low = name.lower()
    for pat in SKIP_PATTERNS:
        if pat in low:
            return pat
    return None


def _find_nested_skips(occurrence, found, depth=0):
    """書き出す部品の中に、除外したいものが入っていないか見る。

    入れ子になっていると STL からは分離できないので、警告するしかない。
    """
    if depth > 8:
        return
    for child in occurrence.childOccurrences:
        if _skip_reason(child.component.name):
            found.append(child.component.name)
        _find_nested_skips(child, found, depth + 1)


def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

        design = adsk.fusion.Design.cast(app.activeProduct)
        if not design:
            ui.messageBox(
                "デザインが開かれていません。\n"
                "{} を開いてから実行してください。".format(EXPECTED_DOC)
            )
            return

        doc_name = app.activeDocument.name
        root = design.rootComponent

        # 別のドキュメントで走らせて上書きしないように確かめる
        want = EXPECTED_DOC.lower()
        if want not in doc_name.lower() and want not in root.name.lower():
            answer = ui.messageBox(
                "開いているのは「{}」です。\n"
                "{} ではありませんが、このまま書き出しますか？".format(doc_name, EXPECTED_DOC),
                "書き出し先の確認",
                adsk.core.MessageBoxButtonTypes.YesNoButtonType,
                adsk.core.MessageBoxIconTypes.WarningIconType,
            )
            if answer != adsk.core.DialogResults.DialogYes:
                return

        out_dir = OUTPUT_DIR or _default_output_dir()
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir)

        refinement = {
            "high": adsk.fusion.MeshRefinementSettings.MeshRefinementHigh,
            "medium": adsk.fusion.MeshRefinementSettings.MeshRefinementMedium,
            "low": adsk.fusion.MeshRefinementSettings.MeshRefinementLow,
        }[REFINEMENT]

        export_mgr = design.exportManager

        exported = []
        skipped = []
        empty = []
        warnings = []
        seen = set()

        for occurrence in root.occurrences:
            component = occurrence.component
            name = component.name

            reason = _skip_reason(name)
            if reason:
                skipped.append("{}   ← {} に一致".format(name, reason))
                continue

            # 同じ部品が複数配置されていても1つでよい
            if name in seen:
                continue
            seen.add(name)

            if component.bRepBodies.count == 0 and component.occurrences.count == 0:
                empty.append(name)
                continue

            nested = []
            _find_nested_skips(occurrence, nested)
            if nested:
                warnings.append(
                    "{} の中に {} が入っています（STL からは分離できません）".format(
                        name, " / ".join(sorted(set(nested)))
                    )
                )

            path = os.path.join(out_dir, _sanitize(name) + ".stl")
            options = export_mgr.createSTLExportOptions(component, path)
            options.meshRefinement = refinement
            options.isBinaryFormat = BINARY_STL
            export_mgr.execute(options)

            size_kb = os.path.getsize(path) / 1024.0
            exported.append("{}  ({:.0f} KB)".format(os.path.basename(path), size_kb))

        # ---- 結果 ----
        lines = ["書き出し先: {}".format(out_dir), ""]
        lines.append("書き出した部品 {} 個".format(len(exported)))
        lines.extend("    " + s for s in exported)

        if skipped:
            lines += ["", "飛ばした部品 {} 個".format(len(skipped))]
            lines.extend("    " + s for s in skipped)
        if empty:
            lines += ["", "形が無いので飛ばした {} 個".format(len(empty))]
            lines.extend("    " + s for s in empty)
        if warnings:
            lines += ["", "確認してください"]
            lines.extend("    " + s for s in warnings)
        if not exported:
            lines += ["", "1つも書き出していません。SKIP_PATTERNS が"
                          "広すぎないか、部品に形があるか確かめてください。"]

        ui.messageBox("\n".join(lines), "STL 書き出し")

    except Exception:
        if ui:
            ui.messageBox("失敗しました:\n{}".format(traceback.format_exc()), "STL 書き出し")
