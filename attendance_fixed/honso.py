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
# [追加] 出退勤画面の「登録」ボタンが押されたときにメール通知するための
# モジュール（notifications.py参照）。
from notifications import send_attendance_notification
# [追加] 「手当」欄（休憩以外）は手配者が手配書登録画面で設定するように
# なったため、出退勤画面では金額が設定されている項目だけを読み取り専用で
# 表示する（allowances.py参照）。
from allowances import allowance_display_items


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
    # [修正] 「手当」欄の休憩以外の項目(リーダー・サブリーダー・研修・
    # 待機・指定日・遠方地・特別手当・高速道路)は、手配者が手配書登録
    # 画面(/arrangement_manage)で金額まで指定して設定する方式に変更した
    # ため、この画面ではチェックボックスとしては扱わず、既にTimeレコード
    # に反映されている金額を読み取り専用で表示するだけにする
    # （allowance_display_items参照）。
    allowance_items = allowance_display_items(existing_record, "honso")
    # [修正] 手配者が「手配書登録」画面(/arrangement_manage)で、この
    # ユーザー・本葬・本日の会館名を事前に選択していた場合、その値が
    # 既にTime.place1/other1に反映されている（arrangement.py参照）。
    # その場合は出勤入力フォームの会館名欄に、その値を初めから
    # 選択された状態で表示する（手配者がユーザーの代理で会館名を
    # 設定したことがそのまま画面に反映されるようにするため）。
    # [追加] さらに、その場合は本人が会館名を選び直せないよう、
    # 会館名欄を変更不可（読み取り専用）にする。place_locked=Trueの
    # 間、テンプレート側で<select>にdisabledを付け、送信用にhidden
    # inputで値を維持する。
    place1 = existing_record.place1 if existing_record else None
    other1 = existing_record.other1 if existing_record else None
    place_locked = bool(place1)

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
       other1 = request.form.get('other1')

       # [修正] 以前は常に新しいTime()行を作って追加していたが、これだと
       # 手配者が「手配書登録」画面で先にこのユーザー・本葬・本日の
       # 会館名を設定していた場合（Time.place1だけが入った行が既に
       # 存在する場合）、ここで新規行を作ろうとしてTime(number, date)の
       # 一意制約に抵触し、下のIntegrityError処理で本葬の出勤打刻
       # そのものが保存されずに/judgeへ戻ってしまっていた。
       # tsuya_stamp()と同様に、その日の行が既にあれば新規作成ではなく
       # その行を更新するようにした。
       if existing_record:
          time = existing_record
       else:
          time = Time()                          # Timeテーブルに追加することを指定
          time.date=today
          time.number=session['user_number']
       time.place1=place1
       time.start1=start1
       time.end1=end1
       time.break1=break1
       time.break_minutes1=break_minutes1
       time.other1=other1
       if not existing_record:
          db.session.add(time)                   # 入力値をTimeテーブルに追加
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

       # [追加] 登録ボタンが押されたことをメールで通知する。出勤のみ入力
       # された場合は【出勤】、（このフォームで同時に）退勤時間まで
       # 入力された場合は【退勤】の件名になる（notifications.py参照）。
       # 送信に失敗しても、ここまでの出勤打刻自体は既に保存済みなので
       # 処理は続行する。
       send_attendance_notification(
           shift_label="本葬",
           user_name=current_user.username,
           number=session['user_number'],
           place=place1,
           other=other1,
           start=start1,
           end=end1,
           break_flag=break1,
           break_minutes=break_minutes1,
       )

       # [修正] 従来は登録後に読み取り専用の確認画面(honso_init.html)へ
       # 遷移して行き止まりになっていたが、本葬・通夜の状態が一目でわかる
       # /judge のハブ画面に戻るようにした（退勤入力もここから行える）。
       return redirect('/judge')

    return render_template('honso_stamp.html',
                            title="本葬出勤入力",
                            today=today,
                            places=get_places_for_current_user(),
                            place1=place1,
                            place_locked=place_locked,
                            start1=start1,
                            end1=end1,
                            break1=break1,
                            break_minutes1=break_minutes1,
                            allowance_items=allowance_items,
                            other1=other1)

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
    # [追加] 通知メール用に、出勤時に登録された会館名(place1/other1)を
    # そのまま保持しておく。下のPOST処理でplace1変数は「未入力」表示用に
    # 上書きされ、other1変数もフォームに入力欄が無いため送信のたびに
    # 空になってしまう（このモジュール内の既知の挙動）ため、メールには
    # ここで確保した値を使う。
    notify_place1 = record.place1
    notify_other1 = record.other1
    place1 = record.place1 if record.place1 else "未入力"
    start1 = record.start1
    end1 = "--:--"
    # [追加] 「休憩」チェックボックスと休憩時間（分）の初期表示値。
    break1 = "checked" if record.break1 else "off"
    break_minutes1 = record.break_minutes1 if record.break_minutes1 else ""
    other1 = record.other1 if record.other1 else ""
    # [修正] 「手当」欄の休憩以外の項目は手配者が手配書登録画面で設定する
    # ようになったため、この画面ではチェックボックスとしては扱わず、
    # 既にTimeレコードに反映されている金額を読み取り専用で表示する。
    allowance_items = allowance_display_items(record, "honso")

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
       other1 = request.form.get('other1')

       # [修正] session['record_id'] 経由の再検索ではなく、関数の先頭で
       # number・today から検索し直した record（＝このユーザーの今日の
       # レコード）をそのまま更新する。
       modify_record = record
       modify_record.date=today
       modify_record.number=number
       modify_record.end1=end1
       modify_record.break1=break1
       modify_record.break_minutes1=break_minutes1
       modify_record.other1=other1
       db.session.commit()

       # [追加] 登録（退勤）ボタンが押されたことをメールで通知する。
       # 退勤時間が入力されているため、件名は【退勤】になる。
       send_attendance_notification(
           shift_label="本葬",
           user_name=current_user.username,
           number=number,
           place=notify_place1,
           other=notify_other1,
           start=start1,
           end=end1,
           break_flag=break1,
           break_minutes=break_minutes1,
       )

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
                            allowance_items=allowance_items)

