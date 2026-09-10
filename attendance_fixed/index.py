#from app import app
#from admin import admin.add_view

# attendance
# __init__

#### アプリの起動と各モジュールの集約 ####

from __init__ import app ,db ,login_manager ,get_today

from flask import Flask, request, render_template, redirect, flash, session 
from flask_login import login_required, login_user, current_user

from models import User, Time
# from models import LoginForm, User ,
from werkzeug.security import generate_password_hash, check_password_hash

from tsuya import tsuya_modify, tsuya_stamp
from honso import honso_modify, honso_stamp
# [追加] 「本日の手配書」機能（手配者専用の登録画面 /arrangement_manage と、
# 一般ユーザー用の表示画面 /today_arrangement）のルートを読み込む。
import arrangement  # noqa: F401



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
# [修正] 以前はここでもモジュール読み込み時点（＝サーバー起動時点）の
# 日付を `today` という固定値として保持していたが、__init__.py側の
# 修正と合わせて廃止した。日付が必要な各ビュー関数の先頭で、その都度
# `get_today()` を呼んで最新の日付を取得するようにしている。
#------------------------------------------------
import datetime


#------------------------------------------------
# トップページ
# [修正] "/" にルートが無く、Colabの埋め込み表示やブラウザで
# ルートURLを開くと404 (Not Found) になっていたため、/login へ
# リダイレクトするルートを追加した。
#------------------------------------------------
@app.route('/')
def root():
    return redirect('/login')


#------------------------------------------------
# ログインページ
#------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == "POST":
       if request.form['login'] == 'ログイン':
          number = request.form.get('number')                       # 入力値の取得
          password = request.form.get('password')                   # 入力値の取得
          user_check = User.query.filter_by(number=number).first()  # Userクラスからnumberをチェック
          if not user_check:
             return render_template('login.html', error_message='従業員番号が違います。', title="ログイン失敗")
          if check_password_hash(user_check.password, password):    # パスワードをハッシュ化してチェック
             # [修正] 同じブラウザ（同じセッション）で、ログアウトせずに別の
             # 従業員番号でログインし直した場合、前回ログインしていたユーザーの
             # record_id 等がセッションに残ったままだった。これが原因で、
             # 通夜の出退勤打刻（tsuya_stamp/tsuya_modify）が「今日のレコードが
             # 既にある」と誤判定し、全く別のユーザーの勤怠レコードを
             # 上書きしてしまう不具合があったため、ログイン成功時に一旦
             # セッションをクリアしてから使うようにした。
             session.clear()
             session.permanent = True
             login_user(user_check)
             session['user_number'] = user_check.number
             session['user_name'] = user_check.username

             # [追加] 管理者アカウント（is_admin=True）でログインした場合は
             # 出退勤画面(/judge)ではなく、データベース管理画面へ直接遷移させる。
             # 遷移先は /admin/ （中身が空の「Home」画面。ナビからも非表示にした）
             # ではなく、実際にデータが見える /admin/user/ にしている。
             if getattr(user_check, "is_admin", False):
                return redirect('/admin/user/')

             # [追加] 手配者アカウント（is_arranger=True）でログインした場合は、
             # 一般従業員の出退勤画面(/judge)ではなく、手配書登録画面へ
             # 直接遷移させる。一般従業員はこの画面には入れない
             # （arrangement.pyのarranger_requiredで制御）。
             if getattr(user_check, "is_arranger", False):
                return redirect('/arrangement_manage')

             return redirect('/judge')

          else:
             return render_template('login.html', error_message='パスワードが違います。', title="ログイン失敗")

    return render_template('login.html', error_message='ログインして出退勤の入力をお願いします。', title="ログイン前")

#------------------------------------------------
# レコード判定ページ
#------------------------------------------------
@app.route('/judge')
@login_required                                  #ログイン必須にしたい関数の前に記述する

