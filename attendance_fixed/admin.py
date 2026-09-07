#------------------------------------------------
# データベース管理画面を利用するためのモジュールのインポート
#------------------------------------------------
from __init__ import app, db
from flask import redirect, request, url_for
from flask_admin import Admin, AdminIndexView
from flask_admin.contrib.sqla import ModelView
from flask_admin.theme import Bootstrap4Theme
from flask_login import current_user
from models import User, Time, Place, Arrangement
# from models import User, Time ,LoginForm


#import models

#------------------------------------------------
#DBのクリエイト宣言
# [修正] 新しいバージョンのFlask-SQLAlchemy(3.x)ではアプリケーション
# コンテキストの外でdb.create_all()を呼ぶと
# "RuntimeError: Working outside of application context" になるため、
# app.app_context()の中で呼び出すよう修正。
#------------------------------------------------
with app.app_context():
    db.create_all()

#admin = Admin(app)

#------------------------------------------------
# [追加] データベース管理画面にユーザー認証を追加。
#
# 以前は /admin にアクセスするだけで誰でもUser/Timeテーブルを
# 閲覧・編集できてしまっていた。従業員の出退勤ログインとは別に、
# models.py に追加した is_admin フラグが立っているアカウントだけが
# 管理画面へアクセスできるようにする。
#
# ログイン自体は既存の /login （従業員ログインと共通の画面）を使う。
# 未ログイン、またはログイン済みでも is_admin が立っていないユーザーが
# アクセスした場合は、/login にリダイレクトする。
#------------------------------------------------
class AdminAuthMixin:
    def is_accessible(self):
        return current_user.is_authenticated and bool(getattr(current_user, "is_admin", False))

    def inaccessible_callback(self, name, **kwargs):
        # ログイン画面にリダイレクトする。next にアクセスしようとしていた
        # URLを入れておくが、このアプリのlogin()は成功後に/judgeへ固定で
        # 遷移するため next は現状使われない（将来の拡張用に残す）。
        return redirect(url_for("login", next=request.url))


class SecureAdminIndexView(AdminAuthMixin, AdminIndexView):
    # [追加] ナビゲーションバーから「Home」タブを非表示にする。
    # is_visible() はメニューへの表示・非表示だけを制御するもので、
    # is_accessible()（アクセス権限そのもの）とは別物。
    # ここをFalseにしても /admin/ 自体は引き続き存在するが、
    # ログイン後の遷移先を /admin/user/ に変更した（index.py参照）ため、
    # 通常の操作でこの空の「Home」画面が表示されることはなくなる。
    def is_visible(self):
        return False


class SecureModelView(AdminAuthMixin, ModelView):
    pass


#------------------------------------------------
# [追加] Time（勤怠記録）テーブルを従業員番号でフィルターし、
# その結果をCSVでダウンロードできるようにする。
#
# Flask-Adminの一覧画面には元々「Export」機能があるが、既定では
# 無効(can_export=False)になっていたため使えなかった。
# can_export=True で有効化し、column_filters / column_searchable_list で
# number（従業員番号）を指定した。
#
# 使い方: /admin/time/ の一覧画面で、上部の検索欄に従業員番号を入力するか、
# 「Filter」から number を選んで絞り込んだ後、右上の「Export」→「Export CSV」
# を押すと、絞り込んだユーザーの勤怠記録だけがCSVでダウンロードされる。
# 絞り込まずにExportすれば、全ユーザー分がまとめてダウンロードされる。
#------------------------------------------------
class TimeModelView(SecureModelView):
    can_export = True
    column_filters = ["number", "date"]
    column_searchable_list = ["number"]
    # column_list は指定しない＝Timeテーブルの全カラム（手当のチェック項目等も
    # 含む）がそのまま一覧・CSVエクスポートの対象になる。
    page_size = 50


#------------------------------------------------
# [追加] 「本日の手配書」機能で使うArrangementテーブルを管理画面から
# 確認できるようにする（登録・削除は通常/arrangement_manageの
# 手配者専用画面から行うが、管理者は状況確認や不整合の修正のために
# ここからも見られるようにしておく）。
#
# target_user・created_by の2つがどちらもUserへの外部キーになっており、
# Flask-Adminにリレーション経由で自動的にフォームを作らせると
# あいまいになりかねないため、form_columns で素の外部キー列(_id)を
# 明示的に指定している。
#------------------------------------------------
class ArrangementModelView(SecureModelView):
    column_list = [
        "id", "date", "shift", "target_user_id", "memo",
        "image_filename", "created_by_id", "created_at", "updated_at",
    ]
    form_columns = ["target_user_id", "shift", "date", "memo", "image_filename"]
    column_filters = ["date", "shift", "target_user_id"]
    column_searchable_list = ["memo"]
    page_size = 50


# [修正] Flask-Adminの新しいバージョンでは template_mode='bootstrap4' 引数が
# 廃止され、theme=Bootstrap4Theme() を渡す形に変わったため対応。
admin = Admin(
    app,
    name='データベース管理画面',
    theme=Bootstrap4Theme(),
    index_view=SecureAdminIndexView(),
)

admin.add_view(SecureModelView(User, db.session))
admin.add_view(TimeModelView(Time, db.session))
# [追加] 会館名(Place)も管理画面から追加・編集できるようにする。
# Placeのuser_idを指定すると、その従業員だけに表示される会館になる
# （未指定＝空欄のままなら、全ユーザー共通の会館として扱われる）。
admin.add_view(SecureModelView(Place, db.session))
# [追加] 「本日の手配書」機能のArrangementテーブル。
admin.add_view(ArrangementModelView(Arrangement, db.session))
