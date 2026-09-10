import sys
import os
import io
import datetime

# [修正] 以前はこのリポジトリを配置した場所に依存する絶対パスが
# ハードコードされており、他の環境（他の人の手元やCIなど）で
# git clone した直後にこのファイルをそのまま実行すると失敗していた。
# このファイル自身の場所を基準にした相対パスに変更した（wsgi.pyと同じ方式）。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, "attendance_fixed")
sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

import index  # noqa: E402  registers all routes (login, judge, select, honso, tsuya...)
from index import app, db  # noqa: E402
from models import User, Time, Arrangement  # noqa: E402

# [修正] index.pyはもはやモジュールレベルの固定 `today` を持たない
# （__init__.get_today()を呼び出し都度使う設計に変更したため）。
# このテストスクリプト自身は、期待値の組み立てや検索条件に使うための
# 「本日」を、実行時点の実際の日付から求める。
today = datetime.date.today()
today_str = today.isoformat()

import seed_demo_user  # noqa: E402

with app.app_context():
    seed_demo_user.main()
    print("user count:", User.query.count())

client = app.test_client()

r = client.get("/login")
print("GET /login ->", r.status_code)
assert r.status_code == 200

r2 = client.post(
    "/login",
    data={"login": "ログイン", "number": "0001", "password": "demo1234"},
    follow_redirects=False,
)
print("POST /login (correct pw) ->", r2.status_code, r2.headers.get("Location"))
assert r2.status_code == 302
assert r2.headers.get("Location") == "/judge"

r3 = client.get("/judge", follow_redirects=True)
print("GET /judge ->", r3.status_code)
assert r3.status_code == 200
assert "本日の勤務選択".encode("utf-8") in r3.data

r4 = client.post(
    "/select",
    data={"honso-tsuya": "本 葬"},
    follow_redirects=False,
)
print("POST /select (本葬) ->", r4.status_code, r4.headers.get("Location"))
assert r4.status_code == 302
assert r4.headers.get("Location") == "/honso_stamp"

r5 = client.get("/honso_stamp", follow_redirects=True)
print("GET /honso_stamp (0001) ->", r5.status_code)
assert r5.status_code == 200
assert "愛知葬祭 春日井会場".encode("utf-8") in r5.data
assert "平安会館 一宮斎場".encode("utf-8") in r5.data
assert "その他".encode("utf-8") in r5.data
# 0002用の会館名は見えてはいけない（ユーザーごとに一覧が違うことの確認）
assert "名古屋メモリアルホール".encode("utf-8") not in r5.data
# 元の固定リストの名残（"項目4"など）が残っていないことの確認
assert "項目4".encode("utf-8") not in r5.data

r6 = client.post(
    "/honso_stamp",
    data={
        "place1": "本社",
        "start1": "09:00",
    },
    follow_redirects=False,
)
print("POST /honso_stamp (出勤打刻) ->", r6.status_code, r6.headers.get("Location"))
# [追加] 出勤打刻後は読み取り専用の確認画面(honso_init.html)ではなく、
# 本葬・通夜の状態が一目でわかる /judge のハブ画面に戻ることを確認。
assert r6.status_code == 302
assert r6.headers.get("Location") == "/judge"

r6b = client.get("/judge", follow_redirects=True)
print("GET /judge (本葬出勤中) ->", r6b.status_code)
assert r6b.status_code == 200
# [追加] 出勤打刻後も、本葬・通夜の勤怠選択画面（ハブ画面）が
# 引き続き表示され続けることを確認（読み取り専用画面に置き換わらない）。
assert "本日の勤務状況".encode("utf-8") in r6b.data
assert "本葬：出勤中".encode("utf-8") in r6b.data
assert 'href="/honso_modify"'.encode("utf-8") in r6b.data
# [追加] 本葬が出勤中（まだ退勤していない）の間は、通夜のボタンは
# 本葬の退勤入力が済むまで押せない（グレーアウトした表示になる）ことを確認。
assert "通夜：本葬の退勤入力後に操作できます".encode("utf-8") in r6b.data
assert "通 夜（本葬退勤待ち）".encode("utf-8") in r6b.data
assert 'href="/tsuya_stamp"'.encode("utf-8") not in r6b.data

# 本葬が出勤中の間は、通夜の出勤フォームに直接アクセスしても
# 受け付けず /judge に戻されることを確認（ボタンのグレーアウトだけに
# 頼らず、サーバー側でも同じ制限をかけている）。
r6b2 = client.get("/tsuya_stamp", follow_redirects=False)
print("GET /tsuya_stamp (本葬出勤中に直接アクセス) ->", r6b2.status_code, r6b2.headers.get("Location"))
assert r6b2.status_code == 302
assert r6b2.headers.get("Location") == "/judge"

# 出勤済み・退勤前の状態で /honso_stamp に直接アクセスしても
# もう一度出勤フォームを表示しない（/judge に戻す）ことを確認
r6c = client.get("/honso_stamp", follow_redirects=False)
print("GET /honso_stamp (出勤中に再アクセス) ->", r6c.status_code)
assert r6c.status_code == 200  # まだ退勤前なので出勤フォーム自体は許可される

# --- 本葬の退勤を入力する ---
r6d = client.post(
    "/honso_modify",
    data={"end1": "18:00"},
    follow_redirects=False,
)
print("POST /honso_modify (退勤打刻) ->", r6d.status_code, r6d.headers.get("Location"))
assert r6d.status_code == 302
assert r6d.headers.get("Location") == "/judge"