def judge():

    number = session['user_number']              #sessionからユーザー情報を取得
    user_name = session['user_name']             #sessionからユーザー情報を取得
    today = get_today()                          #[修正] 呼び出し都度、現在の日付を取得する
    today_record = Time.query.filter(Time.number==number, Time.date==today).first() #パート番号と本日日付でレコードを検索

    if not today_record: #レコードが無い場合

       # [追加] 今日のレコードが無いのに、以前の（別の日・別のユーザーの）
       # record_id がセッションに残っていると、通夜の出退勤打刻が誤って
       # 別のレコードを更新してしまう可能性があるため、念のためここで消しておく。
       session.pop("record_id", None)

       # [修正] レコードが無い(=本葬・通夜どちらも未着手)場合も、
       # 本葬・通夜どちらも「未出勤」状態として同じハブ画面を表示する。
       return render_template('select.html',
                               user_name=user_name,
                               number=number,
                               today=today,
                               title="本日の勤務選択",
                               honso_status="not_started",
                               honso_start=None,
                               honso_end=None,
                               tsuya_status="not_started",
                               tsuya_start=None,
                               tsuya_end=None)

    else:                #レコードがある場合

       record_id = today_record.id
       session["record_id"] = record_id

       if not today_record.place1:
          place1 = "未入力"
       else:
          place1 = today_record.place1

       if not today_record.start1:
          start1 = "--:--"
       else:
          start1 = today_record.start1

       if not today_record.end1:
          end1 = "--:--"
       else:
          end1 = today_record.end1

       if not today_record.leader1:
          leader1 = "off"
       else:
          leader1 = "checked"

       if not today_record.subleader1:
          subleader1 = "off"
       else:
          subleader1 = "checked"

       if not today_record.teach1:
          teach1 = "off"
       else:
          teach1 = "checked"

       if not today_record.wait1:
          wait1 = "off"
       else:
          wait1 = "checked"

       if not today_record.designated1:
          designated1 = "off"
       else:
          designated1 = "checked"

       if not today_record.distant1:
          distant1 = "off"
       else:
          distant1 = "checked"

       if not today_record.special1:
          special1 = "off"
       else:
          special1 = "checked"

       if not today_record.highway1:
          highway1 = "off"
       else:
          highway1 = "checked"

       if not today_record.express1:
          express1 = "-,---"
       else:
          express1 = today_record.express1

       if not today_record.other1:
          other1 = ""
       else:
          other1 = today_record.other1

       if not today_record.place2:
          place2 = "未入力"
       else:
          place2 = today_record.place2

       if not today_record.start2:
          start2 = "--:--"
       else:
          start2 = today_record.start2

       if not today_record.end2:
          end2 = "--:--"
       else:
          end2 = today_record.end2

       if not today_record.leader2:
          leader2 = "off"
       else:
          leader2 = "checked"

       if not today_record.subleader2:
          subleader2 = "off"
       else:
          subleader2 = "checked"

       if not today_record.teach2:
          teach2 = "off"
       else:
          teach2 = "checked"

       if not today_record.wait2:
          wait2 = "off"
       else:
          wait2 = "checked"

       if not today_record.special2:
          special2 = "off"
       else:
          special2 = "checked"

       if not today_record.designated2:
          designated2 = "off"
       else:
          designated2 = "checked"

       if not today_record.distant2:
          distant2 = "off"
       else:
          distant2 = "checked"

       if not today_record.highway2:
          highway2 = "off"
       else:
          highway2 = "checked"

       if not today_record.express2:
          express2 = "-,---"
       else:
          express2 = today_record.express2

       if not today_record.other2:
          other2 = ""
       else:
          other2 = today_record.other2

       session["place1"] = place1          #sessionに情報をセット
       session["start1"] = start1
       session["end1"] = end1
       session["leader1"] = leader1
       session["subleader1"] = subleader1
       session["teach1"] = teach1
       session["wait1"] = wait1
       session["designated1"] = designated1
       session["distant1"] = distant1
       session["special1"] = special1
       session["highway1"] = highway1
       session["express1"] = express1
       session["other1"] = other1

       session["place2"] = place2
       session["start2"] = start2
       session["end2"] = end2
       session["leader2"] = leader2
       session["subleader2"] = subleader2
       session["teach2"] = teach2
       session["wait2"] = wait2
       session["designated2"] = designated2
       session["distant2"] = distant2
       session["highway2"] = highway2
       session["special2"] = special2
       session["express2"] = express2
       session["other2"] = other2

       # [修正] 従来は、打刻済みの場合は読み取り専用の一覧画面(exit_view.html)
       # に遷移し、本葬・通夜の勤怠選択画面(select.html)には二度と戻れなかった。
       # ここを変更し、出勤・退勤の入力が済んだ後も常に select.html
       # （本葬・通夜それぞれの状態とボタンを表示するハブ画面）を表示するようにした。
       # 各シフトのボタンは、退勤時間が入力済みなら押せないようグレーアウトする
       # （状態の判定と表示切り替えは select.html 側で行う）。
       honso_status = "not_started" if start1 == "--:--" else ("completed" if end1 != "--:--" else "in_progress")
       tsuya_status = "not_started" if start2 == "--:--" else ("completed" if end2 != "--:--" else "in_progress")

       return render_template('select.html',
                               user_name=user_name,
                               number=number,
                               today=today,
                               title="本日の勤務選択",
                               honso_status=honso_status,
                               honso_start=start1,
                               honso_end=end1,
                               tsuya_status=tsuya_status,
                               tsuya_start=start2,
                               tsuya_end=end2)


