#------------------------------------------------
# [追加] 「本日の手配書」機能。
#
# ・手配者アカウント（models.Userのis_arranger=True）専用の登録画面
#   (/arrangement_manage) で、一般ユーザー・本葬/通夜・日付を指定して
#   画像（またはPDF）とメモを登録する。
# ・一般ユーザーは、ログイン後の勤務選択画面(select.html)にある
#   「本日の手配書」ボタンから /today_arrangement を開き、自分宛て・
#   本日分の画像・PDFとメモだけを確認できる。
# ・アップロードしたファイルは、本人・手配者・管理者以外には見えないよう、
#   専用のルート(/arrangement_image/<id>) 経由でアクセス制御した上で
#   配信する（Flaskの静的配信(/static/...)は使わない）。
#   [修正] 会館案内図など、PDFで渡されることも多いため、画像形式に
#   加えてPDFもアップロードできるようにした。DBのカラム名・フォーム項目名
#   （image_filename等）は既存のまま流用しており、「画像」という名前だが
#   実際にはPDFも保存できる（テンプレート側では拡張子がpdfかどうかで
#   表示方法を分けている）。
#   [修正/Neon対応] ファイル本体の保存先を、サーバーのディスク
#   （uploads/arrangements/ 配下）からDB内（models.Arrangement.image_data、
#   バイナリ型）に変更した。DBをSQLiteからNeon(PostgreSQL)へ移行するのに
#   合わせて、Render側に永続ディスクを用意しなくても画像・PDFが
#   再デプロイ・再起動で消えないようにするため。
#------------------------------------------------

import datetime
import uuid
from functools import wraps

from __init__ import app, db, login_manager, get_today

from flask import (
    request, render_template, redirect, url_for, Response, abort,
)
from flask_login import login_required, current_user

from models import User, Arrangement, Place, Time
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
# [追加] 「手当」欄（休憩以外）に関する共通定義・ヘルパー（honso.py/tsuya.py
# と共有するため、allowances.pyに切り出している）。
from allowances import ALLOWANCE_ITEMS, ALLOWANCE_LABELS, parse_allowance_amounts
# [追加] 手配書登録時のメール通知（出退勤画面と同じ仕組みを使う）。
import notifications


ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "pdf"}

# [追加/Neon対応] DBに保存したバイナリを配信する際、拡張子から適切な
# Content-Typeを判定するための対応表。
_MIME_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "pdf": "application/pdf",
}


def _is_allowed_image(filename):
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_IMAGE_EXTENSIONS


def _guess_mimetype(filename):
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[1].lower()
        return _MIME_TYPES.get(ext, "application/octet-stream")
    return "application/octet-stream"


#------------------------------------------------
# [追加] 指定したユーザーに紐づく会館名の一覧を取得するヘルパー。
# honso.get_places_for_current_user / tsuya.get_places_for_current_user と
# 同じ考え方だが、こちらはログイン中の本人ではなく、手配書の対象ユーザー
# （手配者が選択した任意のユーザー）向けに使うため、user_idを引数で受け取る。
#------------------------------------------------
def _places_for_user(user_id):
    return [
        p.place
        for p in Place.query.filter(
            (Place.user_id == user_id) | (Place.user_id.is_(None))
        )
        .order_by(Place.id)
        .all()
    ]


#------------------------------------------------
# [追加] 手配書登録画面で、対象ユーザーを切り替えたときに会館名の選択肢も
# 連動して切り替えられるようにするため、従業員ごとの会館名一覧を
# あらかじめまとめて用意し、JavaScript側（テンプレートの<script>内）に
# 渡す。{"1": ["会館A", "会館B"], "2": [...] , ...} という形式。
#------------------------------------------------
def _employee_places_map(employees):
    return {str(e.id): _places_for_user(e.id) for e in employees}


#------------------------------------------------
# [追加] 「その他」が選択されていた場合は手入力の会館名(other_place)を、
# それ以外の場合は選択された会館名(place)をそのまま返す表示用ヘルパー。
# 未入力の場合はNoneを返す（テンプレート側で「未定」等の表示に使う）。
#------------------------------------------------
def _effective_place(place, other_place):
    if place == "その他":
        return other_place or None
    return place or None


