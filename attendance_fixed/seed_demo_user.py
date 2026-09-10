#------------------------------------------------
# Colab / ローカル環境でこのアプリを試すためのセットアップスクリプト。
#
# 元リポジトリにコミットされていた db/attendance.db には、実際の従業員
# データ（従業員番号やパスワードハッシュ）が含まれている可能性があったため、
# このプロジェクトには含めていない。代わりに、このスクリプトを実行すると
# 空のDBを作成し、動作確認用のアカウントとサンプルの会館データ・勤怠データを
# 作成する。
#
#   1. 一般の従業員アカウント（出退勤の打刻用。is_admin=False）を3件
#      → それぞれ別々の会館名（Place）が割り当てられており、
#        本葬・通夜の出勤画面の「会館」プルダウンに、ログインした
#        ユーザーごとに異なる会館名が表示されることを確認できる。
#   2. 管理者アカウント（/admin のデータベース管理画面用。is_admin=True）を1件
#   3. [追加] 手配者アカウント（/arrangement_manage の手配書登録画面用。
#      is_arranger=True）を1件
#   4. [追加] 各従業員に、過去数ヶ月分のサンプル勤怠記録（Timeテーブル）
#      → ログイン後の「勤怠一覧」画面で、月を切り替えて過去の記録を
#        確認できることをすぐに試せるようにするため。
#   5. [追加] 本日分の手配書（Arrangementテーブル）のサンプルを1件
#      → ログイン後の「本日の手配書」ボタンをすぐに試せるようにするため。
#
# いずれも同じ /login 画面からログインするが、管理画面へは is_admin=True、
# 手配書登録画面へは is_arranger=True のアカウントでログインした場合だけ
# アクセスできる（admin.py・arrangement.py 参照）。
# 「その他」を選ぶと従来通り手動入力ができる（プルダウンの一覧には含めない）。
#
# 実際の従業員データ・会館データを使う場合は、管理者アカウントでログイン後、
# /admin 画面からUser・Placeを登録してください。
#------------------------------------------------

import os
import sys
import calendar
import datetime

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

from __init__ import app, db  # noqa: E402
from models import User, Place, Time, Arrangement  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402
from sqlalchemy.exc import IntegrityError, DataError  # noqa: E402

ADMIN_NUMBER = os.environ.get("ADMIN_USER_NUMBER", "9001")
ADMIN_NAME = os.environ.get("ADMIN_USER_NAME", "管理者")
ADMIN_PASSWORD = os.environ.get("ADMIN_USER_PASSWORD", "admin1234")

# [追加] 手配者アカウント（手配書登録画面 /arrangement_manage 専用）
ARRANGER_NUMBER = os.environ.get("ARRANGER_USER_NUMBER", "7001")
ARRANGER_NAME = os.environ.get("ARRANGER_USER_NAME", "手配担当")
ARRANGER_PASSWORD = os.environ.get("ARRANGER_USER_PASSWORD", "staff1234")

# 従業員番号・氏名・パスワード・その従業員が選べる会館名のリスト（適当なサンプル）。
# 「その他」はテンプレート側で自動的に末尾に追加されるため、ここには含めない。
DEMO_EMPLOYEES = [
    {
        "number": "0001",
        "name": "デモ太郎",
        "password": "demo1234",
        "places": ["愛知葬祭 春日井会場", "平安会館 一宮斎場"],
        # [追加] 本葬／通夜それぞれの時給サンプル値。管理画面(/admin/user/)で
        # 時給欄（honso_wage/tsuya_wage）がすぐに確認できるようにするため。
        "honso_wage": 1200,
        "tsuya_wage": 1000,
    },
    {
        "number": "0002",
        "name": "デモ次郎",
        "password": "demo2345",
        "places": ["名古屋メモリアルホール", "豊田会館"],
        "honso_wage": 1300,
        "tsuya_wage": 1100,
    },
    {
        "number": "0003",
        "name": "デモ花子",
        "password": "demo3456",
        "places": ["岡崎セレモニーホール", "安城会館", "刈谷会館"],
        "honso_wage": 1250,
        "tsuya_wage": 1050,
    },
]


