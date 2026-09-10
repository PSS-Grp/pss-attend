#from app import app
#from admin import admin.add_view

# attendance
# __init__

#### アプリの起動と各モジュールの集約 ####

from __init__ import app ,db ,login_manager ,get_today

from flask import Flask, request, render_template, redirect, flash, session 
from flask_login import login_required, login_user, current_user

from models import User, Time, Place
# from models import LoginForm, User ,
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError


#------------------------------------------------
# [追加] ログイン中のユーザーに紐づく会館名の一覧を取得するヘルパー。
# Place.user_id が current_user.id と一致する行、またはuser_idが
# 未設定（全ユーザー共通）の行を、登録順で返す。
# 「その他」は一覧には含めず、テンプレート側で常に末尾に固定表示する。
#------------------------------------------------
def get_places_for_current_user():
    return [
        p.place
        for p in Place.query.filter(
            (Place.user_id == current_user.id) | (Place.user_id.is_(None))
        )
        .order_by(Place.id)
        .all()
    ]

#------------------------------------------------
# DB 管理ページ  # データベース管理画面のモジュール(admin.py)の読み込み
#------------------------------------------------
from admin import admin


#------------------------------------------------
# デコレータを付与したload_user関数を定義
# 現在のログインユーザーの情報を保持し、必要なときに参照できるようになる。
#------------------------------------------------
@login_manager.user_loader
def load_user(id):                               # usersテーブルから指定のidを持つレコードを取り出す
    return User.query.get(int(id))               # flask-loginがこの関数に引数として渡すidの値は文字列であるため、数値に変換する


#------------------------------------------------
# 本葬選択後の表示ページ
#------------------------------------------------
@app.route('/honso_stamp', methods=["GET","POST"])
@login_required                                  #ログイン必須にしたい関数の前に記述する

def honso_stamp():

    number = session['user_number']              #sessionからユーザー情報を取得
    today = get_today()                          #[修正] 呼び出し都度、現在の日付を取得する

    # [追加] 本葬の退勤が既に入力済みの場合は、出勤入力フォームに
    # 直接アクセスされても打刻をやり直せないようにする
    # （ハブ画面(/judge)側でもボタン自体をグレーアウトして押せなくしている）。
    existing_record = Time.query.filter(Time.number==number, Time.date==today).first()
    if existing_record and existing_record.end1:
        return redirect('/judge')

    # [追加] 通夜の出勤時間が入力済みの場合は、本葬の勤務を新たに
    # 開始させないようにする（通夜の後に本葬の勤務をすることはないため、
    # 通夜の出勤時間が入力された時点で、退勤時間の入力有無に関わらず
    # 本葬は恒久的に利用不可にする）。
    if existing_record and existing_record.start2:
        return redirect('/judge')

    start1 = "--:--"
    end1 = "--:--"
    # [追加] 「手当」欄の先頭に追加した「休憩」チェックボックスと、
    # チェック時に入力する休憩時間（分）の初期値。
    break1=None
    break_minutes1=None
    leader1='off'
    subleader1=None
    teach1=None
    wait1=None
    designated1=None
    distant1=None
    special1=None
    highway1=None
    express1=None
    other1=None

    if request.method =='POST':                  # POSTがリクエストされた場合
       place1 = request.form.get('place1')       # place1をから入力値を取得
       start1 = request.form.get('start1')
       end1 = request.form.get('end1')
       break1 = request.form.get('break1')
       # [追加] 休憩時間（分）は数値として保存する。未入力・不正な値の
       # 場合はNoneのまま（＝休憩なし扱い）にする。
       break_minutes1_raw = request.form.get('break_minutes1')
       try:
          break_minutes1 = int(break_minutes1_raw) if break_minutes1_raw else None
       except ValueError:
          break_minutes1 = None
       leader1 = request.form.get('leader1')
       subleader1 = request.form.get('subleader1')
       teach1 = request.form.get('teach1')
       wait1 = request.form.get('wait1')
       designated1 = request.form.get('designated1')
       distant1 = request.form.get('distant1')
       special1 = request.form.get('special1')
       highway1 = request.form.get('highway1')
       express1 = request.form.get('express1')
       other1 = request.form.get('other1')

       time = Time()                             # Timeテーブルに追加することを指定
       time.date=today
       time.number=session['user_number']
       time.place1=place1
       time.start1=start1
       time.end1=end1
       time.break1=break1
       time.break_minutes1=break_minutes1
       time.leader1=leader1
       time.subleader1=subleader1
       time.teach1=teach1
       time.wait1=wait1
       time.designated1=designated1
       time.distant1=distant1
       time.special1=special1
       time.highway1=highway1
       time.express1=express1
       time.other1=other1
       db.session.add(time)                      # 入力値をTimeテーブルに追加
       try:
          db.session.commit()
       except IntegrityError:
          # [追加] Time(number, date)にはDBの一意制約があり（models.py参照）、
          # 同じユーザー・同じ日のレコードは1件しか作れない。フォームの
          # 二重送信（連打）などでこの関数が同時に2回実行された場合、
          # 片方はここでエラーになるが、既に本葬の出勤記録自体は保存
          # されているはずなので、エラー画面ではなく通常通り/judgeの
          # ハブ画面に戻す。
          db.session.rollback()
          return redirect('/judge')


       if not end1:
          end1 = "--:--"
       else:
          end1 = end1

       if not other1:
          other1 = ""
       else:
          other1 = other1

       # [修正] 従来は登録後に読み取り専用の確認画面(honso_init.html)へ
       # 遷移して行き止まりになっていたが、本葬・通夜の状態が一目でわかる
       # /judge のハブ画面に戻るようにした（退勤入力もここから行える）。
       return redirect('/judge')

    return render_template('honso_stamp.html',
                            title="本葬出勤入力",
                            today=today,
                            places=get_places_for_current_user(),
                            start1=start1,
                            end1=end1,
                            break1=break1,
                            break_minutes1=break_minutes1,
                            leader1=leader1,
                            subleader1=subleader1, 
                            teach1=teach1, 
                            wait1=wait1, 
                            designated1=designated1, 
                            distant1=distant1, 
                            special1=special1, 
                            highway1=highway1, 
                            express1=express1, 
                            other1=other1)  # パラメータをexit_view.htmlに送る