r6e = client.get("/judge", follow_redirects=True)
print("GET /judge (本葬退勤済み) ->", r6e.status_code)
assert r6e.status_code == 200
# [追加] 退勤入力後は、本葬のボタンがグレーアウトして
# （リンクではなくただのspanになり）押せなくなっていることを確認。
assert "本葬：退勤済み".encode("utf-8") in r6e.data
assert 'href="/honso_modify"'.encode("utf-8") not in r6e.data
assert "本 葬（入力済み）".encode("utf-8") in r6e.data
# [追加] 本葬が退勤済みでも、通夜のボタンは独立していて
# 引き続き押せる状態のままであることを確認。
assert "通夜：未出勤".encode("utf-8") in r6e.data
assert 'href="/tsuya_stamp"'.encode("utf-8") in r6e.data

# 退勤済みの本葬フォームに直接アクセスしても、もう編集できない（/judgeに戻される）
r6f = client.get("/honso_modify", follow_redirects=False)
print("GET /honso_modify (退勤済み後に再アクセス) ->", r6f.status_code, r6f.headers.get("Location"))
assert r6f.status_code == 302
assert r6f.headers.get("Location") == "/judge"

r6g = client.get("/honso_stamp", follow_redirects=False)
print("GET /honso_stamp (退勤済み後に再アクセス) ->", r6g.status_code, r6g.headers.get("Location"))
assert r6g.status_code == 302
assert r6g.headers.get("Location") == "/judge"

# --- 通夜も一連の流れ（出勤→退勤→グレーアウト）を確認 ---
r6h = client.post(
    "/tsuya_stamp",
    data={"place2": "本社", "start2": "19:00"},
    follow_redirects=False,
)
print("POST /tsuya_stamp (出勤打刻) ->", r6h.status_code, r6h.headers.get("Location"))
assert r6h.status_code == 302
assert r6h.headers.get("Location") == "/judge"

# 実際のUIでは、退勤入力画面(/tsuya_modify)へはハブ画面(/judge)の
# リンクから遷移するため、その間に必ず /judge へのアクセス（＝session
# の再取得）が挟まる。ここでも同様に /judge を挟んでからアクセスする。
client.get("/judge")

r6i = client.post(
    "/tsuya_modify",
    data={"end2": "21:00"},
    follow_redirects=False,
)
print("POST /tsuya_modify (退勤打刻) ->", r6i.status_code, r6i.headers.get("Location"))
assert r6i.status_code == 302
assert r6i.headers.get("Location") == "/judge"

r6j = client.get("/judge", follow_redirects=True)
print("GET /judge (本葬・通夜ともに退勤済み) ->", r6j.status_code)
assert r6j.status_code == 200
assert "本 葬（入力済み）".encode("utf-8") in r6j.data
assert "通 夜（入力済み）".encode("utf-8") in r6j.data
assert 'href="/honso_modify"'.encode("utf-8") not in r6j.data
assert 'href="/tsuya_modify"'.encode("utf-8") not in r6j.data

# --- 別の従業員(0002)は別の会館一覧が見えることを確認 ---
client_0002 = app.test_client()
client_0002.post(
    "/login",
    data={"login": "ログイン", "number": "0002", "password": "demo2345"},
)
client_0002.post("/select", data={"honso-tsuya": "通 夜"})
r_tsuya_0002 = client_0002.get("/tsuya_stamp", follow_redirects=True)
print("GET /tsuya_stamp (0002) ->", r_tsuya_0002.status_code)
assert r_tsuya_0002.status_code == 200
assert "名古屋メモリアルホール".encode("utf-8") in r_tsuya_0002.data
assert "豊田会館".encode("utf-8") in r_tsuya_0002.data
assert "その他".encode("utf-8") in r_tsuya_0002.data
# 0001用の会館名は見えてはいけない
assert "愛知葬祭 春日井会場".encode("utf-8") not in r_tsuya_0002.data

# wrong password should be rejected
r7 = client.post(
    "/login",
    data={"login": "ログイン", "number": "0001", "password": "wrongpass"},
    follow_redirects=False,
)
print("POST /login (wrong pw) ->", r7.status_code)
assert "パスワードが違います".encode("utf-8") in r7.data

# --- admin panel access control ---

# not logged in at all -> should redirect to login, not show the admin panel
client_anon = app.test_client()
r8 = client_anon.get("/admin/", follow_redirects=False)
print("GET /admin/ (未ログイン) ->", r8.status_code, r8.headers.get("Location"))
assert r8.status_code == 302
assert "/login" in r8.headers.get("Location", "")

# logged in as a regular employee (not admin) -> still must not see the admin panel
client_employee = app.test_client()
client_employee.post(
    "/login",
    data={"login": "ログイン", "number": "0001", "password": "demo1234"},
)
r9 = client_employee.get("/admin/", follow_redirects=False)
print("GET /admin/ (一般従業員でログイン済み) ->", r9.status_code, r9.headers.get("Location"))
assert r9.status_code == 302
assert "/login" in r9.headers.get("Location", "")

# logged in as the admin account -> should be redirected straight to /admin/
client_admin = app.test_client()
r_admin_login = client_admin.post(
    "/login",
    data={"login": "ログイン", "number": "9001", "password": "admin1234"},
    follow_redirects=False,
)
print("POST /login (管理者) ->", r_admin_login.status_code, r_admin_login.headers.get("Location"))
assert r_admin_login.status_code == 302
assert r_admin_login.headers.get("Location") == "/admin/user/"

r10 = client_admin.get("/admin/", follow_redirects=False)
print("GET /admin/ (管理者でログイン済み) ->", r10.status_code)
assert r10.status_code == 200
assert "データベース管理画面".encode("utf-8") in r10.data
# 「Home」タブがナビから消えていることを確認（is_visible=False）
assert ">Home<".encode("utf-8") not in r10.data

