from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    Text,
    Numeric,
    ForeignKey,
    JSON,
)
from sqlalchemy.orm import relationship
from app.db.base_class import Base, TimestampMixin


class SiteSetting(Base):
    __tablename__ = "site_settings"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    key = Column(String(100), unique=True, index=True, nullable=False)
    value = Column(Text, nullable=False)


class NavMenu(Base, TimestampMixin):
    __tablename__ = "nav_menus"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(150), nullable=False)
    url = Column(String(255), nullable=False)
    location = Column(String(100), nullable=False)
    section = Column(String(100), nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_maintenance = Column(Boolean, default=False, nullable=False)
    parent_id = Column(Integer, ForeignKey("nav_menus.id", ondelete="CASCADE"), nullable=True)

    children = relationship("NavMenu", backref="parent", remote_side=[id])


class HeroSection(Base, TimestampMixin):
    __tablename__ = "hero_sections"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    page = Column(String(100), nullable=False)
    title = Column(String(255), nullable=False)
    subtitle = Column(Text, nullable=True)
    image = Column(Text, nullable=True)
    image_alt = Column(String(255), nullable=True)
    primary_btn_text = Column(String(100), nullable=True)
    primary_btn_url = Column(String(255), nullable=True)
    secondary_btn_text = Column(String(100), nullable=True)
    secondary_btn_url = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)


class Announcement(Base, TimestampMixin):
    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    message = Column(Text, nullable=False)
    btn_text = Column(String(100), nullable=True)
    btn_url = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    start_at = Column(DateTime(timezone=True), nullable=True)
    end_at = Column(DateTime(timezone=True), nullable=True)


class Partner(Base, TimestampMixin):
    __tablename__ = "partners"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    logo = Column(Text, nullable=False)
    logo_type = Column(String(50), default="image", nullable=False)
    url = Column(String(255), nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


class Feature(Base, TimestampMixin):
    __tablename__ = "features"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    svg_icon = Column(Text, nullable=True)
    section = Column(String(100), default="general", nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


class Service(Base, TimestampMixin):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    subtitle = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    image = Column(Text, nullable=True)
    slug = Column(String(200), unique=True, index=True, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    category = Column(String(100), default="mobil", nullable=False)
    description = Column(Text, nullable=True)
    image = Column(Text, nullable=True)
    slug = Column(String(200), unique=True, index=True, nullable=False)
    price = Column(Numeric(12, 2), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)


class BlogPost(Base, TimestampMixin):
    __tablename__ = "blog_posts"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, index=True, nullable=False)
    excerpt = Column(Text, nullable=True)
    content = Column(Text, nullable=False)
    image = Column(Text, nullable=True)
    author = Column(String(150), nullable=True)
    is_published = Column(Boolean, default=False, nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=True)


class Testimonial(Base, TimestampMixin):
    __tablename__ = "testimonials"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    role = Column(String(150), nullable=True)
    company = Column(String(200), nullable=True)
    content = Column(Text, nullable=False)
    avatar = Column(Text, nullable=True)
    rating = Column(Integer, default=5, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


class Faq(Base, TimestampMixin):
    __tablename__ = "faqs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    question = Column(String(500), nullable=False)
    answer = Column(Text, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


class Statistic(Base, TimestampMixin):
    __tablename__ = "statistics"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    label = Column(String(150), nullable=False)
    value = Column(String(100), nullable=False)
    page = Column(String(100), default="home", nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


class ContactSubmission(Base):
    __tablename__ = "contact_submissions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    email = Column(String(255), nullable=False)
    subject = Column(String(255), nullable=True)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class Certification(Base, TimestampMixin):
    __tablename__ = "certifications"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    issuer = Column(String(200), nullable=False)
    certificate_number = Column(String(150), nullable=True)
    issued_date = Column(DateTime(timezone=True), nullable=True)
    expiry_date = Column(DateTime(timezone=True), nullable=True)
    image = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


class Facility(Base, TimestampMixin):
    __tablename__ = "facilities"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(200), nullable=False)
    category = Column(String(100), default="Produksi", nullable=False)
    image = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    specifications = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


class SustainabilityReport(Base, TimestampMixin):
    """News & Sustainability documents (waste, GHG, B3, water) — fully CMS-editable."""

    __tablename__ = "sustainability_reports"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    category = Column(String(100), default="general", nullable=False)
    category_title_en = Column(String(255), nullable=True)
    category_title_id = Column(String(255), nullable=True)
    category_desc_en = Column(Text, nullable=True)
    category_desc_id = Column(Text, nullable=True)
    category_badge = Column(String(255), nullable=True)
    file_url = Column(Text, nullable=False)
    file_type = Column(String(20), default="PDF", nullable=False)
    file_size = Column(String(50), nullable=True)
    tag = Column(String(100), nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)


class CustomPage(Base, TimestampMixin):
    """Dynamic custom pages (Gallery, Rich Text, Documents) managed via CMS."""

    __tablename__ = "custom_pages"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    slug = Column(String(120), unique=True, index=True, nullable=False)
    template_type = Column(String(50), default="gallery", nullable=False)
    content = Column(Text, nullable=True)
    gallery_images = Column(JSON, default=list, nullable=True)
    meta_title = Column(String(255), nullable=True)
    meta_description = Column(Text, nullable=True)
    sort_order = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
