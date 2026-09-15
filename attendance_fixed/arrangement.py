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

from models import User, Arrangement, Place
from sqlalchemy.exc import IntegrityError


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

        place_target_user = (
            User.query.get(int(place_target_user_id))
            if place_target_user_id and place_target_user_id.isdigit() else None
        )

        if not place_target_user:
            place_error_message = "会館名を登録する対象ユーザーを選択してください。"
        elif not place_name:
            place_error_message = "会館名を入力してください。"
        else:
            db.session.add(Place(user_id=place_target_user.id, place=place_name))
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

            if existing:
                if image_filename:
                    existing.image_filename = image_filename
                    existing.image_data = image_data
                existing.memo = memo or None
                existing.place = place
                existing.other_place = other_place
                existing.created_by_id = current_user.id
                existing.updated_at = now
            else:
                db.session.add(Arrangement(
                    target_user_id=target_user.id,
                    shift=shift,
                    date=date_str,
                    image_filename=image_filename,
                    image_data=image_data,
                    memo=memo or None,
                    place=place,
                    other_place=other_place,
                    created_by_id=current_user.id,
                    created_at=now,
                    updated_at=now,
                ))

            try:
                db.session.commit()
            except IntegrityError:
                # [追加] Arrangement(target_user_id, shift, date)にはDBの
                # 一意制約がある（models.py参照）。複数の手配者が同時に
                # 同じ対象者・本葬/通夜・日付の手配書を新規登録しようと
                # した場合など、ごく稀にここで衝突することがあるが、
                # エラー画面を出さずに登録済み一覧の画面に戻す
                # （どちらか一方の内容が保存されている状態になる）。
                db.session.rollback()
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

    return render_template(
        'arrangement_manage.html',
        title="手配書登録",
        employees=employees,
        employee_places=employee_places,
        arrangements=arrangements,
        places=places,
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