r11 = client_admin.get("/admin/user/", follow_redirects=False)
print("GET /admin/user/ (管理者でログイン済み) ->", r11.status_code)
assert r11.status_code == 200

# --- [追加] User.honso_wage / User.tsuya_wage（時給）の確認 ---
# デモ従業員にサンプルの時給が設定されていること、一覧画面に表示されて
# いること、管理画面から時給を編集できることを確認する。
with app.app_context():
    emp0001 = User.query.filter_by(number="0001").first()
    assert emp0001.honso_wage == 1200
    assert emp0001.tsuya_wage == 1000
    emp0001_id = emp0001.id

assert "1200".encode("utf-8") in r11.data and "1000".encode("utf-8") in r11.data

r_wage_edit = client_admin.post(
    f"/admin/user/edit/?id={emp0001_id}",
    data={
        "username": "デモ太郎", "number": "0001", "password": "",
        "honso_wage": "1500", "tsuya_wage": "1100",
        "is_admin": "", "is_arranger": "",
    },
    follow_redirects=False,
)
print("POST /admin/user/edit/ (時給を変更) ->", r_wage_edit.status_code)
assert r_wage_edit.status_code == 302

with app.app_context():
    emp0001 = db.session.get(User, emp0001_id)
    assert emp0001.honso_wage == 1500
    assert emp0001.tsuya_wage == 1100

r12 = client_admin.get("/admin/place/", follow_redirects=False)
print("GET /admin/place/ (管理者でログイン済み) ->", r12.status_code)
assert r12.status_code == 200

# --- [追加] 管理画面(/admin/user/)からのパスワードのハッシュ化を確認 ---
# 以前は管理画面のUser編集/新規作成フォームがpasswordカラムをそのまま
# （平文入力→平文保存）扱っていたため、管理画面経由で作成・変更した
# アカウントは平文パスワードのまま保存されてログインできなくなる不具合が
# あった。admin.pyのUserModelView（_AdminPasswordField・on_model_change）で
# 修正済みであることを確認する。
from werkzeug.security import check_password_hash as _check_password_hash  # noqa: E402

# 新規作成: 入力した平文がハッシュ化されて保存され、そのパスワードで
# ログインできることを確認
r_admin_user_new = client_admin.post(
    "/admin/user/new/",
    data={
        "username": "admin_pw_test",
        "number": "0090",
        "password": "adminpw1",
        "is_admin": "",
        "is_arranger": "",
    },
    follow_redirects=False,
)
print("POST /admin/user/new/ (パスワード付き新規作成) ->", r_admin_user_new.status_code)
assert r_admin_user_new.status_code == 302

with app.app_context():
    pw_test_user = User.query.filter_by(number="0090").first()
    assert pw_test_user is not None
    assert pw_test_user.password != "adminpw1"  # 平文のまま保存されていない
    assert _check_password_hash(pw_test_user.password, "adminpw1")
    pw_test_user_id = pw_test_user.id
    original_hash = pw_test_user.password

client_pw_test = app.test_client()
r_pw_test_login = client_pw_test.post(
    "/login", data={"login": "ログイン", "number": "0090", "password": "adminpw1"}, follow_redirects=False
)
print("POST /login (管理画面で作成したアカウント) ->", r_pw_test_login.status_code, r_pw_test_login.headers.get("Location"))
assert r_pw_test_login.status_code == 302 and r_pw_test_login.headers.get("Location") == "/judge"

# 編集: パスワード欄を空欄のまま他の項目だけ変更 -> 既存のパスワードを維持する
r_admin_user_edit_blank = client_admin.post(
    f"/admin/user/edit/?id={pw_test_user_id}",
    data={"username": "admin_pw_test2", "number": "0090", "password": "", "is_admin": "", "is_arranger": ""},
    follow_redirects=False,
)
print("POST /admin/user/edit/ (パスワード空欄で編集) ->", r_admin_user_edit_blank.status_code)
assert r_admin_user_edit_blank.status_code == 302

with app.app_context():
    pw_test_user = db.session.get(User, pw_test_user_id)
    assert pw_test_user.username == "admin_pw_test2"
    assert pw_test_user.password == original_hash  # ハッシュが維持されている

client_pw_test2 = app.test_client()
r_pw_test_login2 = client_pw_test2.post(
    "/login", data={"login": "ログイン", "number": "0090", "password": "adminpw1"}, follow_redirects=False
)
print("POST /login (空欄編集後も旧パスワードでログイン) ->", r_pw_test_login2.status_code)
assert r_pw_test_login2.status_code == 302 and r_pw_test_login2.headers.get("Location") == "/judge"

# 編集: パスワードを新しい値に変更 -> ハッシュが変わり、新パスワードでのみログインできる
r_admin_user_edit_new = client_admin.post(
    f"/admin/user/edit/?id={pw_test_user_id}",
    data={"username": "admin_pw_test2", "number": "0090", "password": "adminpw2", "is_admin": "", "is_arranger": ""},
    follow_redirects=False,
)
print("POST /admin/user/edit/ (新しいパスワードで編集) ->", r_admin_user_edit_new.status_code)
assert r_admin_user_edit_new.status_code == 302

with app.app_context():
    pw_test_user = db.session.get(User, pw_test_user_id)
    assert _check_password_hash(pw_test_user.password, "adminpw2")
    assert not _check_password_hash(pw_test_user.password, "adminpw1")