#------------------------------------------------
# [追加] 手配者が手配書登録画面で設定した会館名・「手当」の金額を、
# 対象ユーザーの出退勤画面(honso_stamp/tsuya_stamp)にも反映されるよう
# Timeレコードに書き込む。「手配者がユーザーの代理で設定する」という
# 位置づけのため、対象ユーザー・日付のTimeレコードが無ければ新規作成する。
#
# ・会館名(place)が選択されていない（未定のまま）場合は、Timeの会館名
#   （place1/other1またはplace2/other2）はそのまま変更しない。手配書の
#   メモだけを更新したくて会館名欄を選び直さなかったときに、既に入って
#   いる会館名を誤って消してしまわないようにするため。
# ・「手当」の金額(amounts)も同様に、この手配書でチェックされた
#   （＝Noneでない）項目だけをTimeに反映し、チェックされなかった項目は
#   そのまま変更しない（同じ理由。フォームは毎回空の状態から入力する
#   ため、前回チェックした項目を今回も律儀に再現しないと消えてしまう、
#   という事態を避けるため）。
# ・会館名・金額のいずれも指定が無ければ、Timeレコード自体を新規に
#   作らない（何も書き込むことが無いため）。
#------------------------------------------------
def _apply_arrangement_to_time_record(number, shift, date_str, place, other_place, amounts):
    has_amount = any(v is not None for v in amounts.values())
    if not place and not has_amount:
        return

    record = Time.query.filter_by(number=number, date=date_str).first()
    if not record:
        record = Time(number=number, date=date_str)
        db.session.add(record)

    suffix = "1" if shift == "honso" else "2"

    if place:
        if shift == "honso":
            record.place1 = place
            record.other1 = other_place if place == "その他" else ""
        else:
            record.place2 = place
            record.other2 = other_place if place == "その他" else ""

    for item in ALLOWANCE_ITEMS:
        amount = amounts.get(item)
        if amount is not None:
            setattr(record, "{}_amount{}".format(item, suffix), amount)

    # [追加] 「高速道路」は、Timeモデルに元々ある専用カラム
    # (highway1/express1・highway2/express2)をそのまま使う。他の項目と
    # 同様、金額が指定されていない場合は既存の値を変更しない。
    highway_amount = amounts.get("highway")
    if highway_amount is not None:
        if shift == "honso":
            record.highway1 = "on"
            record.express1 = str(highway_amount)
        else:
            record.highway2 = "on"
            record.express2 = str(highway_amount)

    try:
        db.session.commit()
    except IntegrityError:
        # [追加] ごく稀に、手配者がこの操作をしたのとほぼ同時に従業員
        # 本人がその日の出勤打刻を行い、Time(number, date)の一意制約に
        # 抵触することがある。その場合は従業員本人の打刻データを
        # 優先し、手配者側の会館名設定は反映しない（エラー画面は
        # 出さず、手配書自体の登録は成功させる）。
        # [修正] 原因調査をしやすくするため、握りつぶす前に必ずログへ
        # 記録する（Renderの Logs タブで確認できる）。
        app.logger.exception("手配書→勤怠(Time)への反映に失敗しました（一意制約違反のため無視）")
        db.session.rollback()
    except SQLAlchemyError:
        # [追加] 想定していない種類のDBエラー（列不足やデータ型不一致など）
        # も、ここで握りつぶさずログに残した上でロールバックする。
        # 手配書(Arrangement)自体は既に保存済みのため、エラー画面は出さない。
        app.logger.exception("手配書→勤怠(Time)への反映に失敗しました")
        db.session.rollback()


#------------------------------------------------
# [追加] 手配者アカウント専用ページ用のデコレータ。
# @login_required と組み合わせて使う（未ログインは@login_requiredが
# 先に/loginへリダイレクトする）。ログイン済みだが手配者でない場合は
# /login にリダイレクトする（一般従業員・管理者はこの画面には入れない）。
#------------------------------------------------
def arranger_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not (current_user.is_authenticated and bool(getattr(current_user, "is_arranger", False))):
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)
    return wrapped


