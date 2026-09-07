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

from models import User, Arrangement
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
