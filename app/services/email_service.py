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

            import ssl

            # Setup permissive SSL context compatible with corporate/on-premise Zimbra mail certs
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

            # Port 465 is implicit SSL; port 587 is explicit TLS (STARTTLS)
            is_ssl = (self.port == 465) or getattr(settings, "SMTP_SSL", False)

            if is_ssl:
                with smtplib.SMTP_SSL(self.host, self.port, timeout=15, context=ssl_ctx) as server:
                    server.login(self.user, self.password)
                    server.sendmail(self.from_email, [to_email], msg.as_string())
            else:
                with smtplib.SMTP(self.host, self.port, timeout=15) as server:
                    if settings.SMTP_TLS:
                        server.starttls(context=ssl_ctx)
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

    def _resolve_maps_url(self, maps_url: Optional[str], location: Optional[str]) -> Optional[str]:
        """Normalize or auto-derive Google Maps link from custom URL, embed iframe, or location keywords."""
        if maps_url and str(maps_url).strip():
            raw = str(maps_url).strip()
            if "<iframe" in raw and 'src="' in raw:
                try:
                    return raw.split('src="')[1].split('"')[0]
                except Exception:
                    pass
            return raw
        if not location:
            return None
        loc_lower = str(location).lower()
        if any(k in loc_lower for k in ["online", "portal", "zoom", "teams", "virtual"]):
            return None
        if any(k in loc_lower for k in ["cikarang", "giic", "deltamas"]):
            return "https://maps.google.com/?q=PT+Indonesia+Thai+Summit+Plastech+GIIC+Cikarang"
        if any(k in loc_lower for k in ["karawang", "kiic"]):
            return "https://maps.google.com/?q=PT+Indonesia+Thai+Summit+Plastech+KIIC+Karawang"
        if "http://" in str(location) or "https://" in str(location):
            return str(location).strip()
        return "https://maps.google.com/?q=PT+Indonesia+Thai+Summit+Plastech"

    def send_screening_passed(
        self,
        to_email: str,
        name: str,
        position: str,
        token: str,
        test_url: str,
        location: Optional[str] = None,
        maps_url: Optional[str] = None,
        scheduled_at: Optional[Any] = None,
        duration_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Notify candidate of passing Stage 1 and receiving token for Stage 2 Psikotes."""
        maps_url = self._resolve_maps_url(maps_url, location)
        subject = f"[PT ITSP] Lolos Screening Administrasi & Undangan Psikotes - {position}"

        sched_part = ""
        if scheduled_at:
            if hasattr(scheduled_at, "strftime"):
                s_str = scheduled_at.strftime("%d %B %Y, Pukul %H:%M WIB")
            else:
                s_str = str(scheduled_at)
            sched_part = f'<p style="margin: 4px 0;"><strong>📅 Jadwal Mulai Ujian:</strong> {s_str}</p>'
            if duration_minutes:
                sched_part += f'<p style="margin: 4px 0;"><strong>⏳ Durasi Pengerjaan:</strong> {duration_minutes} Menit</p>'

        loc_part = ""
        if location:
            loc_part = f'<p style="margin: 4px 0;"><strong>📍 Tempat / Lokasi:</strong> {location}</p>'

        maps_part = ""
        if maps_url:
            maps_part = f'''
            <div style="margin-top: 12px; margin-bottom: 8px;">
                <a href="{maps_url}" target="_blank" style="display: inline-block; background-color: #018730; color: #ffffff; padding: 9px 18px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13px;">
                    🗺️ Buka Rute Lokasi Ujian di Google Maps &rarr;
                </a>
            </div>
            '''

        content = f"""
        <p>Yth. Sdr/i. <strong>{name}</strong>,</p>
        <p>Selamat! Berdasarkan hasil evaluasi berkas lamaran Anda untuk posisi <strong>{position}</strong> di PT Indonesia Thai Summit Plastech, kami mengundang Anda untuk mengikuti <strong>Ujian Psikotes Online (Tahap 2)</strong>.</p>
        
        <div style="background-color: #f8fafc; border-left: 4px solid #018730; padding: 16px 18px; margin: 20px 0; border-radius: 6px; border: 1px solid #e2e8f0; border-left-width: 4px;">
            <p style="margin: 0 0 8px;"><strong>Token Sesi Ujian:</strong> <span style="font-family: monospace; font-size: 18px; color: #018730; font-weight: bold; background: #dcfce7; padding: 3px 10px; border-radius: 4px; border: 1px solid #86efac;">{token}</span></p>
            {sched_part}
            {loc_part}
            {maps_part}
            <p style="margin: 8px 0 0; font-size: 13px; color: #64748b;">Token ini bersifat rahasia dan unik untuk akun Anda.</p>
        </div>
        <p>Silakan klik tombol di bawah ini untuk mengakses ruang ujian pada Portal Karir kami:</p>
        """
        html = self._wrap_corporate_template(subject, content, "Mulai Ujian Psikotes", test_url)
        return self.send_email(to_email, subject, html)

    def send_user_test_invitation(
        self,
        to_email: str,
        name: str,
        position: str,
        token: str,
        test_url: str,
        location: Optional[str] = None,
        maps_url: Optional[str] = None,
        scheduled_at: Optional[Any] = None,
        duration_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Notify candidate of passing Psikotes and receiving token for Stage 3 Technical Test."""
        maps_url = self._resolve_maps_url(maps_url, location)
        subject = f"[PT ITSP] Lolos Psikotes & Undangan Ujian Teknis - {position}"

        sched_part = ""
        if scheduled_at:
            if hasattr(scheduled_at, "strftime"):
                s_str = scheduled_at.strftime("%d %B %Y, Pukul %H:%M WIB")
            else:
                s_str = str(scheduled_at)
            sched_part = f'<p style="margin: 4px 0;"><strong>📅 Jadwal Mulai Ujian:</strong> {s_str}</p>'
            if duration_minutes:
                sched_part += f'<p style="margin: 4px 0;"><strong>⏳ Durasi Pengerjaan:</strong> {duration_minutes} Menit</p>'

        loc_part = ""
        if location:
            loc_part = f'<p style="margin: 4px 0;"><strong>📍 Tempat / Lokasi:</strong> {location}</p>'

        maps_part = ""
        if maps_url:
            maps_part = f'''
            <div style="margin-top: 12px; margin-bottom: 8px;">
                <a href="{maps_url}" target="_blank" style="display: inline-block; background-color: #018730; color: #ffffff; padding: 9px 18px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13px;">
                    🗺️ Buka Rute Lokasi Ujian di Google Maps &rarr;
                </a>
            </div>
            '''

        content = f"""
        <p>Yth. Sdr/i. <strong>{name}</strong>,</p>
        <p>Selamat! Anda dinyatakan <strong>lolos Ujian Psikotes (Tahap 2)</strong> untuk posisi <strong>{position}</strong> di PT Indonesia Thai Summit Plastech. Selanjutnya kami mengundang Anda mengikuti <strong>Ujian Teknis User (Tahap 3)</strong>.</p>

        <div style="background-color: #f8fafc; border-left: 4px solid #018730; padding: 16px 18px; margin: 20px 0; border-radius: 6px; border: 1px solid #e2e8f0; border-left-width: 4px;">
            <p style="margin: 0 0 8px;"><strong>Token Sesi Ujian:</strong> <span style="font-family: monospace; font-size: 18px; color: #018730; font-weight: bold; background: #dcfce7; padding: 3px 10px; border-radius: 4px; border: 1px solid #86efac;">{token}</span></p>
            {sched_part}
            {loc_part}
            {maps_part}
            <p style="margin: 8px 0 0; font-size: 13px; color: #64748b;">Token ini bersifat rahasia dan unik untuk akun Anda.</p>
        </div>
        <p>Silakan klik tombol di bawah ini untuk mengakses ruang ujian pada Portal Karir kami:</p>
        """
        html = self._wrap_corporate_template(subject, content, "Mulai Ujian Teknis", test_url)
        return self.send_email(to_email, subject, html)

    def send_interview_invitation(
        self,
        to_email: str,
        name: str,
        position: str,
        interview_type: str,
        scheduled_at: Optional[Any] = None,
        location_mode: Optional[str] = "online",
        meeting_platform: Optional[str] = "teams",
        meeting_link: Optional[str] = None,
        meeting_passcode: Optional[str] = None,
        location_address: Optional[str] = None,
        maps_url: Optional[str] = None,
        room_name: Optional[str] = None,
        interviewer_name: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send official Interview HR or Interview User invitation."""
        if location_mode != "online":
            maps_url = self._resolve_maps_url(maps_url, location_address)
        type_label = "Interview HR Recruitment (Tahap 4)" if interview_type == "hr" else "Interview Teknis User Departemen (Tahap 5)"
        subject = f"[PT ITSP] Undangan Sesi {type_label} - {position}"

        sched_str = "Akan diinformasikan lebih lanjut oleh tim HR"
        if scheduled_at:
            if hasattr(scheduled_at, "strftime"):
                sched_str = scheduled_at.strftime("%d %B %Y, Pukul %H:%M WIB")
            else:
                sched_str = str(scheduled_at)

        mode_text = "Online (Virtual Meeting)" if location_mode == "online" else "Tatap Muka Onsite (Pabrik PT ITSP)"
        loc_details = ""
        if location_mode == "online":
            plat = (meeting_platform or "Microsoft Teams").capitalize()
            link_part = f'<p style="margin: 4px 0;"><strong>Link Meeting:</strong> <a href="{meeting_link}" target="_blank" style="color: #2563eb; word-break: break-all;">{meeting_link}</a></p>' if meeting_link else ''
            passcode_part = f'<p style="margin: 4px 0;"><strong>Passcode / ID:</strong> <code>{meeting_passcode}</code></p>' if meeting_passcode else ''
            loc_details = f"""
            <p style="margin: 4px 0;"><strong>Platform:</strong> {plat}</p>
            {link_part}
            {passcode_part}
            """
        else:
            maps_btn = ""
            if maps_url:
                maps_btn = f"""
                <div style="margin-top: 14px; margin-bottom: 6px;">
                    <a href="{maps_url}" target="_blank" style="display: inline-block; background-color: #018730; color: #ffffff; padding: 10px 20px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13px; box-shadow: 0 2px 4px rgba(1,135,48,0.25);">
                        🗺️ Buka Rute Lokasi di Google Maps &rarr;
                    </a>
                </div>
                """
            loc_details = f"""
            <p style="margin: 4px 0;"><strong>Tempat / Ruangan:</strong> {room_name or 'Gedung Administrasi PT ITSP'}</p>
            <p style="margin: 4px 0;"><strong>Lokasi Pabrik:</strong> {location_address or 'Kawasan Industri KIIC Karawang / GIIC Cikarang'}</p>
            {maps_btn}
            """

        interviewer_part = f'<p style="margin: 8px 0 0; color: #475569;"><strong>👤 Pewawancara:</strong> {interviewer_name}</p>' if interviewer_name else ''
        notes_part = f'<div style="background: #fffbeb; border: 1px solid #fde68a; padding: 12px 16px; border-radius: 6px; margin: 15px 0;"><p style="margin: 0; font-size: 13px; color: #92400e;"><strong>Catatan Tambahan:</strong><br>{notes}</p></div>' if notes else ''

        content = f"""
        <p>Yth. Sdr/i. <strong>{name}</strong>,</p>
        <p>Selamat! Anda dinyatakan <strong>LOLOS</strong> pada tahapan sebelumnya untuk posisi <strong>{position}</strong> di PT Indonesia Thai Summit Plastech.</p>
        <p>Dengan bangga kami mengundang Anda untuk menghadiri sesi <strong>{type_label}</strong> dengan rincian jadwal sebagai berikut:</p>

        <div style="background-color: #f8fafc; border-left: 4px solid #018730; padding: 18px 20px; margin: 20px 0; border-radius: 6px; border: 1px solid #e2e8f0; border-left-width: 4px;">
            <p style="margin: 0 0 8px; font-size: 15px; color: #0f172a;"><strong>📅 Waktu:</strong> <span style="color: #018730; font-weight: bold;">{sched_str}</span></p>
            <p style="margin: 0 0 8px;"><strong>📍 Mode:</strong> {mode_text}</p>
            {loc_details}
            {interviewer_part}
        </div>

        {notes_part}

        <p style="font-size: 13px; color: #475569;">Harap bergabung/hadir 10 menit sebelum jadwal dimulai dengan berpakaian rapi dan formal (Kemeja Putih/Bebas Rapi). Silakan cek rincian lebih lanjut di Portal Karir Anda.</p>
        """
        html = self._wrap_corporate_template(subject, content, "Buka Portal Karir & Konfirmasi", f"{settings.FRONTEND_CAREER_URL}/portal/dashboard")
        return self.send_email(to_email, subject, html)

    def send_stage_passed_notification(
        self,
        to_email: str,
        name: str,
        position: str,
        stage_num: int,
        stage_name: str,
        message: Optional[str] = None,
        cta_url: Optional[str] = None,
        maps_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Notify candidate of advancing to a new stage."""
        subject = f"[PT ITSP] Pemberitahuan Kelolosan Seleksi: Tahap {stage_num} ({stage_name}) - {position}"

        maps_part = ""
        if maps_url:
            maps_part = f'''
            <div style="margin: 16px 0;">
                <a href="{maps_url}" target="_blank" style="display: inline-block; background-color: #018730; color: #ffffff; padding: 10px 20px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 13px;">
                    🗺️ Buka Peta Lokasi / Rujukan di Google Maps &rarr;
                </a>
            </div>
            '''

        content = f"""
        <p>Yth. Sdr/i. <strong>{name}</strong>,</p>
        <p>{message or f'Selamat! Anda telah dinyatakan lolos ke Tahap {stage_num}: {stage_name} untuk posisi {position} di PT Indonesia Thai Summit Plastech.'}</p>
        {maps_part}
        <p>Silakan kunjungi Portal Karir PT ITSP untuk melihat perkembangan status lamaran kerja Anda dan instruksi tahapan berikutnya.</p>
        """
        target_url = cta_url or f"{settings.FRONTEND_CAREER_URL}/portal/dashboard"
        html = self._wrap_corporate_template(subject, content, "Lihat Status di Portal Karir", target_url)
        return self.send_email(to_email, subject, html)

    def send_stage_override_notification(
        self,
        to_email: str,
        name: str,
        position: str,
        stage_num: int,
        stage_name: str,
        status_text: str,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Notify candidate when Super Admin adjusts their stage."""
        subject = f"[PT ITSP] Pembaruan Status Alur Seleksi - {position}"
        content = f"""
        <p>Yth. Sdr/i. <strong>{name}</strong>,</p>
        <p>Terdapat penyesuaian administratif resmi pada tahapan proses seleksi Anda untuk posisi <strong>{position}</strong> di PT Indonesia Thai Summit Plastech.</p>
        <div style="background-color: #f8fafc; border-left: 4px solid #0f172a; padding: 15px; margin: 20px 0; border-radius: 4px;">
            <p style="margin: 0 0 6px;"><strong>Tahap Seleksi Saat Ini:</strong> Tahap {stage_num} ({stage_name})</p>
            <p style="margin: 0;"><strong>Status:</strong> {status_text.upper()}</p>
        </div>
        {f'<p style="color: #475569; font-size: 13px;"><em>Catatan: {notes}</em></p>' if notes else ''}
        <p>Silakan login ke Portal Karir untuk melihat perkembangan dan informasi terbaru terkait proses rekrutmen Anda.</p>
        """
        html = self._wrap_corporate_template(subject, content, "Akses Portal Karir", f"{settings.FRONTEND_CAREER_URL}/portal/dashboard")
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
