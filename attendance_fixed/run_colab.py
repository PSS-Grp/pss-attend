#------------------------------------------------
# Google Colab のノートブック上でこのFlaskアプリを動かすための起動スクリプト。
#
# Colabのノートブックは1つのカーネルで動いており、app.run()をそのまま
# 呼ぶとセルがブロックされて他のセルを実行できなくなる。
# そのため、Flaskサーバーは別スレッドで起動し、Colab内蔵の
# google.colab.output.serve_kernel_port_as_iframe() を使って
# ノートブック上に埋め込み表示する（ngrok等の外部サービスは不要）。
#
# Colab以外の環境（ローカル等）で実行した場合は、
# 通常通り http://127.0.0.1:<port> にアクセスすればよい。
#------------------------------------------------

import os
import sys
import threading
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

import index  # noqa: E402  ルーティングを登録するために必要（本葬/通夜も含む）
from index import app  # noqa: E402

_server_started = False


def _run_app(port: int):
    # use_reloader=False: Colab上で自動リロードは不要かつ二重起動の原因になる
    # debug=False: 本番運用ではないが、Colab上でdebug=Trueにすると
    #              リローダが別プロセスを起動しようとして相性が悪いため無効化
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def start(port: int = 5000):
    """Flaskサーバーをバックグラウンドスレッドで起動し、
    Colab内であればノートブックにiframeで表示する。"""
    global _server_started

    try:
        from google.colab import output  # type: ignore

        in_colab = True
    except ImportError:
        in_colab = False

    if in_colab:
        # [修正] ログイン直後に "Unauthorized" になる不具合の原因。
        #
        # Colabの埋め込み表示(serve_kernel_port_as_iframe)は、アプリを
        # ノートブックとは別オリジン(*.googleusercontent.com)のiframe内で
        # 表示する。Flaskのセッションクッキーは既定で SameSite=Lax のため、
        # ブラウザはこの「別オリジンのiframe埋め込み」からのクッキー送信を
        # ブロックしてしまい、ログイン直後のリクエストでセッションが
        # 認識されず、@login_required のページが401 Unauthorizedになっていた。
        #
        # SameSite=None（+ Secure必須）にすることで、iframe内でも
        # クッキーが送受信されるようにする。Colabのポート転送はHTTPS経由
        # なのでSecure=Trueでも問題ない。
        app.config["SESSION_COOKIE_SAMESITE"] = "None"
        app.config["SESSION_COOKIE_SECURE"] = True

    if _server_started:
        print(f"サーバーは既に起動しています（ポート {port}）。")
    else:
        thread = threading.Thread(target=_run_app, args=(port,), daemon=True)
        thread.start()
        _server_started = True
        time.sleep(1.5)  # サーバーの起動を待つ
        print(f"Flaskサーバーをポート {port} で起動しました。")

    if in_colab:
        from google.colab import output  # type: ignore

        # [修正] path を指定しないとルート "/" を開こうとして404になる
        # （"/" にルートが無かったため）。/login を明示的に指定する。
        output.serve_kernel_port_as_iframe(port, height=720, path="/login")
    else:
        print(f"Colab環境ではないため、ブラウザで http://127.0.0.1:{port}/login を開いてください。")


if __name__ == "__main__":
    start()
