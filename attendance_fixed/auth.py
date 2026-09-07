#------------------------------------------------
# パスワードのハッシュ値を作るための補助スクリプト。
#
# [修正] 以前はここに実際のパスワード ('hujiko0-') が平文でハードコードされ、
# 公開リポジトリにそのまま残っていた。現在は、環境変数 AUTH_PASSWORD で
# 渡すか、未指定なら実行時に安全に（画面に表示せず）入力してもらう方式にした。
#
# 使い方:
#   AUTH_PASSWORD='任意のパスワード' python auth.py
#   もしくは
#   python auth.py   （プロンプトが出るので入力する）
#------------------------------------------------

import os
import getpass

from werkzeug.security import generate_password_hash

if __name__ == "__main__":
    pw = os.environ.get("AUTH_PASSWORD")
    if not pw:
        pw = getpass.getpass("ハッシュ化したいパスワードを入力してください: ")

    pw_hash = generate_password_hash(pw)

    print("pw_hash = " + pw_hash)
