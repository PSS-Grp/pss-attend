#------------------------------------------------
# flask パッケージ から Flask モジュールのインポート
#------------------------------------------------

#from flask import Flask, render_template, request, redirect
from flask import Flask
from datetime import timedelta

#------------------------------------------------
# データベースを利用するための flask_sqlalchemy モジュールから SQLAlchemy クラスのインポート
#------------------------------------------------

from flask_sqlalchemy import SQLAlchemy

#------------------------------------------------
# データベース管理画面を利用するためのモジュールのインポート
#------------------------------------------------

from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView

#------------------------------------------------
# ログイン機能を利用するためのモジュールのインポート
#------------------------------------------------

from flask_login import LoginManager, login_required

#------------------------------------------------
# 実行環境に依存しないパス・シークレットキーを扱うためのモジュール
# [Colab対応] os / secrets を追加。カレントディレクトリに依存せず、
# このファイルがある場所を基準にパスを解決する。
#------------------------------------------------

import os
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

#------------------------------------------------
# Flask モジュールを(__name__)でモジュール指定してアプリの生成
#------------------------------------------------

app = Flask(__name__)

#------------------------------------------------
# [修正] 末尾スラッシュの有無で自動的に別URLへリダイレクトされる挙動
# （例: /admin -> /admin/）を無効化。
# Colabのポート転送プロキシ経由だと、このリダイレクト先URLが
# 正しい外部アドレスではなく "localhost" になってしまい、埋め込み
# iframeが手元のPCのlocalhost（＝存在しない場所）を開こうとして
# 画面が真っ白になる不具合があったため。
#------------------------------------------------
app.url_map.strict_slashes = False

#------------------------------------------------
# LoginManagerの起動 #extensionを起動させる際の標準的な記述
#
# [修正] 以前は 'pss_security_key' というパスワードが平文でハードコードされ、
# 公開リポジトリに残っていた。環境変数 ATTENDANCE_SECRET_KEY があればそれを使い、
# なければ実行のたびに安全なランダム値を自動生成する。
# （ランダム生成の場合、サーバーを再起動するとログインセッションは切れる。
#   本番で使う場合は環境変数で固定値を設定すること。）
#------------------------------------------------

_secret_key = os.environ.get("ATTENDANCE_SECRET_KEY") or secrets.token_hex(32)
app.secret_key = _secret_key

login_manager = LoginManager()
login_manager.init_app(app)

#------------------------------------------------
# [修正] login_view が未設定だと、未ログイン状態で @login_required の
# ページに来た際にFlask-Loginが abort(401) を返し、ブラウザには
# 素の「Unauthorized」画面が表示されてしまう。ログインページへ
# リダイレクトされるよう明示的に設定する。
#------------------------------------------------
login_manager.login_view = "login"

#------------------------------------------------
# DBの指定
# [修正/Neon対応] 本番(Render)ではSQLiteをやめ、Neon（マネージドの
# PostgreSQL）を使うようにした。環境変数 DATABASE_URL が設定されていれば
# それを使い、未設定の場合はColab・ローカル実行時と同じくSQLiteに
# フォールバックする（従来通りの挙動なので、Colabでの動作確認には
# 何も影響しない）。
#
# NeonやHerokuなどが発行する接続文字列は "postgres://..." 形式のことが
# あるが、SQLAlchemy 1.4以降は "postgresql://..." でないと受け付けない
# ため、先頭がpostgres://の場合はpostgresql://に読み替える。
#------------------------------------------------

_database_url = os.environ.get("DATABASE_URL")

if _database_url:
    if _database_url.startswith("postgres://"):
        _database_url = "postgresql://" + _database_url[len("postgres://"):]
    app.config["SQLALCHEMY_DATABASE_URI"] = _database_url
    # [追加/Neon対応] Neonはサーバーレスで、しばらく使われないと自動的に
    # 接続がスリープ・切断されることがある。pool_pre_ping=Trueにより、
    # SQLAlchemyがコネクションを使う直前に軽く生存確認を行い、切れていれば
    # 自動的に張り直してくれるため、「久しぶりのアクセスでエラーになる」
    # 事態を防げる。
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
    # DATA_DIRはSQLite利用時（下記else節）にしか使わないが、他のモジュールが
    # 参照している可能性を考慮し、一応BASE_DIR基準の値を入れておく。
    DATA_DIR = os.environ.get("ATTENDANCE_DATA_DIR") or BASE_DIR
