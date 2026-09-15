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
# honso.py 側と同じロジック（重複しているが、既存ファイル構成を
# 大きく変えないよう、あえてそれぞれのファイルに置いている）。
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
# 通夜選択後の表示ページ
#------------------------------------------------
@app.route('/tsuya_stamp', methods=["GET","POST"])
@login_required                                  #ログイン必須にしたい関数の前に記述する

def tsuya_stamp():

    number = session['user_number']              #sessionからユーザー情報を取得
    today = get_today()                          #[修正] 呼び出し都度、現在の日付を取得する

    # [追加] 通夜の退勤が既に入力済みの場合は、出勤入力フォームに
    # 直接アクセスされても打刻をやり直せないようにする
    # （ハブ画面(/judge)側でもボタン自体をグレーアウトして押せなくしている）。
    existing_record = Time.query.filter(Time.number==number, Time.date==today).first()
    if existing_record and existing_record.end2:
        return redirect('/judge')

    # [追加] 本葬の出勤時間が入力済みで、まだ退勤時間が入力されていない
    # （＝本葬が出勤中の）間は、通夜の出勤入力に直接アクセスされても
    # 受け付けないようにする（ハブ画面側でもボタンをグレーアウトしている）。
    if existing_record and existing_record.start1 and not existing_record.end1:
        return redirect('/judge')

    start2 = "--:--"
    end2 = "--:--"
    # [追加] 「手当」欄の先頭に追加した「休憩」チェックボックスと、
    # チェック時に入力する休憩時間（分）の初期値。
    break2=None
    break_minutes2=None
    # [修正] 「手当」欄の休憩以外の項目は、手配者が手配書登録画面
    # (/arrangement_manage)で金額まで指定して設定する方式に変更した
    # ため、この画面ではチェックボックスとしては扱わず、既にTime
    # レコードに反映されている金額を読み取り専用で表示するだけにする
    # （allowance_display_items参照）。
    allowance_items = allowance_display_items(existing_record, "tsuya")
    # [修正] 手配者が「手配書登録」画面(/arrangement_manage)で、この
    # ユーザー・通夜・本日の会館名を事前に選択していた場合、その値が
    # 既にTime.place2/other2に反映されている（arrangement.py参照）。
    # その場合は出勤入力フォームの会館名欄に、その値を初めから
    # 選択された状態で表示する（honso_stamp()と同じ考え方）。
    # [追加] さらに、その場合は本人が会館名を選び直せないよう、
    # 会館名欄を変更不可（読み取り専用）にする。
    place2 = existing_record.place2 if existing_record else None
    other2 = existing_record.other2 if existing_record else None
    place_locked = bool(place2)
    record_id=None

    if request.method =='POST':                  # POSTがリクエストされた場合
       place2 = request.form.get('place2')       # place2をから入力値を取得
       start2 = request.form.get('start2')
       end2 = request.form.get('end2')
       break2 = request.form.get('break2')
       # [追加] 休憩時間（分）は数値として保存する。未入力・不正な値の
       # 場合はNoneのまま（＝休憩なし扱い）にする。
       break_minutes2_raw = request.form.get('break_minutes2')
       try:
          break_minutes2 = int(break_minutes2_raw) if break_minutes2_raw else None
       except ValueError:
          break_minutes2 = None
       other2 = request.form.get('other2')

       # [修正] 元コードは「今日のレコードが既にあるか」を session['record_id']
       # で判定していたが、これだと別のユーザーが同じブラウザで先に
       # ログインしていた場合などにセッションの値が古い・別人のものになって
       # いることがあり、全く別人のレコードを誤って上書きしてしまう
       # 不具合があった（かつ、その日まだ一件もレコードが無い場合は
       # session['record_id'] 自体が無く KeyError で500エラーにもなっていた）。
       # ここでは、関数の先頭で number（現在ログイン中のユーザー）と
       # today（本日日付）で改めて検索し直した existing_record を、
       # 「今日の記録が既にあるかどうか」の判定にそのまま使う。
       new_record = existing_record
       record_id = new_record.id if new_record else None
       print("デバッグ１ = ",number,record_id,new_record)

       if not new_record:

          print("デバッグ２ = ",number,record_id,new_record)

          time = Time()                             # Timeテーブルに追加することを指定
