#------------------------------------------------
# [追加] 「手当」欄（休憩を除く：リーダー・サブリーダー・研修・待機・
# 指定日・遠方地・特別手当・高速道路）に関する共通定義・ヘルパー。
#
# 従来はこれらの項目を従業員本人が出退勤画面（honso_stamp/tsuya_stamp・
# honso_modify/tsuya_modify）でチェックしていたが、手配者が手配書登録
# 画面(/arrangement_manage)で金額まで指定して設定する方式に変更した
# （高速道路は元々「チェック＋金額」の組み合わせだったため、それを
# 他の項目にも広げた形）。
#
# 手配書登録画面(arrangement.py)・出退勤画面(honso.py/tsuya.py)の
# 両方から参照するため、共通モジュールとしてここに定義している。
#------------------------------------------------

from models import Time  # noqa: F401  (型ヒント代わりのコメント用途、実際の参照はしない)

# [追加] 「高速道路」は、models.Timeに元々ある専用カラム
# (highway1/express1・highway2/express2)をそのまま使うため、
# ALLOWANCE_ITEMS（Arrangement/Timeの"{item}_amount"系カラムを
# そのまま使う項目）には含めず、別扱いにしている。
ALLOWANCE_ITEMS = ["leader", "subleader", "teach", "wait", "designated", "distant", "special"]

ALLOWANCE_LABELS = {
    "leader": "リーダー",
    "subleader": "サブリーダー",
    "teach": "研修",
    "wait": "待機",
    "designated": "指定日",
    "distant": "遠方地",
    "special": "特別手当",
    "highway": "高速道路",
}


#------------------------------------------------
# [追加] フォームから受け取った金額の文字列を、0以上の整数に変換する。
# チェックが外れている項目は、その金額入力欄自体がdisabledになっており
# フォーム送信時に値が送られない（会館名選択のロック機能と同じ仕組み）
# ため、未入力(None)として扱う。数値として解釈できない値・マイナスの
# 値が来た場合も、安全側に倒してNone（＝この項目は設定しない）とする。
#------------------------------------------------
def parse_optional_amount(raw):
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value < 0:
        return None
    return value


#------------------------------------------------
# [追加] 手配書登録フォームから、「手当」欄の各項目の金額をまとめて取得する。
# 戻り値は {"leader": 500, "subleader": None, ..., "highway": 1000} の形式
# （ALLOWANCE_ITEMSの各項目＋"highway"）。
#------------------------------------------------
def parse_allowance_amounts(form):
    amounts = {item: parse_optional_amount(form.get("{}_amount".format(item))) for item in ALLOWANCE_ITEMS}
    amounts["highway"] = parse_optional_amount(form.get("highway_amount"))
    return amounts


#------------------------------------------------
# [追加] Timeレコードから、実際に金額が設定されている「手当」項目
# （休憩を除く）だけを、出退勤画面(honso_stamp/tsuya_stamp・
# honso_modify/tsuya_modify)の「休憩」欄の下に表示するためのリストを
# 組み立てる。shiftには"honso"または"tsuya"を渡す。
# 戻り値は [{"label": "リーダー", "amount": 500}, ...] の形式
# （金額が設定されている項目が無ければ空リスト）。
#------------------------------------------------
def allowance_display_items(record, shift):
    if not record:
        return []

    suffix = "1" if shift == "honso" else "2"
    items = []
    for item in ALLOWANCE_ITEMS:
        amount = getattr(record, "{}_amount{}".format(item, suffix), None)
        if amount is not None:
            items.append({"label": ALLOWANCE_LABELS[item], "amount": amount})

    # [追加] 「高速道路」は既存のhighway1/express1・highway2/express2を
    # そのまま使う。express1/2は文字列型で保存されているため、数値に
    # 変換できる場合のみ表示する。
    express = record.express1 if shift == "honso" else record.express2
    if express not in (None, ""):
        try:
            highway_amount = int(express)
        except (TypeError, ValueError):
            highway_amount = None
        if highway_amount is not None:
            items.append({"label": ALLOWANCE_LABELS["highway"], "amount": highway_amount})

    return items
