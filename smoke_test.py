import sys
import os
import io
import json
import re
import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, "attendance_fixed")
sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

import index  # noqa: E402  registers all routes (login, judge, select, honso, tsuya...)
from index import app, db  # noqa: E402
from models import User, Time, Arrangement, Place  # noqa: E402
import honso  # noqa: E402
import tsuya  # noqa: E402
import notifications  # noqa: E402
from unittest import mock  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

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
# [追加] 手配者が会館名を事前設定していない通常のケースでは、会館名欄は
# 変更可能（<select>にdisabledが付かない）で、注意書きも出ないこと
assert '<select id="place1" name="place1" required disabled>'.encode("utf-8") not in r5.data
assert "会館名は手配者が設定済みのため、変更できません".encode("utf-8") not in r5.data

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
# [追加] 会館(Place)に追加したtransportation_fee列が、Flask-Adminの
# 一覧画面にも自動的に表示されること（列名はスネークケースから
# タイトルケースに自動変換される。Break Minutes1と同じ挙動）。
assert "Transportation Fee".encode("utf-8") in r12.data

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
# [追加] Timeテーブルのcolumn_listは指定していない（全カラムがそのまま
# CSV出力の対象になる）ため、新しく追加したbreak_minutes1/break_minutes2列も
# 自動的にヘッダーへ含まれているはず（Flask-Adminはヘッダーをタイトル
# ケースに変換するため "Break Minutes1"/"Break Minutes2" という表記になる）。
assert b"Break Minutes1" in r13.data
assert b"Break Minutes2" in r13.data

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

# [追加] 本葬・通夜それぞれの実働時間（行ごと）と、月合計（本葬合計・
# 通夜合計・本葬+通夜合計）が正しく計算・表示されていることを確認する。
#
# seed_demo_user.pyのpatterns（3種類、i%3で循環）は、前月の5日・12日・19日の
# 3件（サンプル数=パターン数と一致）に対して、開始オフセットに関わらず
# 3パターンとも必ず1回ずつ出現する。各パターンの実働時間は固定値なので、
# 行ごとの表示（8時間0分・3時間0分・4時間30分・4時間0分）をそのまま
# 期待値として検証できる。
#   パターン0: 本葬 09:00-17:00 = 8時間0分（通夜なし）
#   パターン1: 通夜 18:00-21:00 = 3時間0分（本葬なし）
#   パターン2: 本葬 08:30-13:00 = 4時間30分／通夜 18:00-22:00 = 4時間0分
assert "8時間0分".encode("utf-8") in r27.data
assert "3時間0分".encode("utf-8") in r27.data
assert "4時間30分".encode("utf-8") in r27.data
assert "4時間0分".encode("utf-8") in r27.data

# 月合計は、上の3パターンから独立に（index.pyのヘルパーを使い、DBを
# 直接読み直して）期待値を計算し、画面表示と一致することを確認する。
with app.app_context():
    prev_month_prefix = "{:04d}-{:02d}-".format(prev_year, prev_month)
    prev_records_0001 = (
        Time.query
        .filter(Time.number == "0001", Time.date.like(prev_month_prefix + "%"))
        .all()
    )
    expected_honso_total = 0
    expected_tsuya_total = 0
    for rec in prev_records_0001:
        hm = index._calc_work_minutes(rec.start1, rec.end1)
        tm = index._calc_work_minutes(rec.start2, rec.end2)
        if hm:
            expected_honso_total += hm
        if tm:
            expected_tsuya_total += tm
    expected_honso_display = index._format_work_minutes(expected_honso_total)
    expected_tsuya_display = index._format_work_minutes(expected_tsuya_total)
    expected_combined_display = index._format_work_minutes(expected_honso_total + expected_tsuya_total)

print(
    f"前月({prev_year}年{prev_month}月, 0001)の期待合計 本葬:{expected_honso_display} "
    f"通夜:{expected_tsuya_display} 合計:{expected_combined_display}"
)
assert expected_honso_display.encode("utf-8") in r27.data
assert expected_tsuya_display.encode("utf-8") in r27.data
assert expected_combined_display.encode("utf-8") in r27.data
# 前月分は本葬・通夜とも必ず記録があるはずなので、期待値が"-"（未入力扱い）に
# なっていないこと（＝集計が本当に行われていること）も念のため確認する。
assert expected_honso_display != "-"
assert expected_tsuya_display != "-"

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

# --- [追加] 「手当」欄に追加した「休憩」チェックボックス・休憩時間(分)の確認 ---
#
# ・honso_stamp/honso_modify・tsuya_stamp/tsuya_modifyの各フォーム画面に
#   「休憩」チェックボックスと休憩時間(分)の入力欄が表示されていること
# ・休憩時間(分)を入力して保存すると、Time.break1/break_minutes1（本葬）・
#   break2/break_minutes2（通夜）としてDBに保存されること
# ・勤怠一覧画面で、休憩時間の列に表示され、実働時間が
#   「出勤〜退勤の時間 - 休憩時間」として正しく計算されて表示されること
#   （月合計にもその差し引き後の値が反映されること）
# を、他のテストの記録と混ざらない専用のテストユーザー(8003)で確認する。

with app.app_context():
    if not User.query.filter_by(number="8003").first():
        db.session.add(User(username="テスト三郎", number="8003",
                             password=generate_password_hash("test9012"), is_admin=False))
    db.session.commit()

client_8003 = app.test_client()
client_8003.post(
    "/login",
    data={"login": "ログイン", "number": "8003", "password": "test9012"},
)

# フォーム画面（出勤入力）に「休憩」項目が追加されていることの確認
# （8003はまだ今日の記録が無いため、出勤フォームがそのまま表示される）
r_break_ui_honso_stamp = client_8003.get("/honso_stamp", follow_redirects=False)
assert r_break_ui_honso_stamp.status_code == 200
assert "休憩".encode("utf-8") in r_break_ui_honso_stamp.data
assert 'id="break_minutes1"'.encode("utf-8") in r_break_ui_honso_stamp.data

r_break_ui_honso_modify_pre = client_8003.post(
    "/honso_stamp",
    data={"place1": "本社", "start1": "09:00"},
    follow_redirects=False,
)
assert r_break_ui_honso_modify_pre.status_code == 302
client_8003.get("/judge")

# フォーム画面（退勤入力）にも「休憩」項目が追加されていることの確認
r_break_ui_honso_modify = client_8003.get("/honso_modify", follow_redirects=False)
assert r_break_ui_honso_modify.status_code == 200
assert "休憩".encode("utf-8") in r_break_ui_honso_modify.data
assert 'id="break_minutes1"'.encode("utf-8") in r_break_ui_honso_modify.data

# 出勤9:00・退勤18:00（9時間=540分）で、休憩45分をチェック付きで保存する
r_break_modify = client_8003.post(
    "/honso_modify",
    data={"end1": "18:00", "break1": "on", "break_minutes1": "45"},
    follow_redirects=False,
)
print("POST /honso_modify (休憩45分付き退勤打刻, 8003) ->", r_break_modify.status_code)
assert r_break_modify.status_code == 302

