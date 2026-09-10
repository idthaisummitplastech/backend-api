"""Seed Company Profile CMS (web_perusahaan): nav-menus + sustainability-reports."""
import logging
from app.db.session import SessionCompanyLocal

logger = logging.getLogger(__name__)


def seed_company_cms() -> None:
    from app.models.cms import NavMenu, SustainabilityReport
    db = SessionCompanyLocal()
    try:
        default_navs = [
            {"title": "Beranda", "url": "/", "location": "navbar", "sort_order": 1},
            {"title": "Tentang Kami", "url": "/about", "location": "navbar", "sort_order": 2},
            {"title": "Produk", "url": "/products", "location": "navbar", "sort_order": 3},
            {"title": "Fasilitas", "url": "/facilities", "location": "navbar", "sort_order": 4},
            {"title": "Sertifikasi", "url": "/certifications", "location": "navbar", "sort_order": 5},
            {"title": "News", "url": "/news", "location": "navbar", "sort_order": 6},
            {"title": "Kontak", "url": "/contact", "location": "navbar", "sort_order": 7},
        ]
        for item in default_navs:
            exists = db.query(NavMenu).filter(
                NavMenu.url == item["url"],
                NavMenu.location == item["location"],
            ).first()
            if not exists:
                db.add(NavMenu(section=None, parent_id=None, is_active=True, **item))
        db.commit()
        if db.query(SustainabilityReport).count() == 0:
            rows = [
                ("Amount General Waste", "general-waste", "Waste Management Summary Report",
                 "Laporan Ringkasan Pengelolaan Sampah",
                 "Traceable general-waste volumes with segregation discipline.",
                 "Volume sampah general yang terdokumentasi dengan disiplin segregasi.",
                 "Waste \u2022 3R \u2022 Circular",
                 "/news/amount-general-waste.pdf", "PDF", "418 KB", "Summary", 1),
                ("DASHBOARD GHG INVENTORY 2023", "ghg", "Greenhouse Gas Emissions Report",
                 "Laporan Emisi Gas Rumah Kaca",
                 "GHG dashboard 2023 plus methodology.",
                 "Dashboard GRK 2023 plus metodologi.",
                 "GHG \u2022 Carbon \u2022 Scope 1 & 2",
                 "/news/dashboard-ghg-inventory-2023.pdf", "PDF", "995 KB", "2023", 2),
                ("DASHBOARD GHG INVENTORY 2024", "ghg", "Greenhouse Gas Emissions Report",
                 "Laporan Emisi Gas Rumah Kaca",
                 "GHG dashboard 2024 plus methodology.",
                 "Dashboard GRK 2024 plus metodologi.",
                 "GHG \u2022 Carbon \u2022 Scope 1 & 2",
                 "/news/dashboard-ghg-inventory-2024.pdf", "PDF", "997 KB", "2024", 3),
                ("DASHBOARD GHG INVENTORY 2025", "ghg", "Greenhouse Gas Emissions Report",
                 "Laporan Emisi Gas Rumah Kaca",
                 "GHG dashboard 2025 plus methodology.",
                 "Dashboard GRK 2025 plus metodologi.",
                 "GHG \u2022 Carbon \u2022 Scope 1 & 2",
                 "/news/dashboard-ghg-inventory-2025.pdf", "PDF", "1008 KB", "2025 \u2022 Latest", 4),
                ("Q6.2 Establish GHG Inventory", "ghg", "Greenhouse Gas Emissions Report",
                 "Laporan Emisi Gas Rumah Kaca",
                 "GHG establishment methodology.",
                 "Metodologi penetapan GRK.",
                 "GHG \u2022 Carbon \u2022 Scope 1 & 2",
                 "/news/q62-establish-ghg-inventory.pdf", "PDF", "369 KB", "Methodology", 5),
                ("Rangkuman Pencatatan Limbah B3 2023-2025", "b3",
                 "Hazardous Waste Management Report", "Laporan Pengelolaan Limbah B3",
                 "Full 2023-2025 B3 logbook recapitulation.",
                 "Rekapitulasi logbook limbah B3 2023-2025.",
                 "B3 \u2022 Hazardous \u2022 Compliant",
                 "/news/rangkuman-pencatatan-limbah-b3-2023-2025.xlsx", "XLSX", "85 KB", "2023-2025", 6),
                ("Water Withdrawal and Waste Water Discharge Volume", "water",
                 "Water Consumption and Wastewater Management", "Konsumsi Air & Pengelolaan Air Limbah",
                 "Withdrawal vs discharge volumes.",
                 "Volume pengambilan vs pembuangan.",
                 "Water \u2022 Wastewater \u2022 PROPER",
                 "/news/water-withdrawal-and-wastewater-discharge-volume.pdf", "PDF", "1.34 MB", "Volume Report", 7),
            ]
            for (t, cat, ten, tid, den, did, badge, furl, ftype, fsize, tag, so) in rows:
                db.add(SustainabilityReport(
                    title=t, category=cat,
                    category_title_en=ten, category_title_id=tid,
                    category_desc_en=den, category_desc_id=did,
                    category_badge=badge, file_url=furl,
                    file_type=ftype, file_size=fsize, tag=tag,
                    sort_order=so, is_active=True,
                ))
            db.commit()
            logger.info("Seeded sustainability_reports (7 docs) + ensured News nav-menu.")
    except Exception as e:
        db.rollback()
        logger.warning(f"Company CMS seed skipped: {e}")
    finally:
        db.close()