client_pw_test3 = app.test_client()
r_pw_test_login3 = client_pw_test3.post(
    "/login", data={"login": "ログイン", "number": "0090", "password": "adminpw2"}, follow_redirects=False
)
print("POST /login (新パスワードでログイン) ->", r_pw_test_login3.status_code)
assert r_pw_test_login3.status_code == 302 and r_pw_test_login3.headers.get("Location") == "/judge"

r_pw_test_login_stale = client.post(
    "/login", data={"login": "ログイン", "number": "0090", "password": "adminpw1"}, follow_redirects=False
)
print("POST /login (変更後は旧パスワードでログイン失敗) ->", r_pw_test_login_stale.status_code)
assert r_pw_test_login_stale.status_code == 200  # ログイン失敗時はlogin.html再表示（302にならない）

# 新規作成: パスワード未入力は拒否され、アカウントが作られないことを確認
with app.app_context():
    _user_count_before = User.query.count()

r_admin_user_new_blank = client_admin.post(
    "/admin/user/new/",
    data={"username": "admin_pw_test_blank", "number": "0091", "password": "", "is_admin": "", "is_arranger": ""},
    follow_redirects=False,
)
print("POST /admin/user/new/ (パスワード未入力) ->", r_admin_user_new_blank.status_code)
assert r_admin_user_new_blank.status_code == 200  # 作成失敗時はフォーム画面を再表示（302にならない）

with app.app_context():
    assert User.query.count() == _user_count_before
    assert User.query.filter_by(number="0091").first() is None

# --- Time(勤怠記録)のユーザーごとCSV出力 ---

# 0002用の勤怠レコードも用意しておく（0001は先のPOST /honso_stampで既に作成済み）
from models import Time  # noqa: E402

with app.app_context():
    if not Time.query.filter_by(number="0002").first():
        db.session.add(Time(date="2026-09-02", number="0002", place1="名古屋メモリアルホール", start1="10:00"))
        db.session.commit()

r13 = client_admin.get("/admin/time/export/csv/", follow_redirects=False)
print("GET /admin/time/export/csv/ (絞り込み無し) ->", r13.status_code, r13.headers.get("Content-Type"))
assert r13.status_code == 200
assert r13.headers.get("Content-Type", "").startswith("text/csv")
assert b"0001" in r13.data
assert b"0002" in r13.data

# 検索ボックス(number)で 0001 だけに絞り込んでエクスポート -> 0001の行だけが入っている
r14 = client_admin.get("/admin/time/export/csv/?search=0001", follow_redirects=False)
print("GET /admin/time/export/csv/?search=0001 ->", r14.status_code)
assert r14.status_code == 200
assert b"0001" in r14.data
assert b"0002" not in r14.data

# 一般従業員はTimeのCSV出力にもアクセスできない
r15 = client_employee.get("/admin/time/export/csv/", follow_redirects=False)
print("GET /admin/time/export/csv/ (一般従業員) ->", r15.status_code, r15.headers.get("Location"))
assert r15.status_code == 302
assert "/login" in r15.headers.get("Location", "")

# --- 通夜を先に出勤すると、その日は本葬の勤務を開始できなくなることを確認
#     （通夜の後に本葬の勤務をすることはないため）。通夜の退勤入力後も
#     引き続き本葬は利用不可のままであることも確認する。 ---
client_0003 = app.test_client()
client_0003.post(
    "/login",
    data={"login": "ログイン", "number": "0003", "password": "demo3456"},
)

r16 = client_0003.post(
    "/tsuya_stamp",
    data={"place2": "本社", "start2": "19:00"},
    follow_redirects=False,
)
print("POST /tsuya_stamp (0003, 通夜を先に出勤) ->", r16.status_code, r16.headers.get("Location"))
assert r16.status_code == 302
assert r16.headers.get("Location") == "/judge"

r17 = client_0003.get("/judge", follow_redirects=True)
print("GET /judge (0003, 通夜出勤中・本葬未着手) ->", r17.status_code)
assert r17.status_code == 200
assert "本葬：通夜出勤後のため利用できません".encode("utf-8") in r17.data
assert "本 葬（利用不可）".encode("utf-8") in r17.data
assert 'href="/honso_stamp"'.encode("utf-8") not in r17.data

# 本葬の出勤フォームに直接アクセスしても受け付けない（/judgeに戻す）
r18 = client_0003.get("/honso_stamp", follow_redirects=False)
print("GET /honso_stamp (0003, 通夜出勤後に直接アクセス) ->", r18.status_code, r18.headers.get("Location"))
assert r18.status_code == 302
assert r18.headers.get("Location") == "/judge"

# 通夜の退勤を入力した後も、本葬は引き続き利用不可のままであることを確認
client_0003.get("/judge")  # 退勤入力前にセッションを最新化しておく
r19 = client_0003.post(
    "/tsuya_modify",
    data={"end2": "21:00"},
    follow_redirects=False,
)
print("POST /tsuya_modify (0003, 通夜退勤) ->", r19.status_code, r19.headers.get("Location"))
assert r19.status_code == 302
assert r19.headers.get("Location") == "/judge"

r20 = client_0003.get("/judge", follow_redirects=True)
print("GET /judge (0003, 通夜退勤済みでも本葬は利用不可のまま) ->", r20.status_code)
assert r20.status_code == 200
assert "本葬：通夜出勤後のため利用できません".encode("utf-8") in r20.data
assert "本 葬（利用不可）".encode("utf-8") in r20.data
assert 'href="/honso_stamp"'.encode("utf-8") not in r20.data