#          time = Time.query.filter(Time.id == record_id).first() # レコードを上書き
          time.date=today
          time.number=session['user_number']
          time.place2=place2
          time.start2=start2
          time.end2=end2
          time.break2=break2
          time.break_minutes2=break_minutes2
          time.other2=other2
          db.session.add(time)                      # 入力値をTimeテーブルに追加
          try:
             db.session.commit()
          except IntegrityError:
             # [追加] Time(number, date)にはDBの一意制約があり（models.py参照）、
             # 同じユーザー・同じ日のレコードは1件しか作れない。フォームの
             # 二重送信（連打）などでこの関数が同時に2回実行された場合、
             # 片方はここでエラーになるが、既に通夜の出勤記録自体は保存
             # されているはずなので、エラー画面ではなく通常通り/judgeの
             # ハブ画面に戻す。
             db.session.rollback()
             return redirect('/judge')

          if not end2:
             end2 = "--:--"
          else:
             end2 = end2

          if not other2:
             other2 = ""
          else:
             other2 = other2

          # [追加] 登録ボタンが押されたことをメールで通知する。
          send_attendance_notification(
              shift_label="通夜",
              user_name=current_user.username,
              number=session['user_number'],
              place=place2,
              other=other2,
              start=start2,
              end=end2,
              break_flag=break2,
              break_minutes=break_minutes2,
          )

          # [修正] 従来は登録後に読み取り専用の確認画面(tsuya_init.html)へ
          # 遷移して行き止まりになっていたが、本葬・通夜の状態が一目で
          # わかる /judge のハブ画面に戻るようにした。
          return redirect('/judge')

       else:

          print("デバッグ３ = ",number,record_id,new_record)

          # [修正] ここも同様に、session['record_id'] ではなく、
          # 上で number・today から検索し直した new_record（＝このユーザーの
          # 今日のレコード）をそのまま更新対象にする。
          modify_record = new_record
          # [修正] 元コードは modify_record.date=record_id という誤代入の直後に
          # modify_record.date=today で上書きしており無意味だったため削除。
          modify_record.date=today
          modify_record.number=session['user_number']
          modify_record.place2=place2
          modify_record.start2=start2
          modify_record.end2=end2
          modify_record.break2=break2
          modify_record.break_minutes2=break_minutes2
          modify_record.other2=other2
          db.session.commit()                     # 入力値で更新

          if not end2:
             end2 = "--:--"
          else:
             end2 = end2

          if not other2:
             other2 = ""
          else:
             other2 = other2

          # [追加] 登録ボタンが押されたことをメールで通知する。
          send_attendance_notification(
              shift_label="通夜",
              user_name=current_user.username,
              number=session['user_number'],
              place=place2,
              other=other2,
              start=start2,
              end=end2,
              break_flag=break2,
              break_minutes=break_minutes2,
          )

          # [修正] 更新後も読み取り専用の確認画面(tsuya_init.html)ではなく、
          # /judge のハブ画面に戻るようにした。
          return redirect('/judge')

    return render_template('tsuya_stamp.html',
                            title="通夜出勤入力",
                            today=today,
                            places=get_places_for_current_user(),
                            place2=place2,
                            place_locked=place_locked,
                            start2=start2,
                            end2=end2,
                            break2=break2,
                            break_minutes2=break_minutes2,
                            allowance_items=allowance_items,
                            other2=other2)


#------------------------------------------------
# 編集ページ
#------------------------------------------------
@app.route('/tsuya_modify', methods=["GET","POST"])
@login_required                                  #ログイン必須にしたい関数の前に記述する

