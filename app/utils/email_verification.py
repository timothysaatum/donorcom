import smtplib
from email.message import EmailMessage
import os



def send_verification_email(email: str, token: str):

    msg = EmailMessage()
    msg["Subject"] = "Verify your email"
    msg["From"] = os.getenv("HOST_EMAIL")
    msg["To"] = email
    msg.set_content(f"Click the link to verify your email:\n\nhttp://localhost:5173/verify-email?token={token}")

    # Gmail SMTP configuration
    smtp_server = "smtp.gmail.com"
    smtp_port = 587
    sender_email = os.getenv("HOST_EMAIL")
    app_password = os.getenv("HOST_PASSWORD")

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, app_password)
            server.send_message(msg)
            print("Verification email sent successfully.")
    except Exception as e:
        print("Error sending email:", e)