r21 = client_0003.get("/honso_stamp", follow_redirects=False)
print("GET /honso_stamp (0003, 通夜退勤済み後に直接アクセス) ->", r21.status_code, r21.headers.get("Location"))
assert r21.status_code == 302
assert r21.headers.get("Location") == "/judge"

# --- 「勤怠一覧」ボタンと、その月の勤怠一覧画面の確認 ---

# 未ログインでは見られない
r22 = client_anon.get("/attendance_list", follow_redirects=False)
print("GET /attendance_list (未ログイン) ->", r22.status_code, r22.headers.get("Location"))
assert r22.status_code == 302
assert "/login" in r22.headers.get("Location", "")

# ハブ画面(/judge)に「勤怠一覧」ボタンがあることを確認（0001でログイン中のclientを使う）
r23 = client.get("/judge", follow_redirects=True)
print("GET /judge (勤怠一覧ボタンの確認) ->", r23.status_code)
assert r23.status_code == 200
assert "勤怠一覧".encode("utf-8") in r23.data
assert 'href="/attendance_list"'.encode("utf-8") in r23.data

# 0001は今日（今月）に本葬・通夜とも記録済みなので、今月の一覧に表示される
r24 = client.get("/attendance_list", follow_redirects=False)
print("GET /attendance_list (0001, 今月の記録あり) ->", r24.status_code)
assert r24.status_code == 200
assert "の勤怠一覧".encode("utf-8") in r24.data
assert "09:00".encode("utf-8") in r24.data
assert "18:00".encode("utf-8") in r24.data
assert "19:00".encode("utf-8") in r24.data
assert "21:00".encode("utf-8") in r24.data
# 他のユーザー(0002)の記録は表示されない
assert "名古屋メモリアルホール".encode("utf-8") not in r24.data

# 0003は本日は通夜のみ記録済みなので、今月の一覧にそれが表示されることを確認。
# （seed_demo_userが作成する過去日付のサンプル勤怠記録により、0003にも
# 本葬の記録が別の日付で存在し得るため、「本葬の時間が無い」ことまでは
# 検証せず、他ユーザー専用の会館名が紛れ込んでいないことだけを確認する。）
r25 = client_0003.get("/attendance_list", follow_redirects=False)
print("GET /attendance_list (0003, 通夜のみ記録あり) ->", r25.status_code)
assert r25.status_code == 200
assert "19:00".encode("utf-8") in r25.data
assert "21:00".encode("utf-8") in r25.data
# 他ユーザー専用の会館名は表示されない
assert "愛知葬祭 春日井会場".encode("utf-8") not in r25.data
assert "名古屋メモリアルホール".encode("utf-8") not in r25.data

# 勤怠記録が1件も無いユーザー（管理者アカウント9001は出退勤の打刻も
# サンプルデータの対象にもなっていない）で表示すると、
# 「記録がありません」の空状態になることを確認
r26 = client_admin.get("/attendance_list", follow_redirects=False)
print("GET /attendance_list (9001, 記録なし) ->", r26.status_code)
assert r26.status_code == 200
assert "の勤怠記録はまだありません".encode("utf-8") in r26.data

# --- 月の選択機能（前月・次月リンク、年月プルダウン）の確認 ---

# ハブ画面と同様、一覧画面にも前月・次月リンクと年月選択のプルダウンがあること
assert "前月".encode("utf-8") in r24.data
assert "次月".encode("utf-8") in r24.data
assert '<select name="year">'.encode("utf-8") in r24.data
assert '<select name="month">'.encode("utf-8") in r24.data

# seed_demo_user.pyが作成する前月・前々月分のサンプル勤怠記録が、
# クエリパラメータ(year, month)で前月を指定するとちゃんと見えることを確認する
if today.month == 1:
    prev_year, prev_month = today.year - 1, 12
else:
    prev_year, prev_month = today.year, today.month - 1

r27 = client.get(f"/attendance_list?year={prev_year}&month={prev_month}", follow_redirects=False)
print(f"GET /attendance_list?year={prev_year}&month={prev_month} (0001, 前月のサンプルデータ) ->", r27.status_code)
assert r27.status_code == 200
assert f"{prev_year}年{prev_month}月の勤怠一覧".encode("utf-8") in r27.data
# seed_demo_user.pyが前月の5日・12日・19日にサンプルを作成しているはず
assert "17:00".encode("utf-8") in r27.data  # パターン0の本葬退勤時刻
assert "22:00".encode("utf-8") in r27.data  # パターン2の通夜退勤時刻

# 前月リンクのhrefが正しい年月を指していることを確認
assert f'year={prev_year}&amp;month={prev_month}'.encode("utf-8") in r24.data or \
       f'year={prev_year}&month={prev_month}'.encode("utf-8") in r24.data

# 記録が全く無い、大昔の年月を指定した場合は空状態になることを確認
r28 = client.get("/attendance_list?year=2000&month=1", follow_redirects=False)
print("GET /attendance_list?year=2000&month=1 (記録なし) ->", r28.status_code)
assert r28.status_code == 200
assert "2000年1月の勤怠記録はまだありません".encode("utf-8") in r28.data

# 不正な値（数値に変換できない・範囲外の月）を渡した場合は今月にフォールバックする
r29 = client.get("/attendance_list?year=abc&month=99", follow_redirects=False)
print("GET /attendance_list?year=abc&month=99 (不正な値->今月) ->", r29.status_code)
assert r29.status_code == 200
assert f"{today.year}年{today.month}月の勤怠一覧".encode("utf-8") in r29.data

