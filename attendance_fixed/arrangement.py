#------------------------------------------------
# [追加] 「本日の手配書」機能。
#
# ・手配者アカウント（models.Userのis_arranger=True）専用の登録画面
#   (/arrangement_manage) で、一般ユーザー・本葬/通夜・日付を指定して
#   画像とメモを登録する。
# ・一般ユーザーは、ログイン後の勤務選択画面(select.html)にある
#   「本日の手配書」ボタンから /today_arrangement を開き、自分宛て・
#   本日分の画像とメモだけを確認できる。
# ・アップロードした画像は uploads/arrangements/ 配下に保存し、
#   本人・手配者・管理者以外には見えないよう、専用のルート
#   (/arrangement_image/<id>) 経由でアクセス制御した上で配信する
#   （Flaskの静的配信(/static/...)は使わない）。
#------------------------------------------------

import os
import uuid
import datetime
from functools import wraps

from __init__ import app, db, login_manager, get_today, ARRANGEMENT_UPLOAD_DIR

from flask import (
    request, render_template, redirect, url_for, send_from_directory, abort,
)
from flask_login import login_required, current_user

from models import User, Arrangement
from sqlalchemy.exc import IntegrityError


ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def _is_allowed_image(filename):
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_IMAGE_EXTENSIONS


def _delete_image_file(filename):
    if not filename:
        return
    path = os.path.join(ARRANGEMENT_UPLOAD_DIR, filename)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


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

    if request.method == 'POST':
        target_user_id = request.form.get('target_user_id')
        shift = request.form.get('shift')
        date_str = request.form.get('date')
        memo = (request.form.get('memo') or '').strip()
        image_file = request.files.get('image')

        target_user = User.query.get(int(target_user_id)) if target_user_id and target_user_id.isdigit() else None

        if not target_user or shift not in ("honso", "tsuya") or not date_str:
            error_message = "対象ユーザー・本葬/通夜・日付を正しく指定してください。"
        elif not memo and not (image_file and image_file.filename):
            error_message = "画像またはメモのいずれかを入力してください。"
        elif image_file and image_file.filename and not _is_allowed_image(image_file.filename):
            error_message = "画像ファイルの形式が対応していません（png/jpg/jpeg/gif/webpのみ）。"
        else:
            image_filename = None
            if image_file and image_file.filename:
                ext = image_file.filename.rsplit(".", 1)[1].lower()
                image_filename = "{}.{}".format(uuid.uuid4().hex, ext)
                image_file.save(os.path.join(ARRANGEMENT_UPLOAD_DIR, image_filename))

            now = datetime.datetime.now()

            # [追加] 同じ (対象ユーザー・本葬/通夜・日付) の手配書が既にあれば、
            # 新しく行を増やすのではなく上書き（更新）する。
            existing = Arrangement.query.filter_by(
                target_user_id=target_user.id, shift=shift, date=date_str
            ).first()

            if existing:
                if image_filename:
                    _delete_image_file(existing.image_filename)
                    existing.image_filename = image_filename
                existing.memo = memo or None
                existing.created_by_id = current_user.id
                existing.updated_at = now
            else:
                db.session.add(Arrangement(
                    target_user_id=target_user.id,
                    shift=shift,
                    date=date_str,
                    image_filename=image_filename,
                    memo=memo or None,
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
                if image_filename:
                    _delete_image_file(image_filename)
            return redirect(url_for('arrangement_manage'))

    # [追加] 対象ユーザーの選択肢は、一般従業員（管理者・手配者を除く）のみ。
    employees = User.query.filter_by(is_admin=False, is_arranger=False).order_by(User.number).all()
    arrangements = (
        Arrangement.query
        .order_by(Arrangement.date.desc(), Arrangement.id.desc())
        .all()
    )

    return render_template(
        'arrangement_manage.html',
        title="手配書登録",
        employees=employees,
        arrangements=arrangements,
        error_message=error_message,
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
        _delete_image_file(record.image_filename)
        db.session.delete(record)
        db.session.commit()
    return redirect(url_for('arrangement_manage'))


#------------------------------------------------
# 手配書の画像配信。
# [追加] uploads/arrangements/ 配下は static フォルダではないため、
# 通常はブラウザから直接アクセスできない。この専用ルートを経由し、
# 本人・手配者・管理者のいずれかであることを確認した上でのみ配信する。
#------------------------------------------------
@app.route('/arrangement_image/<int:arrangement_id>')
@login_required
def arrangement_image(arrangement_id):
    record = Arrangement.query.get(arrangement_id)
    if not record or not record.image_filename:
        abort(404)

    allowed = (
        bool(getattr(current_user, "is_admin", False))
        or bool(getattr(current_user, "is_arranger", False))
        or current_user.id == record.target_user_id
    )
    if not allowed:
        abort(403)

    return send_from_directory(ARRANGEMENT_UPLOAD_DIR, record.image_filename)


#------------------------------------------------
# 「本日の手配書」画面（一般ユーザー用）。
# ログイン中の本人・本日日付の分だけを、本葬・通夜それぞれ表示する。
# `get_today()` で呼び出し都度の現在日付を求めることで、本葬・通夜の
# 勤怠記録(Time)と同じ「本日」の考え方に揃えている。
#------------------------------------------------
@app.route('/today_arrangement')
@login_required
def today_arrangement():

    today_str = get_today()
    today = today_str

    honso_arrangement = Arrangement.query.filter_by(
        target_user_id=current_user.id, shift="honso", date=today_str
    ).first()
    tsuya_arrangement = Arrangement.query.filter_by(
        target_user_id=current_user.id, shift="tsuya", date=today_str
    ).first()

    return render_template(
        'today_arrangement.html',
        title="本日の手配書",
        today=today,
        honso_arrangement=honso_arrangement,
        tsuya_arrangement=tsuya_arrangement,
    )