def tsuya_modify():

    number = session['user_number']              #sessionからユーザー情報をとってくる
    today = get_today()                          #[修正] 呼び出し都度、現在の日付を取得する

    # [修正] 以前はセッションに保存されていた record_id や place2/start2など
    # の値を無条件に信用していたが、別のユーザーが同じブラウザで先に
    # ログインしていた場合などにセッションの値が古い・別人のものになって
    # いることがあり、誤って他人のレコードを更新してしまう不具合があった。
    # 常に number（現在ログイン中のユーザー）と today（本日日付）でDBを
    # 検索し直し、そのレコードだけを対象にするよう修正した。
    record = Time.query.filter(Time.number == number, Time.date == today).first()

    if not record or not record.start2:
        # 通夜がまだ出勤打刻されていない場合は、この画面を表示する意味が無い
        return redirect('/judge')

    # [追加] 退勤が既に入力済みの場合は編集させない
    # （ハブ画面(/judge)側でもボタン自体をグレーアウトして押せなくしている）。
    if record.end2:
        return redirect('/judge')

    # [追加] 本葬が出勤中（出勤時間入力済み・退勤時間未入力）の間は、
    # 既に出勤済みの通夜であっても退勤入力に直接アクセスされないようにする。
    if record.start1 and not record.end1:
        return redirect('/judge')

    record_id = record.id
    # [追加] 通知メール用に、出勤時に登録された会館名(place2/other2)を
    # そのまま保持しておく。下のPOST処理でplace2変数は「未入力」表示用に
    # 上書きされ、other2変数もフォームに入力欄が無いため送信のたびに
    # 空になってしまう（このモジュール内の既知の挙動）ため、メールには
    # ここで確保した値を使う。
    notify_place2 = record.place2
    notify_other2 = record.other2
    place2 = record.place2 if record.place2 else "未入力"
    start2 = record.start2
    end2 = "--:--"
    # [追加] 「休憩」チェックボックスと休憩時間（分）の初期表示値。
    break2 = "checked" if record.break2 else "off"
    break_minutes2 = record.break_minutes2 if record.break_minutes2 else ""
    other2 = record.other2 if record.other2 else ""
    # [修正] 「手当」欄の休憩以外の項目は手配者が手配書登録画面で設定する
    # ようになったため、この画面ではチェックボックスとしては扱わず、
    # 既にTimeレコードに反映されている金額を読み取り専用で表示する。
    allowance_items = allowance_display_items(record, "tsuya")

    if request.method == 'POST':                  # リクエストがPOSTの場合

       end2 = request.form.get('end2')
       break2 = request.form.get('break2')
       # [追加] 休憩時間（分）を数値として保存する。未入力・不正な値の
       # 場合はNoneのまま（＝休憩なし扱い）にする。
       break_minutes2_raw = request.form.get('break_minutes2')
       try:
          break_minutes2 = int(break_minutes2_raw) if break_minutes2_raw else None
       except ValueError:
          break_minutes2 = None
       other2 = request.form.get('other2')

       if not other2:
          other2 = ""
       else:
          other2 = other2

       # [修正] session['record_id'] 経由の再検索ではなく、関数の先頭で
       # number・today から検索し直した record（＝このユーザーの今日の
       # レコード）をそのまま更新する。
       modify_record = record
       modify_record.date=today
       modify_record.number=number
       modify_record.end2=end2
       modify_record.break2=break2
       modify_record.break_minutes2=break_minutes2
       modify_record.other2=other2
       db.session.commit()                     # 入力値で更新

       # [追加] 登録（退勤）ボタンが押されたことをメールで通知する。
       # 退勤時間が入力されているため、件名は【退勤】になる。
       send_attendance_notification(
           shift_label="通夜",
           user_name=current_user.username,
           number=number,
           place=notify_place2,
           other=notify_other2,
           start=start2,
           end=end2,
           break_flag=break2,
           break_minutes=break_minutes2,
       )

       # [修正] 更新後は読み取り専用の確認画面(tsuya_init.html)ではなく、
       # 本葬・通夜の状態が一目でわかる /judge のハブ画面に戻るようにした。
       return redirect('/judge')

    # [修正] GETの場合は編集用フォーム(tsuya_modify.html)をそのまま表示する。
    # 以前はindex.pyのexit_view()のPOSTを経由しないとこの画面に到達できなかった。
    return render_template('tsuya_modify.html',
                            title="通夜退勤入力",
                            record_id=record_id,
                            today=today,
                            place2=place2,
                            start2=start2,
                            end2=end2,
                            break2=break2,
                            break_minutes2=break_minutes2,
                            other2=other2,
                            allowance_items=allowance_items)