with app.app_context():
    record_8003 = Time.query.filter(Time.number == "8003", Time.date == today_str).first()
    assert record_8003 is not None
    assert record_8003.start1 == "09:00"
    assert record_8003.end1 == "18:00"
    assert record_8003.break1 == "on"
    assert record_8003.break_minutes1 == 45
    # 9:00-18:00は9時間(540分)。休憩45分を差し引くと8時間15分(495分)になるはず
    # （index.py側のヘルパーで独立に再計算し、期待値とする）。
    expected_minutes_8003 = index._calc_work_minutes(
        record_8003.start1, record_8003.end1, break_minutes=record_8003.break_minutes1
    )
    assert expected_minutes_8003 == 540 - 45
    expected_display_8003 = index._format_work_minutes(expected_minutes_8003)

r_attendance_8003 = client_8003.get("/attendance_list", follow_redirects=False)
print("GET /attendance_list (8003, 休憩45分の実働時間確認) ->", r_attendance_8003.status_code)
assert r_attendance_8003.status_code == 200
assert "45分".encode("utf-8") in r_attendance_8003.data  # 休憩の列
assert expected_display_8003.encode("utf-8") in r_attendance_8003.data  # 実働時間の列（8時間15分）
# 今月は本葬のみ1件・通夜の記録は無いので、行の実働時間と月の本葬合計・
# （本葬＋通夜）合計の3か所すべてが同じ「8時間15分」になっているはず。
assert r_attendance_8003.data.count(expected_display_8003.encode("utf-8")) >= 3
# 通夜は今月まだ記録が無いので、通夜合計は「0時間0分」のままであること
assert "0時間0分".encode("utf-8") in r_attendance_8003.data

# --- [追加] 出退勤画面の「登録」ボタンを押した際のメール通知の確認 ---
#
# (1) notifications.send_attendance_notification単体のテスト：
#     Resend APIへの実際のHTTPリクエスト(requests.post)を実際には
#     送らず（差し替えて）、件名・本文・宛先が仕様通りに組み立てられる
#     ことを確認する。
#       ・出勤時間だけが入力されている場合 -> 件名は「【出勤】氏名 会館名」
#       ・退勤時間まで入力されている場合   -> 件名は「【退勤】氏名 会館名」
#       ・会館が「その他」の場合は、手入力された会館名を件名・本文に使う
#       ・休憩時間が入力されている場合は本文に「◯分」、無い場合は「なし」
# (2) honso.py/tsuya.pyの各画面（出勤・退勤の登録処理）が、実際に
#     send_attendance_notification()を正しい引数で呼び出していることの確認
#     （関数自体をテスト用の記録関数に差し替えて検証する）。


class _FakeResendResponse:
    """[追加] requests.postの戻り値の代わりに使うテスト用のダミークラス。
    Resend APIが返す成功レスポンス(HTTP 200)を模倣する。"""
    status_code = 200
    text = '{"id": "fake-email-id"}'


_sent_requests = []


def _fake_requests_post(url, headers=None, data=None, timeout=None):
    """[追加] requests.postの代わりに使うテスト用のダミー関数。
    実際にはネットワーク接続を行わず、送信されようとしたリクエスト内容
    （URL・ヘッダー・ボディ）だけを記録する。"""
    _sent_requests.append({"url": url, "headers": headers, "data": data})
    return _FakeResendResponse()


_orig_requests_post = notifications.requests.post
notifications.requests.post = _fake_requests_post

_orig_honso_send = honso.send_attendance_notification
_orig_tsuya_send = tsuya.send_attendance_notification

_orig_env = {
    k: os.environ.get(k)
    for k in ("RESEND_API_KEY", "MAIL_FROM", "NOTIFY_EMAIL_TO")
}
os.environ["RESEND_API_KEY"] = "re_dummy_api_key"
os.environ["NOTIFY_EMAIL_TO"] = "notify@example.com"

try:
    # 出勤のみ（休憩なし） -> 件名は【出勤】
    _sent_requests.clear()
    ok = notifications.send_attendance_notification(
        shift_label="本葬", user_name="デモ太郎", number="0001",
        place="愛知葬祭 春日井会場", other=None,
        start="09:00", end=None, break_flag=None, break_minutes=None,
    )
    assert ok is True
    assert len(_sent_requests) == 1
    payload = json.loads(_sent_requests[0]["data"])
    print("通知メール(出勤のみ)の件名 ->", payload["subject"])
    assert payload["subject"] == "【出勤】デモ太郎 愛知葬祭 春日井会場"
    assert payload["to"] == ["notify@example.com"]
    assert "onboarding@resend.dev" in payload["from"]  # MAIL_FROM未設定時の既定送信元
    body = payload["text"]
    assert "氏名: デモ太郎" in body
    assert "従業員番号: 0001" in body
    assert "会館名: 愛知葬祭 春日井会場" in body
    assert "出勤時間: 09:00" in body
    assert "退勤時間: 未入力" in body
    assert "休憩時間: なし" in body
    assert _sent_requests[0]["headers"]["Authorization"] == "Bearer re_dummy_api_key"

    # [追加] メール本文の「クリック日時」が、サーバーのタイムゾーン設定に
    # 関わらず日本時間(JST=UTC+9)で表示されることの確認。
    # このテスト実行環境自体がUTCで動いている（=以前の実装のバグを
    # 再現できる）ことを利用し、素朴な`datetime.datetime.now()`
    # （サーバーのローカル時刻、このテスト環境ではUTC）とは一致せず、
    # 明示的にJSTへ変換した時刻と一致することを確認する。
    clicked_match = re.search(r"クリック日時: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", body)
    assert clicked_match, "クリック日時が本文に見つかりません"
    clicked_dt = datetime.datetime.strptime(clicked_match.group(1), "%Y-%m-%d %H:%M:%S")
    expected_jst_now = datetime.datetime.now(notifications.JST).replace(tzinfo=None)
    assert abs((clicked_dt - expected_jst_now).total_seconds()) < 60, (
        "クリック日時がJSTになっていません: {} (期待値の目安: {})".format(
            clicked_dt, expected_jst_now
        )
    )
    # サーバーのローカル時刻（このテスト環境ではUTC）とは9時間ずれている
    # はず（=単純に datetime.datetime.now() を使っていないことの確認）。
    naive_server_now = datetime.datetime.now()
    assert abs((clicked_dt - naive_server_now).total_seconds() - 9 * 3600) < 60

    # 退勤まで入力・休憩あり・「その他」の会館 -> 件名は【退勤】、
    # 会館名は手入力されたother側が使われる
    _sent_requests.clear()
    notifications.send_attendance_notification(
        shift_label="通夜", user_name="デモ次郎", number="0002",
        place="その他", other="臨時会場（公民館）",
        start="18:00", end="21:30", break_flag="on", break_minutes=30,
    )
    assert len(_sent_requests) == 1
    payload2 = json.loads(_sent_requests[0]["data"])
    print("通知メール(退勤・その他会場・休憩あり)の件名 ->", payload2["subject"])
    assert payload2["subject"] == "【退勤】デモ次郎 臨時会場（公民館）"
    body2 = payload2["text"]
    assert "会館名: 臨時会場（公民館）" in body2
    assert "出勤時間: 18:00" in body2
    assert "退勤時間: 21:30" in body2
    assert "休憩時間: 30分" in body2

    # RESEND_API_KEY/NOTIFY_EMAIL_TOの設定が未完了の場合は、例外にならず
    # 送信をスキップすること
    del os.environ["NOTIFY_EMAIL_TO"]
    _sent_requests.clear()
    ok_skipped = notifications.send_attendance_notification(
        shift_label="本葬", user_name="デモ太郎", number="0001",
        place="本社", other=None, start="09:00", end=None,
        break_flag=None, break_minutes=None,
    )
    assert ok_skipped is False
    assert len(_sent_requests) == 0
    os.environ["NOTIFY_EMAIL_TO"] = "notify@example.com"

    # --- (2) honso.py/tsuya.pyからの呼び出し自体の確認（記録用の
    #     差し替え関数を使い、実際の出退勤フローで正しい引数が
    #     渡されていることを検証する） ---
    _notification_calls = []

    def _recording_send_attendance_notification(**kwargs):
        _notification_calls.append(kwargs)
        return True

    honso.send_attendance_notification = _recording_send_attendance_notification
    tsuya.send_attendance_notification = _recording_send_attendance_notification

    with app.app_context():
        if not User.query.filter_by(number="8004").first():
            db.session.add(User(username="テスト四郎", number="8004",
                                 password=generate_password_hash("test3456"), is_admin=False))
        db.session.commit()

    client_8004 = app.test_client()
    client_8004.post("/login", data={"login": "ログイン", "number": "8004", "password": "test3456"})

    # 本葬：出勤（休憩なし、会館は「その他」）
    client_8004.post("/honso_stamp", data={"place1": "その他", "other1": "8004会場", "start1": "11:00"})
    client_8004.get("/judge")
    # 本葬：退勤（休憩30分）
    client_8004.post("/honso_modify", data={"end1": "15:00", "break1": "on", "break_minutes1": "30"})
    client_8004.get("/judge")
    # 通夜：出勤
    client_8004.post("/tsuya_stamp", data={"place2": "本社", "start2": "19:00"})
    client_8004.get("/judge")
    # 通夜：退勤（休憩なし）
    client_8004.post("/tsuya_modify", data={"end2": "22:00"})

    print("8004の一連の操作で記録された通知呼び出し件数 ->", len(_notification_calls))
    assert len(_notification_calls) == 4

    honso_stamp_call = _notification_calls[0]
    assert honso_stamp_call["shift_label"] == "本葬"
    assert honso_stamp_call["place"] == "その他"
    assert honso_stamp_call["other"] == "8004会場"
    assert honso_stamp_call["start"] == "11:00"
    assert not honso_stamp_call["end"] or honso_stamp_call["end"] == "--:--"

    honso_modify_call = _notification_calls[1]
    assert honso_modify_call["shift_label"] == "本葬"
    # honso_modify()では、フォームに無いother1が毎回空になってしまう
    # 既知の挙動があるため、通知には出勤時に記録されたplace1/other1
    # （"その他"/"8004会場"）がそのまま使われることを確認する。
    assert honso_modify_call["place"] == "その他"
    assert honso_modify_call["other"] == "8004会場"
    assert honso_modify_call["start"] == "11:00"
    assert honso_modify_call["end"] == "15:00"
    assert honso_modify_call["break_flag"] == "on"
    assert honso_modify_call["break_minutes"] == 30

    tsuya_stamp_call = _notification_calls[2]
    assert tsuya_stamp_call["shift_label"] == "通夜"
    assert tsuya_stamp_call["place"] == "本社"
    assert tsuya_stamp_call["start"] == "19:00"

    tsuya_modify_call = _notification_calls[3]
    assert tsuya_modify_call["shift_label"] == "通夜"
    assert tsuya_modify_call["start"] == "19:00"
    assert tsuya_modify_call["end"] == "22:00"
    assert not tsuya_modify_call["break_flag"]
