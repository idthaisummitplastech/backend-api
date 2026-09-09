import logging
import smtplib
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Dict, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailNotificationService:
    """
    Corporate Email Service compatible with Zimbra, Gmail SMTP, and on-premise mail servers.
    Handles HTML + Plain Text multipart formatting and corporate branding.
    """

    def __init__(self):
        self.host = settings.SMTP_HOST
        self.port = settings.SMTP_PORT
        self.user = settings.SMTP_USER
        self.password = settings.SMTP_PASS
        self.from_email = settings.SMTP_FROM_EMAIL or self.user
        self.from_name = settings.SMTP_FROM_NAME

    def _html_to_text(self, html: str) -> str:
        """Strip HTML tags for clean plain-text fallback to boost spam score deliverability."""
        text = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", html, flags=re.IGNORECASE)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<li[^>]*>", "• ", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _wrap_corporate_template(self, title: str, content: str, cta_text: str = "", cta_url: str = "") -> str:
        """Generate official PT ITSP corporate HTML email template."""
        cta_button = ""
        if cta_text and cta_url:
            cta_button = f"""
            <div style="margin: 30px 0; text-align: center;">
                <a href="{cta_url}" style="background-color: #0f172a; color: #ffffff; padding: 12px 28px; text-decoration: none; border-radius: 6px; font-weight: 600; display: inline-block; font-size: 14px;">
                    {cta_text}
                </a>
            </div>
            """

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{title}</title>
        </head>
        <body style="font-family: 'Segoe UI', Arial, sans-serif; background-color: #f1f5f9; margin: 0; padding: 30px 15px; color: #334155;">
            <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border: 1px solid #e2e8f0;">
                <div style="background-color: #0f172a; padding: 24px 30px; text-align: center;">
                    <h2 style="color: #ffffff; margin: 0; font-size: 18px; letter-spacing: 0.5px;">PT INDONESIA THAI SUMMIT PLASTECH</h2>
                    <p style="color: #94a3b8; margin: 5px 0 0; font-size: 12px; text-transform: uppercase;">Portal Karir & Rekrutmen Terpadu</p>
                </div>
                <div style="padding: 30px 30px 20px;">
                    {content}
                    {cta_button}
                    <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #f1f5f9; font-size: 12px; color: #64748b;">
                        <p style="margin: 0;"><strong>Catatan Penting:</strong> Email ini dikirim otomatis oleh Sistem ATS PT Indonesia Thai Summit Plastech. Harap tidak membalas email ini secara langsung.</p>
                    </div>
                </div>
                <div style="background-color: #f8fafc; padding: 15px; text-align: center; font-size: 11px; color: #94a3b8; border-top: 1px solid #f1f5f9;">
                    © 2026 PT Indonesia Thai Summit Plastech. Hak Cipta Dilindungi Undang-Undang.
                </div>
            </div>
        </body>
        </html>
        """

    def send_email(self, to_email: str, subject: str, html_content: str) -> Dict[str, Any]:
        """Dispatch email via authenticated SMTP server with TLS."""
        if not self.user or not self.password:
            logger.warning("SMTP credentials missing. Email not dispatched to: %s", to_email)
            return {"success": False, "error": "Kredensial SMTP belum diset pada environment."}

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{self.from_name} <{self.from_email}>"
            msg["To"] = to_email
            msg["Reply-To"] = self.from_email
            msg["X-Mailer"] = "PT ITSP Career ATS Engine Python/FastAPI"

            text_content = self._html_to_text(html_content)
            msg.attach(MIMEText(text_content, "plain", "utf-8"))
            msg.attach(MIMEText(html_content, "html", "utf-8"))

            with smtplib.SMTP(self.host, self.port, timeout=15) as server:
                if settings.SMTP_TLS:
                    server.starttls()
                server.login(self.user, self.password)
                server.sendmail(self.from_email, [to_email], msg.as_string())

            logger.info("Email successfully sent to: %s with subject: %s", to_email, subject)
            try:
                from app.core.observability import push_email_log_to_grafana
                push_email_log_to_grafana("web_karir", self.from_name, to_email, subject, "SUCCESS")
            except Exception:
                pass
            return {"success": True}
        except Exception as e:
            logger.error("Failed to send email to %s: %s", to_email, str(e))
            try:
                from app.core.observability import push_email_log_to_grafana
                push_email_log_to_grafana("web_karir", self.from_name, to_email, subject, "FAILED", str(e))
            except Exception:
                pass
            return {"success": False, "error": str(e)}

    def send_screening_passed(self, to_email: str, name: str, position: str, token: str, test_url: str) -> Dict[str, Any]:
        """Notify candidate of passing Stage 1 and receiving token for Stage 2 Psikotes."""
        subject = f"[PT ITSP] Lolos Screening Administrasi & Undangan Psikotes - {position}"
        content = f"""
        <p>Yth. Sdr/i. <strong>{name}</strong>,</p>
        <p>Selamat! Berdasarkan hasil evaluasi berkas lamaran Anda untuk posisi <strong>{position}</strong> di PT Indonesia Thai Summit Plastech, kami mengundang Anda untuk mengikuti <strong>Ujian Psikotes Online (Tahap 2)</strong>.</p>
        
        <div style="background-color: #f8fafc; border-left: 4px solid #0f172a; padding: 15px; margin: 20px 0; border-radius: 4px;">
            <p style="margin: 0 0 8px;"><strong>Token Sesi Ujian:</strong> <span style="font-family: monospace; font-size: 18px; color: #2563eb; font-weight: bold; background: #e0e7ff; padding: 2px 8px; border-radius: 4px;">{token}</span></p>
            <p style="margin: 0; font-size: 13px; color: #64748b;">Token ini bersifat rahasia dan unik untuk akun Anda.</p>
        </div>
        <p>Silakan klik tombol di bawah ini untuk mengakses ruang ujian pada Portal Karir kami:</p>
        """
        html = self._wrap_corporate_template(subject, content, "Mulai Ujian Psikotes", test_url)
        return self.send_email(to_email, subject, html)

    def send_user_test_invitation(self, to_email: str, name: str, position: str, token: str, test_url: str) -> Dict[str, Any]:
        """Notify candidate of passing Psikotes and receiving token for Stage 3 Technical Test."""
        subject = f"[PT ITSP] Lolos Psikotes & Undangan Ujian Teknis - {position}"
        content = f"""
        <p>Yth. Sdr/i. <strong>{name}</strong>,</p>
        <p>Selamat! Anda dinyatakan <strong>lolos Ujian Psikotes (Tahap 2)</strong> untuk posisi <strong>{position}</strong> di PT Indonesia Thai Summit Plastech. Selanjutnya kami mengundang Anda mengikuti <strong>Ujian Teknis User (Tahap 3)</strong>.</p>

        <div style="background-color: #f8fafc; border-left: 4px solid #0f172a; padding: 15px; margin: 20px 0; border-radius: 4px;">
            <p style="margin: 0 0 8px;"><strong>Token Sesi Ujian:</strong> <span style="font-family: monospace; font-size: 18px; color: #2563eb; font-weight: bold; background: #e0e7ff; padding: 2px 8px; border-radius: 4px;">{token}</span></p>
            <p style="margin: 0; font-size: 13px; color: #64748b;">Token ini bersifat rahasia dan unik untuk akun Anda.</p>
        </div>
        <p>Silakan klik tombol di bawah ini untuk mengakses ruang ujian pada Portal Karir kami:</p>
        """
        html = self._wrap_corporate_template(subject, content, "Mulai Ujian Teknis", test_url)
        return self.send_email(to_email, subject, html)

    def send_stage_reminder(self, to_email: str, name: str, position: str, stage: int, stage_status: Optional[str] = None) -> Dict[str, Any]:
        """Generic stage status reminder (recovery resend for stages without dedicated token email)."""
        subject = f"[PT ITSP] Pengingat Status Seleksi Tahap {stage} - {position}"
        status_text = "sedang berjalan" if (stage_status or "in_progress") == "in_progress" else str(stage_status)
        content = f"""
        <p>Yth. Sdr/i. <strong>{name}</strong>,</p>
        <p>Ini adalah pengiriman ulang notifikasi resmi terkait proses seleksi Anda untuk posisi <strong>{position}</strong> di PT Indonesia Thai Summit Plastech.</p>
        <p>Status Anda saat ini: <strong>Tahap {stage} ({status_text})</strong>.</p>
        <p>Silakan pantau Portal Karir kami secara berkala untuk jadwal, token ujian, atau undangan wawancara terbaru. Jika Anda belum menerima token padahal seharusnya sudah dijadwalkan, hubungi tim HR kami.</p>
        """
        html = self._wrap_corporate_template(subject, content, "Buka Portal Karir", f"{settings.FRONTEND_CAREER_URL}/portal")
        return self.send_email(to_email, subject, html)

    def send_rejection_notice(self, to_email: str, name: str, position: str, reason: Optional[str] = None) -> Dict[str, Any]:
        """Send respectful corporate rejection notice."""
        subject = f"[PT ITSP] Pembaruan Status Seleksi - {position}"
        content = f"""
        <p>Yth. Sdr/i. <strong>{name}</strong>,</p>
        <p>Terima kasih atas partisipasi dan waktu yang telah Anda luangkan dalam proses seleksi untuk posisi <strong>{position}</strong> di PT Indonesia Thai Summit Plastech.</p>
        <p>Setelah mempertimbangkan dengan saksama seluruh kriteria kualifikasi yang kami butuhkan, kami menyampaikan bahwa saat ini kami belum dapat melanjutkan proses seleksi Anda ke tahap berikutnya.</p>
        {f'<p style="color: #64748b; font-size: 13px;"><em>Catatan Evaluator: {reason}</em></p>' if reason else ''}
        <p>Data profil Anda akan tetap tersimpan dalam database talent pool kami untuk lowongan yang sesuai di masa mendatang.</p>
        <p>Kami mendoakan yang terbaik bagi kesuksesan karir profesional Anda.</p>
        """
        html = self._wrap_corporate_template(subject, content)
        return self.send_email(to_email, subject, html)


email_service = EmailNotificationService()