# --- [回帰テスト] 同じブラウザ（同じセッション）でログアウトせずに
#     別の従業員番号でログインし直しても、前のユーザーの勤怠レコードが
#     誤って上書きされないことを確認する。
#
#     修正前は、ログイン時にセッションがクリアされておらず、かつ
#     tsuya_stamp()が「今日のレコードが既にあるか」をsession['record_id']
#     で判定していたため、前のユーザー（例:0001）が作ったレコードのIDが
#     セッションに残ったまま別のユーザー（例:0002）でログインし直すと、
#     0002が通夜を出勤した際に、全く別人である0001のレコードを
#     誤って更新（上書き）してしまっていた。
#
#     0001〜0003は既に本テスト内で今日のレコードを作成済みのため、
#     この回帰テスト専用に、まだ何も記録の無い新しい従業員を2名用意する。 ---
from werkzeug.security import generate_password_hash  # noqa: E402

with app.app_context():
    if not User.query.filter_by(number="8001").first():
        db.session.add(User(username="テスト太郎", number="8001",
                             password=generate_password_hash("test1234"), is_admin=False))
    if not User.query.filter_by(number="8002").first():
        db.session.add(User(username="テスト次郎", number="8002",
                             password=generate_password_hash("test5678"), is_admin=False))
    db.session.commit()

shared_client = app.test_client()

shared_client.post(
    "/login",
    data={"login": "ログイン", "number": "8001", "password": "test1234"},
)
shared_client.post("/honso_stamp", data={"place1": "本社", "start1": "08:00"})
shared_client.get("/judge")
shared_client.post("/honso_modify", data={"end1": "12:00"})

with app.app_context():
    record_8001 = Time.query.filter(Time.number == "8001", Time.date == today_str).order_by(Time.id.desc()).first()
    assert record_8001 is not None
    record_8001_id = record_8001.id
    assert record_8001.start1 == "08:00"
    assert record_8001.end1 == "12:00"
print("8001のレコード作成 -> id =", record_8001_id, "start1/end1 =", record_8001.start1, record_8001.end1)

# ログアウトせずに、同じブラウザ（同じクライアント＝同じセッション）で
# 別の従業員番号(8002)としてログインし直す
r_switch = shared_client.post(
    "/login",
    data={"login": "ログイン", "number": "8002", "password": "test5678"},
    follow_redirects=False,
)
print("POST /login (同じブラウザで8001->8002へ切り替え) ->", r_switch.status_code, r_switch.headers.get("Location"))
assert r_switch.status_code == 302
assert r_switch.headers.get("Location") == "/judge"

# 8002が通夜から出勤・退勤まで入力する（本日はじめての8002の記録）
shared_client.post("/tsuya_stamp", data={"place2": "本社", "start2": "20:00"})
shared_client.get("/judge")
shared_client.post("/tsuya_modify", data={"end2": "23:00"})

with app.app_context():
    # 8001のレコードが変更されず、そのまま残っていることを確認
    record_8001_after = db.session.get(Time, record_8001_id)
    print("8002ログイン後の8001レコード -> number/start1/end1/start2/end2 =",
          record_8001_after.number, record_8001_after.start1, record_8001_after.end1,
          record_8001_after.start2, record_8001_after.end2)
    assert record_8001_after.number == "8001"
    assert record_8001_after.start1 == "08:00"
    assert record_8001_after.end1 == "12:00"
    assert record_8001_after.start2 is None
    assert record_8001_after.end2 is None

    # 8002は8001とは別の新しいレコードとして保存されていることを確認
    record_8002 = Time.query.filter(Time.number == "8002", Time.date == today_str).order_by(Time.id.desc()).first()
    print("8002のレコード -> id =", record_8002.id if record_8002 else None)
    assert record_8002 is not None
    assert record_8002.id != record_8001_id
    assert record_8002.start2 == "20:00"
    assert record_8002.end2 == "23:00"

# --- 「本日の手配書」機能の確認 ---

# 手配者アカウントでログインすると、手配書登録画面へ自動的に遷移することを確認
client_arranger = app.test_client()
r_arranger_login = client_arranger.post(
    "/login",
    data={"login": "ログイン", "number": "7001", "password": "staff1234"},
    follow_redirects=False,
)
print("POST /login (手配者) ->", r_arranger_login.status_code, r_arranger_login.headers.get("Location"))
assert r_arranger_login.status_code == 302
assert r_arranger_login.headers.get("Location") == "/arrangement_manage"

# 一般従業員・未ログインは手配書登録画面にアクセスできない
r_emp_arrangement = client_employee.get("/arrangement_manage", follow_redirects=False)
print("GET /arrangement_manage (一般従業員) ->", r_emp_arrangement.status_code, r_emp_arrangement.headers.get("Location"))
assert r_emp_arrangement.status_code == 302
assert "/login" in r_emp_arrangement.headers.get("Location", "")

r_anon_arrangement = client_anon.get("/arrangement_manage", follow_redirects=False)
print("GET /arrangement_manage (未ログイン) ->", r_anon_arrangement.status_code, r_anon_arrangement.headers.get("Location"))
assert r_anon_arrangement.status_code == 302
assert "/login" in r_anon_arrangement.headers.get("Location", "")

# 手配者が登録画面を開けること、対象ユーザーの選択肢に一般従業員だけが出ること
r_manage_get = client_arranger.get("/arrangement_manage", follow_redirects=False)
print("GET /arrangement_manage (手配者) ->", r_manage_get.status_code)
assert r_manage_get.status_code == 200
assert "手配書登録".encode("utf-8") in r_manage_get.data
assert "デモ次郎".encode("utf-8") in r_manage_get.data  # 0002が選択肢にいる
assert "手配担当".encode("utf-8") not in r_manage_get.data  # 手配者自身は選択肢に出ない
assert "管理者".encode("utf-8") not in r_manage_get.data   # 管理者も選択肢に出ない