#------------------------------------------------
# [追加] 勤怠一覧ページ
#
# ログイン後のハブ画面(/judge)に追加した「勤怠一覧」ボタンから遷移する画面。
# ログイン中の従業員自身の勤怠記録（本葬・通夜それぞれの会館名・出勤時間・
# 退勤時間）を、指定した年月の分だけ一覧表示する。
# クエリパラメータ(year, month)で表示する月を切り替えられるようにしており、
# 指定が無い場合は今月を表示する（前月・次月リンクや年月選択のプルダウンから
# 過去の月の記録も見られる）。
#
# Time.date は "YYYY-MM-DD" 形式の文字列で保存されているため（sqlite3の
# date型デフォルトアダプタによる）、"YYYY-MM-" で始まる行を月の絞り込みに
# 使っている。
#------------------------------------------------
#------------------------------------------------
# [追加] 出勤時刻・退勤時刻（"HH:MM"形式の文字列）から実働時間（分）を
# 計算するヘルパー。勤怠一覧画面で本葬・通夜それぞれの実働時間や
# 月合計を表示するために使う。
#
# 出勤・退勤のどちらかが未入力（None・空文字・"--:--"）だったり、
# "HH:MM"形式として解釈できない値だった場合はNone（計算不可）を返す。
# 退勤時刻が出勤時刻より前になっているケース（通夜の勤務が深夜0時を
# またぐ場合など）は、日をまたいだものとして退勤時刻に24時間分を
# 加算してから計算する。
#
# [追加] break_minutesを指定すると、算出した実働時間からその分数を
# 差し引く（「手当」欄に追加した「休憩」チェック時の休憩時間）。
# 差し引いた結果がマイナスになる場合（休憩時間を実際の勤務時間より
# 長く入力してしまった場合など）は0分に切り下げる。
#------------------------------------------------
def _calc_work_minutes(start_str, end_str, break_minutes=None):
    if not start_str or not end_str:
        return None
    if start_str == "--:--" or end_str == "--:--":
        return None
    try:
        start_h, start_m = (int(x) for x in start_str.split(":"))
        end_h, end_m = (int(x) for x in end_str.split(":"))
    except (ValueError, AttributeError):
        return None
    start_total = start_h * 60 + start_m
    end_total = end_h * 60 + end_m
    if end_total < start_total:
        end_total += 24 * 60
    work_minutes = end_total - start_total
    if break_minutes:
        work_minutes -= break_minutes
        if work_minutes < 0:
            work_minutes = 0
    return work_minutes


#------------------------------------------------
# [追加] 分数を「◯時間◯分」の表示用文字列に変換するヘルパー。
# 実働時間が計算できない（出退勤どちらかが未入力）場合は"-"を返す。
#------------------------------------------------
def _format_work_minutes(minutes):
    if minutes is None:
        return "-"
    hours, mins = divmod(minutes, 60)
    return "{}時間{}分".format(hours, mins)


#------------------------------------------------
# [追加] 休憩時間（分）を勤怠一覧の表に表示するための文字列に変換する。
# 休憩が入力されていない（None・0）場合は"-"を返す。
#------------------------------------------------
def _format_break_minutes(minutes):
    if not minutes:
        return "-"
    return "{}分".format(minutes)


@app.route('/attendance_list')
@login_required                                  #ログイン必須にしたい関数の前に記述する