finally:
    # [追加] テスト用に差し替えたものは、後続のテストに影響しないよう
    # 必ず元に戻す。
    notifications.requests.post = _orig_requests_post
    honso.send_attendance_notification = _orig_honso_send
    tsuya.send_attendance_notification = _orig_tsuya_send
    for k, v in _orig_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

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
# [修正] 「手配者」列（今回追加）には、登録済みの手配書の手配者名として
# "手配担当" が正当に表示されうる（サンプルの手配書が手配担当によって
# 登録されているため）ので、「対象ユーザーの選択肢」に出ないことを、
# ページ全体ではなく<option>のマークアップそのもので確認する。
assert "手配担当（7001）".encode("utf-8") not in r_manage_get.data  # 手配者自身は選択肢に出ない
assert "管理者（9001）".encode("utf-8") not in r_manage_get.data   # 管理者も選択肢に出ない

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

# --- [追加] 手配書登録画面(/arrangement_manage)で「登録する」ボタンを押した際の
#     メール通知・手配者名(created_by_name)の記録の確認 ---
# 他のテストとの日付・対象ユーザーの組み合わせの衝突を避けるため、
# この確認専用の従業員(8008)を用意する（8007用のテストと同じやり方）。
with app.app_context():
    if not User.query.filter_by(number="8008").first():
        db.session.add(User(username="テスト八郎", number="8008",
                             password=generate_password_hash("test7890"), is_admin=False))
        db.session.commit()
    target_8008 = User.query.filter_by(number="8008").first()
    target_8008_id = target_8008.id

_sent_requests.clear()
_orig_env_arrangement_notify = {
    k: os.environ.get(k)
    for k in ("RESEND_API_KEY", "MAIL_FROM", "NOTIFY_EMAIL_TO")
}
os.environ["RESEND_API_KEY"] = "re_dummy_api_key"
os.environ["NOTIFY_EMAIL_TO"] = "notify@example.com"
notifications.requests.post = _fake_requests_post