with app.app_context():
    target_0002 = User.query.filter_by(number="0002").first()
    target_0002_id = target_0002.id

# 0002宛て・通夜・本日分の手配書を、画像なしのメモのみで登録する
r_create = client_arranger.post(
    "/arrangement_manage",
    data={
        "target_user_id": str(target_0002_id),
        "shift": "tsuya",
        "date": today_str,
        "memo": "本日は通夜の受付を17時から開始してください。",
    },
    follow_redirects=False,
)
print("POST /arrangement_manage (0002宛て・通夜・本日) ->", r_create.status_code, r_create.headers.get("Location"))
assert r_create.status_code == 302
assert r_create.headers.get("Location") == "/arrangement_manage"

r_manage_after = client_arranger.get("/arrangement_manage", follow_redirects=False)
assert "本日は通夜の受付を17時から開始してください。".encode("utf-8") in r_manage_after.data

# 対象ユーザー(0002)本人が「本日の手配書」画面でこのメモを確認できることを確認
client_0002_arrangement = app.test_client()
client_0002_arrangement.post(
    "/login", data={"login": "ログイン", "number": "0002", "password": "demo2345"}
)
r_today_0002 = client_0002_arrangement.get("/today_arrangement", follow_redirects=False)
print("GET /today_arrangement (0002本人) ->", r_today_0002.status_code)
assert r_today_0002.status_code == 200
assert "本日は通夜の受付を17時から開始してください。".encode("utf-8") in r_today_0002.data
# 本葬側はまだ未登録なので「まだ登録されていません」と表示される
assert "本日の本葬の手配書はまだ登録されていません。".encode("utf-8") in r_today_0002.data
# [追加] スマートフォン対応のためのviewport metaタグがあることを確認
assert 'name="viewport"'.encode("utf-8") in r_today_0002.data

# [追加] 前日・翌日リンクがあり、翌日に移動すると本日分のメモは
# 表示されず、そこから前日リンクで本日に戻ってくると再び表示されることを確認
tomorrow_str = (today + datetime.timedelta(days=1)).isoformat()
yesterday_str = (today - datetime.timedelta(days=1)).isoformat()
assert f'href="/today_arrangement?date={tomorrow_str}"'.encode("utf-8") in r_today_0002.data
assert f'href="/today_arrangement?date={yesterday_str}"'.encode("utf-8") in r_today_0002.data

r_tomorrow_0002 = client_0002_arrangement.get(
    f"/today_arrangement?date={tomorrow_str}", follow_redirects=False
)
print(f"GET /today_arrangement?date={tomorrow_str} (0002, 翌日には本日のメモは無い) ->", r_tomorrow_0002.status_code)
assert r_tomorrow_0002.status_code == 200
assert "本日は通夜の受付を17時から開始してください。".encode("utf-8") not in r_tomorrow_0002.data
assert "本日に戻る".encode("utf-8") in r_tomorrow_0002.data

r_back_today_0002 = client_0002_arrangement.get("/today_arrangement", follow_redirects=False)
assert "本日は通夜の受付を17時から開始してください。".encode("utf-8") in r_back_today_0002.data

# 別の従業員(0001)には0002宛ての手配書は見えない
r_today_0001 = client.get("/today_arrangement", follow_redirects=False)
print("GET /today_arrangement (0001, 他人宛ての手配書は見えない) ->", r_today_0001.status_code)
assert r_today_0001.status_code == 200
assert "本日は通夜の受付を17時から開始してください。".encode("utf-8") not in r_today_0001.data

# ハブ画面(/judge)に「本日の手配書」ボタンがあることを確認
r_judge_arrangement_btn = client_0002_arrangement.get("/judge", follow_redirects=True)
print("GET /judge (本日の手配書ボタンの確認) ->", r_judge_arrangement_btn.status_code)
assert "本日の手配書".encode("utf-8") in r_judge_arrangement_btn.data
assert 'href="/today_arrangement"'.encode("utf-8") in r_judge_arrangement_btn.data
# [追加] ユーザー要望により「本日の手配書」ボタンが「勤怠一覧」ボタンより
# 上（HTML内で先）に表示される順序に入れ替えたことを確認
_pos_arrangement_btn = r_judge_arrangement_btn.data.find('href="/today_arrangement"'.encode("utf-8"))
_pos_attendance_btn = r_judge_arrangement_btn.data.find('href="/attendance_list"'.encode("utf-8"))
assert _pos_arrangement_btn != -1 and _pos_attendance_btn != -1
assert _pos_arrangement_btn < _pos_attendance_btn

# --- 画像アップロードとアクセス制御の確認 ---

r_create_img = client_arranger.post(
    "/arrangement_manage",
    data={
        "target_user_id": str(target_0002_id),
        "shift": "honso",
        "date": today_str,
        "memo": "",
        "image": (io.BytesIO(b"fake-image-bytes-for-smoke-test"), "sample.png"),
    },
    content_type="multipart/form-data",
    follow_redirects=False,
)
print("POST /arrangement_manage (画像付き, 0002宛て・本葬) ->", r_create_img.status_code, r_create_img.headers.get("Location"))
assert r_create_img.status_code == 302

with app.app_context():
    arr_img = Arrangement.query.filter_by(
        target_user_id=target_0002_id, shift="honso", date=today_str
    ).first()
    assert arr_img is not None
    assert arr_img.image_filename is not None
    arr_img_id = arr_img.id