#------------------------------------------------
# 編集ページ
#------------------------------------------------
@app.route('/honso_modify', methods=["GET","POST"])
@login_required                                  #ログイン必須にしたい関数の前に記述する

def honso_modify():

    number = session['user_number']              #sessionからユーザー情報をとってくる
    today = get_today()                          #[修正] 呼び出し都度、現在の日付を取得する

    # [修正] 以前はセッションに保存されていた record_id や place1/start1など
    # の値を無条件に信用していたが、別のユーザーが同じブラウザで先に
    # ログインしていた場合などにセッションの値が古い・別人のものになって
    # いることがあり、誤って他人のレコードを更新してしまう不具合があった。
    # 常に number（現在ログイン中のユーザー）と today（本日日付）でDBを
    # 検索し直し、そのレコードだけを対象にするよう修正した。
    record = Time.query.filter(Time.number == number, Time.date == today).first()

    if not record or not record.start1:
        # 本葬がまだ出勤打刻されていない場合は、この画面を表示する意味が無い
        return redirect('/judge')

    # [追加] 退勤が既に入力済みの場合は編集させない
    # （ハブ画面(/judge)側でもボタン自体をグレーアウトして押せなくしている）。
    if record.end1:
        return redirect('/judge')

    record_id = record.id
    place1 = record.place1 if record.place1 else "未入力"
    start1 = record.start1
    end1 = "--:--"
    # [追加] 「休憩」チェックボックスと休憩時間（分）の初期表示値。
    break1 = "checked" if record.break1 else "off"
    break_minutes1 = record.break_minutes1 if record.break_minutes1 else ""
    leader1 = "checked" if record.leader1 else "off"
    subleader1 = "checked" if record.subleader1 else "off"
    teach1 = "checked" if record.teach1 else "off"
    wait1 = "checked" if record.wait1 else "off"
    designated1 = "checked" if record.designated1 else "off"
    distant1 = "checked" if record.distant1 else "off"
    special1 = "checked" if record.special1 else "off"
    highway1 = "checked" if record.highway1 else "off"
    express1 = record.express1 if record.express1 else "-,---"
    other1 = record.other1 if record.other1 else ""

    print("セッションゲット",express1)

    if request.method == 'POST':                  # リクエストがPOSTの場合

       end1 = request.form.get('end1')
       break1 = request.form.get('break1')
       # [追加] 休憩時間（分）を数値として保存する。未入力・不正な値の
       # 場合はNoneのまま（＝休憩なし扱い）にする。
       break_minutes1_raw = request.form.get('break_minutes1')
       try:
          break_minutes1 = int(break_minutes1_raw) if break_minutes1_raw else None
       except ValueError:
          break_minutes1 = None
       leader1 = request.form.get('leader1')
       subleader1 = request.form.get('subleader1')
       teach1 = request.form.get('teach1')
       wait1 = request.form.get('wait1')
       designated1 = request.form.get('designated1')
       distant1 = request.form.get('distant1')
       special1 = request.form.get('special1')
       highway1 = request.form.get('highway1')
#       express1 = request.form.get('express1')

       if express1 == "-,---":
          express1 = request.form.get('express1')
       else:
          express1 = express1

       other1 = request.form.get('other1')

       print("入力ゲット",express1)

       # [修正] session['record_id'] 経由の再検索ではなく、関数の先頭で
       # number・today から検索し直した record（＝このユーザーの今日の
       # レコード）をそのまま更新する。
       modify_record = record
       modify_record.date=today
       modify_record.number=number
       modify_record.end1=end1
       modify_record.break1=break1
       modify_record.break_minutes1=break_minutes1
       modify_record.leader1=leader1
       modify_record.subleader1=subleader1
       modify_record.teach1=teach1
       modify_record.wait1=wait1
       modify_record.designated1=designated1
       modify_record.distant1=distant1
       modify_record.special1=special1
       modify_record.highway1=highway1
       modify_record.express1=express1
       modify_record.other1=other1
       db.session.commit()

       print("DB更新",express1)

       # [修正] 更新後は読み取り専用の確認画面(honso_init.html)ではなく、
       # 本葬・通夜の状態が一目でわかる /judge のハブ画面に戻るようにした。
       return redirect('/judge')

    # [修正] GETの場合は編集用フォーム(honso_modify.html)をそのまま表示する。
    # 以前はexit_view()のPOSTを経由しないとこの画面に到達できなかった。
    return render_template('honso_modify.html',
                            title="本葬退勤入力",
                            record_id=record_id,
                            today=today,
                            place1=place1,
                            start1=start1,
                            end1=end1,
                            break1=break1,
                            break_minutes1=break_minutes1,
                            other1=other1,
                            leader1=leader1,
                            subleader1=subleader1,
                            teach1=teach1,
                            wait1=wait1,
                            designated1=designated1,
                            distant1=distant1,
                            special1=special1,
                            highway1=highway1,
                            express1=express1)

