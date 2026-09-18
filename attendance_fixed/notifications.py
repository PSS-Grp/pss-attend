#------------------------------------------------
# [追加] 出退勤画面の「登録」ボタンが押されたときに、指定したメール
# アドレスへ通知メールを送信するためのモジュール。
#
# [修正] 当初はGmailのSMTP(smtplib)経由で送信する実装にしていたが、
# Renderの無料プランではSMTP用のポート(25/465/587)への外向き通信が
# ブロックされており（Render公式ドキュメントに明記された既知の制限）、
# 実際にデプロイすると "Network is unreachable" で送信に失敗することが
# 判明した。ポート制限の影響を受けないよう、HTTPS(443番ポート)経由の
# メール配信API（Resend, https://resend.com）を使う実装に変更した。
#
# 実際にメールを送信するには、Render（またはローカル環境）に以下の
# 環境変数を設定する必要がある。
#
#   RESEND_API_KEY  : Resendのダッシュボードで発行するAPIキー
#                      （"re_"で始まる文字列）
#   MAIL_FROM       : 送信元として表示するアドレス
#                      （省略時は "onboarding@resend.dev"。これはResendが
#                        用意している検証不要の送信元アドレスで、独自
#                        ドメインの認証をしなくても送信できる）
#   NOTIFY_EMAIL_TO : 通知メールの送信先アドレス
#                      （複数宛てにする場合はカンマ区切りで指定。
#                        Resend無料プランでは、原則としてResendアカウント
#                        登録時に使ったメールアドレス宛てにしか送信できない
#                        ため、このアドレスと同じメールでResendに登録する）
#
# RESEND_API_KEY・NOTIFY_EMAIL_TOのいずれかが未設定の環境（ローカルでの
# 動作確認や、このアプリを開発しているセッションのサンドボックス環境
# など）では、エラーにはせず送信をスキップする。メール通知はあくまで
# 補助的な機能であり、その成否によって本来の出退勤データの登録処理
# 自体を失敗させないようにするため。
#------------------------------------------------
import os
import json
import datetime
import requests

RESEND_API_URL = "https://api.resend.com/emails"

# [追加] メール本文の「クリック日時」がJST（日本時間）で表示されるようにする
# ためのタイムゾーン定義。
#
# 従来は `datetime.datetime.now()`（タイムゾーン情報を持たない、サーバーの
# ローカル時刻）をそのまま使っていたが、Render上のコンテナはOSの時刻設定が
# UTC（＝GMT相当）になっているため、実際の日本時間より9時間遅い時刻が
# メール本文に表示されてしまっていた。
# サーバーの設定に依存せず常に正しく変換されるよう、`datetime.timezone`で
# 固定のUTC+9オフセットを明示的に指定する（日本時間には夏時間が無いため、
# 標準ライブラリの`zoneinfo`が提供するtzデータベースを使わなくても、この
# 固定オフセットだけで正確に変換できる）。
JST = datetime.timezone(datetime.timedelta(hours=9), name="JST")


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
#------------------------------------------------
# [追加] Resend APIへメールを送信する共通処理。
# send_attendance_notification（出退勤画面用）・send_arrangement_notification
# （手配書登録画面用）の両方から呼び出す。件名・本文の組み立ては呼び出し側の
# 責務とし、ここでは「宛先・送信元の解決」「実際のAPI呼び出し」「失敗時の
# ログ出力」だけを共通化する。
#
# 戻り値は送信できたかどうかの真偽値（テスト・デバッグ用。呼び出し側は
# 戻り値を見て処理を分ける必要はない＝失敗しても登録処理は継続してよい）。
#------------------------------------------------
def _send_email(subject, body):
    api_key = os.environ.get("RESEND_API_KEY")
    mail_from = os.environ.get("MAIL_FROM") or "onboarding@resend.dev"
    notify_to_raw = os.environ.get("NOTIFY_EMAIL_TO")

    if not (api_key and notify_to_raw):
        print("[通知メール] RESEND_API_KEY / NOTIFY_EMAIL_TO の"
              "いずれかが未設定のため、通知メールの送信をスキップしました。")
        return False

    notify_to_list = [addr.strip() for addr in notify_to_raw.split(",") if addr.strip()]
    if not notify_to_list:
        return False

    payload = {
        "from": "勤怠管理システム <{}>".format(mail_from),
        "to": notify_to_list,
        "subject": subject,
        "text": body,
    }

    try:
        response = requests.post(
            RESEND_API_URL,
            headers={
                "Authorization": "Bearer {}".format(api_key),
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=10,
        )
        if response.status_code >= 400:
            # [追加] メール送信に失敗しても、呼び出し元の登録処理自体は
            # 失敗させない。エラー内容はログに残す。
            print("[通知メール] 送信に失敗しました（HTTP {}）: {}".format(
                response.status_code, response.text))
            return False
        return True
    except Exception as e:
        print("[通知メール] 送信に失敗しました:", e)
        return False


def send_attendance_notification(shift_label, user_name, number, place, other,
                                  start, end, break_flag, break_minutes):
    effective_place = _effective_place(place, other)
    # [仕様] 退勤時間が入力されている場合は「退勤」、そうでない場合は「出勤」。
    is_checkout = bool(end) and end != "--:--"
    action_label = "退勤" if is_checkout else "出勤"
    subject = "【{}】{} {}".format(action_label, user_name, effective_place)

    # [修正] サーバーのタイムゾーン設定に関わらず日本時間で表示されるよう、
    # 上で定義した固定のJSTオフセットに変換する。
    clicked_at = datetime.datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
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

    return _send_email(subject, body)


#------------------------------------------------
# [追加] 手配書登録画面(/arrangement_manage)で「登録する」ボタンが押された
# ときに呼び出す通知メール送信関数。send_attendance_notification（出退勤
# 画面用）と同じ送信先(NOTIFY_EMAIL_TO)へ送る。
#
#   arranger_name     : 手配者の氏名（current_user.username）
#   target_user_name  : 手配書の対象ユーザーの氏名
#   date              : 手配書登録フォームで選択された日付（"YYYY-MM-DD"形式の文字列）
#   place             : 選択された会館名（"その他"の場合は"その他"という文字列）
#   other             : 「その他」選択時に手入力された会館名（未入力ならNone可）
#   shift_label       : "本葬" または "通夜"
#   has_attachment    : 画像・PDFが登録されているかどうか（真偽値）
#   has_memo          : メモが入力されているかどうか（真偽値）
#------------------------------------------------
def send_arrangement_notification(arranger_name, target_user_name, date, place, other,
                                   shift_label, has_attachment, has_memo):
    effective_place = _effective_place(place, other)
    subject = "【登録】手配書が登録されました。"
    body = "\n".join([
        "手配者：{}".format(arranger_name),
        "対象ユーザ：{}".format(target_user_name),
        # [追加] ユーザー要望により、手配書登録フォームで選択した日付も
        # 本文の対象ユーザーの下に追加する。
        "日付：{}".format(date),
        "会館名：{}".format(effective_place),
        "勤務：{}".format(shift_label),
        "添付：{}".format("あり" if has_attachment else "なし"),
        "メモ：{}".format("あり" if has_memo else "なし"),
    ])

    return _send_email(subject, body)
