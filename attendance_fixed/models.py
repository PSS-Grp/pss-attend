# Flask-Loginがユーザーを管理する際に利用するクラスを作成する
# Userクラスに入れた情報はAPIの中でcurrent_userとして取得ができるようになるので、後で利用したい情報があればこのクラスに入れておく

# attendance
# __init__

#------------------------------------------------
# 基本的なモジュールの読み込み
#------------------------------------------------

from __init__ import app, db, login_manager

#------------------------------------------------
# ハッシュ化されたパスワードを管理するために、werkzeug(flaskのDependency)を利用する
#------------------------------------------------

#from werkzeug.security import generate_password_hash, check_password_hash

#------------------------------------------------
# UserMixinクラスをimport UserMixinでログインに必要な機能を継承する。
#------------------------------------------------

from flask import render_template, redirect
from flask_login import UserMixin, login_user, logout_user, current_user
from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Length

class User(UserMixin):
   def __init__(self,id):
       self.id = id

#------------------------------------------------
# UserMixinクラスを継承したUserクラスを定義
# モデル
# 2つ継承「db.Model」はSQLAlchemy、「UserMixin」はflask_login
#------------------------------------------------

class User(db.Model, UserMixin):
    __tablename__ = "user"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(30), nullable=False, unique=True)
    number = db.Column(db.String(8), nullable=False, unique=True)
    password = db.Column(db.String(256), nullable=False)
    # [追加] データベース管理画面(/admin)にアクセスできるかどうかを表すフラグ。
    # 一般の従業員アカウントではFalseのままにし、管理者専用アカウントだけ
    # Trueにすることで、出退勤ログインと管理者アクセスを区別する。
    is_admin = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    # [追加] 「手配者」アカウントかどうかを表すフラグ。
    # 手配者アカウントでログインすると、一般従業員の出退勤画面(/judge)や
    # 管理画面(/admin)ではなく、手配書登録画面(/arrangement_manage)に入る。
    # 一般の従業員アカウントは、この手配書登録画面には入れない。
    is_arranger = db.Column(db.Boolean, nullable=False, default=False, server_default="0")


#------------------------------------------------
# パスワードをハッシュ化
#------------------------------------------------
    def set_password(self, password):
        self.password = generate_password_hash(password)
        return self.password

#------------------------------------------------
# 入力されたパスワードが登録されているパスワードハッシュと一致するかを確認
#------------------------------------------------
#    def check_password(self, password):
#        return check_password_hash(self.password, password)
#
#    def __repr__(self):
#        return "User('{self.password}')"
#
#    def check_password(self, password):
#        password_hash = generate_password_hash(password)
#        print('password_hash = ' + 'self.password')


#------------------------------------------------
# ログイン入力項目・ボタンとの紐づけ
#------------------------------------------------

# class LoginForm(FlaskForm):
#     __tablename__ = "user"
#     username = StringField('username', validators=[DataRequired()])
#     password = PasswordField('password', validators=[DataRequired()])
#     number = StringField('number', validators=[DataRequired()])
#     submit = SubmitField('ログイン')


#------------------------------------------------
# 出退勤時間のクラスを定義
#------------------------------------------------

class Time(db.Model):

    __tablename__ = "time"
    # [追加] このアプリ全体が「1人のユーザーにつき1日1件」を前提に
    # 動いている（judge()やhonso_stamp()等がnumber+dateで検索して
    # 「その日のレコード」を1件だけ取り出す設計）ため、その前提をDB側でも
    # 強制する一意制約を追加した。これにより、万が一アプリ側のチェックを
    # すり抜けて同じユーザー・同じ日の行を2重に作ろうとした場合（例:
    # デプロイ時に複数ワーカーが同時にサンプルデータ作成処理を実行した
    # 場合など）は、片方がエラーになって重複データが作られずに済む。
    __table_args__ = (
        db.UniqueConstraint("number", "date", name="uq_time_number_date"),
    )
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(10))
    number = db.Column(db.String(8))
    # [修正/Neon対応] place1/place2（選択した会館名）・other1/other2
    # （「その他」選択時に手入力する会館名）は、SQLiteでは文字数上限が
    # 事実上チェックされないため気づかなかったが、db.String(10)のままだと
    # 実際の会館名（例:「名古屋メモリアルホール」で11文字）が入らず、
    # 文字数を厳格にチェックするPostgreSQL(Neon)では
    # "value too long for type character varying(10)" エラーで
    # 保存できなかった。会館名(Place.place)の上限に合わせて255文字に広げた。
    place1 = db.Column(db.String(255))
    start1 = db.Column(db.String(10))
    end1 = db.Column(db.String(10))
    leader1 = db.Column(db.String(10))
    subleader1 = db.Column(db.String(10))
    teach1 = db.Column(db.String(10))
    wait1 = db.Column(db.String(10))
    designated1 = db.Column(db.String(10))
    distant1 = db.Column(db.String(10))
    highway1 = db.Column(db.String(10))
    express1 = db.Column(db.String(10))
    other1 = db.Column(db.String(255))
    special1 = db.Column(db.String(10))
    place2 = db.Column(db.String(255))
    start2 = db.Column(db.String(10))
    end2 = db.Column(db.String(10))
    leader2 = db.Column(db.String(10))
    subleader2 = db.Column(db.String(10))
    teach2 = db.Column(db.String(10))
    wait2 = db.Column(db.String(10))
    designated2 = db.Column(db.String(10))
    distant2 = db.Column(db.String(10))
    highway2 = db.Column(db.String(10))
    express2 = db.Column(db.String(10))
    other2 = db.Column(db.String(255))
    special2 = db.Column(db.String(10))