def attendance_list():

    number = session['user_number']              #sessionからユーザー情報を取得
    user_name = session['user_name']             #sessionからユーザー情報を取得

    # [修正] このアプリ全体で使われているモジュールレベルの `today` は
    # サーバー起動時点の日付で固定されてしまっているため、「今月」の
    # 判定にはそれを使わず、実行時点の実際の日付から年月を求める。
    now = datetime.datetime.now()

    # [追加] year・month をクエリパラメータで指定できるようにし、過去の月の
    # 記録も見られるようにした。指定が無い場合や、数値として解釈できない
    # 場合・月が1〜12の範囲外の場合は今月を表示する。
    try:
        year = int(request.args.get('year', now.year))
    except (TypeError, ValueError):
        year = now.year
    try:
        month = int(request.args.get('month', now.month))
    except (TypeError, ValueError):
        month = now.month
    if not (1 <= month <= 12):
        month = now.month

    month_prefix = "{:04d}-{:02d}-".format(year, month)

    records = (
        Time.query
        .filter(Time.number == number, Time.date.like(month_prefix + "%"))
        .order_by(Time.date)
        .all()
    )

    # [追加] 本葬(start1/end1)・通夜(start2/end2)それぞれの実働時間を計算し、
    # テンプレートに渡す行データ(record_rows)に含める。あわせて、月全体の
    # 本葬合計・通夜合計・（本葬＋通夜の）合計時間も集計する。
    # [追加] 「手当」欄の「休憩」で入力された休憩時間（break_minutes1/2）は、
    # 実働時間の計算時にそれぞれ差し引く。休憩時間そのものも表示用に
    # 一覧の列へ含める。
    honso_total_minutes = 0
    tsuya_total_minutes = 0
    record_rows = []
    for r in records:
        honso_minutes = _calc_work_minutes(r.start1, r.end1, break_minutes=r.break_minutes1)
        tsuya_minutes = _calc_work_minutes(r.start2, r.end2, break_minutes=r.break_minutes2)
        if honso_minutes:
            honso_total_minutes += honso_minutes
        if tsuya_minutes:
            tsuya_total_minutes += tsuya_minutes
        record_rows.append({
            "date": r.date,
            "place1": r.place1,
            "start1": r.start1,
            "end1": r.end1,
            "honso_break": _format_break_minutes(r.break_minutes1),
            "honso_duration": _format_work_minutes(honso_minutes),
            "place2": r.place2,
            "start2": r.start2,
            "end2": r.end2,
            "tsuya_break": _format_break_minutes(r.break_minutes2),
            "tsuya_duration": _format_work_minutes(tsuya_minutes),
        })

    honso_total_display = _format_work_minutes(honso_total_minutes)
    tsuya_total_display = _format_work_minutes(tsuya_total_minutes)
    combined_total_display = _format_work_minutes(honso_total_minutes + tsuya_total_minutes)

    # [追加] 画面上の「前月」「次月」リンク用に、前後の年月を計算する。
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1

    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    # 未来の月には（まだ記録が存在しえないため）「次月」で進めないようにする。
    next_disabled = (next_year, next_month) > (now.year, now.month)

    # [追加] 年月選択プルダウン用の年の選択肢。今年を含む直近数年分に加えて、
    # 今表示している年がその範囲に無ければそれも含める。
    year_options = list(range(now.year - 2, now.year + 1))
    if year not in year_options:
        year_options.append(year)
        year_options.sort()

    return render_template('attendance_list.html',
                            title="勤怠一覧",
                            user_name=user_name,
                            number=number,
                            year=year,
                            month=month,
                            records=record_rows,
                            honso_total_display=honso_total_display,
                            tsuya_total_display=tsuya_total_display,
                            combined_total_display=combined_total_display,
                            prev_year=prev_year,
                            prev_month=prev_month,
                            next_year=next_year,
                            next_month=next_month,
                            next_disabled=next_disabled,
                            year_options=year_options,
                            month_options=range(1, 13))


#------------------------------------------------
# 選択ページ
#------------------------------------------------
@app.route('/select', methods=['GET', 'POST'])
@login_required                                  #ログイン必須にしたい関数の前に記述する

def select():

    if request.method == 'POST':                 # 本葬、通夜を選択
       if request.form['honso-tsuya'] == '本 葬':
          return redirect('/honso_stamp')

       if request.form['honso-tsuya'] == '通 夜':
          return redirect('/tsuya_stamp')


#------------------------------------------------
# 入力済みの表示ページ
#------------------------------------------------
@app.route('/exit_view', methods=["GET","POST"])
@login_required                                  #ログイン必須にしたい関数の前に記述する

