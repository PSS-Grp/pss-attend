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
from index import app  # noqa: E402


#------------------------------------------------
# [追加] 動作確認用のデモアカウント・会館名・サンプル勤怠データ・
# サンプル手配書を、アプリ起動時に自動的に作成する。
#
# seed_demo_user.py内の各関数はすべて「既に同じデータがあれば何もしない」
# 設計になっている（seed_demo_user.pyのコメント参照）ため、再デプロイや
# 再起動のたびに実行しても安全（重複作成やデータ破壊は起きない）。
#------------------------------------------------
import seed_demo_user  # noqa: E402

with app.app_context():
    seed_demo_user.main()


if __name__ == "__main__":
    # ローカルで `python wsgi.py` として簡易的に動作確認したい場合用。
    # 本番はgunicorn経由 (`gunicorn wsgi:app`) で起動するため、通常は
    # この分岐は使われない。
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