#------------------------------------------------
# 手配書登録画面（手配者専用）
#------------------------------------------------
@app.route('/arrangement_manage', methods=["GET", "POST"])
@login_required
@arranger_required
def arrangement_manage():

    error_message = None
    # [追加] 会館名(Place)登録フォーム用のエラーメッセージ。手配書登録フォーム
    # とは別のフォームなので、エラーメッセージも分けて持つ。
    place_error_message = None

    if request.method == 'POST' and request.form.get('form_type') == 'place':
        # [追加] 「会館名の登録」フォーム（手配者が特定の従業員向けの会館名を
        # 追加する）。従来は管理画面(/admin/place/)からしか登録できなかった
        # 会館名(models.Place)を、手配者アカウントからも登録できるようにする。
        place_target_user_id = request.form.get('place_target_user_id')
        place_name = (request.form.get('place_name') or '').strip()
        # [追加] 会館ごとの交通費（円）。未入力・数値として解釈できない場合は
        # 0円として扱う（honso_wage/tsuya_wage等と同じ考え方）。
        transportation_fee_raw = request.form.get('transportation_fee')
        try:
            transportation_fee = int(transportation_fee_raw) if transportation_fee_raw else 0
        except ValueError:
            transportation_fee = 0
        if transportation_fee < 0:
            transportation_fee = 0

        place_target_user = (
            User.query.get(int(place_target_user_id))
            if place_target_user_id and place_target_user_id.isdigit() else None
        )

        if not place_target_user:
            place_error_message = "会館名を登録する対象ユーザーを選択してください。"
        elif not place_name:
            place_error_message = "会館名を入力してください。"
        else:
            db.session.add(Place(
                user_id=place_target_user.id,
                place=place_name,
                transportation_fee=transportation_fee,
            ))
            db.session.commit()
            return redirect(url_for('arrangement_manage'))

    elif request.method == 'POST':
        target_user_id = request.form.get('target_user_id')
        shift = request.form.get('shift')
        date_str = request.form.get('date')
        memo = (request.form.get('memo') or '').strip()
        image_file = request.files.get('image')
        # [追加] 対象ユーザーの出退勤画面と同じ会館名選択肢から、この手配が
        # どの会館のものかを指定できるようにする（任意入力。未定のまま
        # 手配書だけ先に登録してもよい）。「その他」を選んだ場合のみ
        # other_placeを使う（models.Time.place1/other1と同じ考え方）。
        place = (request.form.get('place') or '').strip() or None
        other_place = (request.form.get('other_place') or '').strip() or None
        if place != "その他":
            other_place = None
        # [追加] 「手当」欄（休憩以外）の各項目の金額。従来は従業員本人が
        # 出退勤画面でチェックしていたが、手配者がこの画面で金額まで
        # 指定して設定する（_apply_arrangement_to_time_record参照）。
        allowance_amounts = parse_allowance_amounts(request.form)

        target_user = User.query.get(int(target_user_id)) if target_user_id and target_user_id.isdigit() else None

        if not target_user or shift not in ("honso", "tsuya") or not date_str:
            error_message = "対象ユーザー・本葬/通夜・日付を正しく指定してください。"
        elif not memo and not (image_file and image_file.filename):
            error_message = "画像・PDF・メモのいずれかを入力してください。"
        elif image_file and image_file.filename and not _is_allowed_image(image_file.filename):
            error_message = "ファイルの形式が対応していません（png/jpg/jpeg/gif/webp/pdfのみ）。"
        else:
            image_filename = None
            image_data = None
            if image_file and image_file.filename:
                ext = image_file.filename.rsplit(".", 1)[1].lower()
                image_filename = "{}.{}".format(uuid.uuid4().hex, ext)
                # [修正/Neon対応] ファイルをディスクに保存する代わりに、
                # 中身をそのままバイト列として読み込み、DBカラムに保存する。
                image_data = image_file.read()

            now = datetime.datetime.now()

            # [追加] 同じ (対象ユーザー・本葬/通夜・日付) の手配書が既にあれば、
            # 新しく行を増やすのではなく上書き（更新）する。
            existing = Arrangement.query.filter_by(
                target_user_id=target_user.id, shift=shift, date=date_str
            ).first()

            # [修正] 「既存レコードの更新」「新規作成」のどちらの分岐でも、
            # 保存に成功した後（メール通知・Time反映）に同じ変数から参照
            # できるよう、対象のArrangementオブジェクトを共通の変数に
            # まとめておく。
            if existing:
                arrangement_record = existing
                if image_filename:
                    arrangement_record.image_filename = image_filename
                    arrangement_record.image_data = image_data
                arrangement_record.memo = memo or None
                arrangement_record.place = place
                arrangement_record.other_place = other_place
                arrangement_record.leader_amount = allowance_amounts["leader"]
                arrangement_record.subleader_amount = allowance_amounts["subleader"]
                arrangement_record.teach_amount = allowance_amounts["teach"]
                arrangement_record.wait_amount = allowance_amounts["wait"]
                arrangement_record.designated_amount = allowance_amounts["designated"]
                arrangement_record.distant_amount = allowance_amounts["distant"]
                arrangement_record.special_amount = allowance_amounts["special"]
                arrangement_record.highway_amount = allowance_amounts["highway"]
                arrangement_record.created_by_id = current_user.id
                # [追加] 手配者の氏名を、登録した時点の値として複製しておく
                # （models.Arrangement.created_by_name参照）。
                arrangement_record.created_by_name = current_user.username
                arrangement_record.updated_at = now
            else:
                arrangement_record = Arrangement(
                    target_user_id=target_user.id,
                    shift=shift,
                    date=date_str,
                    image_filename=image_filename,
                    image_data=image_data,
                    memo=memo or None,
                    place=place,
                    other_place=other_place,
                    leader_amount=allowance_amounts["leader"],
                    subleader_amount=allowance_amounts["subleader"],
                    teach_amount=allowance_amounts["teach"],
                    wait_amount=allowance_amounts["wait"],
                    designated_amount=allowance_amounts["designated"],
                    distant_amount=allowance_amounts["distant"],
                    special_amount=allowance_amounts["special"],
                    highway_amount=allowance_amounts["highway"],
                    created_by_id=current_user.id,
                    created_by_name=current_user.username,
                    created_at=now,
                    updated_at=now,
                )
                db.session.add(arrangement_record)

            # [修正] 以前はここでIntegrityError等が起きても画面には何も
            # 表示せず一覧画面へリダイレクトしていたため、実際には保存に
            # 失敗していても「登録できたように見えて一覧に増えない」という
            # 分かりにくい状態になっていた（原因調査時に判明）。
            # 保存が失敗した場合は必ずログに記録した上で、リダイレクトせず
            # エラーメッセージ付きで登録画面を再表示するようにした。
            save_succeeded = True
            try:
                db.session.commit()
            except IntegrityError:
                # [追加] Arrangement(target_user_id, shift, date)にはDBの
                # 一意制約がある（models.py参照）。複数の手配者が同時に
                # 同じ対象者・本葬/通夜・日付の手配書を新規登録しようと
                # した場合など、ごく稀にここで衝突することがある。
                db.session.rollback()
                app.logger.exception("手配書の保存に失敗しました（一意制約違反）")
                error_message = (
                    "同じ内容の手配書が別の手配者によってほぼ同時に登録された"
                    "可能性があります。画面を更新してから、もう一度お試しください。"
                )
                save_succeeded = False
            except SQLAlchemyError:
                # [追加] 想定していない種類のDBエラー（例: DB側の列が
                # 足りない等）が起きた場合も、エラー画面ではなく登録画面に
                # メッセージを表示しつつ、詳細はログ（Renderの Logs タブ）に
                # 残す。原因調査をしやすくするための変更。
                db.session.rollback()
                app.logger.exception("手配書の保存に失敗しました")
                error_message = (
                    "手配書の保存に失敗しました。時間をおいて再度お試しいただくか、"
                    "解決しない場合は管理者にお問い合わせください。"
                )
                save_succeeded = False

            if save_succeeded:
                # [追加] 会館名・「手当」の金額が指定されていれば、対象ユーザーの
                # 出退勤画面（honso_stamp/tsuya_stamp）にも反映されるよう、
                # Timeレコードに書き込む
                # （「手配者がユーザーの代理で設定する」イメージ）。
                _apply_arrangement_to_time_record(
                    target_user.number, shift, date_str, place, other_place, allowance_amounts
                )

                # [追加] 手配書登録画面で「登録する」ボタンが押されたときにも、
                # 出退勤画面と同じ宛先(NOTIFY_EMAIL_TO)へ通知メールを送る。
                # 添付・メモの有無は、今回の入力だけでなく保存後の実際の値
                # （既存の手配書を更新した場合、今回添付しなくても以前の
                # 添付が残っていればそれも「あり」として扱う）を見る。
                notifications.send_arrangement_notification(
                    arranger_name=current_user.username,
                    target_user_name=target_user.username,
                    place=place,
                    other=other_place,
                    shift_label="本葬" if shift == "honso" else "通夜",
                    has_attachment=bool(arrangement_record.image_filename),
                    has_memo=bool(arrangement_record.memo),
                )

                return redirect(url_for('arrangement_manage'))

    # [追加] 対象ユーザーの選択肢は、一般従業員（管理者・手配者を除く）のみ。
    employees = User.query.filter_by(is_admin=False, is_arranger=False).order_by(User.number).all()
    arrangements = (
        Arrangement.query
        .order_by(Arrangement.date.desc(), Arrangement.id.desc())
        .all()
    )
    # [追加] ユーザーごとに登録された会館名(Place)の一覧。全員共通
    # (user_id が未設定)の行は、このページからは追加・削除できない
    # （引き続き管理画面(/admin/place/)でのみ扱う）ため、一覧にも含めない。
    places = (
        Place.query
        .filter(Place.user_id.isnot(None))
        .join(User, Place.user_id == User.id)
        .order_by(User.number, Place.id)
        .all()
    )
    # [追加] 手配書登録フォームの会館名選択肢を、対象ユーザーの切り替えに
    # 連動させるためのデータ（テンプレート側でJavaScriptに渡す）。
    employee_places = _employee_places_map(employees)
    # [追加] 手配書登録フォームに表示する「手当」項目一覧（表示順を固定する
    # ため、辞書ではなくタプルのリストとして渡す）。
    allowance_items = [(item, ALLOWANCE_LABELS[item]) for item in ALLOWANCE_ITEMS + ["highway"]]

    return render_template(
        'arrangement_manage.html',
        title="手配書登録",
        employees=employees,
        employee_places=employee_places,
        arrangements=arrangements,
        places=places,
        allowance_items=allowance_items,
        error_message=error_message,
        place_error_message=place_error_message,
        today_str=get_today(),
    )