def exit_view():

    number = session['user_number']              #sessionからユーザー情報を取得
    user_name = session['user_name']             #sessionからユーザー情報を取得
    today = get_today()                          #[修正] 呼び出し都度、現在の日付を取得する
    today_record = Time.query.filter(Time.number==number, Time.date==today).first() #パート番号と本日日付でレコードを検索
    honso_start1 = Time.query.filter(Time.start1==today_record.start1).first()
    tsuya_start2 = Time.query.filter(Time.start2==today_record.start2).first()
    honso_end1 = Time.query.filter(Time.end1==today_record.end1).first()            #本葬退勤時間を検索
    tsuya_end2 = Time.query.filter(Time.end2==today_record.end2).first()

    record_id = session['record_id']
    place1 = session["place1"]
    start1 = session["start1"]
    end1 = session["end1"]
    leader1 = session["leader1"]
    subleader1 = session["subleader1"]
    teach1 = session["teach1"]
    wait1 = session["wait1"]
    designated1 = session["designated1"]
    distant1 = session["distant1"]
    special1 = session["special1"]
    highway1 = session["highway1"]
    express1 = session["express1"]
    other1 = session["other1"]
    place2 = session["place2"]
    start2 = session["start2"]
    end2 = session["end2"]
    leader2 = session["leader2"]
    subleader2 = session["subleader2"]
    teach2 = session["teach2"]
    wait2 = session["wait2"]
    designated2 = session["designated2"]
    distant2 = session["distant2"]
    special2 = session["special2"]
    highway2 = session["highway2"]
    express2 = session["express2"]
    other2 = session["other2"]

    if request.method =='POST':                  # リクエストがPOSTの場合

       if end1 == "--:--" and start2 == "--:--":

          return render_template('honso_modify.html', 
                                  title="本葬退勤入力", 
                                  record_id=record_id, 
                                  today=today, 
                                  place1=place1, 
                                  start1=start1, 
                                  end1=end1, 
                                  other1=other1, 
                                  leader1=leader1, 
                                  subleader1=subleader1, 
                                  teach1=teach1, 
                                  wait1=wait1, 
                                  designated1=designated1, 
                                  distant1=distant1, 
                                  special1=special1, 
                                  highway1=highway1, 
                                  express1=express1 )  # パラメータをhonso_modify.htmlに送る

       else:

          if start2 == "--:--" and end2 == "--:--":

             return render_template('tsuya_stamp.html', 
                                     title="通夜勤怠入力", 
                                     record_id=record_id, 
                                     today=today, 
                                     place2=place2, 
                                     start2=start2, 
                                     end2=end2, 
                                     other2=other2, 
                                     leader2=leader2, 
                                     subleader2=subleader2, 
                                     teach2=teach2, 
                                     wait2=wait2, 
                                     designated2=designated2, 
                                     distant2=distant2, 
                                     special2=special2, 
                                     highway2=highway2, 
                                     express2=express2 )  # パラメータをtsuya_stamp.htmlに送る

          else:

             return render_template('tsuya_modify.html', 
                                     title="通夜勤怠更新", 
                                     record_id=record_id, 
                                     today=today, 
                                     place2=place2, 
                                     start2=start2, 
                                     end2=end2, 
                                     other2=other2, 
                                     leader2=leader2, 
                                     subleader2=subleader2, 
                                     teach2=teach2, 
                                     wait2=wait2, 
                                     designated2=designated2, 
                                     distant2=distant2, 
                                     special2=special2, 
                                     highway2=highway2, 
                                     express2=express2 )  # パラメータをtsuya_modify.htmlに送る



#------------------------------------------------
# DB管理の表示ページ
#------------------------------------------------
# @app.route('/admin', methods=['GET', 'POST'])
# @login_required                                  #ログイン必須にしたい関数の前に記述する
# def admin():
#     return redirect('/admin')

#employee # 従業員


#------------------------------------------------
# ログアウト
#------------------------------------------------
@app.route("/init_view", methods=["GET","POST"]) #ログアウトする
@login_required                                  #ログイン必須にしたい関数の前に記述する

def init_view():

    if request.method =='POST':                  # リクエストがPOSTの場合

       return render_template('login.html')

       logout_user() # ログアウト
       driver.close()


#------------------------------------------------
# ログアウト
#------------------------------------------------
@app.route("/honso_init", methods=["GET","POST"]) #ログアウトする
@login_required                                   #ログイン必須にしたい関数の前に記述する

def honso_init():

    if request.method =='POST':                   #リクエストがPOSTの場合

       return render_template('login.html')

       logout_user() # ログアウト
       driver.close()


#------------------------------------------------
# ログアウト
#------------------------------------------------
@app.route("/tsuya_init", methods=["GET","POST"]) #ログアウトする
@login_required                                   #ログイン必須にしたい関数の前に記述する

def tsuya_init():

    if request.method =='POST':                   #リクエストがPOSTの場合

       return render_template('login.html')

       logout_user() # ログアウト
       driver.close()


if __name__ == '__main__':
    app.run(debug=True)
