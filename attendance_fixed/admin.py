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

#------------------------------------------------
# [追加] 管理画面(/admin/user/)からユーザーを新規作成・編集する際、
# パスワード欄に入力した平文を自動的にハッシュ化して保存するための部品。
#------------------------------------------------
from sqlalchemy import inspect
from werkzeug.security import generate_password_hash
from wtforms.fields import PasswordField
from wtforms.validators import ValidationError, InputRequired


class _AdminPasswordField(PasswordField):
    # [追加] 編集画面を開いたときに、DBに保存済みのハッシュ値が
    # フォームの初期値として表示（＝画面上に見えてしまう、うっかり
    # そのまま保存すると再ハッシュ化されて壊れる、等）されないよう、
    # 常に空欄から始まるようにする。
    def process_data(self, value):
        self.data = ""


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
# [追加] Userテーブル専用の管理画面。
#
# 以前はUserもただのSecureModelViewだったため、/admin/user/の新規作成・
# 編集フォームに「password」列がそのまま（平文入力→平文保存）表示されて
# いた。実際のログイン処理(index.pyのlogin())はwerkzeugの
# check_password_hash()でハッシュ値と照合する作りのため、管理画面経由で
# 作成・変更したアカウントは、平文のまま保存されてしまいログインできない
# という不具合があった。
#
# ここでは、
#   ・一覧画面(column_list)からはpassword列そのもの（ハッシュ値）を隠す。
#   ・フォームのpassword欄は _AdminPasswordField にして、常に空欄で
#     表示する（既存のハッシュ値を画面に表示しない）。
#   ・保存直前(on_model_change)に、入力された平文をgenerate_password_hash()
#     でハッシュ化してから実際のモデルにセットする。
#   ・編集時にpassword欄を空欄のまま保存した場合は「変更しない」ものとして
#     扱い、既存のパスワード（ハッシュ値）をそのまま維持する。
#   ・新規作成なのにpassword欄が空欄の場合はエラーにする。
#------------------------------------------------
class UserModelView(SecureModelView):
    column_list = ["id", "username", "number", "is_admin", "is_arranger"]
    form_columns = ["username", "number", "password", "is_admin", "is_arranger"]
    form_overrides = {"password": _AdminPasswordField}
    form_widget_args = {
        "password": {
            "placeholder": "新規作成時は必ず入力／編集時は変更する場合のみ入力（空欄なら変更しません）",
        },
    }
    column_searchable_list = ["username", "number"]

    # [追加] passwordカラムはnullable=Falseのため、Flask-Adminのフォーム
    # 自動生成が既存のvalidatorsに関係なく無条件でInputRequired（必須）を
    # 追加してしまう（form_args={"validators": []}のような指定では
    # 打ち消せなかった。動作確認の過程で発覚）。そのままだと、編集画面で
    # パスワード欄を空欄のまま（＝変更しないつもりで）保存しようとしても
    # 「Failed to save record.」となり保存自体ができなくなってしまう。
    # scaffold_form()でフォームクラスを組み立てた直後に、password欄に
    # 付与されたInputRequiredだけを取り除き、常に任意項目にしている。
    # 「新規作成時は必須・編集時は空欄なら変更しない」という制御は
    # 下のon_model_change側で行う。
    def scaffold_form(self):
        form_class = super().scaffold_form()
        password_field = getattr(form_class, "password", None)
        if password_field is not None and hasattr(password_field, "kwargs"):
            password_field.kwargs["validators"] = [
                v for v in password_field.kwargs.get("validators", [])
                if not isinstance(v, InputRequired)
            ]
        return form_class

    def on_model_change(self, form, model, is_created):
        submitted_password = form.password.data

        if submitted_password:
            # 入力された平文パスワードをハッシュ化してから保存する。
            model.password = generate_password_hash(submitted_password)
        elif is_created:
            # 新規作成時にパスワード未入力はエラーにする
            # （空欄のまま保存すると、ログインできないアカウントができてしまうため）。
            # [補足] passwordカラムはnullable=Falseのため、実際には
            # Flask-Adminがフォームに自動付与する「必須」バリデーションの方が
            # 先に働き、この時点まで処理が来る前に「Failed to create record.」
            # という汎用エラーで新規作成が止まる（動作確認済み）。
            # ここでの例外は、その自動バリデーションが何らかの理由で
            # 効かなかった場合の保険。
            raise ValidationError("新規作成時はパスワードを入力してください。")
        else:
            # 編集時に空欄のまま保存された場合は「変更しない」として扱い、
            # DBに保存されている元のパスワード（ハッシュ値）を維持する。
            # （このタイミングでは既にform.populate_obj()によりmodel.passwordに
            #   空文字が入ってしまっているため、SQLAlchemyの変更履歴から
            #   変更前の値を取り出して戻す。）
            history = inspect(model).attrs.password.history
            if history.deleted:
                model.password = history.deleted[0]


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

admin.add_view(UserModelView(User, db.session))
admin.add_view(TimeModelView(Time, db.session))
# [追加] 会館名(Place)も管理画面から追加・編集できるようにする。
# Placeのuser_idを指定すると、その従業員だけに表示される会館になる
# （未指定＝空欄のままなら、全ユーザー共通の会館として扱われる）。
admin.add_view(SecureModelView(Place, db.session))
# [追加] 「本日の手配書」機能のArrangementテーブル。
admin.add_view(ArrangementModelView(Arrangement, db.session))
