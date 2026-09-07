#------------------------------------------------
# [修正] 以前はこのファイルに
#     flask db init
#     flask db migrate
#     flask db upgrade
# という「シェルで打つコマンド」がPythonの文としてそのまま書かれており、
# 構文エラー（SyntaxError）で import どころか実行すらできない状態だった。
# また、flask_migrate（Flask-Migrate）はこのアプリでは requirements に
# 含まれておらず、実際には models.py のテーブルは admin.py 内の
# db.create_all() で作成されている。
#
# そのため、このファイルは「以前コマンドラインで打っていたメモ」を
# コメントとして残すだけの、実行しても安全なドキュメントに直した。
# 通常はこのファイルを実行する必要はない。
#------------------------------------------------

# Flask-Migrate を使ってDBマイグレーションを行いたい場合は、
# 別途 `pip install Flask-Migrate` した上で、ターミナルから
# 以下のコマンドを実行してください（このファイルの実行では動きません）。
#
#   flask db init
#   flask db migrate
#   flask db upgrade

if __name__ == "__main__":
    print(
        "このファイルはメモ用です。DBの初期化は "
        "`from __init__ import db; db.create_all()` で行われます。"
    )