try:
    # (1) 添付なし・メモありで登録 -> 「添付：なし」「メモ：あり」
    r_arr_notify = client_arranger.post(
        "/arrangement_manage",
        data={
            "target_user_id": str(target_8008_id),
            "shift": "honso",
            "date": today_str,
            "memo": "メール通知確認用のメモ",
            "place": "五郎会館",
        },
        follow_redirects=False,
    )
    print("POST /arrangement_manage (手配書登録メール通知の確認) ->", r_arr_notify.status_code)
    assert r_arr_notify.status_code == 302
    assert len(_sent_requests) == 1
    payload_arr = json.loads(_sent_requests[0]["data"])
    print("手配書登録通知メールの件名 ->", payload_arr["subject"])
    assert payload_arr["subject"] == "【登録】手配書が登録されました。"
    assert payload_arr["to"] == ["notify@example.com"]
    body_arr = payload_arr["text"]
    print("手配書登録通知メールの本文 ->", body_arr.replace("\n", " / "))
    assert "手配者：手配担当" in body_arr
    assert "対象ユーザ：テスト八郎" in body_arr
    assert "会館名：五郎会館" in body_arr
    assert "勤務：本葬" in body_arr
    assert "添付：なし" in body_arr
    assert "メモ：あり" in body_arr

    # DB側にも手配者の氏名(created_by_name)が記録されていることを確認
    with app.app_context():
        arr_notify = Arrangement.query.filter_by(
            target_user_id=target_8008_id, shift="honso", date=today_str
        ).first()
        assert arr_notify is not None
        assert arr_notify.created_by_name == "手配担当"

    # 一覧画面にも「手配者」列として表示されることを確認
    r_manage_after_notify = client_arranger.get("/arrangement_manage", follow_redirects=False)
    assert "手配者".encode("utf-8") in r_manage_after_notify.data

    # (2) 添付あり・メモなしで登録（別の勤務区分・同じ対象ユーザー）
    #     -> 「添付：あり」「メモ：なし」
    _sent_requests.clear()
    r_arr_notify_img = client_arranger.post(
        "/arrangement_manage",
        data={
            "target_user_id": str(target_8008_id),
            "shift": "tsuya",
            "date": today_str,
            "memo": "",
            "image": (io.BytesIO(b"fake-image-for-notify-test"), "notify.png"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    print("POST /arrangement_manage (手配書登録メール通知の確認、添付あり) ->", r_arr_notify_img.status_code)
    assert r_arr_notify_img.status_code == 302
    assert len(_sent_requests) == 1
    payload_arr_img = json.loads(_sent_requests[0]["data"])
    body_arr_img = payload_arr_img["text"]
    assert "勤務：通夜" in body_arr_img
    assert "添付：あり" in body_arr_img
    assert "メモ：なし" in body_arr_img
finally:
    notifications.requests.post = _orig_requests_post
    for k, v in _orig_env_arrangement_notify.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

# --- [追加] 手配者画面からの「会館名」登録機能の確認 ---

# 手配書登録画面に「会館名の登録」フォームが表示されていること
assert "会館名の登録".encode("utf-8") in r_manage_get.data

# 0002宛てに新しい会館名を登録する
r_place_create = client_arranger.post(
    "/arrangement_manage",
    data={
        "form_type": "place",
        "place_target_user_id": str(target_0002_id),
        "place_name": "テスト葬祭 桜ヶ丘会場",
    },
    follow_redirects=False,
)
print("POST /arrangement_manage (会館名登録, 0002宛て) ->", r_place_create.status_code, r_place_create.headers.get("Location"))
assert r_place_create.status_code == 302
assert r_place_create.headers.get("Location") == "/arrangement_manage"

with app.app_context():
    created_place = Place.query.filter_by(user_id=target_0002_id, place="テスト葬祭 桜ヶ丘会場").first()
    assert created_place is not None
    created_place_id = created_place.id
    # [追加] 交通費を入力しなかった場合は0円として登録されること
    assert created_place.transportation_fee == 0

# 一覧画面に、登録した会館名と対象ユーザー名が表示されること
r_manage_after_place = client_arranger.get("/arrangement_manage", follow_redirects=False)
assert "テスト葬祭 桜ヶ丘会場".encode("utf-8") in r_manage_after_place.data
assert "デモ次郎".encode("utf-8") in r_manage_after_place.data
# [追加] 交通費0円の会館名も一覧に「0円」と表示されること
assert "0円".encode("utf-8") in r_manage_after_place.data

# [追加] 交通費を指定して会館名を登録した場合、その金額が保存され、
# 一覧にも「○○円」の形式で表示されること
r_place_create_with_fee = client_arranger.post(
    "/arrangement_manage",
    data={
        "form_type": "place",
        "place_target_user_id": str(target_0002_id),
        "place_name": "テスト葬祭 交通費あり会場",
        "transportation_fee": "1500",
    },
    follow_redirects=False,
)
print("POST /arrangement_manage (会館名登録, 交通費1500円) ->", r_place_create_with_fee.status_code)
assert r_place_create_with_fee.status_code == 302

with app.app_context():
    created_place_with_fee = Place.query.filter_by(
        user_id=target_0002_id, place="テスト葬祭 交通費あり会場"
    ).first()
    assert created_place_with_fee is not None
    assert created_place_with_fee.transportation_fee == 1500

r_manage_after_place_fee = client_arranger.get("/arrangement_manage", follow_redirects=False)
assert "テスト葬祭 交通費あり会場".encode("utf-8") in r_manage_after_place_fee.data
assert "1,500円".encode("utf-8") in r_manage_after_place_fee.data

# 負の値やおかしな値を入力しても0円として扱われ、エラーにはならないこと
r_place_create_bad_fee = client_arranger.post(
    "/arrangement_manage",
    data={
        "form_type": "place",
        "place_target_user_id": str(target_0002_id),
        "place_name": "テスト葬祭 不正交通費会場",
        "transportation_fee": "-500",
    },
    follow_redirects=False,
)
assert r_place_create_bad_fee.status_code == 302
with app.app_context():
    created_place_bad_fee = Place.query.filter_by(
        user_id=target_0002_id, place="テスト葬祭 不正交通費会場"
    ).first()
    assert created_place_bad_fee is not None
    assert created_place_bad_fee.transportation_fee == 0

# 登録した会館名が、対象ユーザー(0002)本人の出退勤画面の会館名選択肢にも
# 反映されていること(honso.get_places_for_current_user経由)を確認
r_honso_0002 = client_0002_arrangement.get("/honso_stamp", follow_redirects=False)
print("GET /honso_stamp (0002, 新しい会館名の確認) ->", r_honso_0002.status_code)
assert "テスト葬祭 桜ヶ丘会場".encode("utf-8") in r_honso_0002.data

# 対象ユーザー・会館名が未入力の場合はエラーになり、登録されないこと
r_place_invalid = client_arranger.post(
    "/arrangement_manage",
    data={"form_type": "place", "place_target_user_id": "", "place_name": ""},
    follow_redirects=False,
)
print("POST /arrangement_manage (会館名登録, 未入力) ->", r_place_invalid.status_code)
assert r_place_invalid.status_code == 200
assert "対象ユーザーを選択してください".encode("utf-8") in r_place_invalid.data

r_place_invalid2 = client_arranger.post(
    "/arrangement_manage",
    data={"form_type": "place", "place_target_user_id": str(target_0002_id), "place_name": "   "},
    follow_redirects=False,
)
print("POST /arrangement_manage (会館名登録, 会館名未入力) ->", r_place_invalid2.status_code)
assert r_place_invalid2.status_code == 200
assert "会館名を入力してください".encode("utf-8") in r_place_invalid2.data

# 一般従業員・未ログインは会館名の登録・削除ができないこと
r_emp_place_create = client_employee.post(
    "/arrangement_manage",
    data={"form_type": "place", "place_target_user_id": str(target_0002_id), "place_name": "不正登録テスト"},
    follow_redirects=False,
)
print("POST /arrangement_manage (会館名登録, 一般従業員) ->", r_emp_place_create.status_code, r_emp_place_create.headers.get("Location"))
assert r_emp_place_create.status_code == 302
assert "/login" in r_emp_place_create.headers.get("Location", "")

r_anon_place_delete = client_anon.post(f"/arrangement_place_delete/{created_place_id}", follow_redirects=False)
print("POST /arrangement_place_delete (未ログイン) ->", r_anon_place_delete.status_code, r_anon_place_delete.headers.get("Location"))
assert r_anon_place_delete.status_code == 302
assert "/login" in r_anon_place_delete.headers.get("Location", "")
with app.app_context():
    assert db.session.get(Place, created_place_id) is not None  # 削除されていないこと

# 手配者による会館名の削除
r_place_delete = client_arranger.post(f"/arrangement_place_delete/{created_place_id}", follow_redirects=False)
print("POST /arrangement_place_delete (手配者) ->", r_place_delete.status_code, r_place_delete.headers.get("Location"))
assert r_place_delete.status_code == 302
with app.app_context():
    assert db.session.get(Place, created_place_id) is None

# 全員共通(user_id未設定)の会館名は、このページの一覧には表示されず、
# このルートからは削除できないことを確認
with app.app_context():
    common_place = Place(user_id=None, place="共通会館テスト")
    db.session.add(common_place)
    db.session.commit()
    common_place_id = common_place.id

r_manage_common_check = client_arranger.get("/arrangement_manage", follow_redirects=False)
assert "共通会館テスト".encode("utf-8") not in r_manage_common_check.data

r_common_delete_attempt = client_arranger.post(f"/arrangement_place_delete/{common_place_id}", follow_redirects=False)
print("POST /arrangement_place_delete (全員共通の会館名) ->", r_common_delete_attempt.status_code)
assert r_common_delete_attempt.status_code == 302
with app.app_context():
    assert db.session.get(Place, common_place_id) is not None  # 削除されず残っていること
    # 後片付け
    db.session.delete(db.session.get(Place, common_place_id))
    db.session.commit()

# --- [追加] 手配書登録フォームへの「会館名」選択機能の確認 ---

# フォームに会館名の項目と、対象ユーザーごとの会館名一覧(JS用データ)が
# 埋め込まれていること
r_manage_place_field = client_arranger.get("/arrangement_manage", follow_redirects=False)
assert "会館名".encode("utf-8") in r_manage_place_field.data
assert "arrangement_place_select".encode("utf-8") in r_manage_place_field.data
assert "名古屋メモリアルホール".encode("utf-8") in r_manage_place_field.data  # 0002の会館名一覧がJSに含まれる

# 既存の会館名(0002の「豊田会館」)を選択して手配書を登録する
r_arr_place_existing = client_arranger.post(
    "/arrangement_manage",
    data={
        "target_user_id": str(target_0002_id),
        "shift": "honso",
        "date": today_str,
        "memo": "会館名テスト（既存の会館名を選択）",
        "place": "豊田会館",
    },
    follow_redirects=False,
)
print("POST /arrangement_manage (会館名=豊田会館, 0002宛て・本葬) ->", r_arr_place_existing.status_code)
assert r_arr_place_existing.status_code == 302

with app.app_context():
    arr_existing_place = Arrangement.query.filter_by(
        target_user_id=target_0002_id, shift="honso", date=today_str
    ).first()
    assert arr_existing_place is not None
    assert arr_existing_place.place == "豊田会館"
    assert arr_existing_place.other_place is None
    arr_existing_place_id = arr_existing_place.id

# 一覧画面の会館名列に反映されていること
r_manage_after_existing_place = client_arranger.get("/arrangement_manage", follow_redirects=False)
assert "豊田会館".encode("utf-8") in r_manage_after_existing_place.data

# 対象ユーザー(0002)本人の「本日の手配書」画面にも会館名が表示されること
r_today_0002_place = client_0002_arrangement.get("/today_arrangement", follow_redirects=False)
assert "会館名：豊田会館".encode("utf-8") in r_today_0002_place.data

# 「その他」を選択し、手入力の会館名(other_place)を指定して更新する
# （同じ対象ユーザー・本葬・本日なので、新規作成ではなく上書きになる）
r_arr_place_other = client_arranger.post(
    "/arrangement_manage",
    data={
        "target_user_id": str(target_0002_id),
        "shift": "honso",
        "date": today_str,
        "memo": "会館名テスト（その他を選択）",
        "place": "その他",
        "other_place": "臨時会場（公民館）",
    },
    follow_redirects=False,
)
print("POST /arrangement_manage (会館名=その他, 0002宛て・本葬) ->", r_arr_place_other.status_code)
assert r_arr_place_other.status_code == 302

with app.app_context():
    arr_other_place = db.session.get(Arrangement, arr_existing_place_id)
    assert arr_other_place.place == "その他"
    assert arr_other_place.other_place == "臨時会場（公民館）"

r_manage_after_other_place = client_arranger.get("/arrangement_manage", follow_redirects=False)
assert "臨時会場（公民館）".encode("utf-8") in r_manage_after_other_place.data

r_today_0002_other_place = client_0002_arrangement.get("/today_arrangement", follow_redirects=False)
assert "会館名：臨時会場（公民館）".encode("utf-8") in r_today_0002_other_place.data

# 会館名を選ばず(「未定」のまま)登録した場合は、一覧に「未定」と表示され、
# 「本日の手配書」画面には会館名の行自体が表示されないこと
with app.app_context():
    target_0003_undecided = User.query.filter_by(number="0003").first()
    target_0003_undecided_id = target_0003_undecided.id

r_arr_place_undecided = client_arranger.post(
    "/arrangement_manage",
    data={
        "target_user_id": str(target_0003_undecided_id),
        "shift": "tsuya",
        "date": today_str,
        "memo": "会館名テスト（未定のまま）",
    },
    follow_redirects=False,
)
print("POST /arrangement_manage (会館名未指定, 0003宛て・通夜) ->", r_arr_place_undecided.status_code)
assert r_arr_place_undecided.status_code == 302

with app.app_context():
    arr_undecided = Arrangement.query.filter_by(
        target_user_id=target_0003_undecided_id, shift="tsuya", date=today_str
    ).first()
    assert arr_undecided is not None
    assert arr_undecided.place is None
    assert arr_undecided.other_place is None

r_manage_after_undecided = client_arranger.get("/arrangement_manage", follow_redirects=False)
assert "未定".encode("utf-8") in r_manage_after_undecided.data

client_0003_place = app.test_client()
client_0003_place.post("/login", data={"login": "ログイン", "number": "0003", "password": "demo3456"})
r_today_0003_undecided = client_0003_place.get("/today_arrangement", follow_redirects=False)
assert "会館名テスト（未定のまま）".encode("utf-8") in r_today_0003_undecided.data
assert "会館名：".encode("utf-8") not in r_today_0003_undecided.data

# --- [追加] 手配者が選択した会館名が、Time.place1/place2にも反映され、
#     対象ユーザー本人の出退勤画面(honso_stamp/tsuya_stamp)にも
#     表示されることの確認（「手配者がユーザーの代理で会館名を
#     設定する」機能）---

# 会館名がTime側にまだ何も無い、全くの新規ユーザーで確認する
with app.app_context():
    if not User.query.filter_by(number="8005").first():
        db.session.add(User(username="テスト五郎", number="8005",
                             password=generate_password_hash("test4567"), is_admin=False))
        db.session.commit()
    target_8005 = User.query.filter_by(number="8005").first()
    target_8005_id = target_8005.id
    # このユーザーにはまだTimeレコードが1件も無いことを前提にする
    assert Time.query.filter_by(number="8005").first() is None

# 8005用の会館名を1件登録しておく（既存の「会館名の登録」機能を利用）
client_arranger.post(
    "/arrangement_manage",
    data={"form_type": "place", "place_target_user_id": str(target_8005_id), "place_name": "五郎会館"},
    follow_redirects=False,
)

# 手配者が、8005・本葬・本日の手配書に「五郎会館」を選んで登録する
# （画像・メモは無しでもよいはずだが、既存のバリデーションに合わせて
# メモを入れておく）
r_arr_new_time = client_arranger.post(
    "/arrangement_manage",
    data={
        "target_user_id": str(target_8005_id),
        "shift": "honso",
        "date": today_str,
        "memo": "事前に会館名だけ設定するテスト",
        "place": "五郎会館",
    },
    follow_redirects=False,
)
print("POST /arrangement_manage (会館名=五郎会館, 8005宛て・本葬・新規Time) ->", r_arr_new_time.status_code)
assert r_arr_new_time.status_code == 302

# Timeレコードが新規作成され、place1に反映されていること
# （start1はまだ本人が打刻していないのでNoneのまま）
with app.app_context():
    time_8005 = Time.query.filter_by(number="8005", date=today_str).first()
    assert time_8005 is not None
    assert time_8005.place1 == "五郎会館"
    assert time_8005.other1 == ""
    assert time_8005.start1 is None
    time_8005_id = time_8005.id

# 対象ユーザー(8005)本人が出勤入力画面を開くと、会館名が既に選択された
# 状態で表示され、リダイレクトされない（＝出勤入力自体は引き続き
# 行える）こと
client_8005 = app.test_client()
client_8005.post("/login", data={"login": "ログイン", "number": "8005", "password": "test4567"})
r_honso_8005_preset = client_8005.get("/honso_stamp", follow_redirects=False)
print("GET /honso_stamp (8005, 手配者設定済みの会館名確認) ->", r_honso_8005_preset.status_code)
assert r_honso_8005_preset.status_code == 200
assert "selected>五郎会館</option>".encode("utf-8") in r_honso_8005_preset.data
# [追加] 会館名欄が変更不可（<select>にdisabled、hidden inputで値を維持）に
# なっており、注意書きも表示されていること
assert '<select id="place1" name="place1" required disabled>'.encode("utf-8") in r_honso_8005_preset.data
assert '<input type="hidden" name="place1" value="五郎会館">'.encode("utf-8") in r_honso_8005_preset.data
assert "会館名は手配者が設定済みのため、変更できません".encode("utf-8") in r_honso_8005_preset.data

# 8005本人が実際に出勤打刻する（会館名は手配者が設定した値のまま）。
# 以前はここで新規にTime行を作ろうとして一意制約に抵触し、
# 出勤時刻が保存されないままIntegrityErrorでもみ消されていたが、
# 既存行を更新するよう修正済みなので、正しく保存されるはず。
r_honso_8005_clockin = client_8005.post(
    "/honso_stamp",
    data={"place1": "五郎会館", "start1": "09:00"},
    follow_redirects=False,
)
print("POST /honso_stamp (8005, 手配者設定済みの会館名のまま出勤) ->", r_honso_8005_clockin.status_code)
assert r_honso_8005_clockin.status_code == 302

with app.app_context():
    time_8005_after_clockin = db.session.get(Time, time_8005_id)
    assert time_8005_after_clockin is not None
    assert time_8005_after_clockin.place1 == "五郎会館"
    assert time_8005_after_clockin.start1 == "09:00"
    # 新しい行が作られたのではなく、手配者が作った行がそのまま
    # 更新されたこと（＝id が変わっていないこと）を確認
    assert Time.query.filter_by(number="8005", date=today_str).count() == 1

# 手配者が後から別の会館名に変更すると、同じTime行が上書きされること
# （新しい行が増えるわけではない）
r_arr_change_place = client_arranger.post(
    "/arrangement_manage",
    data={
        "target_user_id": str(target_8005_id),
        "shift": "honso",
        "date": today_str,
        "memo": "会館名を変更するテスト",
        "place": "その他",
        "other_place": "変更後の会場",
    },
    follow_redirects=False,
)
assert r_arr_change_place.status_code == 302
with app.app_context():
    time_8005_after_change = db.session.get(Time, time_8005_id)
    assert time_8005_after_change.place1 == "その他"
    assert time_8005_after_change.other1 == "変更後の会場"
    assert time_8005_after_change.start1 == "09:00"  # 既存の打刻データは維持される
    assert Time.query.filter_by(number="8005", date=today_str).count() == 1

# 会館名を選ばず(「未定」のまま)手配書のメモだけ更新した場合は、
# 既にTimeに入っている会館名を誤って消さないこと
r_arr_no_change = client_arranger.post(
    "/arrangement_manage",
    data={
        "target_user_id": str(target_8005_id),
        "shift": "honso",
        "date": today_str,
        "memo": "会館名は変更しない・メモだけ更新するテスト",
    },
    follow_redirects=False,
)
assert r_arr_no_change.status_code == 302
with app.app_context():
    time_8005_after_noop = db.session.get(Time, time_8005_id)
    assert time_8005_after_noop.place1 == "その他"
    assert time_8005_after_noop.other1 == "変更後の会場"

# --- [追加] 勤怠一覧画面(/attendance_list)の「支給額」に、会館名に応じた
#     交通費(Place.transportation_fee)の合計が反映されることの確認 ---

with app.app_context():
    if not User.query.filter_by(number="8006").first():
        db.session.add(User(username="テスト六郎", number="8006",
                             password=generate_password_hash("test5678"), is_admin=False,
                             honso_wage=1000, tsuya_wage=900))
        db.session.commit()
    target_8006 = User.query.filter_by(number="8006").first()
    target_8006_id = target_8006.id

# 8006用に、交通費ありの会館(本葬用700円・通夜用300円)と、交通費未設定
# （0円のまま）の会館を1件ずつ登録しておく
client_arranger.post(
    "/arrangement_manage",
    data={
        "form_type": "place", "place_target_user_id": str(target_8006_id),
        "place_name": "六郎会館（本葬）", "transportation_fee": "700",
    },
    follow_redirects=False,
)
client_arranger.post(
    "/arrangement_manage",
    data={
        "form_type": "place", "place_target_user_id": str(target_8006_id),
        "place_name": "六郎会館（通夜）", "transportation_fee": "300",
    },
    follow_redirects=False,
)

client_8006 = app.test_client()
client_8006.post("/login", data={"login": "ログイン", "number": "8006", "password": "test5678"})

# 本葬：交通費が登録された会館で、出退勤とも入力（実働時間が計算できる状態）
client_8006.post("/honso_stamp", data={"place1": "六郎会館（本葬）", "start1": "09:00"})
client_8006.post("/honso_modify", data={"end1": "18:00"})

# 通夜：交通費が登録された別の会館で、出退勤とも入力
client_8006.post("/tsuya_stamp", data={"place2": "六郎会館（通夜）", "start2": "19:00"})
client_8006.post("/tsuya_modify", data={"end2": "21:00"})

r_attendance_8006 = client_8006.get("/attendance_list", follow_redirects=False)
print("GET /attendance_list (8006, 会館名に応じた交通費の合計確認) ->", r_attendance_8006.status_code)
assert r_attendance_8006.status_code == 200
# 本葬支給額: 1000円 x 9時間 = 9,000円 / 通夜支給額: 900円 x 2時間 = 1,800円
assert "9,000円".encode("utf-8") in r_attendance_8006.data
assert "1,800円".encode("utf-8") in r_attendance_8006.data
# 交通費合計: 700円 + 300円 = 1,000円
assert "交通費".encode("utf-8") in r_attendance_8006.data
assert "1,000円".encode("utf-8") in r_attendance_8006.data
# 支給額合計（本葬9,000円 + 通夜1,800円 + 交通費1,000円）= 11,800円
assert "支給額合計".encode("utf-8") in r_attendance_8006.data
assert "11,800円".encode("utf-8") in r_attendance_8006.data

# 「その他」（手入力の会館名、Placeに未登録）を選んで出退勤した日は、
# 交通費が0円として扱われる（エラーにならず、合計に加算されない）ことを確認
with app.app_context():
    # 前日の日付で、交通費対象外の記録を1件作っておく
    yesterday_str = (today - datetime.timedelta(days=1)).isoformat()
    db.session.add(Time(
        date=yesterday_str, number="8006",
        place1="その他", other1="8006手入力の会場", start1="10:00", end1="15:00",
    ))
    db.session.commit()

r_attendance_8006_after = client_8006.get("/attendance_list", follow_redirects=False)
print("GET /attendance_list (8006, その他会場は交通費0円のまま) ->", r_attendance_8006_after.status_code)
assert r_attendance_8006_after.status_code == 200
# 前日分の本葬支給額(1000円 x 5時間 = 5,000円)が加算されても、
# 交通費の合計は引き続き1,000円のまま（「その他」分は加算されない）
assert "1,000円".encode("utf-8") in r_attendance_8006_after.data

# --- [追加] 「手当」欄（休憩以外：リーダー・サブリーダー・研修・待機・
#     指定日・遠方地・特別手当・高速道路）を、手配書登録画面
#     (/arrangement_manage)で金額まで指定して設定できるようにし、
#     金額が設定された項目だけが出退勤画面(honso_stamp/honso_modify)の
#     休憩欄の下に読み取り専用で表示されることの確認 ---

with app.app_context():
    if not User.query.filter_by(number="8007").first():
        db.session.add(User(username="テスト七郎", number="8007",
                             password=generate_password_hash("test6789"), is_admin=False))
        db.session.commit()
    target_8007 = User.query.filter_by(number="8007").first()
    target_8007_id = target_8007.id

# 8007用の会館を1件登録しておく（この手配書で会館名も同時に設定する）
client_arranger.post(
    "/arrangement_manage",
    data={
        "form_type": "place", "place_target_user_id": str(target_8007_id),
        "place_name": "七郎会館",
    },
    follow_redirects=False,
)

# 手配者が、8007・本葬・本日の手配書に、会館名とあわせて「手当」の
# リーダー(500円)・高速道路(1000円)だけをチェックして登録する
# （サブリーダー等は未チェックのまま＝金額を送らない）。
r_arr_allowance_1 = client_arranger.post(
    "/arrangement_manage",
    data={
        "target_user_id": str(target_8007_id),
        "shift": "honso",
        "date": today_str,
        "memo": "手当のテスト（1回目）",
        "place": "七郎会館",
        "leader_amount": "500",
        "highway_amount": "1000",
    },
    follow_redirects=False,
)
print("POST /arrangement_manage (8007宛て・本葬・リーダー500円+高速道路1000円) ->", r_arr_allowance_1.status_code)
assert r_arr_allowance_1.status_code == 302

with app.app_context():
    arrangement_8007 = Arrangement.query.filter_by(
        target_user_id=target_8007_id, shift="honso", date=today_str
    ).first()
    assert arrangement_8007 is not None
    assert arrangement_8007.leader_amount == 500
    assert arrangement_8007.highway_amount == 1000
    assert arrangement_8007.subleader_amount is None
    assert arrangement_8007.special_amount is None

    time_8007 = Time.query.filter_by(number="8007", date=today_str).first()
    assert time_8007 is not None
    assert time_8007.place1 == "七郎会館"
    assert time_8007.leader_amount1 == 500
    assert time_8007.highway1 == "on"
    assert time_8007.express1 == "1000"
    assert time_8007.subleader_amount1 is None
    assert time_8007.special_amount1 is None
    time_8007_id = time_8007.id

# 手配書登録画面の一覧にも、金額が設定された項目だけが表示されること
r_manage_allowance = client_arranger.get("/arrangement_manage", follow_redirects=False)
assert "リーダー：500円".encode("utf-8") in r_manage_allowance.data
assert "高速道路：1,000円".encode("utf-8") in r_manage_allowance.data
assert "サブリーダー：".encode("utf-8") not in r_manage_allowance.data

# 対象ユーザー(8007)本人が出勤入力画面を開くと、会館名は手配者設定済みで
# 選び直せず、「手当」は金額が設定された項目（リーダー・高速道路）だけが
# 休憩欄の下に読み取り専用で表示されること。チェックボックス自体は
# もう表示されない（手配書登録画面に機能が移動したため）。
client_8007 = app.test_client()
client_8007.post("/login", data={"login": "ログイン", "number": "8007", "password": "test6789"})
r_honso_8007_preset = client_8007.get("/honso_stamp", follow_redirects=False)
print("GET /honso_stamp (8007, 手配者設定済みの手当の確認) ->", r_honso_8007_preset.status_code)
assert r_honso_8007_preset.status_code == 200
assert "リーダー：500円".encode("utf-8") in r_honso_8007_preset.data
assert "高速道路：1,000円".encode("utf-8") in r_honso_8007_preset.data
# [追加] 金額が設定されていない項目（サブリーダー・研修など）は、
# 読み取り専用表示（"項目名：金額円"の形式）としては出てこないこと。
# （HTMLコメント中に項目名そのものは残るため、完全一致の"サブリーダー："
# のような表示用文字列で判定する。）
assert "サブリーダー：".encode("utf-8") not in r_honso_8007_preset.data
assert "研修：".encode("utf-8") not in r_honso_8007_preset.data
# [追加] 旧チェックボックス（leader1・highway1・express1等）が、この画面
# からは完全に無くなっている（手配書登録画面に機能が移動した）ことの確認。
assert 'id="leader1"'.encode("utf-8") not in r_honso_8007_preset.data
assert 'id="highway1"'.encode("utf-8") not in r_honso_8007_preset.data
assert 'name="express1"'.encode("utf-8") not in r_honso_8007_preset.data

# 実際に出勤打刻しても、リーダー・高速道路の金額はそのまま維持される
# （honso_stamp()側はこれらのカラムに一切触れないため）。
r_honso_8007_clockin = client_8007.post(
    "/honso_stamp",
    data={"place1": "七郎会館", "start1": "09:00"},
    follow_redirects=False,
)
assert r_honso_8007_clockin.status_code == 302

with app.app_context():
    time_8007_after_clockin = db.session.get(Time, time_8007_id)
    assert time_8007_after_clockin.start1 == "09:00"
    assert time_8007_after_clockin.leader_amount1 == 500
    assert time_8007_after_clockin.express1 == "1000"
    assert Time.query.filter_by(number="8007", date=today_str).count() == 1

# 出勤済み・退勤前の退勤入力画面(honso_modify)でも、同じ内容が読み取り
# 専用で表示され続けること。
r_honso_modify_8007 = client_8007.get("/honso_modify", follow_redirects=False)
print("GET /honso_modify (8007, 手当の表示確認) ->", r_honso_modify_8007.status_code)
assert r_honso_modify_8007.status_code == 200
assert "リーダー：500円".encode("utf-8") in r_honso_modify_8007.data
assert "高速道路：1,000円".encode("utf-8") in r_honso_modify_8007.data
assert 'id="leader1"'.encode("utf-8") not in r_honso_modify_8007.data

# 退勤打刻後も金額はそのまま保持される
r_honso_modify_8007_post = client_8007.post(
    "/honso_modify", data={"end1": "18:00"}, follow_redirects=False,
)
assert r_honso_modify_8007_post.status_code == 302
with app.app_context():
    time_8007_after_end = db.session.get(Time, time_8007_id)
    assert time_8007_after_end.end1 == "18:00"
    assert time_8007_after_end.leader_amount1 == 500
    assert time_8007_after_end.express1 == "1000"

# 手配者が同じ(8007・本葬・本日)の手配書を再度更新し、今度は特別手当だけを
# チェックしてリーダー・高速道路はチェックしなかった場合：
# ・手配書自体(Arrangement)は毎回全体を上書きするので、リーダー・高速道路は
#   Noneに戻る。
# ・Timeレコードは「今回チェックされた項目だけ」を反映するので、特別手当が
#   新たに反映されつつ、既にTimeへ反映済みのリーダー・高速道路の金額は
#   そのまま維持される（フォームは毎回空の状態から入力する仕組みのため、
#   前回チェックした項目をうっかり消してしまわないようにするための設計）。
r_arr_allowance_2 = client_arranger.post(
    "/arrangement_manage",
    data={
        "target_user_id": str(target_8007_id),
        "shift": "honso",
        "date": today_str,
        "memo": "手当のテスト（2回目・特別手当のみ）",
        "place": "七郎会館",
        "special_amount": "300",
    },
    follow_redirects=False,
)
assert r_arr_allowance_2.status_code == 302

with app.app_context():
    arrangement_8007_after = Arrangement.query.filter_by(
        target_user_id=target_8007_id, shift="honso", date=today_str
    ).first()
    assert arrangement_8007_after.special_amount == 300
    assert arrangement_8007_after.leader_amount is None
    assert arrangement_8007_after.highway_amount is None

    time_8007_after_update = db.session.get(Time, time_8007_id)
    assert time_8007_after_update.special_amount1 == 300
    assert time_8007_after_update.leader_amount1 == 500
    assert time_8007_after_update.express1 == "1000"

# マイナスの金額（不正な入力）は、Arrangement・Timeのどちらにも反映されず
# 未設定(None)のまま扱われることの確認（通夜側でテスト）。
r_arr_allowance_negative = client_arranger.post(
    "/arrangement_manage",
    data={
        "target_user_id": str(target_8007_id),
        "shift": "tsuya",
        "date": today_str,
        "memo": "マイナス金額のテスト",
        "wait_amount": "-50",
    },
    follow_redirects=False,
)
assert r_arr_allowance_negative.status_code == 302
with app.app_context():
    arrangement_8007_tsuya = Arrangement.query.filter_by(
        target_user_id=target_8007_id, shift="tsuya", date=today_str
    ).first()
    assert arrangement_8007_tsuya is not None
    assert arrangement_8007_tsuya.wait_amount is None

    # 本葬側と同じ(number, date)の行なので、同じTimeレコードのはず
    time_8007_tsuya = Time.query.filter_by(number="8007", date=today_str).first()
    assert time_8007_tsuya.id == time_8007_id
    assert time_8007_tsuya.wait_amount2 is None

# --- [追加] 勤怠一覧画面(/attendance_list)の支給額に、「手当」（リーダー・
#     高速道路・特別手当等）の月合計が、交通費の下に表示されることの確認 ---
r_attendance_8007 = client_8007.get("/attendance_list", follow_redirects=False)
print("GET /attendance_list (8007, 手当の月合計確認) ->", r_attendance_8007.status_code)
assert r_attendance_8007.status_code == 200
# リーダー500円・高速道路1,000円・特別手当300円が、それぞれ項目名と
# 金額付きで表示されること
assert "リーダー".encode("utf-8") in r_attendance_8007.data
assert "500円".encode("utf-8") in r_attendance_8007.data
assert "高速道路".encode("utf-8") in r_attendance_8007.data
assert "1,000円".encode("utf-8") in r_attendance_8007.data
assert "特別手当".encode("utf-8") in r_attendance_8007.data
assert "300円".encode("utf-8") in r_attendance_8007.data
# 金額が設定されていない項目（サブリーダー等）は表示されない
assert "サブリーダー".encode("utf-8") not in r_attendance_8007.data
# 支給額合計に、手当の月合計(500+1000+300=1,800円)も含まれること
# （8007は時給未設定のため本葬・通夜の支給額は0円、七郎会館の交通費も0円）
assert "1,800円".encode("utf-8") in r_attendance_8007.data
assert "支給額合計".encode("utf-8") in r_attendance_8007.data

# --- [追加] 手配書登録画面で、保存(db.session.commit())に失敗した場合の
#     挙動の確認。
#     [修正前の不具合] 以前はDB保存に失敗しても画面には何も表示せず、
#     登録済み一覧画面へリダイレクトしていたため、「登録できたように
#     見えて実は一覧に増えない」という分かりにくい状態になっていた
#     （本番で実際に問い合わせを受けた不具合の原因のひとつ）。
#     修正後は、保存に失敗した場合はリダイレクトせず、エラーメッセージ
#     付きで登録画面を再表示することを確認する。
#     db.session.commit()が例外を投げるケースを、実際のDB制約違反を
#     再現する代わりにモックで再現する（一意制約違反はテスト用クライアント
#     から確実に再現するのが難しいため）。
with app.app_context():
    target_0003_for_fail = User.query.filter_by(number="0003").first()
    target_0003_fail_id = target_0003_for_fail.id
    # 失敗時にArrangementが実際には保存されていないことを確認するため、
    # テスト対象の(target_user, shift, date)の組み合わせがまだ無いことを確認
    assert Arrangement.query.filter_by(
        target_user_id=target_0003_fail_id, shift="honso", date=today_str
    ).first() is None

with mock.patch(
    "sqlalchemy.orm.Session.commit", side_effect=IntegrityError("stmt", {}, Exception("dup"))
):
    r_arr_commit_fail = client_arranger.post(
        "/arrangement_manage",
        data={
            "target_user_id": str(target_0003_fail_id),
            "shift": "honso",
            "date": today_str,
            "memo": "保存失敗時の挙動確認用",
        },
        follow_redirects=False,
    )
print("POST /arrangement_manage (保存失敗をモックで再現) ->", r_arr_commit_fail.status_code)
# リダイレクト(302)ではなく、登録画面がそのまま(200)再表示されること
assert r_arr_commit_fail.status_code == 200
# エラーメッセージが表示されること（無言で一覧に戻らない）
assert "同じ内容の手配書が別の手配者によってほぼ同時に登録された".encode("utf-8") in r_arr_commit_fail.data

with app.app_context():
    # 保存が失敗しているため、Arrangementは作成されていないこと
    assert Arrangement.query.filter_by(
        target_user_id=target_0003_fail_id, shift="honso", date=today_str
    ).first() is None

# モック解除後、同じ内容で通常通り登録できること（アプリ自体は壊れていないこと）の確認
r_arr_commit_retry = client_arranger.post(
    "/arrangement_manage",
    data={
        "target_user_id": str(target_0003_fail_id),
        "shift": "honso",
        "date": today_str,
        "memo": "保存失敗時の挙動確認用（再試行）",
    },
    follow_redirects=False,
)
print("POST /arrangement_manage (モック解除後の再試行) ->", r_arr_commit_retry.status_code)
assert r_arr_commit_retry.status_code == 302
with app.app_context():
    assert Arrangement.query.filter_by(
        target_user_id=target_0003_fail_id, shift="honso", date=today_str
    ).first() is not None

print("\nALL SMOKE TESTS PASSED")
