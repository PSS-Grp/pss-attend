#------------------------------------------------
# Render.com（またはその他のgunicorn/WSGI対応ホスティング）でこのアプリを
# 動かすためのエントリポイント。
#
# 起動コマンドとしては `gunicorn wsgi:app` の形を想定している。
#
# attendance_fixed/ 配下の各ファイルは、Colab用のrun_colab.pyと同様に
# 「カレントディレクトリがattendance_fixed/そのものである」ことを前提にした
# 書き方（`from __init__ import ...` 等）をしているため、ここでも同じように
# 起動時にこのファイルの場所を基準としてsys.pathとカレントディレクトリを
# attendance_fixed/ に合わせてからimportする。
#------------------------------------------------

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, "attendance_fixed")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

import index  # noqa: E402  ルーティングを登録するために必要（本葬/通夜/手配書も含む）
from index import app, db  # noqa: E402


#------------------------------------------------
# [修正] 以前は起動時に、動作確認用のデモアカウント・会館名・
# サンプル勤怠データ・サンプル手配書(seed_demo_user.py)を自動的に
# 作成していたが、実運用を開始したため不要になり、削除した
# （動作確認用のスクリプトとしては、seed_demo_user.py自体は
# ローカル環境での確認用(run_colab.py等)にそのまま残してある）。
#
# db.create_all()（まだ存在しないテーブルだけを作成する処理。既存の
# テーブルへの列追加などは行わない）は、新しいテーブルを追加した際に
# 必要になるため、そのまま残す。再デプロイ・再起動のたびに実行しても
# 安全（既存のテーブル・データには影響しない）。
#------------------------------------------------
with app.app_context():
    db.create_all()


if __name__ == "__main__":
    # ローカルで `python wsgi.py` として簡易的に動作確認したい場合用。
    # 本番はgunicorn経由 (`gunicorn wsgi:app`) で起動するため、通常は
    # この分岐は使われない。
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