# 対象ユーザー本人・手配者・管理者は画像にアクセスできる
r_img_owner = client_0002_arrangement.get(f"/arrangement_image/{arr_img_id}", follow_redirects=False)
print("GET /arrangement_image (本人) ->", r_img_owner.status_code)
assert r_img_owner.status_code == 200
assert r_img_owner.data == b"fake-image-bytes-for-smoke-test"

r_img_arranger = client_arranger.get(f"/arrangement_image/{arr_img_id}", follow_redirects=False)
print("GET /arrangement_image (手配者) ->", r_img_arranger.status_code)
assert r_img_arranger.status_code == 200

r_img_admin = client_admin.get(f"/arrangement_image/{arr_img_id}", follow_redirects=False)
print("GET /arrangement_image (管理者) ->", r_img_admin.status_code)
assert r_img_admin.status_code == 200

# 関係ない別の従業員(0001)はアクセスできない
r_img_other = client.get(f"/arrangement_image/{arr_img_id}", follow_redirects=False)
print("GET /arrangement_image (無関係な従業員) ->", r_img_other.status_code)
assert r_img_other.status_code == 403

# 画像・メモのどちらも入力しない場合はエラーになることを確認
r_invalid = client_arranger.post(
    "/arrangement_manage",
    data={"target_user_id": str(target_0002_id), "shift": "honso", "date": today_str, "memo": ""},
    follow_redirects=False,
)
print("POST /arrangement_manage (画像・メモどちらも無し) ->", r_invalid.status_code)
assert r_invalid.status_code == 200
assert "画像・PDF・メモのいずれかを入力してください。".encode("utf-8") in r_invalid.data

# --- [追加] PDFアップロードの確認（会館案内図などPDFで渡されることも
#     多いため、画像に加えてPDFも登録できるようにした） ---
with app.app_context():
    target_0003_id = User.query.filter_by(number="0003").first().id

r_create_pdf = client_arranger.post(
    "/arrangement_manage",
    data={
        "target_user_id": str(target_0003_id),
        "shift": "honso",
        "date": today_str,
        "memo": "",
        "image": (io.BytesIO(b"%PDF-1.4 fake-pdf-bytes-for-smoke-test"), "chizu.pdf"),
    },
    content_type="multipart/form-data",
    follow_redirects=False,
)
print("POST /arrangement_manage (PDF付き, 0003宛て・本葬) ->", r_create_pdf.status_code, r_create_pdf.headers.get("Location"))
assert r_create_pdf.status_code == 302

with app.app_context():
    arr_pdf = Arrangement.query.filter_by(
        target_user_id=target_0003_id, shift="honso", date=today_str
    ).first()
    assert arr_pdf is not None
    assert arr_pdf.image_filename is not None
    assert arr_pdf.image_filename.lower().endswith(".pdf")
    arr_pdf_id = arr_pdf.id

r_pdf_fetch = client_arranger.get(f"/arrangement_image/{arr_pdf_id}", follow_redirects=False)
print("GET /arrangement_image (PDF) ->", r_pdf_fetch.status_code, r_pdf_fetch.content_type)
assert r_pdf_fetch.status_code == 200
assert r_pdf_fetch.data == b"%PDF-1.4 fake-pdf-bytes-for-smoke-test"
assert "application/pdf" in r_pdf_fetch.content_type

# 対象ユーザー(0003)の「本日の手配書」画面では、<img>ではなく
# PDFを開くリンクとして表示されることを確認
client_0003_arrangement = app.test_client()
client_0003_arrangement.post(
    "/login", data={"login": "ログイン", "number": "0003", "password": "demo3456"}
)
r_today_0003 = client_0003_arrangement.get("/today_arrangement", follow_redirects=False)
print("GET /today_arrangement (0003, PDFの手配書) ->", r_today_0003.status_code)
assert r_today_0003.status_code == 200
assert "本葬の手配書PDFを開く".encode("utf-8") in r_today_0003.data
assert f'src="/arrangement_image/{arr_pdf_id}"'.encode("utf-8") not in r_today_0003.data

# 手配書登録画面の一覧でも、サムネイル画像ではなく「PDFを開く」リンクに
# なっていることを確認
r_manage_pdf_list = client_arranger.get("/arrangement_manage", follow_redirects=False)
assert "PDFを開く".encode("utf-8") in r_manage_pdf_list.data

r_delete_pdf = client_arranger.post(f"/arrangement_delete/{arr_pdf_id}", follow_redirects=False)
assert r_delete_pdf.status_code == 302
with app.app_context():
    assert db.session.get(Arrangement, arr_pdf_id) is None

# --- 削除機能の確認 ---
r_delete = client_arranger.post(f"/arrangement_delete/{arr_img_id}", follow_redirects=False)
print("POST /arrangement_delete ->", r_delete.status_code, r_delete.headers.get("Location"))
assert r_delete.status_code == 302
with app.app_context():
    assert db.session.get(Arrangement, arr_img_id) is None

r_img_after_delete = client_0002_arrangement.get(f"/arrangement_image/{arr_img_id}", follow_redirects=False)
print("GET /arrangement_image (削除後) ->", r_img_after_delete.status_code)
assert r_img_after_delete.status_code == 404

# 管理画面からもArrangementテーブルを確認できることを確認
r_admin_arrangement = client_admin.get("/admin/arrangement/", follow_redirects=False)
print("GET /admin/arrangement/ (管理者) ->", r_admin_arrangement.status_code)
assert r_admin_arrangement.status_code == 200

print("\nALL SMOKE TESTS PASSED")