else:
    # [修正] 相対パス "sqlite:///db/attendance.db" はカレントディレクトリに
    # 依存し、どこから起動しても壊れないよう、このファイルの場所からの
    # 絶対パスに変更した。
    #
    # [追加/Render対応] 環境変数 ATTENDANCE_DATA_DIR が設定されていれば、
    # DBファイルをその場所（Renderの「Persistent Disk」のマウント先などを
    # 想定）に保存する。未設定の場合は、Colabやローカル実行時と同じく
    # アプリのコードと同じフォルダ（BASE_DIR）に保存する。
    DATA_DIR = os.environ.get("ATTENDANCE_DATA_DIR") or BASE_DIR
    _db_dir = os.path.join(DATA_DIR, "db")
    os.makedirs(_db_dir, exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(_db_dir, "attendance.db")

#------------------------------------------------
# セッションタイムアウト時間
#------------------------------------------------
app.permanent_session_lifetime = timedelta(minutes=30)

#------------------------------------------------
# DBの指定（MySQL）
# [修正] 実際の接続パスワードが平文でコミットされていたため削除。
# MySQLを使う場合は環境変数から読み込むこと（例）。
# ------------------------------------------------
# app.config["SQLALCHEMY_DATABASE_URI"] = 'mysql+pymysql://{user}:{password}@{host}/{db_name}?charset=utf8'.format(
#     user=os.environ["DB_USER"],
#     password=os.environ["DB_PASSWORD"],
#     host=os.environ.get("DB_HOST", "localhost"),
#     db_name=os.environ.get("DB_NAME", "attend_db"),
# )

#------------------------------------------------
# ローカルな現在の日付を取得する関数
#
# [修正] 以前はここで `today = datetime.datetime.today().date()` として、
# モジュール読み込み時点（＝アプリ起動時点）の日付を固定値として
# キャッシュしていた。Google Colabの短時間セッションでは問題にならなくても、
# Renderのように長時間・無停止で動かし続ける本番環境では、日付が変わっても
# この値が起動時点の日付のまま変わらず、出退勤の判定・記録が実際の日付と
# ずれてしまう不具合があったため、値ではなく「呼び出す都度、現在時刻から
# 計算する関数」に変更した。
#
# また、戻り値は datetime.date オブジェクトではなく、Time.date /
# Arrangement.date カラムの実際の保存形式に合わせた "YYYY-MM-DD" 形式の
# 文字列にしている。date オブジェクトのままSQLiteの文字列カラムに
# バインドすると、Python 3.12以降で非推奨（将来のバージョンで削除予定）に
# なっているsqlite3の暗黙の日付アダプタに依存してしまうため、それも避ける。
#------------------------------------------------
import datetime


def get_today():
    return datetime.date.today().isoformat()

#------------------------------------------------
# sessionを使う際にSECRET_KEYを設定
# [修正] 上の app.secret_key と重複していたうえ 'secret_key' という
# 固定文字列がハードコードされていたため、同じ値を再利用するよう統一。
#------------------------------------------------

app.config['SECRET_KEY'] = _secret_key


#------------------------------------------------
# おまじない
#------------------------------------------------

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

#------------------------------------------------
# [追加] 「本日の手配書」機能でアップロードするファイル（画像・PDF）の
# サイズ上限（1ファイルあたりではなくリクエスト全体で10MB）。
# 極端に大きなファイルが送られてサーバーのメモリを圧迫しないよう上限を
# 設けている。
# [修正/Neon対応] 以前はここでファイルの保存先ディレクトリ
# （ARRANGEMENT_UPLOAD_DIR）も定義していたが、ファイル本体をDB内
# （models.Arrangement.image_data）に保存する方式に変更したため、
# ディスク上の保存先ディレクトリは不要になった（詳細はarrangement.py参照）。
#------------------------------------------------

app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

#------------------------------------------------
# [追加/Render対応] Render上で動いていることを示す環境変数 `RENDER`
# （Renderが自動的に設定する）が立っている場合は、セッションクッキーに
# Secure属性を付ける（HTTPS接続でのみクッキーを送信する）。
# Renderの本番URLは常にHTTPSのため安全に有効化できる一方、ローカルでの
# 動作確認(http://127.0.0.1:...)やColabでは影響しないよう、Render上での
# 実行時だけ有効にしている。
#------------------------------------------------
if os.environ.get("RENDER") == "true":
    app.config["SESSION_COOKIE_SECURE"] = True

#------------------------------------------------
# dbの初期化
#------------------------------------------------

db = SQLAlchemy(app)

#------------------------------------------------
# Flask-LoginがユーザーIDからユーザー情報を復元する方法や、ログインする処理などをFlaskと連携するために利用するオブジェクトを作成する
#------------------------------------------------