class Place(db.Model):
    # [修正/追加]
    # ・元々このモデルは定義されているだけで、どこからも使われていなかった。
    #   これを使って「会館名」を一般ユーザーごとに変えられるようにした。
    # ・user_id を追加し、どのユーザーに表示する会館かを紐づけられるようにした。
    #   （user_idがNULLの行は、全ユーザー共通の会館として扱う）
    # ・company/area/place の文字数上限が10文字と短く、実際の会館名
    #   （例:「愛知葬祭 春日井会場」で10文字ちょうど）だと収まらないケースが
    #   あったため、余裕を持たせて100文字に広げた。

    __tablename__ = "Place"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    company = db.Column(db.String(100))
    area = db.Column(db.String(100))
    place = db.Column(db.String(100), nullable=False)
    other = db.Column(db.String(100))

    user = db.relationship("User", backref=db.backref("places", lazy="dynamic"))


class Arrangement(db.Model):
    # [追加] 「本日の手配書」機能用のモデル。
    # 手配者アカウントが、一般ユーザー(target_user)・本葬/通夜(shift)・日付(date)
    # を指定して、画像とメモを登録する。一般ユーザーは自分宛て・当日の分だけを
    # 「本日の手配書」画面(/today_arrangement)で確認できる。
    #
    # 同じ (target_user, shift, date) の組み合わせに対しては1件だけを保持し、
    # 再度登録すると上書き（更新）する方針にしている（同じ日の同じ勤務に
    # 手配書が複数できて紛らわしくなるのを防ぐため）。

    __tablename__ = "arrangement"
    # [追加] 上のコメントの通り「同じ(target_user, shift, date)は1件だけ」
    # という前提を、アプリ側のチェックだけでなくDB側の一意制約としても
    # 強制する（同時実行時の二重作成を防ぐため）。
    __table_args__ = (
        db.UniqueConstraint(
            "target_user_id", "shift", "date", name="uq_arrangement_target_shift_date"
        ),
    )
    id = db.Column(db.Integer, primary_key=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    # "honso"（本葬） または "tsuya"（通夜）
    shift = db.Column(db.String(10), nullable=False)
    # "YYYY-MM-DD" 形式の文字列（HTMLのdate inputからそのまま受け取る）
    date = db.Column(db.String(10), nullable=False)
    # アップロードされたファイルの名前（拡張子から画像かPDFかを判定するために
    # 使う。未アップロードならNULL）。
    image_filename = db.Column(db.String(255), nullable=True)
    # [修正/Neon対応] 以前はファイル本体をサーバーのディスク
    # （uploads/arrangements/ 配下）に保存していたが、DBをNeon(PostgreSQL)に
    # 移行するのに合わせて、ファイル本体もこのカラムにバイナリとして
    # DB内に保存する方式に変更した。これにより、Render側にファイル保存用の
    # 永続ディスクを別途用意する必要がなくなる（SQLiteではBLOB、
    # PostgreSQLではbytea型として保存される）。
    image_data = db.Column(db.LargeBinary, nullable=True)
    memo = db.Column(db.Text, nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    created_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=True)

    target_user = db.relationship(
        "User", foreign_keys=[target_user_id],
        backref=db.backref("arrangements", lazy="dynamic"),
    )
    created_by = db.relationship("User", foreign_keys=[created_by_id])