#------------------------------------------------
# 手配書の削除（手配者専用）
#------------------------------------------------
@app.route('/arrangement_delete/<int:arrangement_id>', methods=["POST"])
@login_required
@arranger_required
def arrangement_delete(arrangement_id):
    record = Arrangement.query.get(arrangement_id)
    if record:
        db.session.delete(record)
        db.session.commit()
    return redirect(url_for('arrangement_manage'))


#------------------------------------------------
# [追加] 手配者が登録した会館名(Place)の削除。
# 全員共通(user_id が未設定)の会館名は、このページの一覧にそもそも
# 表示していない（登録時と同じく、手配者が扱えるのは特定ユーザー向けの
# 会館名だけ）ため、削除でも念のため user_id が設定されている行のみを
# 対象にする。
#------------------------------------------------
@app.route('/arrangement_place_delete/<int:place_id>', methods=["POST"])
@login_required
@arranger_required
def arrangement_place_delete(place_id):
    record = Place.query.get(place_id)
    if record and record.user_id is not None:
        db.session.delete(record)
        db.session.commit()
    return redirect(url_for('arrangement_manage'))


#------------------------------------------------
# 手配書の画像配信。
# [追加] DBに保存したバイナリはstaticフォルダ経由では配信されないため、
# この専用ルートを経由し、本人・手配者・管理者のいずれかであることを
# 確認した上でのみ配信する。
#------------------------------------------------
@app.route('/arrangement_image/<int:arrangement_id>')
@login_required
def arrangement_image(arrangement_id):
    record = Arrangement.query.get(arrangement_id)
    if not record or not record.image_filename or not record.image_data:
        abort(404)

    allowed = (
        bool(getattr(current_user, "is_admin", False))
        or bool(getattr(current_user, "is_arranger", False))
        or current_user.id == record.target_user_id
    )
    if not allowed:
        abort(403)

    return Response(record.image_data, mimetype=_guess_mimetype(record.image_filename))