def _create_user_if_missing(
    number, name, password, is_admin, places=None, is_arranger=False, honso_wage=0, tsuya_wage=0
):
    existing = User.query.filter_by(number=number).first()
    if existing:
        print(f"  従業員番号 {number} は既に存在します（作成をスキップ）。")
        return existing

    user = User(
        username=name,
        number=number,
        password=generate_password_hash(password),
        is_admin=is_admin,
        is_arranger=is_arranger,
        honso_wage=honso_wage,
        tsuya_wage=tsuya_wage,
    )
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        # [追加/Render対応] Renderではgunicornが複数ワーカープロセスで
        # このアプリを起動し、各ワーカーがそれぞれ起動時にこの関数を
        # 呼び出す。上の「既に存在するか」の確認から実際のcommitまでの間に
        # 別のワーカーが先に同じ従業員番号のユーザーを作成していた場合、
        # ここでUNIQUE制約違反になる。その場合はエラーにせず、既に作られた
        # 行を取得して返す（結果的に「既に存在する」場合と同じ扱いになる）。
        db.session.rollback()
        print(f"  従業員番号 {number} は他のプロセスが同時に作成済みでした（作成をスキップ）。")
        return User.query.filter_by(number=number).first()

    if is_admin:
        kind = "管理者アカウント"
    elif is_arranger:
        kind = "手配者アカウント"
    else:
        kind = "従業員アカウント"
    print(f"  {kind}を作成しました。 従業員番号: {number} / パスワード: {password}")

    for place_name in places or []:
        db.session.add(Place(user_id=user.id, place=place_name))
    if places:
        db.session.commit()
        print(f"    会館名を登録しました: {', '.join(places)}")

    return user


#------------------------------------------------
# [追加] 「勤怠一覧」画面の月選択機能をすぐに試せるように、各従業員へ
# 過去数ヶ月分のサンプル勤怠記録（Timeテーブル）を作成する。
#
# ・当月分は、まだ本日の打刻に使っていない「本日より前の日付」だけに
#   限定して作成する（本日の日付には絶対に作らない）。これは、本日の
#   打刻機能（本葬・通夜の出退勤）が別途このレコードを検索・更新する際に、
#   サンプルデータと衝突しないようにするための安全対策。
# ・前月・前々月分は、月全体が必ず過去なので日付の制限は不要。
# ・既にその従業員・その日付のレコードがあれば作らない（重複防止・再実行安全）。
#------------------------------------------------
def _month_add(year, month, delta):
    total = (year * 12 + (month - 1)) + delta
    return total // 12, total % 12 + 1


def _sample_days_for_month(year, month, days, today_date=None):
    last_day = calendar.monthrange(year, month)[1]
    result = []
    for d in days:
        if d > last_day:
            continue
        candidate = datetime.date(year, month, d)
        if today_date is not None and candidate >= today_date:
            # 当月のうち、本日以降の日付にはサンプルを作らない
            continue
        result.append(candidate)
    return result


def _create_sample_attendance_for_employee(number, places):
    today_date = datetime.date.today()
    y0, m0 = today_date.year, today_date.month
    y1, m1 = _month_add(y0, m0, -1)
    y2, m2 = _month_add(y0, m0, -2)

    sample_dates = (
        _sample_days_for_month(y0, m0, [3, 10], today_date=today_date)
        + _sample_days_for_month(y1, m1, [5, 12, 19])
        + _sample_days_for_month(y2, m2, [7, 14])
    )

    place_a = places[0] if places else "本社"
    place_b = places[1] if len(places) > 1 else place_a

    # (place1, start1, end1, leader1, place2, start2, end2, wait2) の
    # パターンを日ごとに順番に使う（本葬のみ／通夜のみ／両方、を混在させる）。
    patterns = [
        (place_a, "09:00", "17:00", "on", None, None, None, None),
        (None, None, None, None, place_b, "18:00", "21:00", "on"),
        (place_a, "08:30", "13:00", None, place_b, "18:00", "22:00", None),
    ]

    created = 0
    for i, d in enumerate(sample_dates):
        date_str = d.isoformat()
        if Time.query.filter_by(number=number, date=date_str).first():
            continue

        place1, start1, end1, leader1, place2, start2, end2, wait2 = patterns[i % len(patterns)]
        record = Time(date=date_str, number=number)
        if start1:
            record.place1 = place1
            record.start1 = start1
            record.end1 = end1
            record.leader1 = leader1
        if start2:
            record.place2 = place2
            record.start2 = start2
            record.end2 = end2
            record.wait2 = wait2

        db.session.add(record)
        try:
            # [追加/Render対応] 1件ずつcommitすることで、複数ワーカーが
            # 同時にこの処理を実行して1件だけ衝突（UNIQUE制約違反）した
            # 場合でも、その1件だけをスキップして残りの日付は正常に
            # 作成できるようにしている（まとめてcommitすると、1件の
            # 衝突で他の正常な行までロールバックされてしまうため）。
            db.session.commit()
            created += 1
        except (IntegrityError, DataError):
            # [追加/Neon対応] DataError（例: PostgreSQLで文字数上限を
            # 超えたためのStringDataRightTruncationなど）も、1件だけ
            # スキップしてロールバックする。以前はIntegrityErrorしか
            # 捕まえていなかったため、サンプル勤怠データの作成中にこの
            # 種のエラーが起きるとアプリ起動処理全体が異常終了して
            # しまっていた（Time.place1等の文字数上限が短すぎた不具合を
            # 機に発覚）。根本原因（models.pyの文字数上限）自体は修正済みだが、
            # 同種の想定外エラーで再度アプリ全体が落ちてしまわないよう、
            # 保険として広めに捕まえるようにした。
            db.session.rollback()
            print(f"    サンプル勤怠記録の作成に失敗したためスキップしました（日付: {date_str}）。")

    return created


