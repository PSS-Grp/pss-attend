#------------------------------------------------
# [追加] 出退勤画面の「登録」ボタンが押されたときに、指定したメール
# アドレスへ通知メールを送信するためのモジュール。
#
# 実際にメールを送信するには、Render（またはローカル環境）に以下の
# 環境変数を設定する必要がある。
#
#   SMTP_HOST       : SMTPサーバーのホスト名（省略時は smtp.gmail.com）
#   SMTP_PORT       : SMTPサーバーのポート番号（省略時は 587）
#   SMTP_USER       : SMTP認証に使うメールアドレス
#                      （Gmailの場合、送信元アドレスにもなる）
#   SMTP_PASSWORD   : SMTP認証用パスワード
#                      （Gmailの場合は通常のパスワードではなく、
#                        Googleアカウントで発行する「アプリパスワード」を使う）
#   MAIL_FROM       : 送信元として表示するアドレス（省略時はSMTP_USERと同じ）
#   NOTIFY_EMAIL_TO : 通知メールの送信先アドレス
#                      （複数宛てにする場合はカンマ区切りで指定）
#
# SMTP_USER・SMTP_PASSWORD・NOTIFY_EMAIL_TOのいずれかが未設定の環境
# （ローカルでの動作確認や、このアプリを開発しているセッションの
# サンドボックス環境など）では、エラーにはせず送信をスキップする。
# メール通知はあくまで補助的な機能であり、その成否によって本来の
# 出退勤データの登録処理自体を失敗させないようにするため。
#------------------------------------------------
import os
import smtplib
import datetime
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr


#------------------------------------------------
# [追加] 会館名の表示用ヘルパー。「その他」が選択されていた場合は、
# 手入力された会館名(other)があればそちらを優先して使う。
#------------------------------------------------
def _effective_place(place, other):
    if place == "その他":
        return other or "その他（未入力）"
    return place or "未入力"


#------------------------------------------------
# [追加] 休憩時間の表示用ヘルパー。休憩チェックが入っていて、かつ
# 休憩時間（分）が入力されている場合のみ「◯分」と表示する。
#------------------------------------------------
def _format_break(break_flag, break_minutes):
    if break_flag and break_minutes:
        return "{}分".format(break_minutes)
    return "なし"


#------------------------------------------------
# [追加] 出退勤の「登録」ボタンが押されたときに呼び出す通知メール送信関数。
#
#   shift_label    : "本葬" または "通夜"
#   user_name      : 従業員名（current_user.username）
#   number         : 従業員番号
#   place          : 選択された会館名（"その他"の場合は"その他"という文字列）
#   other          : 「その他」選択時に手入力された会館名（未入力ならNone可）
#   start          : 出勤時間（"HH:MM"形式の文字列。未入力ならNone可）
#   end            : 退勤時間（"HH:MM"形式の文字列。未入力ならNone・"--:--"可）
#   break_flag     : 「休憩」チェックボックスの値（チェック時"on"、未チェックはNone）
#   break_minutes  : 休憩時間（分、int）。未入力ならNone可
#
# 件名は、退勤時間が入力されているかどうかだけで「【出勤】」「【退勤】」を
# 切り替える（本葬・通夜どちらの画面からの登録かは件名には含めない）。
#
# 戻り値は送信できたかどうかの真偽値（テスト・デバッグ用。呼び出し側は
# 戻り値を見て処理を分ける必要はない＝失敗しても登録処理は継続してよい）。
#------------------------------------------------
def send_attendance_notification(shift_label, user_name, number, place, other,
                                  start, end, break_flag, break_minutes):
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    mail_from = os.environ.get("MAIL_FROM") or smtp_user
    notify_to_raw = os.environ.get("NOTIFY_EMAIL_TO")

    if not (smtp_user and smtp_password and notify_to_raw):
        print("[通知メール] SMTP_USER / SMTP_PASSWORD / NOTIFY_EMAIL_TO の"
              "いずれかが未設定のため、通知メールの送信をスキップしました。")
        return False

    notify_to_list = [addr.strip() for addr in notify_to_raw.split(",") if addr.strip()]
    if not notify_to_list:
        return False

    effective_place = _effective_place(place, other)
    # [仕様] 退勤時間が入力されている場合は「退勤」、そうでない場合は「出勤」。
    is_checkout = bool(end) and end != "--:--"
    action_label = "退勤" if is_checkout else "出勤"
    subject = "【{}】{} {}".format(action_label, user_name, effective_place)

    clicked_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    body = "\n".join([
        "登録ボタンがクリックされました。",
        "",
        "クリック日時: {}".format(clicked_at),
        "氏名: {}".format(user_name),
        "従業員番号: {}".format(number),
        "会館名: {}".format(effective_place),
        "勤務区分: {}".format(shift_label),
        "出勤時間: {}".format(start if start and start != "--:--" else "未入力"),
        "退勤時間: {}".format(end if end and end != "--:--" else "未入力"),
        "休憩時間: {}".format(_format_break(break_flag, break_minutes)),
    ])

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header("勤怠管理システム", "utf-8")), mail_from))
    msg["To"] = ", ".join(notify_to_list)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(mail_from, notify_to_list, msg.as_string())
        return True
    except Exception as e:
        # [追加] メール送信に失敗しても、出退勤の登録処理自体は失敗させない。
        print("[通知メール] 送信に失敗しました:", e)
        return False