#------------------------------------------------
# 「本日の手配書」画面（一般ユーザー用）。
# ログイン中の本人・指定した日付の分だけを、本葬・通夜それぞれ表示する。
# [追加] クエリパラメータ(date)で表示する日付を切り替えられるようにし、
# 前日・翌日リンクから他の日の手配書も確認できるようにした
# （attendance_list()のyear/month切り替えと同じ考え方）。
# 指定が無い場合や、日付として解釈できない値が渡された場合は、
# `get_today()`（呼び出し都度の現在日付）を表示する。
# 手配書は勤怠記録と違い、手配者が翌日以降の分を事前に登録しておく
# ことも想定されるため、attendance_list()の「次月」と異なり、未来日への
# 移動を制限してはいない。
#------------------------------------------------
@app.route('/today_arrangement')
@login_required
def today_arrangement():

    today_str = get_today()

    date_param = request.args.get('date')
    try:
        view_date = datetime.date.fromisoformat(date_param) if date_param else datetime.date.fromisoformat(today_str)
    except ValueError:
        view_date = datetime.date.fromisoformat(today_str)

    view_date_str = view_date.isoformat()
    prev_date_str = (view_date - datetime.timedelta(days=1)).isoformat()
    next_date_str = (view_date + datetime.timedelta(days=1)).isoformat()
    is_today = view_date_str == today_str

    honso_arrangement = Arrangement.query.filter_by(
        target_user_id=current_user.id, shift="honso", date=view_date_str
    ).first()
    tsuya_arrangement = Arrangement.query.filter_by(
        target_user_id=current_user.id, shift="tsuya", date=view_date_str
    ).first()

    return render_template(
        'today_arrangement.html',
        title="本日の手配書",
        view_date=view_date_str,
        is_today=is_today,
        prev_date=prev_date_str,
        next_date=next_date_str,
        honso_arrangement=honso_arrangement,
        tsuya_arrangement=tsuya_arrangement,
    )