#------------------------------------------------
# [追加] 「本日の手配書」機能をすぐに試せるように、本日分のサンプルの
# 手配書（Arrangement）を1件作成する（画像は同梱していないため、
# メモのみのサンプルにしている。画像付きの手配書は/arrangement_manageから
# 手配者アカウントでアップロードして試せる）。
#------------------------------------------------
def _create_sample_arrangement(target_number, shift, memo, created_by_number, today_date):
    target_user = User.query.filter_by(number=target_number).first()
    created_by_user = User.query.filter_by(number=created_by_number).first()
    if not target_user:
        return False

    date_str = today_date.isoformat()
    if Arrangement.query.filter_by(target_user_id=target_user.id, shift=shift, date=date_str).first():
        return False

    now = datetime.datetime.now()
    db.session.add(Arrangement(
        target_user_id=target_user.id,
        shift=shift,
        date=date_str,
        memo=memo,
        created_by_id=created_by_user.id if created_by_user else None,
        created_at=now,
        updated_at=now,
    ))
    try:
        db.session.commit()
    except IntegrityError:
        # [追加/Render対応] 複数ワーカーが同時にこの処理を実行し、
        # 既に他のワーカーが同じ手配書を作成済みだった場合（UNIQUE制約
        # 違反）は、エラーにせず「既に作成済み」として扱う。
        db.session.rollback()
        return False
    return True


def main():
    with app.app_context():
        db.create_all()

        print("デモ用アカウントを準備します。")
        for emp in DEMO_EMPLOYEES:
            _create_user_if_missing(
                emp["number"], emp["name"], emp["password"], is_admin=False, places=emp["places"],
                honso_wage=emp.get("honso_wage", 0), tsuya_wage=emp.get("tsuya_wage", 0),
            )
        _create_user_if_missing(ADMIN_NUMBER, ADMIN_NAME, ADMIN_PASSWORD, is_admin=True)
        _create_user_if_missing(ARRANGER_NUMBER, ARRANGER_NAME, ARRANGER_PASSWORD, is_admin=False, is_arranger=True)

        print("過去数ヶ月分のサンプル勤怠記録を準備します。")
        for emp in DEMO_EMPLOYEES:
            created = _create_sample_attendance_for_employee(emp["number"], emp["places"])
            if created:
                print(f"  従業員番号 {emp['number']} に {created} 件のサンプル勤怠記録を作成しました。")
            else:
                print(f"  従業員番号 {emp['number']} のサンプル勤怠記録は既に作成済みです（スキップ）。")

        print("本日分のサンプル手配書を準備します。")
        created = _create_sample_arrangement(
            target_number=DEMO_EMPLOYEES[0]["number"],
            shift="honso",
            memo="本日は式場入り口の設営を先に行ってください。祭壇の花は14時搬入予定です。",
            created_by_number=ARRANGER_NUMBER,
            today_date=datetime.date.today(),
        )
        if created:
            print(f"  従業員番号 {DEMO_EMPLOYEES[0]['number']} 宛て・本葬のサンプル手配書を作成しました。")
        else:
            print("  本日分のサンプル手配書は既に作成済みです（スキップ）。")


if __name__ == "__main__":
    main()
